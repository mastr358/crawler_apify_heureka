# Crawler Plan for Heureka.cz

## 1. Architecture & Technology Stack

To address the high volume (millions of products) and sophisticated anti-scraping protections (Cloudflare, behavioral analysis), we will use the **Apify Python SDK** with **Playwright**.

*   **Language**: Python 3.11+
*   **Core Library**: `apify` (Apify SDK for Python)
*   **Browser Automation**: `playwright` (for rendering, JS execution, and handling Cloudflare challenges)
*   **Proxy**: Apify Proxy (Residential IPs, CZ country code)

### Why Playwright?
While slower than raw HTTP requests, `research.md` indicates that Heureka uses TLS fingerprinting and active JS challenges. A pure HTTP approach (even with `curl-impersonate`) is risky and likely to be "graylisted" quickly. Playwright allows us to:
1.  Pass Cloudflare "Under Attack" modes.
2.  Render dynamic content (prices/stock often loaded via XHR).
3.  Handle CAPTCHAs (via plugins or manual intervention if needed, though we aim to avoid them via proxies).

## 2. Strategy

### A. Queue Management & Discovery
We will use `RequestQueue` to manage the crawl frontier.
*   **Start**: User provides Category URLs.
*   **Category Handler**:
    *   Iterates through pagination.
    *   Extracts Product URLs.
    *   Adds Product URLs to the queue with a unique key (deduplication).
*   **Product Handler**:
    *   Extracts structured data.

### B. Anti-Blocking Measures
1.  **Proxies**: Use Apify Residential Proxies (`groups=['RESIDENTIAL']`, `countryCode='CZ'`). This is non-negotiable.
2.  **Session Rotation**: Rotate sessions frequently to avoid the "100-page trap".
3.  **Browser Fingerprinting**: Use Playwright's stealth plugins (if available/needed) or standard browser profiles.
4.  **Request Throttling**: Although "speed is key", we must respect a reasonable concurrency limit per IP to avoid burning the proxy pool. We will achieve speed through *horizontal scaling* (more concurrent sessions) rather than hammering from a single session.

### C. Performance Optimization
To mitigate the slowness of a full browser:
1.  **Resource Blocking**: Block images, fonts, stylesheets, and media requests (`route.abort()`) to reduce bandwidth and load time.
2.  **Headless Mode**: Run browsers headless.
3.  **Concurrency**: Use `AutoscaledPool` (managed by `PlaywrightCrawler`) to maximize resource usage (CPU/RAM).

## 3. Implementation Steps

### Step 1: Project Structure
Refactor the existing `crawler_apify_heureka.py` to use the modern `PlaywrightCrawler` class instead of the custom `Fetcher`/`Parser` loop.

### Step 2: Router & Handlers
Create a routing logic:
*   `handle_category`:
    *   Selector for product links (e.g., `.product-container a`).
    *   Selector for "Next Page" (e.g., `.pagination .next`).
*   `handle_product`:
    *   Extract `title`, `url`, `rating`, `price`, `store_prices`.
    *   Parse the "store prices" list (often a separate table or list).

### Step 3: Data Extraction Logic
Replace the Markdown parser with a robust CSS/XPath selector extraction logic using `BeautifulSoup` (fed by Playwright's `content()`) or Playwright's own locators.
*   **Fields**:
    *   `title`: `h1`
    *   `rating`: `.rating-value` or similar.
    *   `lowest_price`: Main price tag.
    *   `store_prices`: Iterate over the offers list.

### Step 4: Configuration
*   **Create `requirements.txt`**: The file is currently missing. It must include:
    *   `apify`
    *   `playwright`
    *   `beautifulsoup4`
*   **Create `actor.json`**: Define the actor configuration (docker image, input schema).
*   **Update `Dockerfile`**: Ensure it installs playwright browsers (`RUN playwright install --with-deps chromium`).

## 4. Scalability Note
For "millions" of products, a single Actor run might time out or become unwieldy.
*   **Resurrection**: The `RequestQueue` persists state. If the actor restarts, it resumes where it left off.
*   **Memory**: Ensure we don't accumulate objects in memory.
