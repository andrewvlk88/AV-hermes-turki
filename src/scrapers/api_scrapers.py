"""Store-specific scrapers for Israeli alcohol stores - using APIs when available."""
import re
import html
import json
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

from src.models import ProductPrice, Store
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product, extract_volume_ml
from src.logger import get_logger

logger = get_logger(__name__)


class HaturkiAPIScraper:
    """Scraper for haturki.com using their REST API."""
    
    API_BASE = "https://api.haturki.com/api"
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search products via the Haturki API."""
        headers = {
            "User-Agent": _get_ua(),
            "Accept": "application/json",
            "Origin": "https://haturki.com",
            "Referer": "https://haturki.com/",
        }
        
        # The API search parameter doesn't filter server-side, so we fetch
        # and filter locally. Limit to first call since API returns 3682 products.
        search_url = f"{self.API_BASE}/products?search={query}"
        
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            try:
                resp = await client.get(search_url, headers=headers)
                if resp.status_code != 200:
                    return []
                data = resp.json()
            except Exception as e:
                print(f"  ⚠️ Haturki API error: {e}")
                return []
        
        if data.get("status") != "success":
            return []
        
        products = []
        query_lower = query.lower().replace("'", "").replace('"', '')
        
        for item in data.get("products", []):
            name = clean_product_name(item.get("name", ""))
            
            # Fix 4: Filter irrelevant products - require relevance to query
            # CRITICAL: The Turki API returns ALL products, not just search matches.
            # We must filter strictly to avoid comparing unrelated products.
            if not is_relevant_product(name, query, min_words=2):
                continue
            
            name_lower = name.lower().replace("'", "").replace('"', '')
            
            # Match: require at least 2 significant words to match, OR full query substring
            if query_lower in name_lower:
                pass  # Direct substring match
            else:
                query_words = [w for w in re.split(r'[\s\-]+', query_lower) if len(w) > 1]
                matches = sum(1 for w in query_words if w in name_lower)
                if matches < min(2, len(query_words)):
                    continue  # Not enough words matched
            
            # Parse attributes
            attrs = item.get("attributes", {})
            
            # Get volume in ml
            volume = None
            ml_str = attrs.get("ml", "")
            if ml_str:
                try:
                    volume = float(ml_str.replace(",", ""))
                except ValueError:
                    pass
            
            # Also extract volume from name if not in attributes
            if not volume:
                volume = extract_volume_ml(name)
            
            # Get prices
            regular_price = None
            sale_price = None
            
            reg_str = item.get("regular_price", "")
            sale_str = item.get("sale_price", "")
            price_str = item.get("price", "")
            
            if reg_str:
                try:
                    regular_price = float(reg_str)
                except (ValueError, TypeError):
                    pass
            
            if sale_str:
                try:
                    sale_price = float(sale_str)
                except (ValueError, TypeError):
                    pass
            
            if not regular_price and price_str:
                try:
                    regular_price = float(price_str)
                except (ValueError, TypeError):
                    pass
            
            if not regular_price and not sale_price:
                continue
            
            # Determine if on sale
            is_on_sale = sale_price is not None and regular_price is not None and sale_price < regular_price
            
            # Fix 2: Filter bogus prices (unless mini bottle)
            best_price = sale_price if is_on_sale else regular_price
            if best_price and is_bogus_price(best_price, name):
                continue
            
            # Build product URL
            slug = item.get("slug", "")
            product_url = f"https://haturki.com/product/{slug}" if slug else ""
            
            # Fix image_url
            raw_image = item.get("featured", "")
            img_url = str(raw_image) if raw_image else ""
            
            # Get SKU
            sku = str(item.get("sku", "") or "")
            
            # Get category
            cat_names = [c.get("name", "") for c in attrs.get("type", []) if isinstance(c, dict)]
            category = " / ".join(cat_names)
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price if is_on_sale else None,
                is_on_sale=is_on_sale,
                product_url=product_url,
                image_url=img_url,
                volume_ml=volume,
                sku=sku,
                category=category,
                unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
            ))
        
        # Sort: exact name matches first, then by price ascending
        products.sort(key=lambda p: (
            -int(query_lower in p.product_name.lower().replace("'", "")),
            p.sale_price or p.regular_price or 999999
        ))
        
        return products[:15]


class GenericAPIScraper:
    """Fallback: tries to scrape from HTML using BeautifulSoup."""
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, html: str, query: str) -> List[ProductPrice]:
        """Extract products from HTML."""
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and "Product" in item.get("@type", ""):
                        name = clean_product_name(item.get("name", query))
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
                logger.warning("Failed to parse JSON-LD in GenericAPIScraper: %s", e)
                continue
        
        if products:
            return products[:5]
        
        # HTML scraping fallback
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


class StoreScraperFactory:
    """Factory that returns the right scraper for each store."""
    
    @staticmethod
    def get_scraper(store: Store):
        """Get the best scraper for a store."""
        store_key = store.name.lower() + " " + store.url.lower()
        
        if "הטורקי" in store_key or "haturki" in store_key:
            return HaturkiAPIScraper(store)
        
        return GenericAPIScraper(store)