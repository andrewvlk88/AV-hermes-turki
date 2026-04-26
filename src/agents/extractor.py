"""Scraper & Extractor Agent - parses HTML from Israeli alcohol stores and extracts structured data."""
import re
from typing import List, Optional
from bs4 import BeautifulSoup
import json

from src.models import ProductPrice, Store


class ExtractorAgent:
    """Extracts structured product data from store HTML pages."""

    # Common price patterns in Israeli e-commerce
    PRICE_PATTERNS = [
        # data- attributes (modern e-commerce)
        r'data-price[=]["\'](\d+\.?\d*)["\']',
        r'data-product-price[=]["\'](\d+\.?\d*)["\']',
        r'data-price-amount[=]["\'](\d+\.?\d*)["\']',
        # Meta tags
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\'](\d+\.?\d*)["\']',
        # JSON-LD
        r'"price"\s*:\s*"(\d+\.?\d*)"',
        r'"price"\s*:\s*(\d+\.?\d*)',
        # Hebrew price formats
        r'(?:מחיר|₪|ש"ח|שקל)[^\d]*(\d+[\d,]*\.?\d*)',
        r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח|שקלים)',
    ]

    SALE_PATTERNS = [
        r'מבצע',
        r'sale',
        r'הנחה',
        r'discount',
        r'%?\s*הנחה',
        r'חיסכון',
    ]

    @staticmethod
    def _clean_price(price_str: str) -> Optional[float]:
        """Clean a price string to float."""
        if not price_str:
            return None
        price_str = price_str.replace(",", "").replace(" ", "").strip()
        try:
            return float(price_str)
        except ValueError:
            return None

    @staticmethod
    def _extract_with_regex(html: str, patterns: List[str]) -> List[float]:
        """Extract all matching prices from HTML using regex."""
        prices = []
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for m in matches:
                cleaned = ExtractorAgent._clean_price(m)
                if cleaned and 1 < cleaned < 100000:  # Sanity check
                    prices.append(cleaned)
        return prices

    @staticmethod
    def _find_product_name(soup: BeautifulSoup, html: str) -> Optional[str]:
        """Try to find the product name from various HTML elements."""
        # Title tag
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()
            # Remove store name suffixes
            for suffix in [" |", " -", " —", " :", " ›", " ⋮"]:
                if suffix in title:
                    title = title.split(suffix)[0].strip()
            if len(title) > 2 and len(title) < 200:
                return title

        # h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        # og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        return None

    @staticmethod
    def _find_volume(text: str) -> Optional[float]:
        """Extract volume in ml from product text."""
        patterns = [
            (r'(\d+\.?\d*)\s*ליטר', 1000),
            (r'(\d+\.?\d*)\s*מ"?ל', 1),
            (r'(\d+)\s*ml', 1),
            (r'(\d+\.?\d*)\s*L', 1000),
            (r'(\d+\.?\d*)\s*ל', 1000),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, text)
            if m:
                return float(m.group(1)) * multiplier
        return None

    def extract_from_html(self, html: str, store: Store, query: str) -> List[ProductPrice]:
        """Extract all product prices from a store's HTML search results."""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Try JSON-LD first (most reliable)
        json_ld_products = self._extract_json_ld(soup, store, query)
        results.extend(json_ld_products)

        # Try HTML-based extraction
        html_products = self._extract_from_html_elements(soup, html, store, query)
        results.extend(html_products)

        # Deduplicate by product_url
        seen_urls = set()
        unique = []
        for p in results:
            if p.product_url not in seen_urls:
                seen_urls.add(p.product_url)
                unique.append(p)

        # Limit to first 5 products per store
        return unique[:5]

    def _extract_json_ld(self, soup: BeautifulSoup, store: Store, query: str) -> List[ProductPrice]:
        """Extract products from JSON-LD structured data."""
        products = []
        json_lds = soup.find_all("script", type="application/ld+json")
        if not json_lds:
            return products

        for script in json_lds:
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            # Handle single product
            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")
                if "Product" not in item_type and "Item" not in item_type:
                    continue

                name = item.get("name", query)
                price_str = ""
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    price_str = offers.get("price", "")
                elif isinstance(offers, list) and offers:
                    price_str = offers[0].get("price", "")

                price = self._clean_price(str(price_str)) if price_str else None
                if not price:
                    continue

                product_url = item.get("url", "")
                image_url = item.get("image", "")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else ""

                volume = self._find_volume(name + " " + query)

                products.append(ProductPrice(
                    product_name=name,
                    store_name=store.name,
                    store_url=store.url,
                    regular_price=price,
                    product_url=product_url,
                    image_url=str(image_url),
                    volume_ml=volume,
                    unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
                ))
        return products

    def _extract_from_html_elements(self, soup: BeautifulSoup, html: str, store: Store, query: str) -> List[ProductPrice]:
        """Extract products from HTML elements (fallback when no JSON-LD)."""
        products = []
        all_prices = self._extract_with_regex(html, self.PRICE_PATTERNS)
        product_name = self._find_product_name(soup, html) or query

        # Find product containers
        potential_containers = soup.find_all(["div", "li", "article"], class_=re.compile(
            r"(product|item|card|tile|result|search-result)", re.I
        ))

        if not potential_containers:
            # Try generic containers
            potential_containers = soup.find_all(["div", "li"], recursive=True)[:30]

        for container in potential_containers[:20]:
            # Find links in container
            links = container.find_all("a", href=True)
            if not links:
                continue

            product_url = links[0]["href"]
            if product_url.startswith("/"):
                product_url = store.url.rstrip("/") + product_url

            # Product name
            name_el = (
                container.find(["h2", "h3", "h4", "span", "a"],
                               class_=re.compile(r"(name|title|product-name|item-name)", re.I))
                or container.find(["h2", "h3", "h4"])
            )
            name = name_el.get_text(strip=True) if name_el else product_name

            if not name or len(name) < 2:
                continue

            # Price from container
            container_html = str(container)
            prices = self._extract_with_regex(container_html, self.PRICE_PATTERNS)
            has_sale = any(re.search(p, container_html, re.I) for p in self.SALE_PATTERNS)

            # Text-based price
            text_prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', container_html)
            for tp in text_prices:
                p = self._clean_price(tp)
                if p and 1 < p < 100000:
                    prices.append(p)

            if not prices:
                continue

            price = prices[0]
            sale_price = prices[1] if len(prices) > 1 else None

            volume = self._find_volume(name + " " + container_html)

            products.append(ProductPrice(
                product_name=name[:100],
                store_name=store.name,
                store_url=store.url,
                regular_price=sale_price or price,
                sale_price=price if has_sale and sale_price else None,
                is_on_sale=has_sale,
                product_url=product_url,
                volume_ml=volume,
                unit="ליטר" if (volume and volume >= 1000) else "מ\"ל" if volume else "בקבוק",
            ))

        # If no containers found, try page-level extraction
        if not products and all_prices:
            products.append(ProductPrice(
                product_name=product_name,
                store_name=store.name,
                store_url=store.url,
                regular_price=all_prices[0],
                sale_price=all_prices[1] if len(all_prices) > 1 else None,
            ))

        return products
