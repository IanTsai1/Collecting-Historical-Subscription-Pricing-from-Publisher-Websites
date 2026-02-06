# **Task Description: Collecting Historical Subscription Pricing from Publisher Websites (Jan 1, 2021 – Feb 1, 2026)**
## **Overview

Our goal is to collect historical subscription pricing menu data for a large set of online publisher websites. At the end of this task, we want to build a dataset that tracks how subscription prices for digital news and magazine publishers have changed over time.

Your job is to identify which sites offer subscription options and then retrieve their historical pricing pages from Jan 1, 2021 through Feb 1, 2026. As you work through sites, you should also flag practical challenges (e.g., dynamic pricing pages, pop-ups) so we can assess feasibility at scale.

---
## **Input Data**
You will receive two CSV files:
### **1. `news_domains.csv`**
This file contains the list of websites to process (total of 6,491 websites). 
- `domain`: the website domain you should visit
- `domain_normalized`: normalized version of the domain
- `topics`: one or more topic IDs associated with the site
### **2. `news_topics.csv`**
This file maps topic IDs to topic names. This is only provided for context only.

------
## **Deliverables**

Upon task completion, please send us the following:

1. **A CSV dataset** containing all collected pricing information. For websites that do not have available pricing data, record the reason code (separate cases where this is due to website not having a subscription plan, or due to the website could not be crawled).
2. **The code** you used to collect, parse, and clean the data;
3. **A short documentation note** describing any challenges encountered; ambiguous cases and how you resolved them.

------
## **Instructions**
### **1. Load the List of Domains** and Determine the Data Source for Historical Pages
- Read `news_domains.csv`.
- Determine the primary data source you use for extracting historical pages. Examples include the Internet Archive and Common Crawl. Depending on the data source, you may need to deal with traffic limits in a later step.
### **2. Determine Whether the Site Offers a Subscription**
For each domain, check whether the site offers a subscription or membership product. A few methods:

- Look for pages such as `/subscribe`, `/membership`, `/join`, `/pricing`.
- Search the site manually using search engines or archives (see below).
- Look for visible paywalls (e.g., “Subscribe to continue reading”).
- You may either access the current live website or use archived versions (e.g., Wayback Machine), but note that the page location you observe today may differ from historical versions.

If the site does not appear to offer subscriptions, mark it as “no subscription” and move on to the next domain. In addition, some of the websites in the provided list may not be accessible today or even in the archives; when you encounter such cases, make sure to mark them too ("not archived", "inaccessible", etc)
### **3. Identify the Correct Subscription Pricing Page**

For domains that do have subscriptions:

- Identify the **URL of the pricing menu** (e.g., `domain.com/subscribe` or a similar pattern).
- Confirm in the data source for historical pages that this page loads and shows pricing.
- Some websites may have multiple subscription products; your job is to capture whatever prices are displayed on the **main pricing page**.

In addition, as you inspect each site, **record the following indicators**:

- Whether the subscription or pricing page uses **dynamic components**
    - Examples: JavaScript-rendered prices, buttons that require interaction, content that does not appear in static HTML.
- Whether subscription plans are shown only in pop-up windows or overlays.

These flags are important even if pricing data cannot ultimately be collected. They will help us assess the fraction of sites where price detection is straightforward versus difficult.

__Record the final subscription URL you decide on for that domain.__

### **4. Collect Historical Pricing Data**

For the chosen pricing page URL:

1. Use the Wayback Machine calendar view to get all available snapshots from **Jan 1, 2021 to Feb 1, 2026** (inclusive).
2. For each week:
   - Obtain the first available data of each week (Sunday to Saturday) and record the week and the date you are fetching the data from. Ex: In the week of 2025/11/23, say the first available snapshot is on 2025/11/25. Obtain that data and record 2025/11/23 as week and 2025/11/25 as the snapshot date.
   - Download the pricing page.
   - Extract the subscription prices shown on that page.
     - __Capture all price options: e.g., monthly, annual, trial, discount available; whether the price corresponds to digital, print, or print + digital.__
   - __Record the snapshot timestamp__ (e.g., `20220115T023000Z`).
3. For weeks with no snapshots, skip the week. If a page fails to load at a specific timestamp, try the next available timestamp (but still record the reason you skipped).

### **5. Store Data in a Structured CSV Format**

For each timestamped snapshot, record:

- Domain
- Pricing page URL
- Week
- Snapshot timestamp
- Pricing type (monthly, annual, etc.)
- Price shown
- Reason code if prices are ambiguous or not visible

You may design the column structure as long as it is consistent and well-documented.

------

### **6. Final Output**

At project completion, submit:

1. **Final CSV dataset** containing all collected pricing data
2. **Your code**, clearly organized and runnable. 
3. **A short “Challenges & Notes” document**, including:
   - Any deviations from the protocol
   - Any assumptions you had to make

