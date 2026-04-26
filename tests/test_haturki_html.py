"""Test: get HTML from haturki with Playwright and test the scraper."""
import asyncio
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from src.models import Store, ProductPrice


async def get_haturki_html(query="ג'ק דניאלס"):
    """Get the actual rendered HTML from haturki search results."""
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="he-IL",
        viewport={"width": 1920, "height": 1080},
    )
    
    page = await context.new_page()
    search_url = f"https://haturki.com/?s={query.replace(' ', '+')}"
    
    print(f"1. Loading: {search_url}")
    await page.goto(search_url, wait_until="networkidle", timeout=20000)
    await asyncio.sleep(3)
    
    # Get the full HTML after JS rendering
    html = await page.content()
    print(f"2. Got HTML: {len(html):,} chars")
    
    # Save HTML for debugging
    with open("data/haturki_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("3. Saved to data/haturki_debug.html")
    
    # Now manually parse
    soup = BeautifulSoup(html, "lxml")
    
    print("\n4. Finding product items...")
    product_items = soup.find_all("div", class_=re.compile(r"product-item"))
    print(f"   product-item divs: {len(product_items)}")
    
    # Also check other classes
    for cls in ["product", "item", "card"]:
        els = soup.find_all(class_=re.compile(cls, re.I))
        if els:
            print(f"   class containing '{cls}': {len(els)}")
    
    # Check h2/h3/h4 elements - product names
    for tag in ["h2", "h3", "h4", "h5", "h6"]:
        names = soup.find_all(tag)
        print(f"   <{tag}> elements: {len(names)}")
        for n in names[:15]:
            txt = n.get_text(strip=True)
            if txt and len(txt) > 2:
                print(f"      [{txt[:60]}]")
    
    # Check li elements
    lis = soup.find_all("li")
    print(f"\n   <li> elements: {len(lis)}")
    
    # Find elements containing price patterns
    price_count = 0
    for el in soup.find_all(True):  # all elements
        text = el.get_text(strip=True)
        if re.search(r'₪\d+', text) and el.name in ['span', 'div', 'ins', 'bdi']:
            price_count += 1
            if price_count <= 10:
                parent = el.parent
                parent_text = parent.get_text(strip=True)[:120] if parent else ""
                print(f"   💰 [{el.name}] {text[:30]} | Parent: {parent_text[:80]}")
    
    print(f"\n   Total price-containing elements: {price_count}")
    
    # Check all price patterns in raw HTML
    print("\n5. Regex patterns in full HTML:")
    patterns = [
        (r'₪(\d+[\d,]*\.?\d*)', "₪123"),
        (r'(\d+[\d,]*\.?\d*)\s*₪', "123₪"),
        (r'data-price[=]["\'](\d+\.?\d*)', "data-price"),
        (r'"price"\s*:\s*"(\d+\.?\d*)"', '"price":'),
        (r'class=["\'][^"\']*price[^"\']*["\']', 'class="price"'),
    ]
    for pat, label in patterns:
        matches = re.findall(pat, html)
        if matches:
            print(f"   ✅ {label}: {matches[:10]}")
        else:
            print(f"   ❌ {label}: not found")
    
    # Check for product structure
    print("\n6. Data attributes on elements:")
    for attr in ["data-id", "data-product", "data-sku", "data-price"]:
        matches = re.findall(f'{attr}=["\']([^"\']+)["\']', html)
        if matches:
            print(f"   {attr}: {matches[:5]}")
        else:
            print(f"   {attr}: not found")
    
    # Check for JSON data in script tags
    print("\n7. Looking for window.__NUXT__ or similar...")
    scripts_with_data = []
    for script in soup.find_all("script"):
        if script.string and ("__NUXT__" in script.string or "__INITIAL" in script.string or "products" in script.string[:500]):
            scripts_with_data.append(script.string[:200])
    
    for s in scripts_with_data:
        print(f"   Found: {s[:150]}")
    
    if not scripts_with_data:
        # Just check all script tags
        for i, script in enumerate(soup.find_all("script")[:10]):
            content = script.string[:100] if script.string else "(empty)"
            src = script.get("src", "(inline)")
            print(f"   [{i}] src={src[:60]}: {content}")
    
    await browser.close()
    await p.stop()
    return html


asyncio.run(get_haturki_html())
