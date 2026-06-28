import asyncio
import urllib.parse
import re
import errno
import logging
from typing import List, Optional
from urllib.parse import quote
from bs4 import BeautifulSoup

# Models and utils
from src.models import ProductPrice, Store
from src.utils.filters import clean_product_name, is_relevant_product
from src.logger import get_logger

logger = get_logger(__name__)

# CloakBrowser integration
try:
    from cloakbrowser import launch_async
    CLOAK_AVAILABLE = True
except ImportError:
    CLOAK_AVAILABLE = False

class PlaywrightEngine:
    @staticmethod
    async def close():
        pass


class ManoVinoCloakScraper:
    """Shopify scraper for ManoVino using CloakBrowser (stealth)."""

    def __init__(self, store: Store):
        self.store = store
        self.search_patterns = [
            "/Search/?q={query}",
            "/collections/search?q={query}",
            "/collections/all/{query}",
        ]

    async def search(self, query: str) -> List[ProductPrice]:
        if not CLOAK_AVAILABLE:
            logger.warning("CloakBrowser not installed, falling back")
            return []

        products = []
        encoded_query = quote(query)

        for pattern in self.search_patterns:
            search_url = self.store.url.rstrip("/") + pattern.replace("{query}", encoded_query)
            try:
                browser = await launch_async(headless=True)
                page = await browser.new_page()
                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(1.5)

                content = await page.content()
                soup = BeautifulSoup(content, "lxml")

                # Shopify product grid parsing
                for item in soup.select(".grid__item, .product-item, .product-card"):
                    try:
                        name_el = item.select_one(".product-item__title, .product-card__title, h3, .title")
                        if not name_el: continue
                        name = clean_product_name(name_el.get_text(strip=True))

                        if not is_relevant_product(name, query, min_words=1):
                            continue

                        price_el = item.select_one(".price, .product-item__price, .price__current")
                        price_text = price_el.get_text() if price_el else item.get_text()
                        prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', price_text)
                        if not prices: continue

                        price = float(prices[0].replace(",", ""))
                        link = item.select_one("a[href]")
                        url = link["href"] if link else ""
                        if url.startswith("/"):
                            url = self.store.url.rstrip("/") + url

                        products.append(ProductPrice(
                            product_name=name[:100],
                            store_name=self.store.name,
                            store_url=self.store.url,
                            regular_price=price,
                            product_url=url,
                        ))
                    except Exception:
                        continue
                
                await browser.close()
                if products: return products[:30]

            except Exception as e:
                logger.warning(f"CloakBrowser failed on {search_url}: {e}")
                continue
        return products

