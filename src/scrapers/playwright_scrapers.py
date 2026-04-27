"""Playwright-based scrapers for JS-heavy Israeli alcohol stores.

Uses headless Chromium to render pages with JavaScript.
These stores need JS because they load products dynamically
or require interaction (age verification, etc.).
"""
import asyncio
import urllib.parse
import re
from typing import List, Optional

try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

from src.models import ProductPrice, Store
from src.logger import get_logger

try:
    from fake_useragent import UserAgent as _FakeUA
    _ua_gen = _FakeUA()
    def _get_ua() -> str:
        try:
            return _ua_gen.random
        except Exception:
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
except ImportError:
    def _get_ua() -> str:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

logger = get_logger(__name__)


class PlaywrightEngine:
    """Shared Playwright browser pool."""
    
    _instance = None
    _browser = None
    _playwright = None
    
    @classmethod
    async def get_browser(cls):
        """Get or create shared browser instance."""
        if cls._browser and cls._browser.is_connected():
            return cls._browser
        
        if not cls._playwright:
            cls._playwright = await async_playwright().start()
        
        cls._browser = await cls._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        return cls._browser
    
    @classmethod
    async def close(cls):
        """Clean up browser."""
        if cls._browser:
            await cls._browser.close()
            cls._browser = None
        if cls._playwright:
            await cls._playwright.stop()
            cls._playwright = None


async def _create_context(browser):
    """Create a context with stealth settings."""
    context = await browser.new_context(
        ignore_https_errors=True,
        user_agent=_get_ua(),
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
        viewport={"width": 1920, "height": 1080},
    )
    # Apply playwright-stealth if available (far more comprehensive than manual scripts)
    if STEALTH_AVAILABLE:
        page = await context.new_page()
        await stealth_async(page)
        await page.close()
    else:
        # Fallback: hide automation hints manually
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { 
                get: () => [1, 2, 3, 4, 5] 
            });
            Object.defineProperty(navigator, 'languages', { 
                get: () => ['he-IL', 'he', 'en'] 
            });
        """)
    return context


class GenericPlaywrightScraper:
    """Generic Playwright-based scraper for JS-heavy stores.
    
    Navigates to search URL, waits for content to render,
    then extracts products using configured selectors.
    """
    
    def __init__(self, store: Store, config: dict = None):
        self.store = store
        self.config = config or {}
        self.timeout = self.config.get("timeout", 15000)
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search using Playwright browser."""
        search_patterns = self.config.get(
            "search_patterns",
            ["/Search/?q={query}", "/?s={query}&post_type=product", 
             "/search/result/?q={query}", "/catalogsearch/result/?q={query}"]
        )
        
        browser = await PlaywrightEngine.get_browser()
        context = await _create_context(browser)
        
        products = []
        try:
            for pattern in search_patterns:
                search_url = self.store.url.rstrip("/") + pattern.replace("{query}", urllib.parse.quote(query))
                
                page = await context.new_page()
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=self.timeout)
                    await asyncio.sleep(2)
                    
                    # Handle age verification popup
                    # Strategy: click age button via JS first (bypassing overlays),
                    # then remove overlay divs, then wait for content to load
                    try:
                        # Step 1: Click age confirmation via JS (avoids overlay blocking)
                        await page.evaluate("""() => {
                            // Wine & More style: <a id="right_popup_click_*">אני מעל 18.</a>
                            const ageLink = document.querySelector('a[id*="right_popup_click"], a[id*="age_confirm"]');
                            if (ageLink) { ageLink.click(); return; }
                            // Generic: any clickable element with age-related text
                            const keywords = ['מעל 18', 'מעל', 'אני מאשר', 'אישור', 'כן', 'המשך', 'Yes', 'I am'];
                            for (const el of document.querySelectorAll('a, button, input[type="button"], input[type="submit"]')) {
                                const t = el.textContent.trim();
                                if (keywords.some(k => t.includes(k))) {
                                    el.click();
                                    return;
                                }
                            }
                        }""")
                        await asyncio.sleep(1)
                        
                        # Step 2: Remove overlay divs that may still block the page
                        await page.evaluate("""() => {
                            const selectors = [
                                '[id*="age_popup"]', '[id*="wrapper_age"]', '[id*="active_popup"]',
                                '[class*="age-overlay"]', '[class*="age-overlay"]',
                                '[id*="age-verification"]', '[class*="age-verification"]',
                                '[class*="modal-overlay"]', '[class*="popup-overlay"]',
                                '[class*="showPictures"]'
                            ];
                            selectors.forEach(sel => {
                                document.querySelectorAll(sel).forEach(el => el.remove());
                            });
                        }""")
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning("Age verification handling failed: %s", e)
                    
                    # Wait a bit more for lazy content
                    await page.wait_for_load_state("networkidle", timeout=self.timeout)
                    await asyncio.sleep(1)
                    
                    html = await page.content()
                    products = self._extract_products(html, query)
                    
                    if products:
                        return products
                        
                except Exception as e:
                    logger.warning("Page navigation/processing failed for %s: %s", search_url, e)
                finally:
                    await page.close()
        finally:
            await context.close()
        
        return products
    
    def _extract_products(self, html: str, query: str) -> List[ProductPrice]:
        """Extract products from rendered HTML.
        
        Override in subclass for store-specific extraction.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Try JSON-LD first (universal)
        import json
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and "Product" in item.get("@type", ""):
                        name = item.get("name", "")
                        offers = item.get("offers", {})
                        if isinstance(offers, dict):
                            price_str = offers.get("price", "")
                        elif isinstance(offers, list):
                            price_str = offers[0].get("price", "") if offers else ""
                        else:
                            price_str = ""
                        try:
                            price = float(price_str)
                        except (ValueError, TypeError):
                            continue
                        products.append(ProductPrice(
                            product_name=name[:100],
                            store_name=self.store.name,
                            store_url=self.store.url,
                            regular_price=price,
                            product_url=item.get("url", ""),
                        ))
            except Exception as e:
                logger.warning("Failed to parse JSON-LD in GenericPlaywrightScraper: %s", e)
                continue
        
        if products:
            return products
        
        # Generic: look for product items
        containers = soup.find_all(["div", "li", "article"], 
                                   class_=re.compile(r"(product|item|card)", re.I))
        
        for c in containers:
            name = ""
            for el in c.find_all(["h2", "h3", "h4", "a", "span", "strong"]):
                n = el.get_text(strip=True)
                if len(n) >= 3:
                    name = n
                    break
            if not name:
                continue
            
            c_html = str(c)
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', c.get_text(separator=" "))
            if not prices:
                # Check data-price attribute
                data_prices = re.findall(r'data-price[=]["\']?(\d+\.?\d*)', c_html)
                prices = data_prices if data_prices else []
            
            if not prices:
                continue
            
            link = c.find("a", href=True)
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            try:
                price = float(prices[0].replace(",", ""))
            except ValueError:
                continue
            
            if price < 5 or price > 10000:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=price,
                product_url=url,
            ))
        
        return products


class AvivDrinksScraper(GenericPlaywrightScraper):
    """Scraper for בית המשקאות של אביב (avivdrinks.co.il).
    
    Elementor-based site. Products loaded dynamically.
    Search page shows results after JS renders.
    """
    
    def __init__(self, store: Store):
        super().__init__(store, {
            "timeout": 15000,
            "search_patterns": [
                "/?s={query}&post_type=product",
                "/search/result/?q={query}",
            ]
        })


class ManoVinoScraper(GenericPlaywrightScraper):
    """Scraper for מנו וינו (manovino.co.il).
    
    Shopify-based store. Products are in collections.
    Shopify search typically works via /search?q= but needs JS.
    """
    
    def __init__(self, store: Store):
        super().__init__(store, {
            "timeout": 15000,
            "search_patterns": [
                "/Search/?q={query}",
                "/collections/search?q={query}",
                "/collections/all/{query}",
            ]
        })


class WineAndMoreScraper(GenericPlaywrightScraper):
    """Scraper for Wine & More (wineandmore.co.il / wnf.co.il).
    
    Custom JS-heavy site. Products loaded dynamically via AJAX/JS.
    Search is at /search?q={query}.
    Product containers use classes like 'layout_list_item', 'ProductItem'.
    """
    
    def __init__(self, store: Store):
        super().__init__(store, {
            "timeout": 20000,
            "search_patterns": [
                "/Search/?q={query}",
            ]
        })
    
    def _extract_products(self, html: str, query: str) -> list:
        """Extract products from Wine & More rendered HTML.
        
        Wine & More uses layout_list_item/ProductItem containers with
        title links and price_item_x spans.
        """
        from bs4 import BeautifulSoup
        import json
        
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        # Handle ItemList with products
                        if item.get("@type") == "ItemList":
                            for elem in item.get("itemListElement", []):
                                prod = elem if isinstance(elem, dict) else {}
                                if "Product" in str(prod.get("@type", "")):
                                    name = prod.get("name", "")
                                    offers = prod.get("offers", {})
                                    if isinstance(offers, dict):
                                        price_str = offers.get("price", "")
                                    elif isinstance(offers, list) and offers:
                                        price_str = offers[0].get("price", "")
                                    else:
                                        price_str = ""
                                    try:
                                        price = float(price_str)
                                        products.append(ProductPrice(
                                            product_name=name[:100],
                                            store_name=self.store.name,
                                            store_url=self.store.url,
                                            regular_price=price,
                                            product_url=prod.get("url", ""),
                                        ))
                                    except (ValueError, TypeError):
                                        continue
                        elif "Product" in item.get("@type", ""):
                            name = item.get("name", "")
                            offers = item.get("offers", {})
                            price_str = ""
                            if isinstance(offers, dict):
                                price_str = offers.get("price", "")
                            elif isinstance(offers, list) and offers:
                                price_str = offers[0].get("price", "")
                            try:
                                price = float(price_str)
                                products.append(ProductPrice(
                                    product_name=name[:100],
                                    store_name=self.store.name,
                                    store_url=self.store.url,
                                    regular_price=price,
                                    product_url=item.get("url", ""),
                                ))
                            except (ValueError, TypeError):
                                continue
            except Exception as e:
                logger.warning("Failed to parse JSON-LD in WineAndMoreScraper: %s", e)
                continue
        
        if products:
            return products
        
        # Wine & More specific: layout_list_item containers with title + price
        containers = soup.find_all(["div", "li", "article"],
            class_=re.compile(r"(layout_list_item|ProductItem|product_item|item.*box)", re.I))
        
        for c in containers:
            # Find title — usually in an <a> inside .title or .name or .item-name
            title_el = (c.find(class_=re.compile(r"(title|name|item-name)", re.I))
                       or c.find(["h2", "h3", "h4", "a"]))
            if not title_el:
                continue
            name = title_el.get_text(strip=True)
            if not name or len(name) < 3:
                # Try the <a> directly
                link = c.find("a", href=True)
                if link:
                    name = link.get_text(strip=True)
                if not name or len(name) < 3:
                    continue
            
            # Find price — look for price_item_x or .price classes or ₪ symbol
            c_html = str(c)
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', c.get_text(separator=" "))
            if not prices:
                data_prices = re.findall(r'data-price[=\s"]+(\d+\.?\d*)', c_html)
                prices = data_prices if data_prices else []
            if not prices:
                price_el = c.find(class_=re.compile(r"(price|Price)", re.I))
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(r'(\d[\d,]*\.?\d*)', price_text)
                    if price_match:
                        prices = [price_match.group(1)]
            
            if not prices:
                continue
            
            link = c.find("a", href=True)
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            try:
                price = float(prices[0].replace(",", ""))
            except ValueError:
                continue
            
            if price < 5 or price > 10000:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=price,
                product_url=url,
            ))
        
        # Fallback: generic product/item containers
        if not products:
            products = super()._extract_products(html, query)
        
        return products


class PwScraperFactory:
    """Factory for Playwright-based scrapers."""
    
    @staticmethod
    def get_scraper(store: Store):
        """Get the right Playwright scraper for a store."""
        key = store.name
        
        if "אביב" in key:
            return AvivDrinksScraper(store)
        elif "מנו וינו" in key or "מנו" in key:
            return ManoVinoScraper(store)
        elif "Wine & More" in key or "wineandmore" in key.lower():
            return WineAndMoreScraper(store)
        else:
            # Generic fallback with store-specific config
            return GenericPlaywrightScraper(store)
