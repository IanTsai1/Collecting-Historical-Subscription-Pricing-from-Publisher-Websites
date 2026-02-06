import re
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_CSV = "./data/has_subscribe_pages.csv"
COL = "pricing_url"

MAX_WORKERS = 32
TIMEOUT = 20
RETRIES = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PricingCheckBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CURRENCY_PATTERNS = [
    r"\$(?!\{)\s*\d",
    r"US\$(?!\{)\s*\d",
    r"CA\$(?!\{)\s*\d",
    r"A\$(?!\{)\s*\d",
    r"NZ\$(?!\{)\s*\d",
    r"S\$(?!\{)\s*\d",
    r"HK\$(?!\{)\s*\d",
    r"\\u0024\s*\d",
    r"\\\\u0024\s*\d",
    r"€\s*\d",
    r"£\s*\d",
    r"¥\s*\d",
    r"₩\s*\d",
    r"₽\s*\d",
    r"₺\s*\d",
    r"₫\s*\d",
    r"₴\s*\d",
    r"₪\s*\d",
    r"₱\s*\d",
    r"฿\s*\d",
    r"₹\s*\d",
    r"\\u20b9\s*\d",
    r"\\\\u20b9\s*\d",
    r"&#36;\s*\d",
    r"&dollar;\s*\d",
    r"&#8377;\s*\d",
    r"&#x20b9;\s*\d",
]

CURRENCY_CODE_PATTERNS = [
    r"\bUSD\b", r"\bINR\b", r"\bEUR\b", r"\bGBP\b", r"\bAUD\b", r"\bCAD\b", r"\bNZD\b",
    r"\bSGD\b", r"\bHKD\b", r"\bJPY\b", r"\bCNY\b", r"\bRMB\b", r"\bKRW\b",
    r"\bAED\b", r"\bSAR\b", r"\bZAR\b", r"\bBRL\b", r"\bMXN\b", r"\bIDR\b", r"\bMYR\b",
    r"\bPHP\b", r"\bTHB\b", r"\bVND\b", r"\bTRY\b", r"\bRUB\b", r"\bILS\b", r"\bNGN\b",
    r"\bRs\.?\b", r"\bINR\s?\d", r"\bRs\.?\s?\d", r"\brupees?\b",
]

PRICE_SHAPE_PATTERNS = [
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b",
    r"\b\d+(?:\.\d{1,2})?\s*/\s*(?:mo|month|yr|year|week|day)\b",
    r"\bper\s*(?:month|year|week|day)\b",
    r"\bbilled\s*(?:monthly|annually|yearly|weekly)\b",
]

CURRENCY_RE = re.compile("|".join(CURRENCY_PATTERNS), re.IGNORECASE)
CODES_RE = re.compile("|".join(CURRENCY_CODE_PATTERNS), re.IGNORECASE)
PRICE_SHAPE_RE = re.compile("|".join(PRICE_SHAPE_PATTERNS), re.IGNORECASE)

# Basic JS-render hints (Angular, React, Next.js)
JS_RENDER_HINTS = [
    "ng-app", "ng-controller", "ng-binding",
    "id=\"root\"", "data-reactroot", "id=\"__next\"", "__NEXT_DATA__",
    "window.__INITIAL_STATE__", "app-root",
]

def has_pricing_signal(text: str) -> bool:
    if not text:
        return False
    return bool(CURRENCY_RE.search(text) or CODES_RE.search(text) or PRICE_SHAPE_RE.search(text))

def looks_js_rendered(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in JS_RENDER_HINTS)

def fetch_text_requests(url: str) -> tuple[str, int | None, str]:
    """Return (text, status_code, error) from raw HTML (no JS)."""
    if not url or not isinstance(url, str):
        return "", None, "empty_url"

    last_err = ""
    for _ in range(RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            return (r.text or "", r.status_code, "")
        except Exception as e:
            last_err = str(e)
    return "", None, last_err or "request_failed"

def fetch_text_playwright(url: str, wait_ms: int = 2500) -> tuple[str, str]:
    """
    Return (rendered_html, error). Requires Playwright installed:
      pip install playwright
      python -m playwright install
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return "", f"playwright_import_failed: {e}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=HEADERS)
            page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
            page.wait_for_timeout(wait_ms)
            rendered = page.content() or ""
            browser.close()
            return rendered, ""
    except Exception as e:
        return "", f"playwright_failed: {e}"

def fetch_text(url: str) -> tuple[str, int | None, str, bool]:
    """
    Return (best_text, status_code, error, used_js).
    Strategy:
      1) requests HTML
      2) if no pricing signal and looks JS-rendered, try Playwright, return rendered DOM
    """
    html, status, err = fetch_text_requests(url)
    if err:
        return "", status, err, False

    if has_pricing_signal(html):
        return html, status, "", False

    if looks_js_rendered(html):
        rendered, perr = fetch_text_playwright(url)
        if perr:
            return html, status, f"js_render_needed_but_failed: {perr}", False
        return rendered, status, "", True

    return html, status, "", False

def check_url(url: str, debug: bool = False) -> dict:
    text, status, err, used_js = fetch_text(url)

    if debug:
        print("status:", status, "used_js:", used_js, "error:", err)
        print("len(text):", len(text))
        # Uncomment if you really want to dump HTML
        # print(text[:5000])

    return {
        "url": url,
        "status": status,
        "error": err,
        "used_js": used_js,
        "has_signal": has_pricing_signal(text),
    }


def main():
    df = pd.read_csv(INPUT_CSV)
    if COL not in df.columns:
        raise ValueError(f"CSV missing required column: {COL}")

    urls = (
        df[COL]
        .dropna()
        .astype(str)
        .str.strip()
    )
    # drop empty strings
    urls = urls[urls != ""].tolist()

    no_signal = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check_url, u): u for u in urls}
        for fut in as_completed(futures):
            res = fut.result()
            if not res["has_signal"]:
                # Print only URLs where we can't find any pricing/currency signal
                print(res["url"])
                no_signal.append(res)

    print(f"\nDone. No-signal URLs: {len(no_signal)} out of {len(urls)}")

if __name__ == "__main__":
    main()
