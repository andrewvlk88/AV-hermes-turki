"""Store-specific HTML scrapers for stores without APIs."""
import re
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx

from src.models import ProductPrice, Store


class MagentoHTMLScraper:
    """Scrapes Magento 2 stores from HTML search results.
    
    Works for: היבואן (the-importer.co.il)
    Patterns: .product-item, .product-item-link, .product-info, data-product-id
    """
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search via HTML."""
        search_url = f"{self.store.url}/search?q={query}&limit=20"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
            "Accept-Language": "he-IL,he;q=0.9",
        }
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                resp = await client.get(search_url, headers=headers)
                if resp.status_code != 200:
                    return []
            except:
                return []
        
        soup = BeautifulSoup(resp.text, "lxml")
        products = []
        
        # Magento 2: product items are in <li> or <div> with class="product-item"
        items = soup.find_all(["li", "div"], class_=re.compile(r"product-item", re.I))
        
        for item in items[:15]:
            # Product name from .product-item-link or <a> inside
            link_el = item.find("a", class_=re.compile(r"product-item-link", re.I)) or \
                      item.find("a", class_=re.compile(r"product.*name", re.I)) or \
                      item.find("a")
            if not link_el:
                continue
            
            name = link_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            # Link
            href = link_el.get("href", "")
            if href and href.startswith("/"):
                href = self.store.url.rstrip("/") + href
            
            # Price - Magento often stores in .price or data attributes
            item_html = str(item)
            
            # Check data-price attribute
            data_prices = re.findall(r'data-price-amount=["\']?(\d+\.?\d*)', item_html)
            
            # Check price elements
            price_el = item.find(class_=re.compile(r"price", re.I))
            price_text = price_el.get_text(strip=True) if price_el else ""
            
            # Regex fallback
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', price_text + item_html)
            
            if data_prices:
                try:
                    regular_price = float(data_prices[0])
                    sale_price = float(data_prices[1]) if len(data_prices) > 1 else None
                except ValueError:
                    continue
            elif prices:
                try:
                    regular_price = float(prices[0].replace(",", ""))
                    sale_price = float(prices[1].replace(",", "")) if len(prices) > 1 else None
                except ValueError:
                    continue
            else:
                continue
            
            # Skip noise
            if regular_price < 5 or regular_price > 10000:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price if sale_price and sale_price < regular_price else None,
                is_on_sale=(sale_price is not None and sale_price < regular_price),
                product_url=href,
            ))
        
        return products[:10]


class SarHascraper:
    """Scraper for שר המשקאות (mashkaot.co.il).
    
    Patterns: .catalog__item > .product-box > .product-box-info
    Structure:
      .product-box-info__title → product name
      .product-box-info__price-new → sale price
      .product-box-info__price-old → regular price
    """
    
    def __init__(self, store: Store):
        self.store = store
    
    async def search(self, query: str) -> List[ProductPrice]:
        search_url = f"{self.store.url}/?s={query}&post_type=product"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
        }
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                resp = await client.get(search_url, headers=headers)
                if resp.status_code != 200:
                    return []
            except:
                return []
        
        soup = BeautifulSoup(resp.text, "lxml")
        products = []
        
        # Find product boxes
        boxes = soup.find_all("div", class_=re.compile(r"product-box", re.I))
        
        for box in boxes[:15]:
            info = box.find("div", class_=re.compile(r"product-box-info", re.I))
            if not info:
                continue
            
            # Name
            title_el = info.find(class_=re.compile(r"title", re.I))
            name = title_el.get_text(strip=True) if title_el else ""
            if not name or len(name) < 3:
                continue
            
            # Prices
            price_new = info.find(class_=re.compile(r"price-new", re.I))
            price_old = info.find(class_=re.compile(r"price-old", re.I))
            
            regular_price = None
            sale_price = None
            
            if price_old:
                m = re.search(r'(\d+[\d,]*\.?\d*)', price_old.get_text())
                if m:
                    regular_price = float(m.group(1).replace(",", ""))
            
            if price_new:
                m = re.search(r'(\d+[\d,]*\.?\d*)', price_new.get_text())
                if m:
                    sale_price = float(m.group(1).replace(",", ""))
            
            if not regular_price and not sale_price:
                # Fallback to any price in box
                box_html = str(box)
                prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', box_html)
                if prices:
                    regular_price = float(prices[0].replace(",", ""))
                    sale_price = float(prices[1].replace(",", "")) if len(prices) > 1 else None
            
            if not regular_price:
                continue
            if regular_price < 5:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price if sale_price and sale_price < regular_price else None,
                is_on_sale=(sale_price is not None and sale_price < regular_price),
            ))
        
        return products[:10]


class ProdBoxScraper:
    """Generic scraper for stores with .prod-box / .products__block structure.
    
    Works for: Drinks4U, אליאסי
    Patterns: .prod-box__title, .prod-box__price
              .products__title, .products__price
    """
    
    def __init__(self, store: Store, 
                 container_class: str = "prod-box",
                 title_class: str = "prod-box__title",
                 price_class: str = "prod-box__price",
                 search_pattern: str = "/?s={query}&post_type=product"):
        self.store = store
        self.container_class = container_class
        self.title_class = title_class
        self.price_class = price_class
        self.search_pattern = search_pattern
    
    async def search(self, query: str) -> List[ProductPrice]:
        search_url = self.store.url.rstrip("/") + self.search_pattern.replace("{query}", query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
        }
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                resp = await client.get(search_url, headers=headers)
                if resp.status_code != 200:
                    return []
            except:
                return []
        
        soup = BeautifulSoup(resp.text, "lxml")
        products = []
        
        # Find containers
        containers = soup.find_all(["div", "li"], class_=re.compile(self.container_class, re.I))
        
        for c in containers[:15]:
            # Title
            title_el = c.find(class_=re.compile(self.title_class, re.I))
            name = title_el.get_text(strip=True)[:100] if title_el else ""
            if not name or len(name) < 3:
                continue
            
            # Skip noise
            if re.search(r'משלוח|לתקנון|מבצע|חינם|קופון|מינימום|הזמנה', name):
                continue
            
            # Link
            a_tag = c.find("a", href=True)
            url = a_tag["href"] if a_tag else ""
            if url and url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            # Price
            price_el = c.find(class_=re.compile(self.price_class, re.I))
            c_html = str(price_el) if price_el else str(c)
            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', c_html)
            
            if not prices:
                continue
            
            try:
                price = float(prices[0].replace(",", ""))
                sale = float(prices[1].replace(",", "")) if len(prices) > 1 else None
            except ValueError:
                continue
            
            if price < 5 or price > 10000:
                continue
            
            products.append(ProductPrice(
                product_name=name,
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=sale if sale and sale < price else price,
                sale_price=price if sale and sale < price else None,
                is_on_sale=(sale is not None and sale < price),
                product_url=url,
            ))
        
        return products[:10]


class StoreMatcher:
    """Matches a store name to the right scraper."""
    
    SCRAPER_MAP = {
        "היבואן": ("magento_html", {}),
        "שר המשקאות": ("sar", {}),
        "Drinks4U": ("prodbox", {
            "container_class": "prod-box",
            "title_class": "prod-box__title",
            "price_class": "prod-box__price",
            "search_pattern": "/?s={query}&post_type=product",
        }),
        "אליאסי משקאות": ("prodbox", {
            "container_class": r"products__block",
            "title_class": r"products__title",
            "price_class": r"products__price",
            "search_pattern": "/?s={query}&post_type=product",
        }),
        "Wine & More": ("prodbox", {
            "container_class": r"ProductItem|layout_list_item",
            "title_class": r"title|name",
            "price_class": r"price|product_quantity",
            "search_pattern": "/search?q={query}",
        }),
        "לגימה": ("prodbox", {
            "container_class": r"boxItem-wrap|productBoxes",
            "title_class": r"item-name|title",
            "price_class": r"product-box-prices|price",
            "search_pattern": "/?s={query}&post_type=product",
        }),
    }
    
    @staticmethod
    def get_scraper(store: Store):
        """Get the right scraper for a store."""
        key = store.name
        if key in StoreMatcher.SCRAPER_MAP:
            scraper_type, config = StoreMatcher.SCRAPER_MAP[key]
            if scraper_type == "magento_html":
                return MagentoHTMLScraper(store)
            elif scraper_type == "sar":
                return SarHascraper(store)
            elif scraper_type == "prodbox":
                return ProdBoxScraper(store, **config)
        
        # Default: generic HTML
        return ProdBoxScraper(store)
