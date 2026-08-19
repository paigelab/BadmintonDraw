"""Check public announcement pages and record their latest content fingerprints.

This deliberately records source-page changes only. A school needs a source entry
in data/sources.csv before it is checked.  Later, source-specific parsers can turn
matching pages into entries in data/announcements.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.csv"
STATUS = ROOT / "data" / "source-status.json"
KEYWORDS = ("羽球", "抽籤", "場地", "登記", "借用", "使用申請")

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.parts = []
    def handle_data(self, data): self.parts.append(data.strip())
    @property
    def text(self): return " ".join(part for part in self.parts if part)

def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
    with urlopen(request, timeout=25) as response:
        parser = TextExtractor()
        parser.feed(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
        return parser.text

def main() -> None:
    prior = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"sources": {}}
    records = prior.setdefault("sources", {})
    taipei = timezone(timedelta(hours=8))
    with SOURCES.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(line for line in file if not line.lstrip().startswith("#")):
            if row.get("enabled", "").lower() != "true": continue
            url = row["source_url"].strip()
            try:
                text = fetch(url)
                digest = hashlib.sha256(text.encode()).hexdigest()
                records[url] = {"school": row["school"], "checked_at": datetime.now(taipei).isoformat(timespec="seconds"), "content_changed": records.get(url, {}).get("digest") != digest, "digest": digest, "keyword_found": any(word in text for word in KEYWORDS)}
            except Exception as error:
                records[url] = {"school": row["school"], "checked_at": datetime.now(taipei).isoformat(timespec="seconds"), "error": str(error)}
    STATUS.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__": main()
