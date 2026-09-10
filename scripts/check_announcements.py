"""Check public announcement pages and record their latest content fingerprints.

This deliberately records source-page changes only. A school needs a source entry
in data/sources.csv before it is checked.  Later, source-specific parsers can turn
matching pages into entries in data/announcements.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.csv"
STATUS = ROOT / "data" / "source-status.json"
ANNOUNCEMENTS = ROOT / "data" / "announcements.json"
NOTIFIED = ROOT / "data" / "notified.json"
NOTIFIABLE_CATEGORIES = {"registration", "result"}
CATEGORY_LABELS = {"registration": "登記／報名", "result": "抽籤結果"}

# We deliberately require a strong combination.  A school homepage often has
# menu entries such as "場地預約" or "羽球隊", which are not lottery notices.
def is_relevant(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    return (
        ("羽球" in normalized and any(word in normalized for word in ("抽籤", "場地", "登記", "借用", "申請", "租借", "預約", "使用")))
        or ("抽籤" in normalized and any(word in normalized for word in ("場地", "球場", "體育館", "場租")))
    )


def categorize(title: str, description: str = "") -> str:
    """Classify a relevant notice for concise presentation on the website."""
    headline = re.sub(r"\s+", "", title)
    details = re.sub(r"\s+", "", description)
    # A headline is more reliable than an explanatory paragraph. For example,
    # registration notices often say that winners will be announced later.
    if any(word in headline for word in ("抽籤結果", "中籤名單", "抽籤名單", "登記結果", "錄取結果")):
        return "result"
    if any(word in headline for word in ("登記", "報名", "申請", "出租", "租用", "租借", "預約", "抽籤辦法")):
        return "registration"
    if any(word in headline for word in ("管理辦法", "使用規則", "使用管理", "租借管理")):
        return "rule"
    if any(word in details for word in ("抽籤結果", "中籤名單", "抽籤名單", "登記結果", "錄取結果")):
        return "result"
    if any(word in details for word in ("登記", "報名", "申請", "出租", "租用", "租借", "預約", "抽籤辦法")):
        return "registration"
    if any(word in details for word in ("管理辦法", "使用規則", "使用管理", "租借管理")):
        return "rule"
    return "other"


DATE = re.compile(r"(?:\d{3,4}[./年-])?\d{1,2}[./月-]\d{1,2}(?:日)?")
GOVERNMENT_VENUE_URL = re.compile(r"^https://service\.gov\.taipei/rental/VenueDetail/", re.IGNORECASE)
ACCEPTANCE_PERIOD = re.compile(
    r"受理期間為\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*[～~至]\s*(\d{4})/(\d{1,2})/(\d{1,2})"
)
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
    # urllib requires non-ASCII paths (such as Google Sites page names) to be
    # percent-encoded before building a request.
    parts = urlsplit(url)
    request_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), quote(parts.query, safe="=&/%"), ""))
    request = Request(request_url, headers={"User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except (HTTPError, URLError):
            if attempt == 2:
                raise
            sleep(attempt + 1)


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


def article_published_at(source_url: str) -> str | None:
    """Read an ordinary announcement page's visible publication date when available."""
    if urlsplit(source_url).path.lower().endswith(".pdf"):
        return None
    try:
        html = get_text(source_url)
    except (HTTPError, URLError):
        return None
    match = re.search(
        r"<th[^>]*>\s*(?:發佈|發布)日期\s*</th>\s*<td[^>]*>\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        html,
        re.IGNORECASE,
    )
    if not match:
        return None
    return "-".join((match.group(1), match.group(2).zfill(2), match.group(3).zfill(2)))


def backfill_missing_publication_dates(existing: dict[str, dict]) -> None:
    """Fill pending dates on retained ordinary announcements no longer listed on their index page."""
    for item in existing.values():
        if item.get("type") != "自動偵測候選公告" or item.get("published_at") != "日期待確認":
            continue
        published_at = article_published_at(str(item.get("source_url", "")))
        if published_at:
            item["published_at"] = published_at
            print(f"Backfilled publication date: {item.get('school', '')} {published_at}")


def government_rental_item(school: str, source_url: str, page: PageExtractor) -> dict | None:
    """Turn one Taipei City venue-detail page into its current registration item."""
    if not GOVERNMENT_VENUE_URL.match(source_url) or not is_relevant(page.text):
        return None

    text = re.sub(r"\s+", " ", page.text).strip()
    # VenueDetail pages place CSS before the visible heading in their HTML.
    # Bound each side of the separator so that embedded style text is never
    # mistaken for part of the venue name.
    venue_match = re.search(r"(臺北市[^|]{1,100}?\|\s*[^|]{1,80}?)\s+受理期間為", text)
    venue_name = venue_match.group(1).strip() if venue_match else school
    period_match = ACCEPTANCE_PERIOD.search(text)
    registration_start = registration_end = None
    published_at = "日期待確認"
    if period_match:
        registration_start = "-".join((period_match.group(1), period_match.group(2).zfill(2), period_match.group(3).zfill(2)))
        registration_end = "-".join((period_match.group(4), period_match.group(5).zfill(2), period_match.group(6).zfill(2)))
        published_at = registration_start

    instructions_match = re.search(r"線上租借說明\s*(.*?)(?=\s*(?:受理期間為|網站地圖|臺北市政府資料開放宣告|$))", text)
    instructions = instructions_match.group(1).strip() if instructions_match else text
    title = f"{venue_name} 場地租借登記"
    return {
        "school": school,
        "title": title,
        "published_at": published_at,
        "registration_start": registration_start,
        "registration_end": registration_end,
        "summary": summary_for(title, instructions),
        "category": "registration",
        "type": "政府場租頁",
        "government_rental": True,
        "source_url": source_url,
    }


def announcement_storage_key(item: dict) -> str:
    """Keep a separate history entry for every acceptance period on a live venue page."""
    source_url = item.get("source_url", "")
    if item.get("government_rental") and item.get("registration_start"):
        return f"{source_url}#registration-{item['registration_start']}"
    return source_url


def nss_feed_urls(home_url: str, html: str) -> list[str]:
    """Discover public NSS announcement feeder URLs embedded in the homepage."""
    pattern = re.compile(r"https?://[^\"\\]+/nss/main/feeder/[^\"\\]+", re.IGNORECASE)
    candidates = [url.replace("\\u0026", "&").replace("&amp;", "&") for url in pattern.findall(html)]
    # Some NSS installations use relative feeder URLs.
    candidates.extend(urljoin(home_url, path) for path in re.findall(r"/nss/main/feeder/[^\"\\]+", html, re.IGNORECASE))
    return list(dict.fromkeys(candidates))


def nss_public_announcement_module(html: str) -> tuple[str, str] | None:
    """Find the public announcement module used by a school's NSS homepage."""
    pattern = re.compile(
        r'"sid":"([^"]+)","mid":"([^"]+)".{0,400}?"setting":\{[^}]*?"name":"([^"]*)"'
    )
    modules = [(sid, mid, name) for sid, mid, name in pattern.findall(html) if mid == "5abf2d62aa93092cee58ceb4"]
    for preferred_name in ("公告資訊", "最新消息"):
        for sid, mid, name in modules:
            if name == preferred_name:
                return mid, sid
    for sid, mid, name in modules:
        if "公告" in name or "消息" in name:
            return mid, sid
    return None


def nss_item_url(home_url: str, result: dict, public_module: tuple[str, str] | None) -> tuple[str, str | None]:
    """Prefer an NSS item's public remote record over its private search index."""
    index_url = urljoin(home_url, result.get("freeze", ""))
    remotes = result.get("data", {}).get("remotes") or []
    remote_ids = [str(remote).rsplit("#", 1)[-1] for remote in remotes if "#" in str(remote)]
    if public_module and remote_ids:
        mid, sid = public_module
        origin = urlsplit(home_url)
        public_url = urlunsplit((origin.scheme, origin.netloc, f"/nss/main/freeze/{mid}/{sid}/{remote_ids[0]}", "vector=private&static=false", ""))
        return public_url, index_url
    return index_url, None


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
    public_module = nss_public_announcement_module(html)
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
                item_url, replaces_url = nss_item_url(home_url, result, public_module)
                items.append({
                    "title": title,
                    "url": item_url,
                    "replaces_url": replaces_url,
                    "description": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(description))).strip(),
                    "published_at": str(result.get("ctime", ""))[:10] or "日期待確認",
                })
    return items


def load_announcements() -> dict:
    if ANNOUNCEMENTS.exists():
        return json.loads(ANNOUNCEMENTS.read_text(encoding="utf-8"))
    return {"last_updated": "尚未更新", "announcements": []}


def source_configuration(row: dict) -> dict:
    """Return the source fields whose change requires a fresh crawl."""
    return {
        "school": row.get("school", "").strip(),
        "source_url": row.get("source_url", "").strip(),
        "enabled": row.get("enabled", "").strip().lower(),
    }


def load_notified() -> dict:
    """Load delivery records; a blank initialization is intentionally safe."""
    if NOTIFIED.exists():
        return json.loads(NOTIFIED.read_text(encoding="utf-8"))
    return {"initialized_at": None, "notified": []}


def save_notified(notified: dict) -> None:
    NOTIFIED.write_text(json.dumps(notified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def notification_record(item: dict, notified_at: str, delivery: str) -> dict:
    return {
        "source_url": item["source_url"],
        "announcement_key": announcement_key(item),
        "notified_at": notified_at,
        "school": item.get("school", "學校待確認"),
        "title": item.get("title", "公告標題待確認"),
        "delivery": delivery,
    }


def announcement_key(item: dict) -> str:
    """Identify the same notice even when an NSS site changes its URL path."""
    def normalized(value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).lower()
        return re.sub(r"\s+", "", text)

    return "|".join((
        normalized(item.get("school")),
        normalized(item.get("title")),
        normalized(item.get("published_at")),
        normalized(item.get("category")),
    ))


def backfill_notification_keys(notified: dict, announcements: list[dict]) -> bool:
    """Add fallback identities to old delivery records without resending them."""
    by_url = {item.get("source_url"): item for item in announcements if item.get("source_url")}
    changed = False
    for record in notified.get("notified", []):
        if record.get("announcement_key"):
            continue
        source_item = by_url.get(record.get("source_url"))
        if not source_item:
            continue
        record["announcement_key"] = announcement_key(source_item)
        changed = True
    return changed


def source_error_record(source_url: str, item: dict, notified_at: str) -> dict:
    """Keep the current alerted error state for one monitored source."""
    return {
        "source_url": source_url,
        "notified_at": notified_at,
        "school": item.get("school", "學校待確認"),
        "error": item.get("error", "讀取公告頁時發生未知錯誤"),
    }


def send_discord_notification(webhook_url: str, item: dict) -> bool:
    """Deliver one Discord embed and return True only when Discord accepts it."""
    title = str(item.get("title", "公告標題待確認"))[:256]
    payload = {
        "embeds": [{
            "title": "🏸 新羽球場地公告",
            "url": item["source_url"],
            "color": 1532757,
            "fields": [
                {"name": "學校", "value": str(item.get("school", "學校待確認"))[:1024], "inline": True},
                {"name": "公告類型", "value": CATEGORY_LABELS[item["category"]], "inline": True},
                {"name": "公告日期", "value": str(item.get("published_at", "日期待確認"))[:1024], "inline": True},
                {"name": "公告標題", "value": title, "inline": False},
                {"name": "原始公告", "value": f"[點擊前往原始公告]({item['source_url']})", "inline": False},
            ],
        }],
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(webhook_url, data=body, headers={"Content-Type": "application/json", "User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
        with urlopen(request, timeout=20) as response:
            if response.status not in (200, 204):
                print(f"Discord notification rejected for {item['source_url']}: HTTP {response.status}")
                return False
        return True
    except Exception as error:
        print(f"Discord notification failed for {item['source_url']}: {error}")
        return False


def send_discord_source_error_notification(webhook_url: str, source_url: str, item: dict) -> bool:
    """Send one alert for a source that the crawler cannot currently read."""
    error_message = str(item.get("error", "讀取公告頁時發生未知錯誤"))[:1024]
    payload = {
        "embeds": [{
            "title": "⚠️ 學校公告來源讀取異常",
            "url": source_url,
            "color": 15158332,
            "fields": [
                {"name": "學校", "value": str(item.get("school", "學校待確認"))[:1024], "inline": True},
                {"name": "檢查時間", "value": str(item.get("checked_at", "時間待確認"))[:1024], "inline": True},
                {"name": "錯誤訊息", "value": error_message, "inline": False},
                {"name": "校方公告頁", "value": f"[點擊前往校方公告頁]({source_url})", "inline": False},
            ],
        }],
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(webhook_url, data=body, headers={"Content-Type": "application/json", "User-Agent": "BadmintonDraw-monitor/0.1 (+GitHub Actions)"})
        with urlopen(request, timeout=20) as response:
            if response.status not in (200, 204):
                print(f"Discord source-error notification rejected for {source_url}: HTTP {response.status}")
                return False
        return True
    except Exception as error:
        print(f"Discord source-error notification failed for {source_url}: {error}")
        return False


def send_discord_test_notification() -> None:
    """Send an opt-in verification message without touching delivery records."""
    if os.environ.get("DISCORD_TEST_NOTIFICATION", "").lower() != "true":
        return
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("Discord test skipped: DISCORD_WEBHOOK_URL is not configured.")
        return
    test_item = {
        "school": "BadmintonDraw 測試",
        "category": "registration",
        "title": "Discord Webhook 設定成功",
        "published_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
        "source_url": "https://github.com/paigelab/BadmintonDraw",
    }
    if send_discord_notification(webhook_url, test_item):
        print("Discord test notification sent successfully.")


def send_discord_source_error_test_notification() -> None:
    """Send an opt-in error-channel verification message without saving state."""
    if os.environ.get("DISCORD_ERROR_TEST_NOTIFICATION", "").lower() != "true":
        return
    webhook_url = os.environ.get("DISCORD_ERROR_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("Discord error test skipped: DISCORD_ERROR_WEBHOOK_URL is not configured.")
        return
    test_source_url = "https://github.com/paigelab/BadmintonDraw"
    test_item = {
        "school": "BadmintonDraw 測試",
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "error": "這是一則測試訊息，並非實際的公告頁讀取異常。",
    }
    if send_discord_source_error_notification(webhook_url, test_source_url, test_item):
        print("Discord source-error test notification sent successfully.")


def is_recent_for_notification(item: dict, now: datetime) -> bool:
    """Do not alert for historic results discovered by a newly added source."""
    try:
        published_at = datetime.strptime(str(item.get("published_at", "")), "%Y-%m-%d").date()
    except ValueError:
        return False
    return published_at >= (now - timedelta(days=31)).date()


def is_expired_government_registration(item: dict, now: datetime) -> bool:
    """Do not announce a closed period merely because its live page was added today."""
    if not item.get("government_rental"):
        return False
    try:
        registration_end = datetime.strptime(str(item.get("registration_end", "")), "%Y-%m-%d").date()
    except ValueError:
        return False
    return registration_end < now.date()


def notify_new_announcements(announcements: list[dict], now: datetime) -> None:
    """Seed history once, then notify only genuinely first-seen announcements."""
    notified = load_notified()
    timestamp = now.isoformat(timespec="seconds")
    eligible = [item for item in announcements if item.get("category") in NOTIFIABLE_CATEGORIES and item.get("source_url")]

    # The first execution deliberately records history without sending it.
    if not notified.get("initialized_at"):
        notified["initialized_at"] = timestamp
        notified["notified"] = [notification_record(item, timestamp, "initialization") for item in eligible]
        save_notified(notified)
        print(f"Discord notification baseline initialized with {len(eligible)} existing announcements.")
        return

    if backfill_notification_keys(notified, announcements):
        save_notified(notified)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not configured; new announcements will be retried later.")
        return

    notified_urls = {item.get("source_url") for item in notified.get("notified", [])}
    notified_keys = {item.get("announcement_key") for item in notified.get("notified", [])}
    for item in eligible:
        item_key = announcement_key(item)
        # A government venue page is a live page reused each quarter. Its URL
        # stays the same, so the acceptance period key—not the URL—identifies
        # the next registration window.
        if (not item.get("government_rental") and item["source_url"] in notified_urls) or item_key in notified_keys:
            continue
        if is_expired_government_registration(item, now):
            notified.setdefault("notified", []).append(notification_record(item, timestamp, "historical"))
            save_notified(notified)
            notified_urls.add(item["source_url"])
            notified_keys.add(item_key)
            continue
        if not is_recent_for_notification(item, now):
            # A source can expose years of archive results only after it is
            # added. Record those once as history rather than alerting users.
            notified.setdefault("notified", []).append(notification_record(item, timestamp, "historical"))
            save_notified(notified)
            notified_urls.add(item["source_url"])
            notified_keys.add(item_key)
            continue
        if send_discord_notification(webhook_url, item):
            notified.setdefault("notified", []).append(notification_record(item, timestamp, "discord"))
            # Persist immediately: a later failure must not resend a successful delivery.
            save_notified(notified)
            notified_urls.add(item["source_url"])
            notified_keys.add(item_key)


def notify_source_errors(records: dict, now: datetime) -> None:
    """Alert once per ongoing source error, and reset it after recovery."""
    notified = load_notified()
    timestamp = now.isoformat(timespec="seconds")
    current_errors = {
        source_url: item
        for source_url, item in records.items()
        if item.get("error")
    }
    prior_errors = notified.get("source_errors", [])

    # A source that recovered is removed from the active-error state. If it
    # fails again later, it is treated as a new incident and can alert again.
    retained_errors = [
        item for item in prior_errors
        if item.get("source_url") in current_errors
    ]
    if len(retained_errors) != len(prior_errors):
        notified["source_errors"] = retained_errors
        save_notified(notified)
        print("Cleared recovered source error notification state.")

    webhook_url = os.environ.get("DISCORD_ERROR_WEBHOOK_URL", "").strip()
    if not webhook_url:
        if current_errors:
            print("DISCORD_ERROR_WEBHOOK_URL is not configured; source error alerts will be retried later.")
        return

    alerted_by_url = {item.get("source_url"): item for item in retained_errors}
    for source_url, item in current_errors.items():
        prior = alerted_by_url.get(source_url)
        if prior and prior.get("error") == item.get("error"):
            continue
        if send_discord_source_error_notification(webhook_url, source_url, item):
            # Replace a changed error message for this source with the newest
            # successful alert; matching errors remain silent on later runs.
            retained_errors = [entry for entry in retained_errors if entry.get("source_url") != source_url]
            retained_errors.append(source_error_record(source_url, item, timestamp))
            notified["source_errors"] = retained_errors
            save_notified(notified)
            alerted_by_url[source_url] = retained_errors[-1]


def summary_for(title: str, description: str = "") -> str:
    clean_description = description[:180].rstrip()
    return clean_description or f"偵測到可能與羽球場地抽籤相關的公開公告：{title}。請以校方原始公告為準。"

def main() -> None:
    prior = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"sources": {}}
    records = prior.setdefault("sources", {})
    data = load_announcements()
    existing = {
        announcement_storage_key(item): item
        for item in data.get("announcements", [])
        if item.get("source_url")
    }
    backfill_missing_publication_dates(existing)
    taipei = timezone(timedelta(hours=8))
    crawl_scope = os.environ.get("CRAWL_SCOPE", "all").strip().lower()
    with SOURCES.open(encoding="utf-8", newline="") as file:
        rows = [row for row in csv.DictReader(line for line in file if not line.lstrip().startswith("#")) if row.get("enabled", "").lower() == "true"]
        active_urls = {row["source_url"].strip() for row in rows}
        for stale_url in set(records) - active_urls:
            records.pop(stale_url)

        # Status files created before selective crawling did not contain this
        # configuration snapshot. Seed it without needlessly recrawling every
        # existing school on the first source-only update.
        for row in rows:
            url = row["source_url"].strip()
            if url in records and "source_configuration" not in records[url]:
                records[url]["source_configuration"] = source_configuration(row)

        if crawl_scope == "changed":
            rows_to_crawl = [
                row for row in rows
                if records.get(row["source_url"].strip(), {}).get("source_configuration") != source_configuration(row)
            ]
            print(f"Selective source update: crawling {len(rows_to_crawl)} changed or new school source(s).")
        else:
            rows_to_crawl = rows
            print(f"Full scheduled/manual crawl: crawling {len(rows_to_crawl)} school source(s).")

        for row in rows_to_crawl:
            url = row["source_url"].strip()
            try:
                raw_html = get_text(url)
                page = PageExtractor()
                page.feed(raw_html)
                digest = hashlib.sha256(page.text.encode()).hexdigest()
                candidates = []
                government_item = government_rental_item(row["school"], url, page)
                if government_item:
                    candidates.append(government_item["title"])
                    existing[announcement_storage_key(government_item)] = government_item
                    # The venue page repeats downloadable attachments in more
                    # than one section. Its dedicated item is the only notice
                    # users need, so remove attachment-only candidates from
                    # previous runs and skip generic link scanning here.
                    for key, item in list(existing.items()):
                        path = urlsplit(str(item.get("source_url", ""))).path
                        if item.get("school") == row["school"] and path.startswith("/rental/RentalDownload/"):
                            existing.pop(key)
                else:
                    for link in page.links:
                        title = re.sub(r"\s+", " ", link["title"])
                        if is_relevant(title):
                            source_url = urljoin(url, link["url"])
                            published_at = DATE.search(title).group(0) if DATE.search(title) else "日期待確認"
                            if published_at == "日期待確認":
                                published_at = article_published_at(source_url) or published_at
                            candidates.append(title)
                            existing[source_url] = {
                                "school": row["school"],
                                "title": title,
                                "published_at": published_at,
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
                # Google Sites and WordPress sources do not provide the NSS
                # full-text endpoint.  Their ordinary page links are still
                # useful, so a missing optional NSS endpoint must not mark
                # the whole school as unreadable.
                fulltext_items = []
                is_nss_source = "/nss/" in url or "/nss/" in raw_html
                if is_nss_source:
                    try:
                        fulltext_items = nss_fulltext_items(url, raw_html)
                    except Exception as error:
                        print(f"NSS full-text search skipped for {row['school']}: {error}")
                for item in fulltext_items:
                    candidates.append(item["title"])
                    if item.get("replaces_url"):
                        existing.pop(item["replaces_url"], None)
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
                    "source_configuration": source_configuration(row),
                }
            except Exception as error:
                records[url] = {
                    "school": row["school"],
                    "checked_at": datetime.now(taipei).isoformat(timespec="seconds"),
                    "error": str(error),
                    "source_configuration": source_configuration(row),
                }
    STATUS.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data["announcements"] = sorted(existing.values(), key=lambda item: item.get("published_at", ""), reverse=True)
    data["last_updated"] = datetime.now(taipei).strftime("%Y-%m-%d %H:%M（台灣時間）")
    ANNOUNCEMENTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    now = datetime.now(taipei)
    notify_new_announcements(data["announcements"], now)
    notify_source_errors(records, now)
    send_discord_test_notification()
    send_discord_source_error_test_notification()

if __name__ == "__main__": main()
