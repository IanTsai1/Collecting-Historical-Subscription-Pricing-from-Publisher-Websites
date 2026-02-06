import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

PAID_SIGNALS = [
    # access + subscription product phrasing
    "digital subscription",
    "subscriber-only",
    "subscriber only",
    "all access",
    "choose plan",
    "choose a plan",
    "subscribe now",
    "start your trial",
    "free trial",
    "paywall",
    "gain unlimited access",
    "unlimited access to",
    "cancel anytime",
    "cancel or pause anytime",

    # billing language that is very common on subscription pages
    "billed",
    "billing",
    "billed as",
    "every 4 weeks",
    "every four weeks",
    "thereafter",

    # checkout/payment UI signals
    "continue with card",
    "credit card",
    "paypal",
    "checkout",
]

NEWSLETTER_SIGNALS = [
    "newsletter",
    "newsletters",
    "subscribe to our newsletter",
    "subscribe to the newsletter",
    "newsletter sign up",
    "sign up",
    "signup",
    "email",
    "inbox",
    "daily",
    "morning",
    "updates",
    "alerts",
    "manage newsletters",
]

COMMERCE_SIGNALS = [
    "$",
    "credit card",
    "paypal",
    "checkout",
    "continue with card",
    "billed",
    "billing",
    "billed as",
    "every 4 weeks",
    "every four weeks",
    "per month",
    "per year",
    "a week",
    "/week",
    "per week",
    "thereafter",
]

def looks_like_paid_subscription(text: str) -> bool:
    t = text.lower()

    has_newsletter = any(s in t for s in NEWSLETTER_SIGNALS)
    has_paid = any(s in t for s in PAID_SIGNALS)

    # price language: keep this conservative
    has_price = ("$" in t) or ("per month" in t) or ("per year" in t) or ("/week" in t) or (" per week" in t)
    has_commerce = any(s in t for s in COMMERCE_SIGNALS) or has_price

    if has_newsletter and not has_commerce:
        return False

    if not has_commerce:
        return False

    if has_paid:
        return True

    if has_price and ("subscribe" in t or "subscription" in t or "subscriber" in t):
        return True

    return False


def check_domain(domain, timeout=10):
    base_url = f"https://{domain}"

    try:
        r = requests.get(base_url, timeout=timeout)
        if r.status_code >= 400:
            return domain, "inaccessible", ""

        for path in [
            "/subscribe",
            "/subscription",
            "/pricing",
            "/membership",
            "/digital-subscription",
            "/offers",
            "/offer",
            "/account/subscribe",
        ]:
            try:
                url = base_url + path
                r2 = requests.get(url, timeout=timeout, allow_redirects=True)
                if r2.status_code < 400:
                    t2 = BeautifulSoup(r2.text, "html.parser").get_text(" ", strip=True)
                    if looks_like_paid_subscription(t2):
                        return domain, "subscription", r2.url
            except requests.RequestException:
                continue

        home_text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        if looks_like_paid_subscription(home_text):
            return domain, "subscription", base_url

        return domain, "no subscription", base_url

    except requests.RequestException:
        return domain, "inaccessible", ""


def main():
    df = pd.read_csv("./Data/news_domains.csv")
    domains = df["domain"].dropna().unique()

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(check_domain, d) for d in domains]
        for future in as_completed(futures):
            results.append(future.result())

    result_df = pd.DataFrame(results, columns=["domain", "subscription_status", "evidence_url"])
    df = df.merge(result_df, on="domain", how="left")
    df.to_csv("domains_with_subscription_status2.csv", index=False)

if __name__ == "__main__":
    main()
