import asyncio
import re
from datetime import datetime
from urllib.parse import urljoin

from apify import Actor
from bs4 import BeautifulSoup
import gc  # For garbage collection
from playwright.async_api import Page

# Crawlee SDK (PlaywrightCrawler is in crawlee, not apify)
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

async def main():
    async with Actor:
        Actor.log.info('Actor starting...')
        
        # Get input
        actor_input = await Actor.get_input() or {}
        start_urls_input = actor_input.get('startUrls', [])
        proxy_config = actor_input.get('proxyConfiguration')
        # Support both keys for backward compatibility or user preference
        max_pages = actor_input.get('maxPages') or actor_input.get('maxRequestsPerCrawl', 100)
        max_products = actor_input.get('maxProducts', 1000)
        
        if not start_urls_input:
            Actor.log.warning('No startUrls provided!')
            return
        
        # Extract URLs from startUrls (handle both string and dict format)
        start_urls = []
        for item in start_urls_input:
            if isinstance(item, dict):
                url = item.get('url')
                if url:
                    start_urls.append(url)
            elif isinstance(item, str):
                start_urls.append(item)
        
        if not start_urls:
            Actor.log.warning('No valid URLs found in startUrls!')
            return
        
        Actor.log.info(f'Starting crawl with {len(start_urls)} URLs: {start_urls}')

        # State management for product count
        product_count = 0

        # Create Proxy Configuration
        # Use residential proxies from Czech Republic for bypassing Cloudflare
        proxy_configuration = None
        
        # Check if running on Apify platform
        is_on_platform = Actor.is_at_home()
        
        try:
            if proxy_config and proxy_config.get('useApifyProxy'):
                proxy_configuration = await Actor.create_proxy_configuration(
                    actor_proxy_input=proxy_config
                )
            elif is_on_platform:
                # Default to residential proxies if running on Apify platform
                Actor.log.info('Using default Apify Residential Proxy configuration (CZ)')
                proxy_configuration = await Actor.create_proxy_configuration(
                    groups=['RESIDENTIAL'],
                    country_code='CZ'
                )
        except ConnectionError as e:
            # Proxy access not available (local testing or plan limitation)
            Actor.log.warning(f'Proxy access not available: {e}')
            Actor.log.warning('Running without proxies. Expect Cloudflare blocking (403 errors).')
            proxy_configuration = None

        # Define the request handler
        async def request_handler(context: PlaywrightCrawlingContext):
            nonlocal product_count
            
            # Check product limit
            if max_products and product_count >= max_products:
                Actor.log.info(f"Reached max products limit ({max_products}). Skipping {context.request.url}")
                return

            page: Page = context.page
            request = context.request
            Actor.log.info(f'Processing {request.url} ...')

            # Wait for body to ensure load
            await page.wait_for_selector('body')
            
            # Handle Cloudflare/Bot detection (basic check)
            title = await page.title()
            if "Just a moment" in title or "Access denied" in title:
                Actor.log.error(f"Blocked by Cloudflare: {request.url}")
                # In a real scenario, we might want to retry or rotate session here
                return

            # Determine page type (heuristic)
            # If we explicitly labeled it, use that. Otherwise guess.
            label = request.user_data.get('label', 'DETECT')
            
            if label == 'DETECT':
                # Use Playwright evaluation to detect page type - no BeautifulSoup needed
                is_product = await page.evaluate('''() => {
                    return document.querySelector('.c-product-price__price') !== null || 
                           document.querySelector('.c-offer-list') !== null;
                }''')
                label = 'PRODUCT' if is_product else 'CATEGORY'
            
            # Only parse HTML when we need to extract data
            if label == 'CATEGORY':
                await handle_category_playwright(context, page)
            elif label == 'PRODUCT':
                # For products, we still need soup for complex extraction
                content = await page.content()
                soup = BeautifulSoup(content, 'lxml')
                await handle_product(context, soup)
                soup.decompose()
                del soup
                del content
                gc.collect()

        async def handle_category_playwright(context: PlaywrightCrawlingContext, page: Page):
            """Handle category pages using Playwright evaluation - no BeautifulSoup"""
            request = context.request
            Actor.log.info(f'Scraping Category: {request.url}')
            
            # Utility/non-product domains to ignore
            IGNORE_DOMAINS = [
                'ucet.heureka.cz',
                'checkout.heureka.cz',
                'sluzby.heureka.cz',
                'napoveda.heureka.cz',
                'obchody.heureka.cz',
            ]
            
            # Extract product links using Playwright evaluation (no DOM parsing in Python)
            product_links = await page.evaluate('''(baseUrl) => {
                const links = [];
                const productElements = document.querySelectorAll('a.c-product__link');
                productElements.forEach(a => {
                    const href = a.getAttribute('href');
                    if (href) {
                        // Resolve relative URLs
                        const url = new URL(href, baseUrl).href;
                        if (url.includes('.heureka.cz')) {
                            links.push(url);
                        }
                    }
                });
                return links;
            }''', request.url)
            
            # Filter ignored domains in Python (simpler)
            filtered_links = [
                url for url in product_links 
                if not any(domain in url for domain in IGNORE_DOMAINS)
            ]
            
            # Enqueue in batches
            BATCH_SIZE = 20
            for i in range(0, len(filtered_links), BATCH_SIZE):
                batch = filtered_links[i:i+BATCH_SIZE]
                if batch:
                    await context.enqueue_links(
                        urls=batch,
                        label='PRODUCT',
                        strategy='same-domain'
                    )
            
            Actor.log.info(f"Found {len(filtered_links)} product links")
            
            # Check for pagination
            next_url = await page.evaluate('''() => {
                const nextBtn = document.querySelector('a.c-pagination__link--next, a.next, .pagination a.next');
                return nextBtn ? nextBtn.href : null;
            }''')
            
            if next_url and '.heureka.cz' in next_url:
                if not any(domain in next_url for domain in IGNORE_DOMAINS):
                    Actor.log.info(f"Found pagination link: {next_url}")
                    await context.enqueue_links(
                        urls=[next_url],
                        label='CATEGORY',
                        strategy='same-domain'
                    )

        async def handle_product(context: PlaywrightCrawlingContext, soup: BeautifulSoup):
            nonlocal product_count
            if max_products and product_count >= max_products:
                return

            request = context.request
            Actor.log.info(f'Scraping Product: {request.url}')
            
            # Try to extract from JSON-LD structured data first (most reliable)
            import json
            title = "Unknown"
            rating_value = None
            review_count = None
            lowest_price = "N/A"
            highest_price = "N/A"
            brand = "Unknown"
            store_prices = []
            
            # Find JSON-LD script tag
            json_ld = soup.find('script', {'type': 'application/ld+json'})
            if json_ld:
                try:
                    data_json = json.loads(json_ld.string)
                    # JSON-LD contains @graph array with product data
                    if isinstance(data_json, dict) and '@graph' in data_json:
                        for item in data_json['@graph']:
                            if item.get('@type') == 'Product':
                                title = item.get('name', title)
                                brand = item.get('brand', brand)
                                
                                # Rating
                                agg_rating = item.get('aggregateRating', {})
                                rating_value = agg_rating.get('ratingValue')
                                review_count = agg_rating.get('reviewCount')
                                
                                # Prices
                                offers = item.get('offers', {})
                                if isinstance(offers, dict):
                                    lowest_price = offers.get('lowPrice', lowest_price)
                                    highest_price = offers.get('highPrice', highest_price)
                                    
                                    # Extract individual store offers
                                    offer_list = offers.get('offers', [])
                                    for offer in offer_list[:10]:  # Top 10 offers
                                        if isinstance(offer, dict):
                                            seller = offer.get('seller', {})
                                            store_name = seller.get('name') if isinstance(seller, dict) else "Unknown"
                                            price = offer.get('price')
                                            availability = offer.get('availability', '').split('/')[-1]
                                            
                                            if price:
                                                store_prices.append({
                                                    "store": store_name,
                                                    "price": str(price),
                                                    "currency": "CZK",
                                                    "availability": availability
                                                })
                                break
                except Exception as e:
                    Actor.log.warning(f"Failed to parse JSON-LD: {e}")
            
            # Fallback: Try to extract from HTML if JSON-LD failed
            if title == "Unknown":
                h1 = soup.select_one('h1.c-product-info__name, h1')
                if h1:
                    title = h1.get_text(strip=True)

            data = {
                "url": request.url,
                "title": title,
                "brand": brand,
                "rating": rating_value,
                "review_count": review_count,
                "lowest_price": lowest_price,
                "highest_price": highest_price,
                "currency": "CZK",
                "store_prices": store_prices,
                "crawled_at": datetime.now().isoformat()
            }
            
            await Actor.push_data(data)
            product_count += 1
            Actor.log.info(f"Products fetched: {product_count}/{max_products}")

        # Create the crawler
        crawler = PlaywrightCrawler(
            request_handler=request_handler,
            proxy_configuration=proxy_configuration,
            max_requests_per_crawl=max_pages,
            headless=True,
        )

        # Run the crawler
        await crawler.run(start_urls)
        
        Actor.log.info('Actor finished.')

if __name__ == "__main__":
    asyncio.run(main())
