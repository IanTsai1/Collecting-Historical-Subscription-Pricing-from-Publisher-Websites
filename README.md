# Historical Subscription Pricing Data Collection

## Project Overview

This project collects historical subscription pricing data from publisher websites spanning **January 1, 2021 through February 1, 2026**. The pipeline consists of three main Python scripts that progressively identify subscription offerings and extract their pricing information from Internet Archive (Wayback Machine) snapshots.

**Goal:** Build a dataset that tracks how subscription prices for digital news and magazine publishers have changed over time.

---

## Deliverables

Upon completion, this project produces:

1. **`historical_pricing_snapshots.csv`** – Final CSV dataset containing all collected pricing information
    - currently in progress, due to difficulty in accessing Wayback Machine API
2. **Three Python scripts** – Self-contained, documented, runnable code
3. **`CHALLENGES.md`** – Documentation of challenges, deviations, and assumptions

---

## File Structure & Pipeline Logic

### **1. `check_site_subscription.py`**

**Purpose:** Determine which domains offer subscription products.

**Code Logic:**
- Iterates through all ~6,491 domains in `news_domains.csv`
- Makes HTTP requests to each domain's homepage and scans common subscription paths:
  - `/subscribe`, `/subscription`, `/membership`, `/join`, `/pricing`, `/plans`, `/account/subscribe`, `/checkout`, `/digital-subscription`, `/offers`
  
- **Heuristic Text Matching** to detect paid subscription signals:
  - **Paid signals:** "digital subscription", "subscriber-only", "choose plan", "subscribe now", "free trial", "paywall", "billed", "billing", "billed as", "every 4 weeks", "cancel anytime", "credit card", "paypal", "checkout"
  - **Newsletter signals:** "newsletter", "email", "inbox", "daily", "sign up"
  - **Commerce signals:** "$", "credit card", "paypal", "per month", "per year", "/week"

- **Smart filtering:** Distinguishes paid subscriptions from free newsletters:
  - If page has newsletter language BUT no commerce signals → marked as "no subscription"
  - If page lacks both newsletter and commerce signals → marked as "no subscription"
  - Only flags as subscription if it has commerce + specific paid language

- **Output:** `domains_with_subscription_status.csv`
  - Columns: `domain`, `subscription_status` (subscription/no subscription/inaccessible), `evidence_url`
  - Uses `ThreadPoolExecutor` with 20 workers for parallel processing

**Key Decision:** Conservative filtering to avoid treating free newsletters as paid subscriptions.

---

### **2. `find_subscription_page.py`**

**Purpose:** Locate the specific pricing page URL and assess its accessibility/complexity.

**Code Logic:**

**Step 1: Identify Pricing Page URL**
- Filters input to only domains marked as having subscriptions
- Systematically searches for pricing page in this order:
  1. **Common paths first** – tries known pricing paths (`/subscribe`, `/pricing`, `/plans`, etc.)
  2. **Homepage link scanning** – extracts all links from homepage containing keywords: "subscribe", "subscription", "membership", "join", "pricing", "plan"
  3. **Fallback** – returns homepage if no dedicated pricing page found
  4. If all fail → returns "none"

**Step 2: Inspect Pricing Page for Metadata**

Once a URL identified, the script inspects the page for **feasibility indicators:**

- **`dynamic_components`** – Detects JavaScript-rendered content:
  - Markers: `id="__next"`, `id="__nuxt"`, `data-reactroot`, React/webpack code, Angular, Svelte
  - Logic: If page mentions "subscribe" but has no price in static text AND contains script tags → likely JS-rendered
  - **Implication:** Static HTML parsing may fail; prices only appear after JS execution

- **`popup_overlay`** – Flags modal/dialog UI patterns:
  - Markers: `modal`, `overlay`, `dialog`, `lightbox`, `popup`, `aria-modal="true"`, `role="dialog"`
  - **Implication:** Pricing may be behind user interaction; Wayback snapshot may not show it

- **`detected_prices`** – Extracts visible price strings using regex:
  - Pattern: `$\d+(\.\d{2})?` or `\d+/mo|month|yr|year` format
  - Confirms page relevance

- **Wayback Availability Check** – Uses Archive.org API to verify page is archived

**Output:** `domains_with_pricing_page1.csv`
- Columns: `domain`, `pricing_url`, `pricing_url_method`, `pricing_page_ok`, `dynamic_components`, `popup_overlay`, `detected_prices`, `wayback_available`, `wayback_url`, `wayback_page_ok`, `notes`
- Uses `ThreadPoolExecutor` with 24 workers for parallel processing

**Key Decisions:**
- Performed manual filtering after running this program to ensure high data quality

---

### **3. `collect_historical_pricing.py`**

**Purpose:** Extract historical pricing from Wayback Machine snapshots (Jan 1, 2021 – Feb 1, 2026).

**Code Logic:**

**§ Phase 1: Snapshot Discovery (CDX API)**

- Uses **CDX API** (https://web.archive.org/cdx/search/cdx) to query Wayback Machine for all snapshots of each pricing page
- Parameters:
  - Date range: Jan 1, 2021 to Feb 1, 2026 (inclusive)
  - HTTP status filter: 200 only (successful responses)

- **Returns:** List of (timestamp, datetime) tuples sorted chronologically

**§ Phase 2: Weekly Grouping & First Snapshot Selection**

- Groups snapshots by week (Sunday–Saturday) using `week_start_sunday()` function
- For each week, selects **first available snapshot**
- If snapshot fails to load, tries next available snapshot in that week
- Records failure reason if all snapshots fail: `week_all_failed:reason_code`

**§ Phase 3: Price Extraction**

Implements a **two-stage price detection pipeline** for robustness:

**Stage A: Context-Aware Extraction** (High Confidence)
```
Pattern: [Currency][Amount]/[Unit] within same HTML element
Examples: $99/month, €10.99/year
```
- Uses regex: `[{CURRENCY_SYMBOLS}]\s*(\d{1,5}(?:\.\d{2})?)\s*/\s*(?:mo|month|yr|year|wk|week|day)`
- Directly assigns pricing type (monthly/annual/weekly/daily) from unit
- **Advantage:** No ambiguity; unit explicitly stated

**Stage B: Windowing + Proximity Detection** (Context Inference)
```
For standalone prices without units: $99, £59.99
```
1. Extracts 140-character context window before and after price
2. Scans window for semantic cues:
   - Annual cues: "annual rates", "annual rate", "annual", "year"
   - Monthly cues: "/mo", "/month", "per month", "a month", "monthly", "billed monthly"
   - Weekly cues: "/wk", "/week", "per week", "weekly"
   - Daily cues: "/day", "per day", "daily"

3. **Distance calculation:** Finds closest cue to price occurrence
   - Computes character distance from cue start/end to price start/end
   - Assigns type based on closest cue (minimum distance)
   

- **Advantage:** Handles flexible layouts; prices separated from unit labels

**§ Phase 4: Output Format**

Each row represents **one price found in one snapshot**:

| Column | Example | Purpose |
|--------|---------|---------|
| `domain` | example.com | Publisher domain |
| `pricing_page_url` | https://example.com/subscribe | Final URL accessed |
| `week_start` | 2025-11-23 | Week start (Sunday) |
| `snapshot_date` | 2025-11-25 | Actual snapshot date fetched |
| `snapshot_timestamp` | 20251125T143022Z | Wayback timestamp |
| `pricing_type` | monthly, annual, unknown | Billing period detected |
| `price_shown` | $99, €10.99 | Currency + amount |
| `reason_code` | no_snapshots_in_range, no_prices_visible_static | Explanation if price missing |
| `archive_url` | https://web.archive.org/web/... | Full Wayback link |

**§ Concurrency & Performance**

- `ThreadPoolExecutor` with 10 workers for parallel domain processing
- Thread-local session management ensures connection reuse and thread safety
- `TIMEOUT = 10` seconds per request to handle slow/unresponsive servers

**Output:** `historical_pricing_snapshots.csv`

**Problem:**


**Challenges:**
- snapshots 
        - CDX API used to access Wayback Machine seems to have an API limit or server problem, so I can't test my updated code 
- each page might have two product; how do you differntiate between the two
    - digital access
    - unlimited digital access


---

## Data Flow Diagram

```
news_domains.csv
    │
    ├─ Columns: domain, domain_normalized, topics
    │
    ↓
[check_site_subscription.py]
    │ • Requests: homepage + /subscribe, /pricing, /membership, etc.
    │ • Heuristic text matching: paid vs. newsletter signals
    │ • Parallel: ThreadPoolExecutor(20 workers)
    │
    ↓
domains_with_subscription_status.csv
    │ Columns: domain, subscription_status, evidence_url
    │
    ↓
[find_subscription_page.py]
    │ • Filters: only "subscription" status domains
    │ • Searches: common paths → homepage links → fallback
    │ • Inspects: dynamic components, popups, prices
    │ • Checks: Wayback availability
    │ • Parallel: ThreadPoolExecutor(24 workers)
    │
manual filtering of price url
    | • clicked into every url to ensure data quality is good
    ↓
domains_with_pricing_page.csv
    │ Columns: domain, pricing_url, dynamic_components, popup_overlay,
    │          detected_prices, wayback_available, notes
    │
    ↓
[collect_historical_pricing.py]
    │ • CDX API: Query Wayback snapshots (2021–2026)
    │ • Weekly grouping: Select first snapshot per week
    │ • Stage A: Extract $X/month patterns
    │ • Stage B: Infer type from context window
    │ • Parallel: ThreadPoolExecutor(10 workers)
    │
    ↓
historical_pricing_snapshots.csv ← FINAL OUTPUT
    Columns: domain, pricing_page_url, week_start, snapshot_date,
             snapshot_timestamp, pricing_type, price_shown, reason_code,
             archive_url
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Wayback Machine (CDX API)** | Scalable, comprehensive historical coverage 2021–2026, no authentication required BUT there might be a rate limit? |
| **Stage A + Stage B extraction** | Handles both well-marked prices (e.g., "$99/month") and contextually-inferred pricing (e.g., "$99" near "annual") for maximum recall |
| **Proximity-based cue matching** | Robust to layout variations, HTML wrapping, and scattered text; distance metric provides confidence scoring |
| **Thread-local sessions** | Ensures thread safety while having optimization; connection pooling speeds up parallel requests |
| **Reason codes** | Enables debugging, analysis of failure modes, and quality assessment |
| **Collapse by digest** | CDX API deduplicates identical snapshots by content hash; reduces processing of redundant captures |
| **Newsletter filtering** | Conservatively distinguishes free newsletters from paid subscriptions to avoid false positives |

---

## Input Files Required

Place in `/Users/Ian/Desktop/Research/Data/` directory:
- **`news_domains.csv`** (6,491 domains)
  - Columns: `domain`, `domain_normalized`, `topics`

---

## Running the Pipeline

```bash
# Navigate to project directory
cd /Users/Ian/Desktop/Research

# Execute scripts in sequence
python3 check_site_subscription.py
python3 find_subscription_page.py
python3 collect_historical_pricing.py

# Check results
ls -lh Data/domains_with_subscription_status.csv
ls -lh Data/domains_with_pricing_page.csv
ls -lh Data/historical_pricing_snapshots.csv
```

Each script reads from the previous output and writes its results to a new CSV.

---

## Dependencies

```bash
pip install requests pandas beautifulsoup4
```

- **requests** – HTTP requests to domains and Wayback API
- **pandas** – CSV reading/writing, data manipulation
- **beautifulsoup4** – HTML parsing for text extraction and link detection

---

## Output Summary

**Final dataset columns:**

```
domain,
pricing_page_url,
week_start,
snapshot_date,
snapshot_timestamp,
pricing_type,
price_shown,
reason_code,
archive_url
```

**Example rows:**

| domain | pricing_type | price_shown | week_start | snapshot_timestamp |
|--------|--------------|-------------|------------|-------------------|
| nytimes.com | monthly | $17 | 2025-11-23 | 20251125T143022Z |
| nytimes.com | annual | $199 | 2025-11-23 | 20251125T143022Z |
| wsj.com | monthly | $39.99 | 2025-11-30 | 20251201T085431Z |
| bbc.com | | | 2025-12-07 | | no_snapshots_in_range |

---

## Documentation

See **`CHALLENGES.md`** for:
- Deviations from protocol
- Assumptions made
- Edge cases encountered
- Ambiguity resolution strategies
- Known limitations
