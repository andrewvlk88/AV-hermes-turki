"""Deep test - scrape actual prices from working stores."""
import asyncio
import re
import httpx
from bs4 import BeautifulSoup


SEARCHES = {
    "ג'ק דניאלס": {
        "הטורקי": "https://haturki.com/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1",
        "וין בוטיק": "https://www.wineboutique.co.il/?s=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1&post_type=product",
        "ביר מרקט": "https://www.beer-market.co.il/?s=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1&post_type=product",
        "ביר שופ": "https://www.beershop.co.il/?s=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1&post_type=product",
    },
    "וודקה אבסולוט": {
        "הטורקי": "https://haturki.com/search?q=%D7%95%D7%95%D7%93%D7%A7%D7%94+%D7%90%D7%91%D7%A1%D7%95%D7%9C%D7%95%D7%98",
        "וין בוטיק": "https://www.wineboutique.co.il/?s=%D7%95%D7%95%D7%93%D7%A7%D7%94+%D7%90%D7%91%D7%A1%D7%95%D7%9C%D7%95%D7%98&post_type=product",
    },
    "ג'יימסון": {
        "הטורקי": "https://haturki.com/search?q=%D7%92%27%D7%99%D7%99%D7%9E%D7%A1%D7%95%D7%9F",
        "ביר מרקט": "https://www.beer-market.co.il/?s=%D7%92%27%D7%99%D7%99%D7%9E%D7%A1%D7%95%D7%9F&post_type=product",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}


def extract_prices_bs4(html: str, store_name: str):
    """Extract product listings using BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    products = []
    
    # Try JSON-LD first
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and "Product" in item.get("@type", ""):
                    name = item.get("name", "")
                    offers = item.get("offers", {})
                    if isinstance(offers, dict):
                        price = offers.get("price", "")
                    else:
                        price = offers[0].get("price", "") if offers else ""
                    products.append({"name": name, "price": price, "source": "JSON-LD"})
        except:
            pass
    
    if products:
        return products
    
    # Try finding product containers
    product_selectors = [
        ("div", {"class": re.compile(r"(product|item)", re.I)}),
        ("li", {"class": re.compile(r"(product|item)", re.I)}),
        ("article", {}),
        ("div", {"class": "product-item"}),
        ("div", {"data-product-id": True}),
    ]
    
    for tag, attrs in product_selectors:
        containers = soup.find_all(tag, attrs)
        if containers:
            for c in containers[:10]:
                # Find name
                name = None
                for ntag in ["h2", "h3", "h4", "a", "span"]:
                    el = c.find(ntag, class_=re.compile(r"(name|title)", re.I)) or c.find(ntag)
                    if el and el.get_text(strip=True):
                        name = el.get_text(strip=True)[:100]
                        break
                
                if not name:
                    continue
                    
                # Find price
                html_section = str(c)
                prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', html_section)
                sale = re.search(r'מבצע|sale|הנחה', html_section, re.I)
                
                if prices:
                    products.append({
                        "name": name,
                        "price": prices[0],
                        "sale_price": prices[1] if len(prices) > 1 else None,
                        "is_sale": bool(sale),
                        "source": "HTML"
                    })
            if products:
                break
    
    return products


async def deep_scan():
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for product_name, stores in SEARCHES.items():
            print(f"\n{'='*60}")
            print(f"🔎 {product_name}")
            print(f"{'='*60}")
            
            for store_name, url in stores.items():
                try:
                    resp = await client.get(url, headers=HEADERS)
                    if resp.status_code != 200:
                        print(f"  ❌ {store_name}: HTTP {resp.status_code}")
                        continue
                        
                    products = extract_prices_bs4(resp.text, store_name)
                    if products:
                        print(f"\n  📍 {store_name}:")
                        for p in products[:5]:
                            price_str = f"💰 {p['price']}₪"
                            if p.get('sale_price'):
                                price_str += f" (מבצע: {p['sale_price']}₪)"
                            print(f"    🏷️ {p['name'][:60]}")
                            print(f"       {price_str}")
                    else:
                        # Try regex fallback
                        prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', resp.text)
                        title = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.DOTALL)
                        t = title.group(1).strip()[:40] if title else "?"
                        print(f"\n  📍 {store_name}: No products parsed - Title: {t}")
                        if prices:
                            print(f"    Raw prices found: {prices[:5]}")
                        print(f"    Page size: {len(resp.text)} chars")
                        
                except Exception as e:
                    print(f"  ❌ {store_name}: {type(e).__name__}: {str(e)[:50]}")


asyncio.run(deep_scan())
