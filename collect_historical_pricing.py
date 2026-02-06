import re
import threading
from datetime import datetime, timedelta, date
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_CSV = "Data/has_subscribe_pages.csv"
OUTPUT_CSV = "Data/historical_pricing_snapshots.csv"

MAX_WORKERS = 10
TIMEOUT = 10

START_DATE = date(2021, 1, 1)
END_DATE = date(2026, 2, 1)  # inclusive

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

THREAD_LOCAL = threading.local()

def get_session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        THREAD_LOCAL.session = s
    return THREAD_LOCAL.session

def normalize_domain(domain: str) -> str:
    d = str(domain).strip()
    d = d.replace("http://", "").replace("https://", "")
    d = d.split("/")[0]
    return d

def week_start_sunday(d: date) -> date:
    # Python weekday(): Monday=0 ... Sunday=6
    # We want Sunday as start, so subtract (weekday+1)%7
    offset = (d.weekday() + 1) % 7
    return d - timedelta(days=offset)

def ts_to_datetime(ts: str) -> datetime:
    # Wayback timestamps are like YYYYMMDDhhmmss
    return datetime.strptime(ts, "%Y%m%d%H%M%S")

def dt_to_ymd(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def date_to_ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def make_archive_url(timestamp: str, target_url: str) -> str:
    return f"https://web.archive.org/web/{timestamp}/{target_url}"

def cdx_list_snapshots(url: str, start: date, end: date) -> list[tuple[str, datetime]]:
    """
    Uses the CDX API to list snapshots (timestamp, datetime) for a URL in range.
    Filters to status 200 and collapses identical content digests to reduce duplicates.
    """
    params = {
        "url": url,
        "from": start.strftime("%Y%m%d"),
        "to": end.strftime("%Y%m%d"),
        "output": "json",
        "fl": "timestamp,statuscode",
        "filter": "statuscode:200",
        "collapse": "digest",
    }
    api = "https://web.archive.org/cdx/search/cdx"
    try:
        r = get_session().get(api, params=params, timeout=TIMEOUT)
        if r.status_code >= 400:
            return []
        data = r.json()
        if not data or len(data) <= 1:
            return []
        out = []
        for row in data[1:]:
            if not row or len(row) < 1:
                continue
            ts = row[0]
            try:
                out.append((ts, ts_to_datetime(ts)))
            except Exception:
                continue
        out.sort(key=lambda x: x[1])
        return out
    except Exception:
        return []

CURRENCY_SYMBOLS = r"$€£¥₹₩₽₺₪₫฿₱₦₡₲₴₭₮₼₾₨₠₢₣₤₥₦₧₨₩₯₰₱"

AMOUNT_RE = re.compile(
    rf"(?:US)?([{CURRENCY_SYMBOLS}])\s*(\d{{1,5}}(?:\.\d{{2}})?)",
    re.IGNORECASE,
)


ADJ_CURRENCY_RE = re.compile(
    rf"""
    (?:US)?([{CURRENCY_SYMBOLS}])\s*(?P<amount>\d{{1,5}}(?:\.\d{{2}})?)
    (?:\s*<[^>]+>\s*)*
    \s*(?:/|\bper\b)\s*
    (?P<unit>mo|month|yr|year|wk|week|day)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


UNIT_TO_TYPE = {
    "mo": "monthly", "month": "monthly",
    "yr": "annual", "year": "annual",
    "wk": "weekly", "week": "weekly",
    "day": "daily",
}

# Stronger annual cues for your exact issue
ANNUAL_CUES = ["annual rates", "regular annual", "annual rate", "annual", "year"]
MONTHLY_CUES = ["/mo", "/month", "per month", "a month", "monthly", "billed monthly", "month"]
WEEKLY_CUES = ["/wk", "/week", "per week", "weekly", "week"]
DAILY_CUES = ["/day", "per day", "daily"]

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()

def _closest_cue(window: str, price_span: tuple[int, int]):
    """
    Find which cue is closest to the price occurrence inside `window`.
    Returns (ptype, distance) or ("unknown", inf).
    """
    w = _norm(window)
    # price_span is in original window indexing, approximate ok after normalization is tricky,
    # so we compute closeness in the raw window (case-insensitive) instead.
    raw = window.lower()
    start, end = price_span

    best = ("unknown", float("inf"))

    def scan(cues, ptype):
        nonlocal best
        for cue in cues:
            for m in re.finditer(re.escape(cue), raw):
                # distance from cue match to price start (0 if overlaps)
                dist = min(abs(m.start() - start), abs(m.end() - start), abs(m.start() - end), abs(m.end() - end))
                if dist < best[1]:
                    best = (ptype, dist)

    scan(ANNUAL_CUES, "annual")
    scan(MONTHLY_CUES, "monthly")
    scan(WEEKLY_CUES, "weekly")
    scan(DAILY_CUES, "daily")
    return best

def extract_prices_with_context(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()

    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    candidate_tags = ["a", "p", "span", "div", "li", "section", "article", "td", "button", "strong", "em"]

    for el in soup.find_all(candidate_tags):
        txt = " ".join(el.stripped_strings)
        if not txt:
            continue

        el_html = el.decode_contents()

        # Stage A: attached units, authoritative
        for m in ADJ_CURRENCY_RE.finditer(el_html):
            symbol = m.group(1)
            amount = m.group("amount")
            unit = m.group("unit").lower()
            ptype = UNIT_TO_TYPE.get(unit, "unknown")

            unit_norm = {"mo": "month", "yr": "year", "wk": "week"}.get(unit, unit)
            price_shown = f"{symbol}{amount}/{unit_norm}"

            key = (ptype, price_shown)
            if key not in seen:
                seen.add(key)
                results.append(key)

        # Stage B: per-price local window around that amount (NO parent blob)
        # Only add fallback results for amounts not already unit-bound.
        # Make a single raw string for windowing.
        raw = txt  # already flattened, visible text only

        for m in AMOUNT_RE.finditer(raw):
            symbol = m.group(1)
            amount = m.group(2)

            # skip if Stage A already bound this amount in this element
            if any(r[1].startswith(f"${amount}/") for r in results):
                continue

            # Window around this exact match
            w_before = 140
            w_after = 140
            ws = max(0, m.start() - w_before)
            we = min(len(raw), m.end() + w_after)
            window = raw[ws:we]

            

            # Determine closest cue in this window
            # price_span relative to window:
            rel_span = (m.start() - ws, m.end() - ws)
            ptype, dist = _closest_cue(window, rel_span)

            # Extra guard: if we saw "annual rates" or "annual" very close, force annual
            # This handles: "regular annual rates ... $99.99 ... $49.99"
            # Within 80 chars of the price is a good heuristic.
            annual_near = False
            for cue in ANNUAL_CUES:
                idx = window.lower().find(cue)
                if idx != -1:
                    if abs(idx - rel_span[0]) <= 120:
                        annual_near = True
                        break
            if annual_near:
                ptype = "annual"

            key = (ptype, f"{symbol}{amount}")

            if key not in seen:
                seen.add(key)
                results.append(key)

    return results

def fetch_archive_html(archive_url: str) -> tuple[bool, str, str]:
    """
    Returns (ok, html, reason_code)
    """
    try:
        r = get_session().get(archive_url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return False, "", f"http_{r.status_code}"
        # Wayback sometimes returns a wrapper page with a message
        html = r.text or ""
        if not html.strip():
            return False, "", "empty_html"
        return True, html, ""
    except requests.RequestException:
        return False, "", "request_exception"

def group_snapshots_by_week(snapshots: list[tuple[str, datetime]]) -> dict[date, list[tuple[str, datetime]]]:
    by_week: dict[date, list[tuple[str, datetime]]] = {}
    for ts, dt in snapshots:
        wk = week_start_sunday(dt.date())
        by_week.setdefault(wk, []).append((ts, dt))
    # keep each week sorted by datetime
    for wk in by_week:
        by_week[wk].sort(key=lambda x: x[1])
    return by_week

def process_domain(domain: str, pricing_url: str) -> list[dict]:
    d = normalize_domain(domain)
    url = str(pricing_url).strip()
    if not url:
        return []

    snapshots = cdx_list_snapshots(url, START_DATE, END_DATE)
    if not snapshots:
        return [{
            "domain": d,
            "pricing_page_url": url,
            "week_start": "",
            "snapshot_date": "",
            "snapshot_timestamp": "",
            "pricing_type": "",
            "price_shown": "",
            "reason_code": "no_snapshots_in_range",
            "archive_url": "",
        }]

    by_week = group_snapshots_by_week(snapshots)
    rows = []

    for wk_start, snaps in sorted(by_week.items(), key=lambda x: x[0]):
        chosen = None
        chosen_reason = ""
        chosen_html = ""

        # Try snapshots in order until one loads
        for ts, dt in snaps:
            archive_url = make_archive_url(ts, url)
            ok, html, reason = fetch_archive_html(archive_url)
            if ok:
                chosen = (ts, dt, archive_url)
                chosen_html = html
                break
            else:
                chosen_reason = reason  # keep last failure reason

        if not chosen:
            # no snapshot in this week could be loaded
            rows.append({
                "domain": d,
                "pricing_page_url": url,
                "week_start": date_to_ymd(wk_start),
                "snapshot_date": "",
                "snapshot_timestamp": "",
                "pricing_type": "",
                "price_shown": "",
                "reason_code": f"week_all_failed:{chosen_reason or 'unknown'}",
                "archive_url": "",
            })
            continue

        ts, dt, archive_url = chosen
        prices = extract_prices_with_context(chosen_html)

        if not prices:
            rows.append({
                "domain": d,
                "pricing_page_url": url,
                "week_start": date_to_ymd(wk_start),
                "snapshot_date": dt_to_ymd(dt),
                "snapshot_timestamp": ts + "Z",
                "pricing_type": "",
                "price_shown": "",
                "reason_code": "no_prices_visible_static",
                "archive_url": archive_url,
            })
        else:
            for ptype, price in prices:
                rows.append({
                    "domain": d,
                    "pricing_page_url": url,
                    "week_start": date_to_ymd(wk_start),
                    "snapshot_date": dt_to_ymd(dt),
                    "snapshot_timestamp": ts + "Z",
                    "pricing_type": ptype,
                    "price_shown": price,
                    "reason_code": "",
                    "archive_url": archive_url,
                })

    return rows

def main():
    df = pd.read_csv(INPUT_CSV)

    pairs = list(zip(df["domain"].astype(str), df["pricing_url"].astype(str)))

    all_rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_domain, d, u) for d, u in pairs]
        for f in as_completed(futures):
            all_rows.extend(f.result())

    out = pd.DataFrame(all_rows, columns=[
        "domain",
        "pricing_page_url",
        "week_start",
        "snapshot_date",
        "snapshot_timestamp",
        "pricing_type",
        "price_shown",
        "reason_code",
        "archive_url",
    ])

    out.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote: {OUTPUT_CSV}")
    print(f"Domains processed: {len(pairs)}")
    print(f"Rows written: {len(out)}")

if __name__ == "__main__":
    main()
