"""Test script - verify Playwright scraping works on Israeli alcohol stores."""
import asyncio
import re
from playwright.async_api import async_playwright


STORES = [
    ("ביר מרקט", "https://www.beer-market.co.il/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"),
    ("דרינקס", "https://www.drinks.co.il/search?q=%D7%92%27%D7%A7+%D7%93%D7%A0%D7%99%D7%90%D7%9C%D7%A1"),
]

# Direct store URLs
STORE_URLS = [
    ("הטורקי", "https://www.haturki.co.il"),
    ("פונקו", "https://www.funko.co.il"),
    ("בינה", "https://www.bina.co.il"),
    ("היבואן", "https://www.hayebuan.co.il"),
]


async def test():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="he-IL",
    )

    # First test: can we reach basic store homepages?
    print("=== Testing store accessibility ===")
    for name, url in STORE_URLS:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            title = await page.title()
            print(f"  {'✅' if title else '❌'} {name}: {title[:60] if title else 'No title'}")
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}")
        finally:
            await page.close()

    # Second test: search on stores that work
    print("\n=== Testing search results ===")
    for name, url in STORES:
        page = await context.new_page()
        try:
            print(f"\n🔍 {name}:")
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            title = await page.title()
            print(f"   Title: {title}")
            
            body = await page.inner_text("body")
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', body)
            if prices:
                print(f"   Prices found: {[p+'₪' for p in prices[:8]]}")
            else:
                print("   No prices found in text")
                
            # Check page length
            print(f"   Page length: {len(body)} chars")
            
        except Exception as e:
            print(f"   ❌ Error: {type(e).__name__}: {e}")
        finally:
            await page.close()

    await browser.close()
    await p.stop()
    print("\n✅ Test complete")


asyncio.run(test())
