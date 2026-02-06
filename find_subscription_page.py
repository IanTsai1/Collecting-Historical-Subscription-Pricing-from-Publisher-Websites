import re
import threading
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_CSV = "Data/domains_with_subscription_status.csv"
OUTPUT_CSV = "Data/domains_with_pricing_page.csv"

MAX_WORKERS = 24
TIMEOUT = 8

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

COMMON_PRICING_PATHS = [
    "/subscribe",
    "/subscriptions",
    "/subscription",
    "/membership",
    "/memberships",
    "/join",
    "/pricing",
    "/plans",
    "/account/subscribe",
    "/checkout",
    "/digital-subscription",
    "/digital",
    "/subscribe/",
    "/subscription/",
    "/paywall",
    "/offers",
    "/offer"
]

LINK_KEYWORDS = [
    "subscribe",
    "subscription",
    "membership",
    "join",
    "pricing",
    "plan",
]

PRICE_REGEX = re.compile(
    r"(?:(?:US)?\$\s?\d+(?:\.\d{2})?)|(?:\d+(?:\.\d{2})?\s?/(?:mo|month|yr|year))",
    re.IGNORECASE
)

THREAD_LOCAL = threading.local()

def get_session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        THREAD_LOCAL.session = s
    return THREAD_LOCAL.session

def safe_get(url: str) -> requests.Response | None:
    try:
        return get_session().get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None

def normalize_domain(domain: str) -> str:
    d = str(domain).strip()
    d = d.replace("http://", "").replace("https://", "")
    d = d.split("/")[0]
    return d

def get_base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}"

def looks_dynamic(html: str, text: str) -> bool:
    h = html.lower()
    t = text.lower()

    # Signals that the content is likely JS-driven, paywalls often do this
    dynamic_markers = [
        "id=\"__next\"",
        "id=\"__nuxt\"",
        "data-reactroot",
        "react",
        "webpack",
        "window.__",
        "application/json",
        "type=\"module\"",
        "ng-app",
        "angular",
        "svelte",
    ]

    # If page says subscribe but no prices in static text, could be JS-rendered
    mentions_subscribe = any(k in t for k in ["subscribe", "subscription", "membership", "plan"])
    has_price = bool(PRICE_REGEX.search(text))

    if any(m in h for m in dynamic_markers):
        return True

    if mentions_subscribe and not has_price and ("script" in h):
        return True

    return False

def looks_popup_or_overlay(html: str) -> bool:
    h = html.lower()
    overlay_markers = [
        "modal",
        "overlay",
        "dialog",
        "lightbox",
        "popup",
        "pop-up",
        "aria-modal=\"true\"",
        "role=\"dialog\"",
        "data-testid=\"modal\"",
        "drawer",
    ]
    return any(m in h for m in overlay_markers)

def extract_prices(text: str) -> list[str]:
    found = PRICE_REGEX.findall(text)
    cleaned = []
    for s in found:
        s2 = re.sub(r"\s+", " ", s).strip()
        if s2 and s2 not in cleaned:
            cleaned.append(s2)
    return cleaned[:25]

def is_same_domain(url: str, domain: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        d = normalize_domain(domain).lower()
        return host.endswith(d)
    except Exception:
        return False

def find_candidate_links_from_homepage(home_url: str, domain: str) -> list[str]:
    r = safe_get(home_url)
    if not r or r.status_code >= 400:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = (a.get_text(" ") or "").strip().lower()
        href_l = href.lower()

        if not href or href.startswith("mailto:") or href.startswith("javascript:"):
            continue

        if any(k in href_l for k in LINK_KEYWORDS):
            full = urljoin(home_url, href)
            if is_same_domain(full, domain):
                links.append(full)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:25]

SUBSCRIPTION_PAGE_KEYWORDS = [
    "subscribe", "subscription", "digital subscription", "unlimited access",
    "trial", "start your trial", "monthly", "annual", "billing", "renew",
    "cancel", "newsletter", "account", "sign in", "log in"
]

BAD_PATH_HINTS = [
    "/article/", "/news/", "/sports/", "/weather/", "/video/", "/watch/",
    "/money/", "/consumer/", "/entertainment/", "/local/", "/traffic/",
]

def looks_like_news_article_url(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in BAD_PATH_HINTS)

def is_likely_subscription_page(text: str, prices: list[str]) -> bool:
    t = text.lower()
    kw_hits = sum(1 for k in SUBSCRIPTION_PAGE_KEYWORDS if k in t)
    # Require at least 2 strong signals, or 1 signal plus at least one price
    if kw_hits >= 2:
        return True
    if kw_hits >= 1 and len(prices) > 0:
        return True
    return False


def pick_pricing_url(domain: str) -> tuple[str, str]:
    """
    Returns (pricing_url, method)
    method: "common_path" | "homepage_link" | "fallback_homepage" | "none"
    """
    base = get_base_url(domain)

    # Try common known pricing paths first
    for path in COMMON_PRICING_PATHS:
        url = base + path
        r = safe_get(url)
        if r and r.status_code < 400:
            return r.url, "common_path"

    # Scan homepage for a pricing/subscription link
    candidates = find_candidate_links_from_homepage(base, domain)
    for u in candidates:
        if looks_like_news_article_url(u):
            continue

        r = safe_get(u)
        if not r or r.status_code >= 400:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        prices = extract_prices(text)

        # Only accept if page content looks like subscription checkout/info
        if is_likely_subscription_page(text, prices):
            return r.url, "homepage_link"


    # Fallback: if homepage clearly has subscription language, treat it as the best URL we have
    r = safe_get(base)
    if r and r.status_code < 400:
        return r.url, "fallback_homepage"

    return "", "none"

def wayback_available(url: str) -> tuple[bool, str]:
    """
    Returns (available, archived_url)
    Uses Wayback availability endpoint.
    """
    api = "https://archive.org/wayback/available"
    try:
        resp = get_session().get(api, params={"url": url}, timeout=TIMEOUT)
        if resp.status_code >= 400:
            return False, ""
        data = resp.json()
        snap = data.get("archived_snapshots", {}).get("closest")
        if snap and snap.get("available") and snap.get("url"):
            return True, snap["url"]
        return False, ""
    except Exception:
        return False, ""

def inspect_pricing_page(url: str) -> dict:
    r = safe_get(url)
    if not r or r.status_code >= 400:
        return {
            "page_ok": False,
            "final_url": url,
            "dynamic_components": "",
            "popup_overlay": "",
            "detected_prices": "",
            "notes": f"pricing page inaccessible (status={getattr(r, 'status_code', 'no_response')})",
        }

    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    prices = extract_prices(text)
    dyn = looks_dynamic(html, text)
    popup = looks_popup_or_overlay(html)

    notes = []
    if not prices and any(k in text.lower() for k in ["subscribe", "membership", "plan", "pricing"]):
        notes.append("no prices found in static HTML")
    if dyn:
        notes.append("likely JS-rendered content")
    if popup:
        notes.append("possible modal or overlay UI")

    return {
        "page_ok": True,
        "final_url": r.url,
        "dynamic_components": "yes" if dyn else "no",
        "popup_overlay": "yes" if popup else "no",
        "detected_prices": "; ".join(prices),
        "notes": " | ".join(notes),
    }

def process_domain(domain: str) -> dict:
    d = normalize_domain(domain)
    pricing_url, method = pick_pricing_url(d)

    if not pricing_url:
        return {
            "domain": d,
            "pricing_url": "",
            "pricing_url_method": method,
            "pricing_page_ok": "no",
            "dynamic_components": "",
            "popup_overlay": "",
            "detected_prices": "",
            "wayback_available": "no",
            "wayback_url": "",
            "wayback_page_ok": "no",
            "notes": "could not determine pricing URL",
        }

    live_info = inspect_pricing_page(pricing_url)

    wb_avail, wb_url = wayback_available(pricing_url) if pricing_url else (False, "")
    wb_info = {"page_ok": False}
    if wb_avail and wb_url:
        wb_info = inspect_pricing_page(wb_url)

    return {
        "domain": d,
        "pricing_url": live_info.get("final_url", pricing_url),
        "pricing_url_method": method,
        "pricing_page_ok": "yes" if live_info.get("page_ok") else "no",
        "dynamic_components": live_info.get("dynamic_components", ""),
        "popup_overlay": live_info.get("popup_overlay", ""),
        "detected_prices": live_info.get("detected_prices", ""),
        "wayback_available": "yes" if wb_avail else "no",
        "wayback_url": wb_url,
        "wayback_page_ok": "yes" if wb_info.get("page_ok") else "no",
        "notes": (live_info.get("notes", "") or "").strip(),
    }

def main():
    df = pd.read_csv(INPUT_CSV)

    # Only process domains that are flagged as having subscriptions
    subs_df = df[df["subscription_status"].astype(str).str.lower() == "subscription"].copy()
    domains = subs_df["domain"].dropna().astype(str).unique().tolist()

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_domain, d): d for d in domains}
        for f in as_completed(futures):
            results.append(f.result())

    add_df = pd.DataFrame(results)

    # Merge back into original rows, so you keep all domains
    out = df.merge(add_df, on="domain", how="left")

    # Save
    out.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote: {OUTPUT_CSV}")
    print(f"Processed subscription domains: {len(domains)}")

if __name__ == "__main__":
    main()
