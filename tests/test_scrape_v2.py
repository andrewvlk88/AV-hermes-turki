"""Test script v2 - test with CloudScraper + different approaches."""
import asyncio
import re
import httpx
from playwright.async_api import async_playwright


async def test_httpx():
    """Test direct HTTP access with various user agents."""
    headers_pc = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    headers_mobile = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    headers_googlebot = {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept": "text/html,application/xhtml+xml",
    }

    stores = [
        ("הטורקי", "https://www.haturki.co.il"),
        ("פונקו", "https://www.funko.co.il"),
        ("בינה", "https://www.bina.co.il"),
        ("היבואן", "https://www.hayebuan.co.il"),
        ("ליקר שופ", "https://www.liquor-shop.co.il"),
        ("וויסקי מרקט", "https://www.whiskymarket.co.il"),
        ("קקטוס", "https://www.cactus.co.il"),
        ("וין בוטיק", "https://www.wineboutique.co.il"),
        ("רויאל ויין", "https://www.royal-wine.co.il"),
        ("ויי שישו", "https://www.myshisho.com"),
        ("וויסקי ישראל", "https://www.whisky-il.com"),
        ("ספיריטס", "https://www.spirits.co.il"),
    ]

    print("=== Testing via httpx (Desktop UA) ===")
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for name, url in stores:
            try:
                resp = await client.get(url, headers=headers_pc)
                status = resp.status_code
                length = len(resp.text)
                title_match = re.search(r'<title>(.*?)</title>', resp.text, re.I | re.DOTALL)
                title = title_match.group(1).strip()[:60] if title_match else "No title"
                print(f"  {status} | {name:12s} | {title}")
            except httpx.ConnectError as e:
                print(f"  ❌  | {name:12s} | ConnectError: {e}")
            except httpx.TimeoutException:
                print(f"  ❌  | {name:12s} | Timeout")
            except Exception as e:
                print(f"  ❌  | {name:12s} | {type(e).__name__}: {str(e)[:40]}")

    print("\n=== Trying search URLs ===")
    searches = [
        ("ביר מרקט", "https://www.beer-market.co.il"),
        ("דרינקס", "https://www.drinks.co.il"),
    ]
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for name, base in searches:
            search_url = f"{base}/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"
            # Try both headers
            for label, hdrs in [("PC", headers_pc), ("Mobile", headers_mobile), ("Googlebot", headers_googlebot)]:
                try:
                    resp = await client.get(search_url, headers=hdrs)
                    prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', resp.text)
                    print(f"  {resp.status_code} | {name:12s} ({label}) | Prices: {prices[:5] if prices else 'none'} | size: {len(resp.text)}")
                except Exception as e:
                    print(f"  ❌  | {name:12s} ({label}) | {type(e).__name__}")


async def test_playwright_smart():
    """Test Playwright with stealthier settings."""
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ]
    )
    
    # Try with stealth via viewport + geolocation
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
        viewport={"width": 1920, "height": 1080},
    )
    
    # Inject JS to hide automation
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['he-IL', 'he', 'en'] });
    """)

    print("\n=== Playwright stealth test ===")
    stores_to_try = [
        "https://www.beer-market.co.il/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1",
    ]
    
    for url in stores_to_try:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await asyncio.sleep(2)
            
            title = await page.title()
            print(f"  Title: {title}")
            
            # Check if Cloudflare or bot detection
            body_text = await page.inner_text("body")
            if "cloudflare" in body_text.lower() or "cf-ray" in body_text.lower():
                print("  ⚠️ Cloudflare detected!")
            
            # Try to find prices
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body_text)
            print(f"  Prices: {prices[:10] if prices else 'none'}")
            
            # Screenshot for debugging
            await page.screenshot(path="debug_screenshot.png")
            print("  📸 Screenshot saved: debug_screenshot.png")
            
        except Exception as e:
            print(f"  ❌ Error: {type(e).__name__}: {str(e)[:80]}")
        finally:
            await page.close()
    
    await browser.close()
    await p.stop()


asyncio.run(test_httpx())
print("\n" + "="*60)
asyncio.run(test_playwright_smart())
