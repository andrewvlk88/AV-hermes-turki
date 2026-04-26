"""Test with working stores - those that have valid DNS."""
import asyncio
import re
import httpx

# Stores with confirmed DNS
WORKING_STORES = [
    ("הטורקי", "https://haturki.com"),
    ("קקטוס", "https://www.cactus.co.il"),
    ("וין בוטיק", "https://www.wineboutique.co.il"),
    ("ביר מרקט", "https://www.beer-market.co.il"),
    ("דרינקס", "https://www.drinks.co.il"),
    ("יקב", "https://www.yekev.co.il"),
    ("ביר שופ", "https://www.beershop.co.il"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

SEARCH_QUERY = "%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"  # ג'ק דניאלס


async def test_accessibility():
    """Test which stores are accessible."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        print("=== Store Accessibility ===")
        for name, url in WORKING_STORES:
            try:
                resp = await client.get(url, headers=HEADERS)
                title = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.DOTALL)
                title_text = title.group(1).strip()[:60] if title else "No title"
                print(f"  {resp.status_code} | {name:12s} | {title_text}")
            except Exception as e:
                print(f"  ❌  | {name:12s} | {type(e).__name__}: {str(e)[:50]}")

    print()

    # Now try search URLs
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        print("=== Search URL testing ===")
        for name, base in WORKING_STORES:
            search_patterns = [
                (f"{base}/search?q={SEARCH_QUERY}", "/search?q="),
                (f"{base}/catalogsearch/result/?q={SEARCH_QUERY}", "/catalogsearch/result/?q="),
                (f"{base}/products?search={SEARCH_QUERY}", "/products?search="),
                (f"{base}/?s={SEARCH_QUERY}&post_type=product", "/?s="),
            ]
            
            for search_url, pattern in search_patterns:
                try:
                    resp = await client.get(search_url, headers=HEADERS)
                    prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', resp.text)
                    has_results = resp.status_code == 200 and len(resp.text) > 500
                    
                    if has_results:
                        search_title = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.DOTALL)
                        st = search_title.group(1).strip()[:40] if search_title else "?"
                        price_info = f" | Prices: {prices[:3]}" if prices else ""
                        print(f"  ✅ {name:12s} | {resp.status_code} | {pattern:30s} | {st}{price_info}")
                    # Only show first working pattern
                    if has_results:
                        break
                except Exception as e:
                    pass  # Skip failed patterns silently
            else:
                print(f"  ❌ {name:12s} | No working search pattern found")


asyncio.run(test_accessibility())
