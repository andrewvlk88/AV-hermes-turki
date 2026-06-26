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
        try:
            from cloakbrowser import CloakBrowser
        except ImportError:
            logger.warning("CloakBrowser not installed, falling back to regular Playwright")
            from src.scrapers.playwright_scrapers import ManoVinoScraper
            return await ManoVinoScraper(self.store).search(query)

        products = []
        encoded_query = quote(query)

        for pattern in self.search_patterns:
            search_url = self.store.url.rstrip("/") + pattern.replace("{query}", encoded_query)

            try:
                with CloakBrowser(headless=True, humanize=True) as browser:
                    page = browser.new_page()
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1500)

                    html = page.content()
                    soup = BeautifulSoup(html, "lxml")

                    # Shopify product grid parsing (same as before)
                    for item in soup.select(".grid__item, .product-item, .product-card"):
                        try:
                            name_el = item.select_one(".product-item__title, .product-card__title, h3, .title")
                            if not name_el:
                                continue
                            name = clean_product_name(name_el.get_text(strip=True))

                            if not is_relevant_product(name, query, min_words=1):
                                continue

                            price_el = item.select_one(".price, .product-item__price, .price__current")
                            price_text = price_el.get_text() if price_el else item.get_text()
                            prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', price_text)
                            if not prices:
                                continue

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

                    if products:
                        return products[:30]

            except Exception as e:
                logger.warning(f"CloakBrowser failed on {search_url}: {e}")
                continue

        return products
