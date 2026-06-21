"""Unified store scraper engine - REST APIs + HTML fallback."""
import re
import html
import json
import asyncio
from urllib.parse import quote
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx

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

try:
    from src.scrapers.playwright_scrapers import PLAYWRIGHT_AVAILABLE
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from src.models import ProductPrice, Store
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product, STOP_WORDS
from src.logger import get_logger

logger = get_logger(__name__)


BASE_HEADERS = {
    "User-Agent": _get_ua(),
    "Accept": "application/json",
}


class WooCommerceAPIScraper:
    """Scrapes stores via WooCommerce REST API.
    
    Uses the store API endpoint (?rest_route=/wc/store/products)
    which is publicly accessible even when the admin API is locked.
    Returns prices as floats (API returns cents, we divide by 100).
    """
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search products via WooCommerce Store API.
        
        Uses progressive querying (first 2 words, then first 1 word as fallback)
        to bypass strict WooCommerce matching which returns 0 results for long Hebrew queries,
        especially when brands are abbreviated (e.g., ק.ס instead of קברנה סוביניון).
        """
        words = [w for w in query.split() if w not in STOP_WORDS]
        if not words:
            return []
            
        # Progressive search terms:
        # Term 1: First 2 words of the query (specific search)
        # Term 2: First word of the query (broad search to find products with abbreviations)
        search_terms = []
        if len(words) >= 2:
            search_terms.append(" ".join(words[:2]))
        search_terms.append(words[0])
        
        # Deduplicate search terms
        seen_terms = set()
        search_terms = [x for x in search_terms if not (x in seen_terms or seen_terms.add(x))]
        
        all_products = []
        seen_urls = set()
        
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, verify=False) as client:
            for term in search_terms:
                query_encoded = quote(term)
                search_url = f"{self.store.url}/?rest_route=/wc/store/products&search={query_encoded}&per_page=100"
                api_url = f"{self.store.url}/wp-json/wc/store/products?search={query_encoded}&per_page=100"
                
                for url in [search_url, api_url]:
                    try:
                        resp = await client.get(url, headers=BASE_HEADERS)
                        if resp.status_code == 200:
                            data = resp.json()
                            if isinstance(data, list) and len(data) > 0:
                                parsed = self._parse_products(data, query)
                                for p in parsed:
                                    if p.product_url not in seen_urls:
                                        seen_urls.add(p.product_url)
                                        all_products.append(p)
                    except Exception as e:
                        logger.warning("WooCommerce API request failed for %s: %s", url, e)
                        continue
                        
        return all_products
    
    def _parse_products(self, data: list, query: str) -> List[ProductPrice]:
        """Parse WooCommerce Store API response using currency_minor_unit."""
        NOISE_WORDS = ["משלוח", "לתקנון", "מבצע", "חינם", "קופון", "שובר"]
        products = []
        
        for item in data[:100]:
            name = clean_product_name(item.get("name", ""))
            
            # Skip noise items
            if any(w in name for w in NOISE_WORDS):
                continue
            
            # Skip HTML entities as names
            if name.startswith("&") or len(name) < 3:
                continue
            
            prices_data = item.get("prices", {})
            raw_price = prices_data.get("price", "0") or "0"
            raw_regular = prices_data.get("regular_price", "0") or "0"
            raw_sale = prices_data.get("sale_price", "") or ""
            minor_unit = prices_data.get("currency_minor_unit", 0)
            
            try:
                divisor = 10 ** int(minor_unit)
                price = float(raw_price) / divisor
                regular_price = float(raw_regular) / divisor if raw_regular else price
                sale_price = float(raw_sale) / divisor if raw_sale else None
            except (ValueError, TypeError):
                continue
            
            # Filter nonsense prices
            if price <= 0 or price < 5:
                continue
            if price > 5000:
                continue
            
            # Filter irrelevant products
            if not is_relevant_product(name, query, min_words=1):
                continue
            
            # Filter bogus prices
            best_price_check = sale_price if (sale_price and sale_price < regular_price) else regular_price
            if is_bogus_price(best_price_check, name):
                continue
            
            # Build URL
            permalink = item.get("permalink", "")
            
            # Image
            images = item.get("images", [])
            image_url = images[0].get("src", "") if images else ""
            
            # Get volume from name or description
            description = item.get("description", "")
            short_desc = item.get("short_description", "")
            all_text = name + " " + description + " " + short_desc
            volume = self._extract_volume(all_text)
            
            # SKU
            sku = item.get("sku", "")
            
            # Category
            categories = [c.get("name", "") for c in item.get("categories", []) if isinstance(c, dict)]
            
            is_on_sale = sale_price is not None and sale_price < regular_price
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price if is_on_sale else None,
                is_on_sale=is_on_sale,
                product_url=permalink,
                image_url=image_url,
                volume_ml=volume,
                sku=sku,
                category=" / ".join(categories),
                unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
            ))
        
        return products
    
    def _extract_volume(self, text: str) -> Optional[float]:
        """Extract volume from product text."""
        patterns = [
            (r'(\d+\.?\d*)\s*(?:ליטר|ל|L|litre|liter)', 1000),
            (r'(\d+\.?\d*)\s*(?:מ"?ל|ml|ML)', 1),
            (r'(\d+)\s*ml', 1),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    return float(m.group(1)) * multiplier
                except ValueError:
                    pass
        return None


class MagentoAPIScraper:
    """Scrapes Magento stores via their REST API."""
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search via Magento REST API.
        
        Uses progressive querying (first 2 words, then first 1 word as fallback)
        to bypass strict substring matching which fails for long Hebrew queries,
        especially when brands or volumes differ.
        """
        words = [w for w in query.split() if w not in STOP_WORDS]
        if not words:
            return []
            
        # Progressive search terms:
        # Term 1: First 2 words of the query (specific search)
        # Term 2: First word of the query (broad search to find products with abbreviations)
        search_terms = []
        if len(words) >= 2:
            search_terms.append(" ".join(words[:2]))
        search_terms.append(words[0])
        
        # Deduplicate search terms
        seen_terms = set()
        search_terms = [x for x in search_terms if not (x in seen_terms or seen_terms.add(x))]
        
        all_products = []
        seen_skus = set()
        
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, verify=False) as client:
            for term in search_terms:
                query_encoded = quote(term)
                search_url = (
                    f"{self.store.url}/rest/default/V1/products"
                    f"?searchCriteria[filterGroups][0][filters][0][field]=name"
                    f"&searchCriteria[filterGroups][0][filters][0][value]=%25{query_encoded}%25"
                    f"&searchCriteria[pageSize]=100"
                )
                try:
                    resp = await client.get(search_url, headers=BASE_HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        if items:
                            parsed = self._parse_items(items, query)
                            for p in parsed:
                                if p.sku not in seen_skus:
                                    seen_skus.add(p.sku)
                                    all_products.append(p)
                except Exception as e:
                    logger.warning("Magento API request failed for %s: %s", self.store.url, e)
                    continue
                    
        return all_products
        
    def _parse_items(self, items: list, query: str) -> List[ProductPrice]:
        """Parse Magento API products."""
        products = []
        for item in items[:100]:
            name = clean_product_name(item.get("name", ""))
            
            # Filter irrelevant products
            if not is_relevant_product(name, query, min_words=1):
                continue
            
            # Price
            price_data = item.get("price", {})
            if isinstance(price_data, dict):
                price = float(price_data.get("regularPrice", 0) or 0)
            else:
                try:
                    price = float(item.get("price", 0))
                except (ValueError, TypeError):
                    price = 0
            
            if price <= 0:
                continue
            
            # Filter bogus prices
            if is_bogus_price(price, name):
                continue
            
            # SKU
            sku = item.get("sku", "")
            
            # Build URL
            product_url = f"{self.store.url}/{item.get('url_key', '')}.html" if item.get('url_key') else ""
            
            # Volume from name
            volume = self._extract_volume(name)
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=price,
                product_url=product_url,
                volume_ml=volume,
                sku=sku,
                unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
            ))
        
        return products
    
    def _extract_volume(self, text: str) -> Optional[float]:
        m = re.search(r'(\d+\.?\d*)\s*(?:ליטר|ל|L|ml|מ"?ל)', text)
        if m:
            val = float(m.group(1))
            unit = m.group(2) if len(m.groups()) > 1 else ""
            if unit in ["ליטר", "ל", "L"]:
                return val * 1000
            return val
        return None


class HTMLFallbackScraper:
    """Fallback: scrape search results from HTML (no JS)."""
    
    def __init__(self, store: Store, search_pattern: str = None):
        self.store = store
        self.search_pattern = search_pattern
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Fetch search page via CloakBrowser and parse HTML."""
        from src.scrapers.html_scrapers import _fetch_html
        
        patterns_to_try = [
            self.search_pattern,
            "/?s={query}&post_type=product",
            "/search?q={query}",
            "/search/result/?q={query}",
        ]
        
        for pattern in patterns_to_try:
            if not pattern:
                continue
            search_url = self.store.url.rstrip("/") + pattern.replace("{query}", quote(query))
            html_src = await _fetch_html(search_url, store_name=self.store.name)
            if html_src and len(html_src) > 500:
                products = self._parse_html(html_src, query)
                if products:
                    return products
        
        return []
    
    def _parse_html(self, html_src: str, query: str) -> List[ProductPrice]:
        """Parse HTML search results."""
        soup = BeautifulSoup(html_src, "lxml")
        products = []
        
        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and "Product" in item.get("@type", ""):
                        name = clean_product_name(item.get("name", ""))
                        offers = item.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        price_str = offers.get("price", "") if isinstance(offers, dict) else ""
                        try:
                            price = float(price_str)
                        except (ValueError, TypeError):
                            continue
                        
                        # Filter irrelevant products
                        if not is_relevant_product(name, query, min_words=1):
                            continue
                        
                        # Filter bogus prices
                        if is_bogus_price(price, name):
                            continue
                        
                        products.append(ProductPrice(
                            product_name=name[:100],
                            store_name=self.store.name,
                            store_url=self.store.url,
                            regular_price=price,
                            product_url=item.get("url", ""),
                        ))
            except Exception as e:
                logger.warning("Failed to parse JSON-LD in HTML fallback: %s", e)
                continue
        
        if products:
            return products[:5]
        
        # HTML containers
        containers = soup.find_all(["div", "li", "article"], 
                                   class_=re.compile(r"(product|item|card)", re.I))
        for c in containers[:20]:
            name_el = c.find(["h2", "h3", "h4", "a", "span"])
            if not name_el:
                continue
            name = clean_product_name(name_el.get_text(strip=True))
            if not name or len(name) < 3:
                continue
            
            # Filter irrelevant products
            if not is_relevant_product(name, query, min_words=1):
                continue
            
            c_html = str(c)
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', c_html)
            if not prices:
                continue
            
            link = c.find("a", href=True)
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            price_val = float(prices[0].replace(",", ""))
            
            # Filter bogus prices
            if is_bogus_price(price_val, name):
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=price_val,
                product_url=url,
            ))
        
        return products[:5]


class UnifiedScraper:
    """Master scraper - picks the right method per store."""
    
    # Per-store hard timeout (seconds). If a store takes longer, it is killed
    # and logged so one bad store cannot stall the entire watchdog run.
    DEFAULT_STORE_TIMEOUT = 90
    STORE_TIMEOUTS = {
        "פאנקו": 120,
        "היבואן": 120,
        "מנו וינו": 120,
        "בית המשקאות של אביב": 120,
        "Wine & More": 120,
    }
    
    # Store configurations
    # Auto-generated from config.yaml — single source of truth
    STORE_CONFIGS = [
        ("הטורקי", "https://haturki.com", "haturki_api", "/search?q={query}"),
        ("פאנקו", "https://www.paneco.co.il", "playwright", "/catalogsearch/result/?q={query}"),
        ("בנא משקאות", "https://www.banamashkaot.co.il", "woocommerce", "/?s={query}&post_type=product"),
        ("היבואן", "https://www.the-importer.co.il", "playwright", "/catalogsearch/result/?q={query}"),
        ("דרך היין", "https://www.wineroute.co.il", "woocommerce", "/?s={query}"),
        ("שר המשקאות", "https://www.mashkaot.co.il", "sar", "/?s={query}&post_type=product"),
        ("אליאסי משקאות", "https://www.eliasi.co.il", "prodbox_eliasi", "/?s={query}&post_type=product"),
        ("ארי משקאות", "https://ari-g.co.il", "woocommerce", "/search/result/?q={query}"),
        ("Liquor Store", "https://www.liquor-store.co.il", "woocommerce", "/?s={query}&post_type=product"),
        ("אלכוהום", "https://www.alcohome.co.il", "woocommerce", "/?s={query}&post_type=product"),
        ("משקאות המשמח", "https://www.hamesameach.co.il", "woocommerce", "/search/result/?q={query}"),
        ("מנו וינו", "https://www.manovino.co.il", "playwright_manovino", "/search?q={query}"),
        ("בית המשקאות של אביב", "https://www.avivdrinks.co.il", "playwright_aviv", "/search/result/?q={query}"),
        ("Wine & More", "https://www.wineandmore.co.il", "playwright_wineandmore", "/search?q={query}"),
        ("לגימה", "https://www.legima.co.il", "prodbox_legima", "/?s={query}&post_type=product"),
        ("Coffeco", "https://www.coffeco.co.il", "woocommerce", "/search/result/?q={query}"),
        ("Drinks4U", "https://www.drinks4u.co.il", "prodbox_drinks4u", "/?s={query}&post_type=product"),
        ("Alcohol123", "https://www.alcohol123.co.il", "woocommerce", "/?s={query}&post_type=product"),
        ("בית היין", "https://www.winehouse.co.il", "woocommerce", "/?s={query}&post_type=product"),
    ]
    
    @staticmethod
    def get_scraper(name: str, url: str):
        """Get the right scraper for a store."""
        store = Store(name=name, url=url, search_path="", type="static")
        
        # Find config
        config = None
        for c in UnifiedScraper.STORE_CONFIGS:
            if c[0] == name:
                config = c
                break
        
        if not config:
            return HTMLFallbackScraper(store)
        
        engine = config[2]
        search_pattern = config[3]
        
        if engine == "haturki_api":
            from src.scrapers.api_scrapers import HaturkiAPIScraper
            return HaturkiAPIScraper(store)
        elif engine == "woocommerce":
            return WooCommerceAPIScraper(store)
        elif engine == "magento":
            return MagentoAPIScraper(store)
        elif engine == "magento_html":
            from src.scrapers.html_scrapers import MagentoHTMLScraper
            return MagentoHTMLScraper(store)
        elif engine == "sar":
            from src.scrapers.html_scrapers import SarHascraper
            return SarHascraper(store)
        elif engine == "prodbox_eliasi":
            from src.scrapers.html_scrapers import ProdBoxScraper
            return ProdBoxScraper(store, container_class=r"products__block", title_class=r"products__title", price_class=r"products__price", search_pattern="/?s={query}&post_type=product")
        elif engine == "prodbox_drinks4u":
            from src.scrapers.html_scrapers import ProdBoxScraper
            return ProdBoxScraper(store, container_class="prod-box", title_class="prod-box__title", price_class="prod-box__price", search_pattern="/?s={query}&post_type=product")
        elif engine == "prodbox_legima":
            from src.scrapers.html_scrapers import ProdBoxScraper
            return ProdBoxScraper(store, container_class=r"boxItem-wrap|productBoxes", title_class=r"item-name|title", price_class=r"product-box-prices|price", search_pattern="/?s={query}&post_type=product")
        elif engine == "prodbox_wineandmore":
            from src.scrapers.html_scrapers import ProdBoxScraper
            return ProdBoxScraper(store, container_class=r"ProductItem|layout_list_item", title_class=r"title|name", price_class=r"price|product_quantity", search_pattern="/search?q={query}")
        elif engine.startswith("playwright"):
            if not PLAYWRIGHT_AVAILABLE:
                return HTMLFallbackScraper(store, search_pattern)
            from src.scrapers.playwright_scrapers import PwScraperFactory
            return PwScraperFactory.get_scraper(store)
        else:
            return HTMLFallbackScraper(store, search_pattern)
    
    @staticmethod
    async def search_all(query: str, progress_callback=None, run_id: str = None) -> dict:
        """Search ALL stores SEQUENTIALLY with per-store hard timeout.

        Each store is wrapped in asyncio.wait_for() so a single hanging site
        cannot stall the whole watchdog run. Results are saved to SQLite
        immediately, so partial progress survives failures.
        """
        from src.storage.sqlite_store import (
            save_store_result, mark_store_error, mark_store_running
        )

        all_prices = {}
        total_stores = len([c for c in UnifiedScraper.STORE_CONFIGS if c[2] != "haturki_api"])
        completed = 0

        for name, url, engine, pattern in UnifiedScraper.STORE_CONFIGS:
            # Haturki excluded (already handled separately in run.py)
            if engine == "haturki_api":
                continue

            store = Store(name=name, url=url, search_path=pattern or "", type="static")
            store_timeout = UnifiedScraper.STORE_TIMEOUTS.get(name, UnifiedScraper.DEFAULT_STORE_TIMEOUT)

            if run_id:
                mark_store_running(run_id, query, name)

            start_ts = asyncio.get_event_loop().time()
            products = []
            error_msg = None
            try:
                scraper = UnifiedScraper.get_scraper(name, url)
                products = await asyncio.wait_for(scraper.search(query), timeout=store_timeout)

                # Apply product name cleaning
                cleaned_results = []
                for p in products:
                    p.product_name = clean_product_name(p.product_name)
                    best_price = p.sale_price or p.regular_price
                    if best_price and not is_bogus_price(best_price, p.product_name):
                        cleaned_results.append(p)
                products = cleaned_results

                if run_id:
                    save_store_result(run_id, query, name, products)

                if progress_callback:
                    progress_callback(name, len(products), "✅")

            except asyncio.TimeoutError:
                error_msg = f"timeout after {store_timeout}s"
                logger.error("Store %s timed out after %ds for query %r", name, store_timeout, query)
                if progress_callback:
                    progress_callback(name, 0, f"⏱️ timeout {store_timeout}s")
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.exception("Store %s failed for query %r", name, query)
                if progress_callback:
                    progress_callback(name, 0, f"❌ {type(e).__name__}")
            finally:
                elapsed = asyncio.get_event_loop().time() - start_ts
                completed += 1
                all_prices[name] = products
                if run_id and error_msg:
                    mark_store_error(run_id, query, name, error_msg)
                logger.info("[%d/%d] %s done in %.1fs | products=%d | error=%s",
                            completed, total_stores, name, elapsed, len(products), error_msg or "none")

        return all_prices
