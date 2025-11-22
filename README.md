Web scraper for heureka.cz, a Czech price aggregator. 

# Requirements 
There are subdomains which exist for every category. 
This has to be scraped first. Then each category is checked for product URLs. After all required categories and subcategories are checked and the product link list is completed and deduplicated, the product crawl can start. The deduplication should happen on a product level, not category level. A product can belong to more than one category. 

Example of a product link:
https://podlahove-myci-stroje.heureka.cz/dyson-wash-g1

# Input of the apify actor:
- one or more category urls to check

# Output of the actor:
- product data in this format:
{
    title,
    url,
    number_of_ratings,
    rating_in_percents,
    lowest_price,
    store_prices: [{
        store_url
        price
    }]
}
- The prices should show only the top offers, not all

# Crawler functionality

- Uses Playwright with browser fingerprinting to bypass Cloudflare protection
- Requires Apify Residential Proxies (Czech Republic) to access Heureka.cz
- Implements automatic session rotation on 403 errors
- Saves progress in RequestQueue for resumable crawling
- Respects maxPages and maxProducts limits

# Proxy Configuration

This crawler requires **Apify Residential Proxies** from Czech Republic to bypass Cloudflare protection.

**Required settings:**
```json
{
  "useApifyProxy": true,
  "apifyProxyGroups": ["RESIDENTIAL"],
  "apifyProxyCountry": "CZ"
}
```

The actor will automatically use these settings by default when running on Apify Platform. 