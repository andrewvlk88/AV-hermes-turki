"""Store-specific scrapers for Israeli alcohol stores."""
import re
from typing import List, Optional
from bs4 import BeautifulSoup

from src.models import ProductPrice, Store


class StoreScraper:
    """Base scraper with common extraction logic."""
    
    def __init__(self, store: Store):
        self.store = store
    
    def extract(self, html: str, query: str) -> List[ProductPrice]:
        raise NotImplementedError


class HaturkiScraper(StoreScraper):
    """Scraper for haturki.com - Nuxt.js (Vue) based store."""
    
    def extract(self, html: str, query: str) -> List[ProductPrice]:
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Find product items - each is a .product-item div
        product_items = soup.find_all("div", class_=re.compile(r"product-item"))
        
        if not product_items:
            # Fallback: try li elements
            product_items = soup.find_all("li", class_=re.compile(r"product"))
        
        for item in product_items:
            # Extract product name
            name_el = (
                item.find(["a", "span", "h2", "h3", "h4"], class_=re.compile(r"(name|title)", re.I))
                or item.find("a")
            )
            if not name_el:
                continue
            
            product_name = name_el.get_text(strip=True)
            if not product_name or len(product_name) < 3:
                continue
            
            # Get product URL
            product_url = ""
            a_tag = item.find("a", href=True) or name_el
            if a_tag and a_tag.get("href"):
                href = a_tag["href"]
                if href.startswith("/"):
                    product_url = self.store.url.rstrip("/") + href
                elif href.startswith("http"):
                    product_url = href
            
            # Extract price - look for ₪ followed by number
            item_html = str(item)
            
            # Find all price-like patterns
            prices = []
            # Pattern: ₪ followed by number
            for m in re.finditer(r'₪(\d+[\d,]*\.?\d*)', item_html):
                try:
                    prices.append(float(m.group(1).replace(",", "")))
                except ValueError:
                    pass
            
            # Pattern: number followed by ₪
            for m in re.finditer(r'(\d+[\d,]*\.?\d*)\s*₪', item_html):
                val = float(m.group(1).replace(",", ""))
                if val not in prices:
                    prices.append(val)
            
            if not prices:
                continue
            
            # First price is main price, second might be sale price
            main_price = prices[0]
            sale_price = prices[1] if len(prices) > 1 else None
            
            # Detect if on sale
            is_sale = bool(re.search(r'מבצע|sale|הנחה', item_html, re.I))
            
            # Detect volume
            volume = None
            vol_match = re.search(r'(\d+[\d,]*\.?\d*)\s*(מ"?ל|ליטר|ל)', item_html)
            if vol_match:
                val = float(vol_match.group(1).replace(",", ""))
                unit = vol_match.group(2)
                if unit == "ליטר" or unit == "ל" or unit == "L":
                    volume = val * 1000
                else:
                    volume = val
            
            products.append(ProductPrice(
                product_name=product_name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=sale_price or main_price,
                sale_price=main_price if is_sale and sale_price else None,
                is_on_sale=is_sale,
                product_url=product_url,
                volume_ml=volume,
                unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
            ))
        
        return products[:10]


class WineboutiqueScraper(StoreScraper):
    """Scraper for wineboutique.co.il."""
    
    def extract(self, html: str, query: str) -> List[ProductPrice]:
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
                        name = item.get("name", query)
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
                            image_url=str(item.get("image", "")),
                        ))
            except (json.JSONDecodeError, TypeError):
                continue
        
        if products:
            return products[:5]
        
        # HTML fallback - look for items with class patterns
        items = soup.find_all(["div", "li"], class_=re.compile(r"product|item", re.I))
        for item in items[:20]:
            name_el = item.find(["h2", "h3", "h4", "a", "span"], 
                               class_=re.compile(r"name|title", re.I)) or item.find("a")
            if not name_el:
                continue
            
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            item_html = str(item)
            prices = []
            for m in re.finditer(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', item_html):
                try:
                    prices.append(float(m.group(1).replace(",", "")))
                except ValueError:
                    pass
            
            if not prices:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=prices[0],
                sale_price=prices[1] if len(prices) > 1 and prices[1] < prices[0] else None,
            ))
        
        return products[:5]


class BeerMarketScraper(StoreScraper):
    """Scraper for beer-market.co.il - Wix site."""
    
    def extract(self, html: str, query: str) -> List[ProductPrice]:
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Wix stores products in JSON-LD or specific data structures
        # Look for product containers
        items = soup.find_all(["div", "li", "a"], class_=re.compile(r"product|item", re.I))
        
        # If Wix renders via JS, we may need Playwright - but try HTML first
        items = items or soup.find_all(["div", "li"], attrs={"data-hook": re.compile(r"product", re.I)})
        
        for item in items[:20]:
            # Extract product info from data attributes or text
            item_html = str(item)
            
            name = ""
            name_el = item.find(["h2", "h3", "h4", "span", "a"], 
                               class_=re.compile(r"name|title|product-name", re.I))
            if name_el:
                name = name_el.get_text(strip=True)
            
            if not name:
                # Try aria-label or title attribute
                name = item.get("aria-label", "") or item.get("title", "")
            
            if not name or len(name) < 3:
                continue
            
            prices = []
            for m in re.finditer(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', item_html):
                try:
                    prices.append(float(m.group(1).replace(",", "")))
                except ValueError:
                    pass
            
            # Check data-price attribute
            for m in re.finditer(r'data-price["\']?\s*[:=]\s*["\']?(\d+\.?\d*)', item_html):
                try:
                    val = float(m.group(1))
                    if val not in prices:
                        prices.append(val)
                except ValueError:
                    pass
            
            if not prices:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=prices[0],
            ))
        
        return products[:5]


def get_scraper(store: Store) -> StoreScraper:
    """Factory - returns the right scraper for each store."""
    scrapers = {
        "הטורקי": HaturkiScraper,
        "haturki": HaturkiScraper,
        "wineboutique": WineboutiqueScraper,
        "וין בוטיק": WineboutiqueScraper,
        "beer-market": BeerMarketScraper,
        "ביר מרקט": BeerMarketScraper,
    }
    
    # Match by name or URL
    for key, scraper_cls in scrapers.items():
        if key in store.name or key in store.url:
            return scraper_cls(store)
    
    # Default generic scraper
    return GenericScraper(store)


class GenericScraper(StoreScraper):
    """Generic HTML scraper - works for simple stores."""
    
    def extract(self, html: str, query: str) -> List[ProductPrice]:
        """Universal extraction logic."""
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and "Product" in item.get("@type", ""):
                        name = item.get("name", query)
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
                        ))
            except:
                continue
        
        if products:
            return products[:5]
        
        # HTML: look for product-like containers
        containers = soup.find_all(["div", "li", "article"], 
                                   class_=re.compile(r"(product|item|card|tile)", re.I))
        
        for c in containers[:20]:
            name_el = c.find(["h2", "h3", "h4", "a", "span", "strong"])
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            c_html = str(c)
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', c_html)
            if not prices:
                continue
            
            link = c.find("a", href=True)
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=float(prices[0].replace(",", "")),
                product_url=url,
            ))
        
        return products[:5]
