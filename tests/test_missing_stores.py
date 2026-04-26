"""Deep analysis of 6 missing stores - find their product structure."""
import asyncio
import httpx
import re
from bs4 import BeautifulSoup
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html",
    "Accept-Language": "he-IL,he;q=0.9",
}

STORES = [
    ("היבואן", "https://www.the-importer.co.il", "/search?q={query}&limit=20"),
    ("שר המשקאות", "https://www.mashkaot.co.il", "/?s={query}&post_type=product"),
    ("אליאסי משקאות", "https://www.eliasi.co.il", "/?s={query}&post_type=product"),
    ("לגימה", "https://www.legima.co.il", "/?s={query}&post_type=product"),
    ("Drinks4U", "https://www.drinks4u.co.il", "/?s={query}&post_type=product"),
    ("Wine & More", "https://www.wineandmore.co.il", "/search?q={query}"),
    ("בית המשקאות של אביב", "https://www.avivdrinks.co.il", "/search/result/?q={query}"),
    ("מנו וינו", "https://www.manovino.co.il", "/collections/search?q={query}"),
]

QUERY = "%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"

async def analyze(name, url, search_pattern):
    """Fetch the search page and analyze HTML structure for product extraction."""
    full_url = url.rstrip("/") + search_pattern.replace("{query}", QUERY)
    
    print(f"\n{'='*60}")
    print(f"🔍 {name}")
    print(f"{'='*60}")
    
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            resp = await client.get(full_url, headers=HEADERS)
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}")
        return None
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # 1. Title
    title = soup.find("title")
    print(f"\n📌 Title: {title.string.strip()[:60] if title else '?'}")
    print(f"📏 Size: {len(resp.text):,} chars")
    
    # 2. Price patterns in raw HTML
    price_matches = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', resp.text)
    print(f"💰 Price matches: {len(price_matches)} → {price_matches[:10]}")
    
    # 3. Check for product-like class names
    print(f"\n🔎 Class names containing 'product' or 'item':")
    classes = set()
    for tag in soup.find_all(True, class_=True):
        for cls in tag.get("class", []):
            if "product" in cls.lower() or "item-" in cls.lower() or "prod-" in cls.lower():
                classes.add(cls)
    for c in sorted(classes)[:20]:
        print(f"   .{c}")
    
    # 4. Check JSON-LD
    jsonlds = soup.find_all("script", type="application/ld+json")
    print(f"\n📦 JSON-LD blocks: {len(jsonlds)}")
    for j in jsonlds[:2]:
        try:
            data = json.loads(j.string)
            items = data if isinstance(data, list) else [data]
            for item in items[:3]:
                if isinstance(item, dict):
                    t = item.get("@type", "")
                    n = item.get("name", "")[:60]
                    print(f"   [{t}] {n}")
        except:
            print(f"   ❌ parse error")
    
    # 5. Find actual product cards
    print(f"\n🏷️ Product-like containers (class containing product/item/card):")
    containers = soup.find_all(["div", "li", "article"], class_=re.compile(r"(product|item|card)", re.I))
    print(f"   Found: {len(containers)}")
    
    # Check if containers actually have product names and prices
    for c in containers[:5]:
        name_el = c.find(["h2", "h3", "h4", "a", "span", "strong"])
        name = name_el.get_text(strip=True)[:60] if name_el else "?"
        price_el = c.find(class_=re.compile(r"price", re.I))
        price_text = price_el.get_text(strip=True)[:30] if price_el else "?"
        print(f"\n   Container: {c.name}.{'.'.join(c.get('class', []))}")
        print(f"   Name: {name}")
        print(f"   Price: {price_text}")
    
    # 6. Check for WooCommerce/WordPress data attributes
    data_attrs = re.findall(r'data-[\w-]+(?:price|product|id|sku)', resp.text)
    if data_attrs:
        print(f"\n🔖 Data attrs: {sorted(set(data_attrs))[:10]}")
    
    # 7. h2/h3 elements (potential product names)
    print(f"\n📝 Heading elements:")
    for tag in ["h2", "h3", "h4"]:
        for el in soup.find_all(tag)[:8]:
            txt = el.get_text(strip=True)
            if txt and len(txt) > 3 and len(txt) < 80:
                print(f"   <{tag}> {txt}")
    
    # 8. Check for JavaScript data
    for trigger in ["__NUXT__", "__INITIAL", "__DATA__", "window._", "products:", "products ="]:
        if trigger in resp.text:
            start = resp.text.find(trigger)
            snippet = resp.text[start:start+200]
            print(f"\n🔄 Found {trigger}: {snippet[:150]}")
    
    print()


async def main():
    for name, url, pattern in STORES:
        await analyze(name, url, pattern)

asyncio.run(main())
