"""Test accessibility and find search URLs for all 20 stores."""
import asyncio
import re
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

STORES = [
    (1, "הטורקי", "https://haturki.com"),
    (2, "פאנקו", "https://www.paneco.co.il"),
    (3, "בנא משקאות", "https://www.banamashkaot.co.il"),
    (4, "היבואן", "https://www.the-importer.co.il"),
    (5, "דרך היין", "https://www.wineroute.co.il"),
    (6, "עולם היין", "https://www.olamhayain.co.il"),
    (7, "שר המשקאות", "https://www.mashkaot.co.il"),
    (8, "אליאסי משקאות", "https://www.eliasi.co.il"),
    (9, "ארי משקאות", "https://www.ari-g.co.il"),
    (10, "Liquor Store", "https://www.liquor-store.co.il"),
    (11, "אלכוהום", "https://www.alcohome.co.il"),
    (12, "משקאות המשמח", "https://www.hamesameach.co.il"),
    (13, "מנו וינו", "https://www.manovino.co.il"),
    (14, "בית המשקאות של אביב", "https://www.avivdrinks.co.il"),
    (15, "Wine & More", "https://www.wineandmore.co.il"),
    (16, "לגימה", "https://www.legima.co.il"),
    (17, "Coffeco", "https://www.coffeco.co.il"),
    (18, "Drinks4U", "https://www.drinks4u.co.il"),
    (19, "Alcohol123", "https://www.alcohol123.co.il"),
    (20, "בית היין", "https://www.winehouse.co.il"),
]

# Common search patterns to try
SEARCH_PATTERNS = [
    "/search?q={query}",
    "/?s={query}&post_type=product",
    "/?s={query}",
    "/catalogsearch/result/?q={query}",
    "/products?search={query}",
    "/search/result/?q={query}",
]


async def test_store(num, name, url):
    """Test a store's homepage and find its search URL."""
    results = []
    
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        # 1. Test homepage
        try:
            resp = await client.get(url, headers=HEADERS)
            title = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.DOTALL)
            title_text = title.group(1).strip()[:60] if title else "No title"
            homepage_ok = resp.status_code == 200
            platform = detect_platform(resp.text)
        except Exception as e:
            return {"num": num, "name": name, "url": url, "status": f"❌ {type(e).__name__}", "title": "", "platform": "", "search_url": "", "works": False}
        
        # 2. Try search patterns (with "ג'ק+דניאלס" encoded)
        query_encoded = "%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"
        found_search = ""
        
        for pattern in SEARCH_PATTERNS:
            search_url = url.rstrip("/") + pattern.replace("{query}", query_encoded)
            try:
                sresp = await client.get(search_url, headers=HEADERS)
                if sresp.status_code == 200 and len(sresp.text) > 1000:
                    prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', sresp.text)
                    if prices:
                        found_search = pattern
                        break
            except:
                continue
        
        if not found_search:
            # Try one more with just the base URL
            for pattern in SEARCH_PATTERNS:
                if pattern in ["/?s={query}&post_type=product", "/?s={query}"]:
                    continue
                search_url = url.rstrip("/") + pattern.replace("{query}", query_encoded)
                try:
                    sresp = await client.get(search_url, headers=HEADERS)
                    if sresp.status_code == 200 and len(sresp.text) > 500:
                        # Check if any search results content
                        body_lower = sresp.text.lower()
                        if "תוצא" in body_lower or "נמצא" in body_lower or "מצאנו" in body_lower:
                            found_search = pattern
                            break
                except:
                    continue
        
        return {
            "num": num,
            "name": name,
            "url": url,
            "status": f"{resp.status_code}" if homepage_ok else f"{resp.status_code}",
            "title": title_text,
            "platform": platform,
            "search_url": found_search,
            "works": homepage_ok,
        }


def detect_platform(html: str) -> str:
    """Detect the e-commerce platform."""
    html_lower = html.lower()
    if "woocommerce" in html_lower or "wc-" in html_lower:
        return "WooCommerce 🛒"
    if "magento" in html_lower:
        return "Magento"
    if "shopify" in html_lower:
        return "Shopify"
    if "wix" in html_lower or "wixstatic" in html_lower:
        return "Wix"
    if "wp-content" in html_lower or "wordpress" in html_lower:
        return "WordPress"
    if "nuxt" in html_lower or "_nuxt" in html_lower:
        return "Nuxt.js (Vue)"
    return "?"


async def main():
    print(f"{'#':>2} | {'חנות':16s} | {'סטטוס':6s} | {'פלטפורמה':18s} | {'חיפוש':30s} | {'כותרת':40s}")
    print("-"*120)
    
    for num, name, url in STORES:
        result = await test_store(num, name, url)
        if result["works"]:
            print(f" {result['num']:>2} | {result['name']:16s} | {result['status']:6s} | {result['platform']:18s} | {result['search_url'] or '❌':30s} | {result['title'][:40]}")
        else:
            print(f" {result['num']:>2} | {result['name']:16s} | ❌     | {'':18s} | {'':30s} | {result['status']}")


asyncio.run(main())
