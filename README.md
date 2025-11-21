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

- download full html of the pages into a temporary folder, we want to be able to run parsing separately when testing it, without having to download all the pages again
- have ability to save progress and state and resume it, we'll be fetching hundreds of thousands of pages, potentially. 