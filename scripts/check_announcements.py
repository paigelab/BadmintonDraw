"""Check public announcement pages and record their latest content fingerprints.

This deliberately records source-page changes only. A school needs a source entry
in data/sources.csv before it is checked.  Later, source-specific parsers can turn
matching pages into entries in data/announcements.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.csv"
STATUS = ROOT / "data" / "source-status.json"
ANNOUNCEMENTS = ROOT / "data" / "announcements.json"

# We deliberately require a strong combination.  A school homepage often has
# menu entries such as "場地預約" or "羽球隊", which are not lottery notices.
def is_relevant(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    return (
        "羽球" in normalized
        or "抽籤" in normalized
        or ("場地" in normalized and any(word in normalized for word in ("登記", "借用", "申請", "租借", "分配")))
    )


DATE = re.compile(r"(?:\d{3,4}[./年-])?\d{1,2}[./月-]\d{1,2}(?:日)?")

class PageExtractor(HTMLParser):
    """Extract readable page text and ordinary links without external packages."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._link_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_parts = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            title = " ".join(part for part in self._link_parts if part).strip()
            if title:
                self.links.append({"title": title, "url": self._href})
            self._href = None
            self._link_parts = []

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)
            if self._href:
                self._link_parts.append(value)

    @property
    def text(self):
        return " ".join(self.parts)

def fetch(url: str) -> PageExtractor:
    request = Request(url, headers={"User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
    with urlopen(request, timeout=25) as response:
        parser = PageExtractor()
        parser.feed(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
        return parser


def load_announcements() -> dict:
    if ANNOUNCEMENTS.exists():
        return json.loads(ANNOUNCEMENTS.read_text(encoding="utf-8"))
    return {"last_updated": "尚未更新", "announcements": []}


def summary_for(title: str) -> str:
    match = DATE.search(title)
    return f"偵測到可能與羽球場地抽籤相關的公開公告。{(' 日期：' + match.group(0) + '。') if match else ''}請以校方原始公告為準。"

def main() -> None:
    prior = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"sources": {}}
    records = prior.setdefault("sources", {})
    data = load_announcements()
    existing = {item.get("source_url"): item for item in data.get("announcements", [])}
    taipei = timezone(timedelta(hours=8))
    with SOURCES.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(line for line in file if not line.lstrip().startswith("#")):
            if row.get("enabled", "").lower() != "true": continue
            url = row["source_url"].strip()
            try:
                page = fetch(url)
                digest = hashlib.sha256(page.text.encode()).hexdigest()
                candidates = []
                for link in page.links:
                    title = re.sub(r"\s+", " ", link["title"])
                    if is_relevant(title):
                        source_url = urljoin(url, link["url"])
                        candidates.append(title)
                        existing[source_url] = {
                            "school": row["school"],
                            "title": title,
                            "published_at": DATE.search(title).group(0) if DATE.search(title) else "日期待確認",
                            "summary": summary_for(title),
                            "type": "自動偵測候選公告",
                            "source_url": source_url,
                        }
                records[url] = {
                    "school": row["school"],
                    "checked_at": datetime.now(taipei).isoformat(timespec="seconds"),
                    "content_changed": records.get(url, {}).get("digest") != digest,
                    "digest": digest,
                    "candidate_count": len(candidates),
                    "candidate_titles": candidates[:10],
                }
            except Exception as error:
                records[url] = {"school": row["school"], "checked_at": datetime.now(taipei).isoformat(timespec="seconds"), "error": str(error)}
    STATUS.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data["announcements"] = sorted(existing.values(), key=lambda item: item.get("published_at", ""), reverse=True)
    data["last_updated"] = datetime.now(taipei).strftime("%Y-%m-%d %H:%M（台灣時間）")
    ANNOUNCEMENTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__": main()
