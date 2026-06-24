"""Playwright-based scrapers for JS-heavy Israeli alcohol stores.

Uses CloakBrowser (stealth Chromium with 58 C++ source-level patches) to bypass
Cloudflare, reCAPTCHA, and bot detection. Falls back to regular Playwright if
CloakBrowser is unavailable.

These stores need JS because they load products dynamically
or require interaction (age verification, etc.).
"""
import asyncio
import urllib.parse
import re
import errno
from typing import List, Optional

try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# CloakBrowser — stealth Chromium with C++ fingerprint patches
try:
    from cloakbrowser import launch_persistent_context_async, launch_async
    CLOAK_AVAILABLE = True
except ImportError:
    CLOAK_AVAILABLE = False

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

# ─────────────────────────────────────────────────────────────────────────────
# Browser timeout configuration (SEPARATE from API-based store timeouts).
# These govern only CloakBrowser/Playwright operations — navigation, network
# idle waits, and the hard ceiling for a single store's browser session.
# The API scrapers (WooCommerce/Magento/Haturki) use their own httpx timeouts
# (see unified_scraper.STORE_TIMEOUTS for the orchestrator-level per-store cap).
# ─────────────────────────────────────────────────────────────────────────────
BROWSER_TIMEOUTS = {
    "navigation": 30000,   # 30s — page.goto() default timeout
    "networkidle": 45000,  # 45s — wait_for_load_state("networkidle")
    "store_max": 60000,    # 60s — hard ceiling for a single browser-based store
}

# Retry configuration for CloakBrowser/Playwright operations.
RETRY_MAX_ATTEMPTS = 3    # total attempts (1 initial + 2 retries)
RETRY_BASE_DELAY = 2.0    # seconds — first retry waits this long
RETRY_BACKOFF_FACTOR = 2   # multiply delay by this each attempt (2x exponential)


def _is_epipe_error(exc: BaseException) -> bool:
    """Return True if *exc* is an EPIPE / BrokenPipeError (the Node.js
    Playwright driver raises these when the IPC pipe to the browser process
    breaks under heavy load).

    The Node driver surfaces the raw errno via a string message like
    ``Error: write EPIPE at PipeTransport.send (...)`` so we also match on
    the textual form in addition to the Python-level errno.
    """
    # Python BrokenPipeError (raised by asyncio transports / subprocess pipes)
    if isinstance(exc, BrokenPipeError):
        return True
    # errno.EPIPE via OSError subclasses (ConnectionError, OSError, …)
    if isinstance(exc, OSError) and exc.errno in (errno.EPIPE, errno.ECONNRESET):
        return True
    # String-form EPIPE coming from the Node.js Playwright driver
    msg = str(exc)
    if "EPIPE" in msg or "PipeTransport" in msg or "write EPIPE" in msg:
        return True
    return False


def _is_browser_retriable(exc: BaseException) -> bool:
    """Decide whether *exc* is worth retrying for browser operations.

    Retries help for transient pipe breaks, driver crashes, and timeouts;
    permanent errors (e.g. invalid selector) are left for the caller.
    """
    # EPIPE / BrokenPipeError family — the primary target of this module.
    if _is_epipe_error(exc):
        return True
    # Playwright's own TimeoutError (navigation/load state timeouts)
    if PwTimeout is not None and isinstance(exc, PwTimeout):
        return True
    # asyncio.TimeoutError raised by asyncio.wait_for around browser calls
    if isinstance(exc, asyncio.TimeoutError):
        return True
    # Generic ConnectionError covers reset/aborted pipe variants
    if isinstance(exc, ConnectionError):
        return True
    return False


async def _browser_retry(coro_factory, store_name: str, op_desc: str):
    """Run a browser operation with exponential backoff retry.

    ``coro_factory`` is a zero-argument callable returning a fresh coroutine
    each attempt (so retries actually re-execute the work). Retries up to
    ``RETRY_MAX_ATTEMPTS`` times, sleeping ``RETRY_BASE_DELAY *
    RETRY_BACKOFF_FACTOR**attempt`` seconds between attempts.

    Only errors classified by :func:`_is_browser_retriable` are retried;
    everything else re-raises immediately so callers see real bugs.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001 — we classify below
            last_exc = exc
            if not _is_browser_retriable(exc) or attempt == RETRY_MAX_ATTEMPTS:
                # Non-retriable, or out of attempts — propagate.
                raise
            delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
            logger.warning(
                "[%s] browser op %r failed (attempt %d/%d): %s — retrying in %.0fs",
                store_name, op_desc, attempt, RETRY_MAX_ATTEMPTS, exc, delay,
            )
            await asyncio.sleep(delay)
    # Should be unreachable, but keep mypy happy.
    if last_exc is not None:  # pragma: no cover
        raise last_exc


class PlaywrightEngine:
    """Shared browser pool — prefers CloakBrowser, falls back to Playwright."""
    
    _instance = None
    _browser = None
    _playwright = None
    _use_cloak = CLOAK_AVAILABLE
    
    @classmethod
    async def get_browser(cls):
        """Get or create shared browser instance (Playwright fallback only).

        Wrapped in :func:`_browser_retry` so transient EPIPE / BrokenPipeError
        from the Node.js driver are retried with exponential backoff.
        """
        if cls._browser and cls._browser.is_connected():
            return cls._browser

        async def _launch():
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

        return await _browser_retry(_launch, "PlaywrightEngine", "get_browser")
    
    @classmethod
    async def close(cls):
        """Clean up browser — EPIPE-safe.

        During heavy scraping the IPC pipe to the browser process can break,
        so we swallow EPIPE/BrokenPipeError here to avoid masking the real
        error that triggered cleanup.
        """
        if cls._browser:
            try:
                await cls._browser.close()
            except (BrokenPipeError, ConnectionError) as e:
                logger.warning("EPIPE while closing browser (ignored): %s", e)
            except Exception as e:
                if _is_epipe_error(e):
                    logger.warning("EPIPE while closing browser (ignored): %s", e)
                else:
                    raise
            cls._browser = None
        if cls._playwright:
            try:
                await cls._playwright.stop()
            except (BrokenPipeError, ConnectionError) as e:
                logger.warning("EPIPE while stopping playwright (ignored): %s", e)
            except Exception as e:
                if _is_epipe_error(e):
                    logger.warning("EPIPE while stopping playwright (ignored): %s", e)
                else:
                    raise
            cls._playwright = None


async def _create_context(browser):
    """Create a Playwright browser context with stealth anti-detection settings.

    Configures locale (he-IL), timezone (Asia/Jerusalem), a randomized User-Agent,
    and a 1920×1080 viewport. If ``playwright-stealth`` is installed, applies
    stealth patches to a throwaway page; otherwise injects a JS init script that
    masks ``navigator.webdriver``, ``plugins``, and ``languages``.

    Args:
        browser: A Playwright Browser instance to create the context on.

    Returns:
        A configured Playwright BrowserContext ready for ``new_page()``.
    """
    context = await browser.new_context(
        ignore_https_errors=True,
        user_agent=_get_ua(),
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
        viewport={"width": 1920, "height": 1080},
    )
    if STEALTH_AVAILABLE:
        page = await context.new_page()
        await stealth_async(page)
        await page.close()
    else:
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


async def _create_cloak_context(store_name: str = None):
    """Create a CloakBrowser context with stealth.
    
    Uses launch_async (non-persistent) to avoid cookie/session interference
    between stores. Persistent sessions caused Paneco to return wrong results
    (cached cocktail pages instead of actual search results).
    
    CloakBrowser patches 58 fingerprints at the C++ source level —
    navigator.webdriver, plugins, chrome object, TLS fingerprint, etc.

    Retries on EPIPE / BrokenPipeError via :func:`_browser_retry`.
    """
    async def _launch():
        return await launch_async(
            headless=True,
            locale="he-IL",
            timezone="Asia/Jerusalem",
            humanize=False,
            stealth_args=True,
        )
    browser = await _browser_retry(
        _launch, store_name or "CloakBrowser", "launch_async"
    )
    # Return the browser — caller uses browser.new_page() / browser.new_context()
    return browser


class GenericPlaywrightScraper:
    """Generic Playwright-based scraper for JS-heavy stores.
    
    Navigates to search URL, waits for content to render,
    then extracts products using configured selectors.
    """
    
    def __init__(self, store: Store, config: dict = None):
        """Initialize the scraper with a store and optional config.

        Args:
            store: The Store to scrape (name, url, search_path).
            config: Optional dict with ``timeout`` (ms, per-store override)
                and ``search_patterns`` (list of URL templates with
                ``{query}`` placeholder). When omitted, defaults from
                :data:`BROWSER_TIMEOUTS` and a generic pattern list are used.
        """
        self.store = store
        self.config = config or {}
        # CloakBrowser is slower to render — give more timeout.
        # Use BROWSER_TIMEOUTS["navigation"] as the floor so even fast
        # stores get at least the 30s navigation timeout.
        base_timeout = self.config.get("timeout", BROWSER_TIMEOUTS["navigation"])
        if CLOAK_AVAILABLE:
            base_timeout = max(base_timeout, BROWSER_TIMEOUTS["navigation"])
        self.timeout = base_timeout
        # Separate timeouts for distinct browser phases (see BROWSER_TIMEOUTS).
        self.navigation_timeout = BROWSER_TIMEOUTS["navigation"]
        self.networkidle_timeout = BROWSER_TIMEOUTS["networkidle"]
        self.store_max_timeout = BROWSER_TIMEOUTS["store_max"]
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search using CloakBrowser (preferred) or Playwright fallback.

        The entire search — context creation, page navigation, content
        extraction — is wrapped in an outer ``try/finally`` that guarantees
        the browser context is closed even on EPIPE/BrokenPipeError.
        Each page operation is retried via :func:`_browser_retry` (3 attempts,
        exponential backoff 2s → 4s).
        """
        search_patterns = self.config.get(
            "search_patterns",
            ["/Search/?q={query}", "/?s={query}&post_type=product", 
             "/search/result/?q={query}", "/catalogsearch/result/?q={query}"]
        )
        
        context = None
        products = []
        try:
            # Use CloakBrowser if available, otherwise fall back to Playwright.
            # Both paths are retried on EPIPE via _browser_retry.
            if CLOAK_AVAILABLE:
                context = await _create_cloak_context(store_name=self.store.name)
            else:
                browser = await PlaywrightEngine.get_browser()
                context = await browser.launch_persistent_context(
                    user_data_dir="./data/playwright_sessions",
                    user_agent=_get_ua(),
                    locale="he-IL",
                    timezone_id="Asia/Jerusalem",
                    viewport={"width": 1920, "height": 1080},
                )

            for pattern in search_patterns:
                search_url = self.store.url.rstrip("/") + pattern.replace("{query}", urllib.parse.quote(query))
                
                page = await context.new_page()
                try:
                    # ── Navigation (retried on EPIPE) ────────────────────────
                    async def _navigate():
                        await page.goto(
                            search_url,
                            wait_until="domcontentloaded",
                            timeout=self.navigation_timeout,
                        )
                    await _browser_retry(_navigate, self.store.name, f"goto {search_url}")
                    
                    await asyncio.sleep(2)
                    logger.info("Scraping %s → %s", self.store.name, search_url)
                    
                    # Handle age verification popup — but only for stores that need it
                    # Paneco/Importer (Magento) don't need it and the click can redirect
                    # to wrong pages. Only apply for non-Magento stores.
                    skip_age_handling = "paneco" in self.store.url.lower() or "importer" in self.store.url.lower()
                    if not skip_age_handling:
                        try:
                            # Step 1: Click age confirmation via JS (avoids overlay blocking)
                            await page.evaluate("""() => {
                                const ageLink = document.querySelector('a[id*="right_popup_click"], a[id*="age_confirm"]');
                                if (ageLink) { ageLink.click(); return; }
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
                            
                            # Step 2: Remove overlay divs
                            await page.evaluate("""() => {
                                const selectors = [
                                    '[id*="age_popup"]', '[id*="wrapper_age"]', '[id*="active_popup"]',
                                    '[class*="age-overlay"]', '[id*="age-verification"]',
                                    '[class*="age-verification"]', '[class*="modal-overlay"]',
                                    '[class*="popup-overlay"]', '[class*="showPictures"]'
                                ];
                                selectors.forEach(sel => {
                                    document.querySelectorAll(sel).forEach(el => el.remove());
                                });
                            }""")
                            await asyncio.sleep(1)
                        except Exception as e:
                            logger.warning("Age verification handling failed: %s", e)
                    
                    # Wait a bit more for lazy content.
                    # Don't use networkidle — heavy sites (Magento) never reach it.
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=self.navigation_timeout)
                    except Exception:
                        pass
                    # Magento sites (Paneco, Importer) load search results via AJAX
                    # — they need more time to replace initial placeholder products
                    await asyncio.sleep(6)
                    
                    # ── Content extraction (retried on EPIPE) ─────────────────
                    async def _get_content():
                        return await page.content()
                    html = await _browser_retry(_get_content, self.store.name, "page.content")
                    products = self._extract_products(html, query)
                    
                    if products:
                        return products
                        
                except Exception as e:
                    if _is_epipe_error(e):
                        logger.error("EPIPE during page ops for %s → %s: %s", self.store.name, search_url, e)
                    else:
                        logger.warning("Page navigation/processing failed for %s: %s", search_url, e)
                finally:
                    # Always close the page, even on error — swallow EPIPE
                    # so cleanup never masks the original failure.
                    try:
                        await page.close()
                    except (BrokenPipeError, ConnectionError) as close_err:
                        logger.warning("EPIPE while closing page (ignored): %s", close_err)
                    except Exception as close_err:
                        if _is_epipe_error(close_err):
                            logger.warning("EPIPE while closing page (ignored): %s", close_err)
                        else:
                            logger.warning("Failed to close page: %s", close_err)
        finally:
            # ── Context cleanup — guaranteed even on EPIPE ──────────────────
            if context is not None:
                try:
                    await context.close()
                except (BrokenPipeError, ConnectionError) as e:
                    logger.warning("EPIPE while closing context (ignored): %s", e)
                except Exception as e:
                    if _is_epipe_error(e):
                        logger.warning("EPIPE while closing context (ignored): %s", e)
                    else:
                        logger.warning("Failed to close context: %s", e)
        
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
        """Configure AvivDrinks with a 15s timeout and Elementor search patterns."""
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
        """Configure ManoVino with a 15s timeout and Shopify search patterns."""
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
        """Configure Wine & More with a 20s timeout and custom search pattern."""
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
        elif "פאנקו" in key or "paneco" in store.url.lower():
            return PanecoScraper(store)
        elif "היבואן" in key or "importer" in store.url.lower():
            return ImporterScraper(store)
        else:
            # Generic fallback with store-specific config
            return GenericPlaywrightScraper(store)


class PanecoScraper(GenericPlaywrightScraper):
    """Scraper for פאנקו (paneco.co.il) — Magento-based.
    
    Magento search URL: /catalogsearch/result/?q={query}
    Product containers: li.product.product-item
    Name: .product-item-link
    Price: .price-box .price (regular) / .special-price .price (register/sale)
    Also: data-price-amount attribute on .price-box
    
    NOTE: Magento search with long Hebrew queries returns irrelevant results.
    We shorten the query to the first 2 words to get better matches.
    """
    
    def __init__(self, store: Store):
        """Configure Paneco with a 30s timeout and Magento search pattern."""
        super().__init__(store, {
            "timeout": 30000,
            "search_patterns": [
                "/catalogsearch/result/?q={query}",
            ]
        })
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search with shortened query — Magento handles short queries better."""
        # Take first 2 words for Magento search
        words = query.split()
        short_query = " ".join(words[:2]) if len(words) > 2 else query
        return await super().search(short_query)
    
    def _extract_products(self, html: str, query: str) -> List[ProductPrice]:
        """Extract products from Magento rendered HTML."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        # Magento product containers: li.item.product.product-item
        items = soup.select("li.product.product-item, li.item.product, div.product-item, div.product")
        
        for item in items:
            # Product name: .product-item-link or .product-item-name
            name_el = item.select_one(".product-item-link, .product-item-name")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            # Product URL
            url = name_el.get("href", "")
            if not url:
                link = item.find("a", href=True)
                url = link["href"] if link else ""
            if url and url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            # Regular price: .price-box .price (JS-rendered text)
            # NOTE: data-price-amount is often empty — .price text is the source of truth
            regular_price = None
            price_box = item.select_one(".price-box")
            if price_box:
                price_el = price_box.select_one(".price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    # Strip Hebrew currency symbols and extract number
                    price_match = re.search(r'(\d+[,.]?\d*)', price_text.replace(",", ""))
                    if price_match:
                        try:
                            regular_price = float(price_match.group(1))
                        except ValueError:
                            pass
                # Fallback: data-price-amount attribute
                if regular_price is None:
                    data_price = price_box.get("data-price-amount", "")
                    if data_price:
                        try:
                            regular_price = float(data_price)
                        except ValueError:
                            pass
            
            # Sale/register price: .special-price .price
            sale_price = None
            special_el = item.select_one(".special-price .price, .register-price .price")
            if special_el:
                sale_text = special_el.get_text(strip=True)
                sale_match = re.search(r'(\d+[,.]?\d*)', sale_text.replace(",", ""))
                if sale_match:
                    try:
                        sale_price = float(sale_match.group(1))
                    except ValueError:
                        pass
            
            if regular_price is None and sale_price is None:
                continue
            
            # Filter out non-product noise (Product Qty, ratings, etc.)
            if name in ("Product Qty", "Update Product Qty", "Minimize Qty Form"):
                continue
            if "מתוך" in name and "היו רוכשים" in name:
                continue
            if regular_price and regular_price < 10:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price,
                is_on_sale=sale_price is not None and sale_price < (regular_price or 999999),
                product_url=url,
            ))
        
        return products


class ImporterScraper(GenericPlaywrightScraper):
    """Scraper for היבואן (the-importer.co.il) — Magento-based.
    
    Same Magento structure as Paneco — shortens query for better results.
    """
    
    def __init__(self, store: Store):
        """Configure Importer with a 30s timeout and Magento search pattern."""
        super().__init__(store, {
            "timeout": 30000,
            "search_patterns": [
                "/catalogsearch/result/?q={query}",
            ]
        })
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search with shortened query — Magento handles short queries better."""
        words = query.split()
        short_query = " ".join(words[:2]) if len(words) > 2 else query
        return await super().search(short_query)
    
    def _extract_products(self, html: str, query: str) -> List[ProductPrice]:
        """Extract products from Magento rendered HTML (same as Paneco)."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        products = []
        
        items = soup.select("li.product.product-item, li.item.product, div.product-item, div.product")
        
        for item in items:
            name_el = item.select_one(".product-item-link, .product-item-name")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            url = name_el.get("href", "")
            if not url:
                link = item.find("a", href=True)
                url = link["href"] if link else ""
            if url and url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            # Price: .price text first (JS-rendered), data-price-amount fallback
            regular_price = None
            price_box = item.select_one(".price-box")
            if price_box:
                price_el = price_box.select_one(".price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(r'(\d+[,.]?\d*)', price_text.replace(",", ""))
                    if price_match:
                        try:
                            regular_price = float(price_match.group(1))
                        except ValueError:
                            pass
                if regular_price is None:
                    data_price = price_box.get("data-price-amount", "")
                    if data_price:
                        try:
                            regular_price = float(data_price)
                        except ValueError:
                            pass
            
            sale_price = None
            special_el = item.select_one(".special-price .price, .register-price .price")
            if special_el:
                sale_text = special_el.get_text(strip=True)
                sale_match = re.search(r'(\d+[,.]?\d*)', sale_text.replace(",", ""))
                if sale_match:
                    try:
                        sale_price = float(sale_match.group(1))
                    except ValueError:
                        pass
            
            if regular_price is None and sale_price is None:
                continue
            
            if name in ("Product Qty", "Update Product Qty", "Minimize Qty Form"):
                continue
            if "מתוך" in name and "היו רוכשים" in name:
                continue
            if regular_price and regular_price < 10:
                continue
            
            products.append(ProductPrice(
                product_name=name[:100],
                store_name=self.store.name,
                store_url=self.store.url,
                regular_price=regular_price,
                sale_price=sale_price,
                is_on_sale=sale_price is not None and sale_price < (regular_price or 999999),
                product_url=url,
            ))
        
        return products
