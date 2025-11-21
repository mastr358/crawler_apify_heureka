Heureka is famously one of the toughest nuts to crack in the Czech e-commerce ecosystem. They employ a sophisticated multi-layered defense strategy that combines standard blockers with behavioral analysis.

Here is a technical breakdown of the protections you will face if you build a scraper on Apify:
1. The Primary Wall: Cloudflare & Behavioral Analysis

Heureka sits behind Cloudflare, but it's configured aggressively. It’s not just a static firewall; it actively challenges visitors.

    TLS Fingerprinting (JA3/JA4): If you make a request using standard Python requests or basic Node.js, you will likely get a 403 Forbidden immediately. They sniff the TLS handshake to see if it matches a legitimate browser (Chrome/Safari) or a script implementation
    crawlxpert.com
    .
    Solution: You must use browser-mimicking tools like curl-impersonate or specialized libraries (Scrapy-impersonate, Playwright with stealth plugins) to spoof the TLS fingerprint.

2. Aggressive Rate Limiting (The "100-Page" Trap)

Discussions on Czech developer forums (Webtrh) highlight that standard scrapers often get flagged after as few as 100 requests
webtrh.cz
.

    The Trap: You might succeed for the first minute. Then, your IP gets "graylisted" or "soft-banned" (CAPTCHAs start appearing, or requests time out).
    Solution: High-quality rotating residential proxies are non-negotiable here. Datacenter IPs (which are cheap) are often flagged by default. You need a pool of Czech residential IPs to blend in.

3. Robots.txt & Strategic Blocking

Heureka’s robots.txt is not just a suggestion; it maps out their sensitive zones.

    Denied Areas: They explicitly disallow crawling of search results (/hledat/, ?searchedQuery=), product comparison exits (/exit/), and reviews. This signals that these endpoints have stricter monitoring rules. Hitting them repeatedly is a fast track to a ban
    robotdreams.cz
    .

4. Captcha Challenges

When Cloudflare suspects you (but isn't sure enough to block you), it serves a "Charge" (Turnstile or managed challenge).

    Impact: Your scraper will hang or crash if it can't render JavaScript and solve the visual/crypto challenge.
    Solution: You need a browser-based scraper (Puppeteer/Playwright) that can actually execute the challenge JavaScript, or an external solving service API (like 2Captcha, though these are slow and expensive).

5. "Soft" Data Obfuscation (Inconsistent DOM)

While not a "hard" block, developers report that Heureka's DOM structure can be inconsistent or load essential data (like prices/stock) dynamically via XHR/Fetch requests after the initial page load. If your scraper only grabs the initial HTML, you might miss the actual data fields you need.
Summary for an Apify Build:

If you build a Heureka scraper, you cannot just "fetch HTML". You need an Actor that:

    Uses Browser Fingerprints: Mimics a real user's TLS backlog.
    Manages Proxies: Rotates Czech residential IPs intelligently (not just random rotation, but sticky sessions until failure).
    Emulates Headers: Sends perfect User-Agent, Referer, and Accept-Language headers (cs-CZ).
    Browser-based (Headless): Likely required for passing Cloudflare challenges, even though it's slower/more expensive than raw HTTP requests.