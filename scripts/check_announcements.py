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
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.csv"
STATUS = ROOT / "data" / "source-status.json"
ANNOUNCEMENTS = ROOT / "data" / "announcements.json"

# We deliberately require a strong combination.  A school homepage often has
# menu entries such as "場地預約" or "羽球隊", which are not lottery notices.
def is_relevant(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    return (
        ("羽球" in normalized and any(word in normalized for word in ("抽籤", "場地", "登記", "借用", "申請", "租借", "預約", "使用")))
        or ("抽籤" in normalized and any(word in normalized for word in ("場地", "球場", "體育館")))
    )


def categorize(title: str, description: str = "") -> str:
    """Classify a relevant notice for concise presentation on the website."""
    headline = re.sub(r"\s+", "", title)
    details = re.sub(r"\s+", "", description)
    # A headline is more reliable than an explanatory paragraph. For example,
    # registration notices often say that winners will be announced later.
    if any(word in headline for word in ("抽籤", "中籤名單", "抽籤名單", "登記結果", "錄取結果")):
        return "result"
    if any(word in headline for word in ("登記", "報名", "申請", "出租", "租用", "預約")):
        return "registration"
    if any(word in headline for word in ("管理辦法", "使用規則", "使用管理", "租借管理")):
        return "rule"
    if any(word in details for word in ("抽籤結果", "中籤名單", "抽籤名單", "登記結果", "錄取結果")):
        return "result"
    if any(word in details for word in ("登記", "報名", "申請", "出租", "租用", "預約")):
        return "registration"
    if any(word in details for word in ("管理辦法", "使用規則", "使用管理", "租借管理")):
        return "rule"
    return "other"


DATE = re.compile(r"(?:\d{3,4}[./年-])?\d{1,2}[./月-]\d{1,2}(?:日)?")
# Some schools call the same information "場租" or "場地租借" and only mention
# badminton / the draw in the body of the notice. The relevance check still
# filters ordinary rental notices out.
SEARCH_TERMS = ("羽球", "羽球場地", "場地抽籤", "場地登記", "場地借用", "場地租借", "場租")

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

def get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))


def fetch_page(url: str) -> PageExtractor:
    parser = PageExtractor()
    parser.feed(get_text(url))
    return parser


def nss_feed_urls(home_url: str, html: str) -> list[str]:
    """Discover public NSS announcement feeder URLs embedded in the homepage."""
    pattern = re.compile(r"https?://[^\"\\]+/nss/main/feeder/[^\"\\]+", re.IGNORECASE)
    candidates = [url.replace("\\u0026", "&").replace("&amp;", "&") for url in pattern.findall(html)]
    # Some NSS installations use relative feeder URLs.
    candidates.extend(urljoin(home_url, path) for path in re.findall(r"/nss/main/feeder/[^\"\\]+", html, re.IGNORECASE))
    return list(dict.fromkeys(candidates))


def local_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child_text(item, name: str) -> str:
    for child in item:
        if local_name(child) == name:
            return "".join(child.itertext()).strip()
    return ""


def nss_items(feed_url: str) -> list[dict[str, str]]:
    """Read an NSS feeder RSS document and normalize its announcement items."""
    root = ElementTree.fromstring(get_text(feed_url))
    items = []
    for node in root.iter():
        if local_name(node) != "item":
            continue
        title = child_text(node, "title")
        link = child_text(node, "link")
        if not title or not link:
            continue
        description = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", child_text(node, "description"))).strip()
        published = child_text(node, "pubDate")
        try:
            published = parsedate_to_datetime(published).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        except (TypeError, ValueError, IndexError):
            published = "日期待確認"
        items.append({"title": title, "url": link, "description": description, "published_at": published})
    return items


def nss_fulltext_items(home_url: str, html: str) -> list[dict[str, str]]:
    """Use the public NSS full-text index, which includes archived announcements."""
    match = re.search(r'"uniq":"([^"\\]+)', html)
    endpoint = urljoin(home_url, "/nss/ext/fulltext")
    seen: set[str] = set()
    items = []
    # An empty searchRange searches the whole public site.  The first `uniq`
    # in a home page can be a menu module instead of its announcements module.
    search_ranges = [""]
    if match:
        search_ranges.append(match.group(1))
    for search_range in search_ranges:
        for term in SEARCH_TERMS:
            response = post_json(endpoint, {"keyword": term, "each": 100, "page": 1, "partten": "", "searchRange": search_range})
            for result in response.get("data", {}).get("result", []):
                identifier = result.get("_id") or result.get("freeze")
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)
                content = result.get("data", {})
                title = content.get("title") or content.get("name") or ""
                description = content.get("content") or ""
                if isinstance(description, list):
                    description = " ".join(map(str, description))
                text = f"{title} {description}"
                if not title or not is_relevant(text):
                    continue
                items.append({
                    "title": title,
                    "url": urljoin(home_url, result.get("freeze", "")),
                    "description": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(description))).strip(),
                    "published_at": str(result.get("ctime", ""))[:10] or "日期待確認",
                })
    return items


def load_announcements() -> dict:
    if ANNOUNCEMENTS.exists():
        return json.loads(ANNOUNCEMENTS.read_text(encoding="utf-8"))
    return {"last_updated": "尚未更新", "announcements": []}


def summary_for(title: str, description: str = "") -> str:
    clean_description = description[:180].rstrip()
    return clean_description or f"偵測到可能與羽球場地抽籤相關的公開公告：{title}。請以校方原始公告為準。"

def main() -> None:
    prior = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"sources": {}}
    records = prior.setdefault("sources", {})
    data = load_announcements()
    existing = {item.get("source_url"): item for item in data.get("announcements", [])}
    taipei = timezone(timedelta(hours=8))
    with SOURCES.open(encoding="utf-8", newline="") as file:
        rows = [row for row in csv.DictReader(line for line in file if not line.lstrip().startswith("#")) if row.get("enabled", "").lower() == "true"]
        active_urls = {row["source_url"].strip() for row in rows}
        for stale_url in set(records) - active_urls:
            records.pop(stale_url)
        for row in rows:
            url = row["source_url"].strip()
            try:
                raw_html = get_text(url)
                page = PageExtractor()
                page.feed(raw_html)
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
                            "category": categorize(title),
                            "type": "自動偵測候選公告",
                            "source_url": source_url,
                        }
                feed_urls = nss_feed_urls(url, raw_html)
                feed_item_count = 0
                for feed_url in feed_urls:
                    for item in nss_items(feed_url):
                        feed_item_count += 1
                        searchable = f"{item['title']} {item['description']}"
                        if not is_relevant(searchable):
                            continue
                        candidates.append(item["title"])
                        existing[item["url"]] = {
                            "school": row["school"],
                            "title": item["title"],
                            "published_at": item["published_at"],
                            "summary": summary_for(item["title"], item["description"]),
                            "category": categorize(item["title"], item["description"]),
                            "type": "自動擷取公告",
                            "source_url": item["url"],
                        }
                fulltext_items = nss_fulltext_items(url, raw_html)
                for item in fulltext_items:
                    candidates.append(item["title"])
                    existing[item["url"]] = {
                        "school": row["school"],
                        "title": item["title"],
                        "published_at": item["published_at"],
                        "summary": summary_for(item["title"], item["description"]),
                        "category": categorize(item["title"], item["description"]),
                        "type": "全文檢索公告",
                        "source_url": item["url"],
                    }
                records[url] = {
                    "school": row["school"],
                    "checked_at": datetime.now(taipei).isoformat(timespec="seconds"),
                    "content_changed": records.get(url, {}).get("digest") != digest,
                    "digest": digest,
                    "candidate_count": len(candidates),
                    "candidate_titles": candidates[:10],
                    "nss_feed_count": len(feed_urls),
                    "nss_announcement_count": feed_item_count,
                    "nss_fulltext_candidate_count": len(fulltext_items),
                }
            except Exception as error:
                records[url] = {"school": row["school"], "checked_at": datetime.now(taipei).isoformat(timespec="seconds"), "error": str(error)}
    STATUS.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data["announcements"] = sorted(existing.values(), key=lambda item: item.get("published_at", ""), reverse=True)
    data["last_updated"] = datetime.now(taipei).strftime("%Y-%m-%d %H:%M（台灣時間）")
    ANNOUNCEMENTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__": main()
