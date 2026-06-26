"""Store-specific HTML scrapers for stores without APIs."""
import html
import re
import asyncio
import urllib.parse
from typing import List, Optional
from bs4 import BeautifulSoup

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

# curl_cffi — primary HTTP client with Chrome TLS fingerprint impersonation.
# Bypasses basic bot protections (Cloudflare, Akamai, PerimeterX) without
# needing a full browser. Falls back to CloakBrowser/Playwright if it fails.
try:
    from curl_cffi import requests as cffi_requests
    CFFI_AVAILABLE = True
except ImportError:
    CFFI_AVAILABLE = False

from src.models import ProductPrice, Store
from src.logger import get_logger
from src.utils.filters import extract_volume_ml

logger = get_logger(__name__)

# Default headers used when curl_cffi needs explicit headers.
# When impersonate='chrome' is set, curl_cffi automatically sends matching
# TLS fingerprint + JA3 + HTTP/2 fingerprint, so we only add minimal overrides.
_CFFI_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ════════════════════════════════════════════════════════════════════
#  Hard Stores — Enhanced Retry & Circuit Breaker Configuration
# ════════════════════════════════════════════════════════════════════
#
# These three competitors are the most problematic in the Israeli alcohol
# price intelligence landscape. They require stronger retry logic and
# dedicated circuit breaker handling to maintain reliability.
#
# Adding a new hard store is as simple as adding its domain here.
#
# Settings:
#   max_attempts: Total fetch attempts before giving up
#   base_delay:   Initial delay in seconds before first retry
#   backoff_factor: Multiplier for exponential backoff (delay × factor^n)
#   circuit_breaker_threshold: Consecutive failures before skipping store

HARD_STORES: dict[str, dict] = {
    "paneco.co.il": {
        "max_attempts": 5,
        "base_delay": 8,
        "backoff_factor": 1.8,
        "circuit_breaker_threshold": 2,
    },
    "the-importer.co.il": {
        "max_attempts": 5,
        "base_delay": 8,
        "backoff_factor": 1.8,
        "circuit_breaker_threshold": 2,
    },
    "mashkaot.co.il": {
        "max_attempts": 5,
        "base_delay": 8,
        "backoff_factor": 1.8,
        "circuit_breaker_threshold": 2,
    },
}

# Default retry settings for non-hard stores
DEFAULT_RETRY = {
    "max_attempts": 3,
    "base_delay": 2,
    "backoff_factor": 2.0,
}


# ════════════════════════════════════════════════════════════════════
#  Dedicated Circuit Breaker for Hard Stores (Paneco, The Importer, Sar Mashkaot)
# ════════════════════════════════════════════════════════════════════
#
# This is a dedicated, in-memory circuit breaker *only* for the three hard stores.
# It is completely separate from any general circuit breaker logic.
# Design goals: clean, extensible (add domain to HARD_STORES to support new ones),
# observable (state exposed for logging).
#
# States:
#   CLOSED     — normal operation, attempts allowed
#   HALF-OPEN  — some failures but under threshold
#   OPEN       — threshold reached, fetches short-circuited (return None immediately)
#
# On success → reset to CLOSED
# On failure → increment; trip to OPEN if >= threshold
class HardStoreCircuitBreaker:
    """Dedicated Circuit Breaker for paneco.co.il, the-importer.co.il, mashkaot.co.il only."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._failures = {}
            cls._instance._tripped = {}
        return cls._instance

    def _get_domain(self, url: str) -> str:
        return _extract_domain_simple(url)

    def _get_threshold(self, domain: str) -> int:
        cfg = HARD_STORES.get(domain, DEFAULT_RETRY)
        return cfg.get("circuit_breaker_threshold", 2)

    def is_open(self, domain: str) -> bool:
        """Return True if circuit is open (skip this store)."""
        return self._tripped.get(domain, False)

    def get_state(self, domain: str) -> str:
        """Return human-readable circuit state for logging."""
        if self._tripped.get(domain, False):
            return "OPEN"
        failures = self._failures.get(domain, 0)
        threshold = self._get_threshold(domain)
        if failures > 0:
            return f"HALF-OPEN ({failures}/{threshold})"
        return "CLOSED"

    def record_result(self, domain: str, success: bool) -> str:
        """Record success/failure. Returns new state string for logging.
        Only affects hard stores (callers check _is_hard_store first).
        """
        if domain not in HARD_STORES:
            return "N/A (not hard)"

        threshold = self._get_threshold(domain)
        if success:
            prev = self._tripped.get(domain, False)
            self._failures[domain] = 0
            self._tripped[domain] = False
            if prev:
                return "CLOSED (recovered)"
            return "CLOSED"
        else:
            self._failures[domain] = self._failures.get(domain, 0) + 1
            failures = self._failures[domain]
            if failures >= threshold:
                self._tripped[domain] = True
                return f"OPEN (tripped after {failures} failures, threshold={threshold})"
            return f"HALF-OPEN ({failures}/{threshold})"


def _get_retry_config(store_name: str = None, url: str = None) -> dict:
    """Look up retry configuration for a store.

    Checks if the store domain matches a HARD_STORES entry. If so, returns
    the enhanced retry settings. Otherwise returns DEFAULT_RETRY.
    """
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.netloc or parsed.path
        host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        domain = host.lower()
        if domain in HARD_STORES:
            return HARD_STORES[domain]
    return DEFAULT_RETRY


def _is_hard_store(url: str) -> bool:
    """Check if a URL belongs to a hard store that needs enhanced retry logic."""
    cfg = _get_retry_config(url=url)
    return cfg is not DEFAULT_RETRY


async def _fetch_html_cffi(
    url: str,
    store_name: str = None,
    retry_config: dict = None,
) -> Optional[str]:
    """Fetch HTML using curl_cffi with Chrome TLS impersonation.

    This is the primary fetching method. curl_cffi sends a real Chrome TLS
    fingerprint (JA3, HTTP/2 settings, ALPN) so most bot protections let it
    through without challenging.

    Args:
        url: URL to fetch.
        store_name: Store name for logging.
        retry_config: Dict with 'max_attempts', 'base_delay', 'backoff_factor'.
            If None, uses DEFAULT_RETRY (3 attempts, 2s base, 2x backoff).
            Hard stores (paneco, importer, mashkaot) pass stronger settings.
    """
    if not CFFI_AVAILABLE:
        return None

    if retry_config is None:
        retry_config = DEFAULT_RETRY

    max_attempts = retry_config.get("max_attempts", 3)
    base_delay = retry_config.get("base_delay", 2)
    backoff_factor = retry_config.get("backoff_factor", 2.0)

    is_hard = _is_hard_store(url)
    domain = _extract_domain_simple(url)
    domain_label = f"[{domain}]" if is_hard else ""

    breaker = None
    circuit_state = "N/A"
    if is_hard:
        breaker = HardStoreCircuitBreaker()
        if breaker.is_open(domain):
            circuit_state = breaker.get_state(domain)
            logger.warning(
                "%s [curl_cffi] Circuit OPEN — skipping fetch | state=%s",
                domain_label, circuit_state
            )
            return None
        circuit_state = breaker.get_state(domain)
        logger.info(
            "%s [curl_cffi] Starting fetch | circuit=%s | attempts=%d base=%.1fs",
            domain_label, circuit_state, max_attempts, base_delay
        )

    for attempt_num in range(1, max_attempts + 1):
        try:
            async with cffi_requests.AsyncSession(impersonate="chrome") as session:
                resp = await session.get(
                    url,
                    headers=_CFFI_HEADERS,
                    timeout=15,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    text = resp.text
                    if text and len(text) > 200:
                        if is_hard:
                            logger.info(
                                "%s [curl_cffi] Attempt %d/%d | Status: Success (%d chars) | circuit=%s",
                                domain_label, attempt_num, max_attempts, len(text), circuit_state,
                            )
                            if breaker:
                                state = breaker.record_result(domain, True)
                                logger.info("%s [curl_cffi] Circuit state after success: %s", domain_label, state)
                        else:
                            logger.debug("curl_cffi SUCCESS for %s (%d chars)", store_name or url, len(text))
                        return text
                    else:
                        logger.warning(
                            "%s [curl_cffi] Attempt %d/%d | Status: Failed (body too short: %d chars)",
                            domain_label, attempt_num, max_attempts, len(text) if text else 0,
                        )
                else:
                    logger.warning(
                        "%s [curl_cffi] Attempt %d/%d | Status: Failed (HTTP %d)",
                        domain_label, attempt_num, max_attempts, resp.status_code,
                    )
                    # Non-200 from Cloudflare-protected sites — retry, might be a challenge
                    if not is_hard:
                        return None
        except Exception as e:
            logger.warning(
                "%s [curl_cffi] Attempt %d/%d | Status: Failed (%s)",
                domain_label, attempt_num, max_attempts, e,
            )

        # Don't sleep after the last attempt
        if attempt_num < max_attempts:
            delay = base_delay * (backoff_factor ** (attempt_num - 1))
            logger.info(
                "%s [curl_cffi] Retrying in %.1fs (attempt %d/%d)...",
                domain_label, delay, attempt_num + 1, max_attempts,
            )
            await asyncio.sleep(delay)

    logger.warning(
        "%s [curl_cffi] All %d attempts exhausted",
        domain_label, max_attempts,
    )
    if is_hard and breaker:
        state = breaker.record_result(domain, False)
        logger.info("%s [curl_cffi] Circuit state after failure: %s", domain_label, state)
    return None


def _extract_domain_simple(url: str) -> str:
    """Extract domain from URL (lightweight, for logging in hard-store retries)."""
    from urllib.parse import urlparse
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc or parsed.path
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


async def _fetch_html_playwright(
    url: str,
    store_name: str = None,
    retry_config: dict = None,
) -> Optional[str]:
    """Fetch HTML using CloakBrowser (stealth Chromium).

    This is the browser fallback when curl_cffi can't get through (e.g.,
    JS-rendered pages, age-gate popups, advanced Cloudflare challenges).

    Args:
        url: URL to fetch.
        store_name: Store name for logging.
        retry_config: Dict with 'max_attempts', 'base_delay', 'backoff_factor'.
            If None, uses DEFAULT_RETRY. Hard stores get stronger settings.
    """
    if retry_config is None:
        retry_config = DEFAULT_RETRY

    max_attempts = retry_config.get("max_attempts", 3)
    base_delay = retry_config.get("base_delay", 2)
    backoff_factor = retry_config.get("backoff_factor", 2.0)

    is_hard = _is_hard_store(url)
    domain = _extract_domain_simple(url)
    domain_label = f"[{domain}]" if is_hard else ""

    breaker = None
    circuit_state = "N/A"
    if is_hard:
        breaker = HardStoreCircuitBreaker()
        if breaker.is_open(domain):
            circuit_state = breaker.get_state(domain)
            logger.warning(
                "%s [playwright] Circuit OPEN — skipping fetch | state=%s",
                domain_label, circuit_state
            )
            return None
        circuit_state = breaker.get_state(domain)
        logger.info(
            "%s [playwright] Starting fetch | circuit=%s | attempts=%d base=%.1fs",
            domain_label, circuit_state, max_attempts, base_delay
        )

    for attempt_num in range(1, max_attempts + 1):
        try:
            from src.scrapers.playwright_scrapers import CLOAK_AVAILABLE, _create_cloak_context
            if not CLOAK_AVAILABLE:
                return None

            browser = await _create_cloak_context(store_name=store_name)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Bypass age popup via JS click
                try:
                    await page.evaluate('''() => {
                        const keywords = ['מעל 18', 'מעל', 'אני מאשר', 'אישור', 'כן', 'המשך', 'Yes', 'I am'];
                        for (const el of document.querySelectorAll('a, button, input')) {
                            const t = el.textContent.trim();
                            if (keywords.some(k => t.includes(k))) { el.click(); break; }
                        }
                        const selectors = [
                            '[id*="age_popup"]', '[id*="popup18plus"]', '[id*="wrapper_age"]',
                            '[id*="active_popup"]', '.age-overlay', '.modal-backdrop',
                            '.modal-overlay', '.popup-overlay'
                        ];
                        selectors.forEach(sel => {
                            document.querySelectorAll(sel).forEach(el => el.remove());
                        });
                        document.body.classList.remove('modal-open');
                        document.body.style.overflow = 'auto';
                    }''')
                    await asyncio.sleep(1)
                except:
                    pass
                await asyncio.sleep(3)
                content = await page.content()
                if content and len(content) > 200:
                    if is_hard:
                        logger.info(
                            "%s [playwright] Attempt %d/%d | Status: Success (%d chars) | circuit=%s",
                            domain_label, attempt_num, max_attempts, len(content), circuit_state,
                        )
                        if breaker:
                            state = breaker.record_result(domain, True)
                            logger.info("%s [playwright] Circuit state after success: %s", domain_label, state)
                    return content
                else:
                    logger.warning(
                        "%s [playwright] Attempt %d/%d | Status: Failed (content too short)",
                        domain_label, attempt_num, max_attempts,
                    )
            except Exception as e:
                logger.warning(
                    "%s [playwright] Attempt %d/%d | Status: Failed (%s)",
                    domain_label, attempt_num, max_attempts, e,
                )
            finally:
                try:
                    await page.close()
                except:
                    pass
                try:
                    await browser.close()
                except:
                    pass
        except ImportError:
            return None
        except Exception as e:
            logger.warning(
                "%s [playwright] Attempt %d/%d | Status: Failed (%s)",
                domain_label, attempt_num, max_attempts, e,
            )

        # Don't sleep after the last attempt
        if attempt_num < max_attempts:
            delay = base_delay * (backoff_factor ** (attempt_num - 1))
            logger.info(
                "%s [playwright] Retrying in %.1fs (attempt %d/%d)...",
                domain_label, delay, attempt_num + 1, max_attempts,
            )
            await asyncio.sleep(delay)

    logger.warning(
        "%s [playwright] All %d attempts exhausted",
        domain_label, max_attempts,
    )
    if is_hard and breaker:
        state = breaker.record_result(domain, False)
        logger.info("%s [playwright] Circuit state after failure: %s", domain_label, state)
    return None


async def _fetch_html(
    url: str,
    store_name: str = None,
    methods: list = None,
    retry_config: dict = None,
) -> Optional[str]:
    """Fetch HTML using a per-store strategy-driven fallback chain.

    Args:
        url: URL to fetch.
        store_name: Store name for logging.
        methods: Ordered list of fetch methods to try. Each method is a string:
            - "curl_cffi"  — Chrome TLS fingerprint impersonation (fast, no browser)
            - "playwright" — CloakBrowser stealth Chromium (fallback, full browser)
            - "llm"        — Fetch via any available method, caller handles LLM extraction
        If ``methods`` is None, defaults to ["curl_cffi", "playwright"]
        (LLM fallback is handled by the caller, not this function).
        retry_config: Dict with 'max_attempts', 'base_delay', 'backoff_factor'.
            If None, auto-detects from HARD_STORES or uses DEFAULT_RETRY.

    Returns:
        HTML string on success, None if all methods fail.
    """
    if methods is None:
        methods = ["curl_cffi", "playwright"]

    # Auto-detect retry config from HARD_STORES if not explicitly provided
    if retry_config is None:
        retry_config = _get_retry_config(store_name=store_name, url=url)

    for method in methods:
        if method == "curl_cffi":
            html_text = await _fetch_html_cffi(url, store_name, retry_config=retry_config)
            if html_text:
                return html_text
            logger.info("curl_cffi failed for %s — trying next method", store_name or url)
        elif method == "playwright":
            html_text = await _fetch_html_playwright(url, store_name, retry_config=retry_config)
            if html_text:
                return html_text
            logger.info("playwright failed for %s — trying next method", store_name or url)
        # "llm" method: this function just fetches HTML. LLM extraction
        # is done by the caller (UnifiedScraper._scrape_one_store) after
        # we return None. So we don't handle it here — if we reach "llm"
        # in the list and all prior methods failed, just return None and
        # let the caller trigger LLM fallback.
        elif method == "llm":
            logger.info("All HTTP methods exhausted for %s — LLM fallback will be triggered by caller", store_name or url)
            return None

    logger.warning("All fetch methods failed for %s", store_name or url)
    return None


class MagentoHTMLScraper:
    """Scrapes Magento 2 stores from HTML search results.
    
    Works for: היבואן (the-importer.co.il)
    Patterns: .product-item, .product-item-link, .product-info, data-product-id
    """
    
    def __init__(self, store: Store, fetch_methods: list = None):
        self.store = store
        self.fetch_methods = fetch_methods  # Per-store strategy from STORE_STRATEGIES
    
    async def search(self, query: str) -> List[ProductPrice]:
        """Search via HTML."""
        search_url = f"{self.store.url}/search?q={urllib.parse.quote(query)}&limit=20"
        headers = {
            "User-Agent": _get_ua(),
            "Accept": "text/html",
            "Accept-Language": "he-IL,he;q=0.9",
        }
        
        html_text = await _fetch_html(search_url, store_name=self.store.name, methods=self.fetch_methods)
        if not html_text: return []
        soup = BeautifulSoup(html.unescape(html_text), "lxml")
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
        
        return products


class SarHascraper:
    """Scraper for שר המשקאות (mashkaot.co.il).
    
    Patterns: .catalog__item > .product-box > .product-box-info
    Structure:
      .product-box-info__title → product name
      .product-box-info__price-new → sale price
      .product-box-info__price-old → regular price
    """
    
    def __init__(self, store: Store, fetch_methods: list = None):
        self.store = store
        self.fetch_methods = fetch_methods
    
    async def search(self, query: str) -> List[ProductPrice]:
        search_url = f"{self.store.url}/?s={urllib.parse.quote(query)}&post_type=product"
        headers = {
            "User-Agent": _get_ua(),
            "Accept": "text/html",
        }
        
        html_text = await _fetch_html(search_url, store_name=self.store.name, methods=self.fetch_methods)
        if not html_text: return []
        soup = BeautifulSoup(html.unescape(html_text), "lxml")
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
                box_html = box.get_text(separator=" ")
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
        
        return products


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
                 search_pattern: str = "/?s={query}&post_type=product",
                 fetch_methods: list = None):
        self.store = store
        self.fetch_methods = fetch_methods
        self.container_class = container_class
        self.title_class = title_class
        self.price_class = price_class
        self.search_pattern = search_pattern
    
    async def search(self, query: str) -> List[ProductPrice]:
        search_url = self.store.url.rstrip("/") + self.search_pattern.replace("{query}", urllib.parse.quote(query))
        headers = {
            "User-Agent": _get_ua(),
            "Accept": "text/html",
        }
        
        html_text = await _fetch_html(search_url, store_name=self.store.name, methods=self.fetch_methods)
        if not html_text: return []
        soup = BeautifulSoup(html.unescape(html_text), "lxml")
        products = []
        
        # Find containers - include "a" for Drinks4U <a class="prod-box"> and "article" for Wine & More
        containers = soup.find_all(["div", "li", "a", "article"], class_=re.compile(self.container_class, re.I))
        
        for c in containers:
            # Title - improved extraction with fallbacks for layout_list_item + ProductItem
            title_el = c.find(class_=re.compile(self.title_class, re.I))
            if not title_el:
                # Fallback: try common title containers or the link itself
                title_el = c.find(["h1", "h2", "h3", "h4", "span", "a"], class_=re.compile(r"title|name|text|heading", re.I))
            if not title_el and c.name == "a" and c.get("href"):
                title_el = c  # <a> itself may contain the title text
            name = title_el.get_text(strip=True)[:100] if title_el else ""
            if not name or len(name) < 3:
                continue
            
            # Skip noise
            if re.search(r'משלוח|לתקנון|מבצע|חינם|קופון|מינימום|הזמנה', name):
                continue
            
            # Link
            a_tag = c.find("a", href=True)
            if not a_tag and c.name == "a" and c.get("href"):
                a_tag = c
            url = a_tag["href"] if a_tag else ""
            if url and url.startswith("/"):
                url = self.store.url.rstrip("/") + url
            
            # Price
            price_el = c.find(class_=re.compile(self.price_class, re.I))
            price_text = price_el.get_text(separator=" ") if price_el else c.get_text(separator=" ")
            prices = re.findall(r'(?:מחיר[^0-9]*)?(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח|NIS|ILS)', price_text, re.IGNORECASE)
            if not prices:
                prices = re.findall(r'(\d+[\d,]*\.?\d*)\s*(?:₪|ש"ח)', price_text)
            
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
        
        return products


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
