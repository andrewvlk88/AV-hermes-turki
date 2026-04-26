"""Deep dive into store HTML structure to build proper parsers."""
import asyncio
import httpx
from bs4 import BeautifulSoup
import re


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def analyze_store(name: str, url: str):
    """Fetch a page and dump key structural info."""
    print(f"\n{'='*60}")
    print(f"📋 Analyzing: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # 1. Title
    title = soup.find("title")
    print(f"\n1. Title: {title.string if title else 'N/A'}")
    
    # 2. JSON-LD
    print("\n2. JSON-LD blocks:")
    for i, script in enumerate(soup.find_all("script", type="application/ld+json")):
        content = script.string[:200] if script.string else "Empty"
        print(f"   [{i}] {content}")
    
    # 3. Product containers - look for common patterns
    print(f"\n3. HTML structure analysis:")
    print(f"   Total size: {len(resp.text):,} chars")
    
    # Look for price patterns in the raw HTML
    price_patterns = [
        r'data-price["\']?\s*[:=]\s*["\']?(\d+\.?\d*)',
        r'data-price-amount["\']?\s*[:=]\s*["\']?(\d+\.?\d*)',
        r'product-price[^>]*>?\s*(\d+[\d,]*\.?\d*)',
        r'<span[^>]*price[^>]*>?\s*(\d+[\d,]*\.?\d*)',
        r'<div[^>]*price[^>]*>?\s*(\d+[\d,]*\.?\d*)',
        r'"price"\s*:\s*"(\d+\.?\d*)"',
        r'"price"\s*:\s*(\d+\.?\d*)',
        r'<meta[^>]+property="product:price:amount"[^>]+content="(\d+\.?\d*)"',
    ]
    
    print("\n4. Price data attributes found:")
    price_attrs = re.findall(r'data-[\w-]+(?:price|Price)', resp.text)
    price_attrs_unique = list(set(price_attrs))
    for pa in price_attrs_unique[:15]:
        print(f"   - {pa}")
    
    print("\n5. Class names containing 'price' or 'product':")
    classes = re.findall(r'class=["\'][^"\']*(?:price|product|item-name|product-name)[^"\']*["\']', resp.text, re.I)
    for c in list(set(classes))[:20]:
        print(f"   - {c}")
    
    print(f"\n6. Price matches (regex):")
    for pattern in price_patterns:
        matches = re.findall(pattern, resp.text)
        if matches:
            print(f"   ✅ {pattern[:50]}... → {matches[:5]}")
    
    # 7. Product names in the page
    print("\n7. Product-like elements:")
    for tag in ["h2", "h3", "h4"]:
        els = soup.find_all(tag, limit=10)
        names = [e.get_text(strip=True)[:50] for e in els if e.get_text(strip=True)]
        if names:
            print(f"   <{tag}>: {names[:5]}")
    
    # 8. Check for common e-commerce platforms
    print("\n8. Platform detection:")
    if "woocommerce" in resp.text.lower():
        print("   ✅ WooCommerce")
    if "magento" in resp.text.lower():
        print("   ✅ Magento")
    if "shopify" in resp.text.lower():
        print("   ✅ Shopify")
    if "wp-content" in resp.text.lower():
        print("   ✅ WordPress")
    if "wix" in resp.text.lower():
        print("   ✅ Wix")
    if "selz" in resp.text.lower():
        print("   ✅ Selz")
    if "koko" in resp.text.lower():
        print("   ✅ Koko")


async def main():
    stores = [
        ("הטורקי - דף הבית", "https://haturki.com"),
        ("הטורקי - חיפוש ג'ק דניאלס", "https://haturki.com/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"),
        ("וין בוטיק - חיפוש", "https://www.wineboutique.co.il/?s=%D7%92%27%D7%A7&post_type=product"),
        ("ביר מרקט - חיפוש", "https://www.beer-market.co.il/?s=%D7%92%27%D7%A7&post_type=product"),
    ]
    
    for name, url in stores:
        await analyze_store(name, url)


asyncio.run(main())
