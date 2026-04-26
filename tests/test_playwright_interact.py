"""Use Playwright to interact with stores - type in search box, get real results."""
import asyncio
import re
from playwright.async_api import async_playwright


async def test_haturki():
    """Test haturki.com with real browser interaction."""
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="he-IL",
        viewport={"width": 1920, "height": 1080},
    )
    
    # Monitor network requests to find API endpoints
    api_requests = []
    
    async def on_request(request):
        if "search" in request.url.lower() or "api" in request.url.lower() or "ajax" in request.url.lower():
            api_requests.append({
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
            })
    
    context.on("request", on_request)
    
    page = await context.new_page()
    
    print("1. Navigating to haturki.com...")
    await page.goto("https://haturki.com", wait_until="networkidle", timeout=20000)
    await asyncio.sleep(2)
    
    # Take screenshot
    await page.screenshot(path="haturki_home.png")
    print("   📸 Screenshot saved")
    
    # Find search input
    search_input = await page.query_selector('input[type="search"], input[name="s"], input[placeholder*="חיפוש"], input[name="search"]')
    
    if not search_input:
        # Try any input in a search form
        search_input = await page.query_selector('form[role="search"] input, .search-form input, input.search')
    
    if search_input:
        print(f"2. Found search input! Typing: ג'ק דניאלס")
        await search_input.click()
        await search_input.fill("ג'ק דניאלס")
        await asyncio.sleep(0.5)
        
        # Try Enter key
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)
        
        current_url = page.url
        print(f"   URL after search: {current_url[:120]}")
        
        # Get page content
        await page.screenshot(path="haturki_results.png")
        
        body = await page.inner_text("body")
        prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
        print(f"   Prices found: {prices[:10]}")
        
        # Check if search results are visible
        results_heading = await page.query_selector('h1, h2, h3, .search-results, .products')
        if results_heading:
            print(f"   Results heading: {await results_heading.inner_text()[:60]}")
        
        # Look for product items
        products = await page.query_selector_all('.product-item, .product, [class*="product"]')
        print(f"   Product elements found: {len(products)}")
        
        if products:
            for i, prod in enumerate(products[:5]):
                text = await prod.inner_text()
                print(f"\n   Product {i+1}:")
                print(f"   {text[:200]}")
    else:
        print("2. No search input found on page")
        # Try to go to a search URL directly and see what happens
        await page.goto("https://haturki.com/?s=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(2)
        body = await page.inner_text("body")
        prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
        print(f"   Direct URL prices: {prices[:10]}")
    
    print("\n3. API requests observed:")
    for req in api_requests[:10]:
        print(f"   {req['method']} {req['url'][:120]}")
    
    # Try to find WooCommerce REST API
    print("\n4. Trying WooCommerce API directly...")
    api_urls = [
        "https://haturki.com/wp-json/wc/v3/products?search=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1",
        "https://haturki.com/wp-json/wp/v2/product?search=%D7%92%27%D7%A7",
        "https://haturki.com/?rest_route=/wc/v3/products&search=%D7%92%27%D7%A7",
    ]
    
    for api_url in api_urls:
        api_page = await context.new_page()
        try:
            resp = await api_page.goto(api_url, wait_until="domcontentloaded", timeout=10000)
            body_text = await api_page.inner_text("body")
            if body_text and len(body_text) > 10 and "rest_forbidden" not in body_text.lower():
                print(f"   ✅ WooCommerce API accessible!")
                print(f"   Response: {body_text[:300]}")
                break
            else:
                print(f"   ❌ No access: {api_url.split('?')[0]}")
        except Exception as e:
            print(f"   ❌ {api_url.split('?')[0]}: {type(e).__name__}")
        finally:
            await api_page.close()
    
    await browser.close()
    await p.stop()


async def test_wineboutique():
    """Test wineboutique with Playwright."""
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="he-IL",
        viewport={"width": 1920, "height": 1080},
    )
    
    page = await context.new_page()
    print(f"\n\n=== Wine Boutique ===")
    
    # Go to search page with Playwright
    print("1. Going to search page...")
    await page.goto(
        "https://www.wineboutique.co.il/?s=%D7%92%27%D7%A7&post_type=product",
        wait_until="networkidle", timeout=20000
    )
    await asyncio.sleep(3)
    
    await page.screenshot(path="wineboutique.png")
    
    # Check what's rendered
    body = await page.inner_text("body")
    prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
    print(f"   Prices: {prices[:10]}")
    
    # Look for products
    products_found = []
    
    # Try various selectors
    selectors = [
        ".item-name",
        ".product-item",
        ".product",
        "[class*='product']",
        ".items-in",
        ".sectionitems",
    ]
    
    for sel in selectors:
        els = await page.query_selector_all(sel)
        print(f"   Selector '{sel}': {len(els)} elements")
        if els and not products_found:
            for el in els[:3]:
                text = await el.inner_text()
                products_found.append(text[:200])
    
    for i, p in enumerate(products_found[:5]):
        print(f"\n   Product {i+1}: {p}")
    
    # Try clicking search and submitting
    search_input = await page.query_selector('input[type="text"], input[name="s"]')
    if search_input:
        print("\n2. Trying to type search...")
        await search_input.click()
        await search_input.fill("")
        await asyncio.sleep(0.3)
        await search_input.fill("ג'ק דניאלס")
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)
        print(f"   New URL: {page.url[:120]}")
        
        body2 = await page.inner_text("body")
        prices2 = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body2)
        print(f"   Prices after search: {prices2[:10]}")
    
    await browser.close()
    await p.stop()


async def main():
    await test_haturki()
    await test_wineboutique()


asyncio.run(main())
