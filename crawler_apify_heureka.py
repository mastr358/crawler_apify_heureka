import asyncio
import re
from datetime import datetime
from urllib.parse import urljoin

from apify import Actor
from apify_client import ApifyClient
from bs4 import BeautifulSoup
from playwright.async_api import Page

# Apify SDK
from apify import Actor
# In newer Apify SDK versions, crawlers might be directly under apify or apify_client is separate.
# However, the standard python sdk usually exposes it. 
# Let's check if we need to install 'apify-client' or if the import path is different.
# Actually, in apify-python-sdk v1.0+, it is `from apify import PlaywrightCrawler`.
from apify import PlaywrightCrawler, PlaywrightCrawlingContext

async def main():
    async with Actor:
        Actor.log.info('Actor starting...')
        
        # Get input
        actor_input = await Actor.get_input() or {}
        start_urls = actor_input.get('startUrls', [])
        proxy_config = actor_input.get('proxyConfiguration')
        # Support both keys for backward compatibility or user preference
        max_pages = actor_input.get('maxPages') or actor_input.get('maxRequestsPerCrawl', 100)
        max_products = actor_input.get('maxProducts', 1000)
        
        if not start_urls:
            Actor.log.warning('No startUrls provided!')
            return

        # State management for product count
        product_count = 0

        # Create Proxy Configuration
        proxy_configuration = await Actor.create_proxy_configuration(
            actor_proxy_input=proxy_config
        )

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
            
            # 1. Enqueue Products
            # Selectors for product links (heuristic based on common Heureka patterns)
            # Usually .c-product__link or similar. We'll look for links inside product containers.
            product_links = []
            for a in soup.select('a.c-product__link, .product-container a.product-name'):
                href = a.get('href')
                if href:
                    product_links.append(urljoin(request.url, href))
            
            # Fallback: Look for any link that looks like a product (often has /product/ or just deep structure)
            if not product_links:
                # Try generic grid items
                for a in soup.select('.c-product-list__item a'):
                    href = a.get('href')
                    if href:
                        product_links.append(urljoin(request.url, href))

            Actor.log.info(f"Found {len(product_links)} products on page.")
            
            await context.enqueue_links(
                urls=product_links,
                label='PRODUCT',
                strategy='same-domain'
            )

            # 2. Enqueue Next Page
            # Look for "Další" or next arrow
            next_page_links = []
            next_btn = soup.select_one('a.c-pagination__link--next, a.next')
            if next_btn and next_btn.get('href'):
                next_page_links.append(urljoin(request.url, next_btn.get('href')))
            
            if next_page_links:
                Actor.log.info(f"Found next page: {next_page_links[0]}")
                await context.enqueue_links(
                    urls=next_page_links,
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
            browser_pool_options={
                "use_fingerprints": True, # Use browser fingerprinting
            }
        )

        # Run the crawler
        await crawler.run(start_urls)
        
        Actor.log.info('Actor finished.')

if __name__ == "__main__":
    asyncio.run(main())
