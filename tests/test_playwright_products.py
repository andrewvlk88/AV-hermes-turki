"""Playwright test - find products on haturki.com with proper async handling."""
import asyncio
import re
import json
from playwright.async_api import async_playwright


async def find_haturki_products():
    """Find products on haturki.com by examining the JS-loaded content."""
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="he-IL",
        viewport={"width": 1920, "height": 1080},
    )
    
    page = await context.new_page()
    
    # Intercept XHR requests to find API endpoints
    api_calls = []
    page.on("response", lambda resp: api_calls.append({
        "url": resp.url,
        "status": resp.status,
    }) if "api" in resp.url.lower() or "search" in resp.url.lower() or "product" in resp.url.lower() else None)
    
    print("1. Loading haturki.com...")
    await page.goto("https://haturki.com", wait_until="networkidle", timeout=20000)
    await asyncio.sleep(3)
    
    print("2. Checking API calls...")
    search_apis = [a for a in api_calls if "search" in a["url"].lower()]
    product_apis = [a for a in api_calls if "product" in a["url"].lower()]
    wp_apis = [a for a in api_calls if "wp-json" in a["url"].lower()]
    
    if search_apis:
        print(f"   Search APIs: {[a['url'][:100] for a in search_apis[:5]]}")
    if product_apis:
        print(f"   Product APIs: {[a['url'][:100] for a in product_apis[:5]]}")
    if wp_apis:
        print(f"   WP JSON APIs: {[a['url'][:100] for a in wp_apis[:5]]}")
    
    if not api_calls:
        print("   No API calls observed in initial load")
    
    # Look for products on the homepage
    print("\n3. Looking for products on homepage...")
    
    # Try to find product data in window.__INITIAL_STATE__ or similar
    js_vars = await page.evaluate("""
        () => {
            const data = {};
            // Check for WooCommerce/WordPress globals
            if (window.wc) data.wc = true;
            if (window.wp) data.wp = true;
            if (window.woocommerce) data.woocommerce = true;
            // Check for store data
            for (const key of Object.keys(window)) {
                if (key.toLowerCase().includes('product') || 
                    key.toLowerCase().includes('store') || 
                    key.toLowerCase().includes('search')) {
                    data[key] = true;
                }
            }
            return data;
        }
    """)
    print(f"   JS globals: {js_vars}")
    
    # Click search and submit to see the response
    search_input = await page.query_selector('input[type="search"], input[name="s"], input[placeholder*="חיפוש"]')
    if search_input:
        print("\n4. Typing search...")
        api_calls.clear()
        await search_input.click()
        await search_input.fill("ג'ק דניאלס")
        await asyncio.sleep(1)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)
        
        # Check what happened
        print(f"   URL: {page.url[:120]}")
        
        # Get the page content
        body = await page.inner_text("body")
        prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
        print(f"   Prices on page: {prices[:15]}")
        
        # Find any product containers
        products = await page.query_selector_all('.product-item, .product, .wc-block-grid__product, li.product')
        print(f"   Product elements: {len(products)}")
        
        if products:
            for i, prod in enumerate(products[:5]):
                text = await prod.inner_text()
                print(f"\n   [{i}] {text[:200]}")
        else:
            # Try to find all elements with prices near them
            price_elements = await page.query_selector_all('[class*="price"], .amount, .woocommerce-Price-amount')
            print(f"   Price elements: {len(price_elements)}")
            for pe in price_elements[:5]:
                text = await pe.inner_text()
                print(f"   💰 {text[:60]}")
    
    # Try WooCommerce REST API directly
    print("\n5. Trying WooCommerce API endpoints...")
    wp_product_urls = [
        "https://haturki.com/wp-json/wc/v3/products?search=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1",
        "https://haturki.com/wp-json/wc/store/products?search=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1",
    ]
    for url in wp_product_urls:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        if resp:
            try:
                text = await page.inner_text("body")
                if text and len(text) > 10 and "rest_forbidden" not in text.lower() and "code" not in text[:50].lower():
                    print(f"   ✅ {url.split('?')[0]} - Got data!")
                    print(f"   Response: {text[:500]}")
                    break
                else:
                    print(f"   ❌ {url.split('?')[0]} - No access: {text[:100]}")
            except:
                print(f"   ❌ {url.split('?')[0]} - Error reading response")
    
    await browser.close()
    await p.stop()


async def test_wineboutique_playwright():
    """Test wineboutique with Playwright."""
    print(f"\n{'='*50}")
    print("Wine Boutique")
    print(f"{'='*50}")
    
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    
    page = await context.new_page()
    
    # Go to search results URL
    await page.goto(
        "https://www.wineboutique.co.il/?s=%D7%92%27%D7%A7&post_type=product",
        wait_until="networkidle", timeout=20000
    )
    await asyncio.sleep(3)
    
    await page.screenshot(path="wineboutique_results.png")
    
    body = await page.inner_text("body")
    prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
    print(f"Prices: {prices[:10]}")
    
    # Look for product elements with class .item-name
    items = await page.query_selector_all('.item-name')
    print(f"item-name elements: {len(items)}")
    for item in items[:5]:
        text = await item.inner_text()
        print(f"  🏷️ {text[:80]}")
    
    # Look for price elements
    price_els = await page.query_selector_all('[class*="price"], .number-price, .item-price')
    print(f"Price elements: {len(price_els)}")
    for pe in price_els[:5]:
        text = await pe.inner_text()
        print(f"  💰 {text[:50]}")
    
    # Check for data attributes
    all_elements = await page.query_selector_all('[class*="product"]')
    print(f"Product-class elements: {len(all_elements)}")
    for el in all_elements[:3]:
        html = await el.inner_html()
        print(f"  HTML: {html[:200]}")
    
    await browser.close()
    await p.stop()


async def main():
    await find_haturki_products()
    await test_wineboutique_playwright()


asyncio.run(main())
