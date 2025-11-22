import asyncio
import re
from datetime import datetime
from urllib.parse import urljoin

from apify import Actor
from bs4 import BeautifulSoup
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

            # Get content
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Determine page type (heuristic)
            # If we explicitly labeled it, use that. Otherwise guess.
            label = request.user_data.get('label', 'DETECT')
            
            if label == 'DETECT':
                # Simple heuristic: Product pages usually have a "Do obchodu" (Go to store) button or specific price tables
                # Category pages have lists of products.
                if soup.select_one('.c-product-price__price') or soup.select_one('.c-offer-list'):
                    label = 'PRODUCT'
                else:
                    label = 'CATEGORY'
            
            if label == 'CATEGORY':
                await handle_category(context, soup)
            elif label == 'PRODUCT':
                await handle_product(context, soup)

        async def handle_category(context: PlaywrightCrawlingContext, soup: BeautifulSoup):
            request = context.request
            Actor.log.info(f'Scraping Category: {request.url}')
            
            # 1. Enqueue Products - ONLY links with .c-product__link class
            product_links = []
            for a in soup.select('a.c-product__link'):
                href = a.get('href')
                if href:
                    full_url = urljoin(request.url, href)
                    # Only add if it's on heureka.cz subdomain
                    if '.heureka.cz' in full_url:
                        product_links.append(full_url)

            Actor.log.info(f"Found {len(product_links)} product links (.c-product__link)")
            
            if product_links:
                await context.enqueue_links(
                    urls=product_links,
                    label='PRODUCT',
                    strategy='same-domain'
                )

            # 2. Enqueue Pagination (next page) - for finding more product links
            next_btn = soup.select_one('a.c-pagination__link--next, a.next, .pagination a.next')
            if next_btn and next_btn.get('href'):
                next_url = urljoin(request.url, next_btn.get('href'))
                # Only enqueue if it's on heureka.cz
                if '.heureka.cz' in next_url:
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
            
            # Extract Data
            title = soup.select_one('h1').get_text(strip=True) if soup.select_one('h1') else "Unknown"
            
            # Rating
            rating_text = "0"
            rating_elem = soup.select_one('.c-review-count__count, .rating-value')
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True)
            
            # Lowest Price
            price = "N/A"
            price_elem = soup.select_one('.c-price__price, .price-wrapper')
            if price_elem:
                price = price_elem.get_text(strip=True)

            # Store Prices (Top offers)
            store_prices = []
            # Heureka often lists top offers in a specific box
            offers = soup.select('.c-offer-list__item, .shops-list .item')
            for offer in offers[:5]: # Top 5
                store_name_elem = offer.select_one('.c-offer-list__shop-name, .shop-name')
                price_elem = offer.select_one('.c-offer-list__price, .price')
                
                if store_name_elem and price_elem:
                    store_prices.append({
                        "store": store_name_elem.get_text(strip=True),
                        "price": price_elem.get_text(strip=True)
                    })

            data = {
                "url": request.url,
                "title": title,
                "rating": rating_text,
                "lowest_price": price,
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
            # fingerprint_generator='default' enables browser fingerprinting by default
        )

        # Run the crawler
        await crawler.run(start_urls)
        
        Actor.log.info('Actor finished.')

if __name__ == "__main__":
    asyncio.run(main())
