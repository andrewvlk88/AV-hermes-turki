"""Searcher Agent - finds products across stores using Playwright + requests."""
import asyncio
import time
import re
import yaml
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
import httpx
from bs4 import BeautifulSoup

from src.models import Store, SearchQuery


class SearcherAgent:
    """Searches for a product across all configured stores."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.stores = [Store(**s) for s in self.config.get("stores", [])]
        self.timeout = self.config.get("tools", {}).get("playwright_timeout", 15000)
        self.max_retries = self.config.get("tools", {}).get("max_retries", 3)
        self.browser = None
        self.context = None

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    async def _init_browser(self):
        """Initialize Playwright browser."""
        p = await async_playwright().start()
        self.browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
            viewport={"width": 1920, "height": 1080}
        )

    async def _close_browser(self):
        if self.browser:
            await self.browser.close()

    def _parse_query(self, raw: str) -> SearchQuery:
        """Parse a product query like 'ג'ק דניאלס 1 ליטר'."""
        query = SearchQuery(raw=raw)
        query.name = raw

        # Extract volume info
        vol_patterns = [
            (r'(\d+\.?\d*)\s*ליטר', lambda m: float(m.group(1)) * 1000),
            (r'(\d+\.?\d*)\s*מ"?ל', lambda m: float(m.group(1))),
            (r'(\d+)\s*ml', lambda m: float(m.group(1))),
            (r'(\d+\.?\d*)\s*L', lambda m: float(m.group(1)) * 1000),
        ]
        for pattern, converter in vol_patterns:
            m = re.search(pattern, raw)
            if m:
                query.volume_ml = converter(m)
                # Remove volume from product name for better search
                query.name = re.sub(pattern, "", raw).strip()
                break

        return query

    async def search_static(self, store: Store, query: str) -> Optional[str]:
        """Search a static HTML store via httpx."""
        search_url = store.url + store.search_path.format(query=quote(query))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(search_url, headers=headers)
                    if resp.status_code == 200:
                        return resp.text
            except Exception as e:
                if attempt == self.max_retries - 1:
                    print(f"  ⚠️ {store.name}: Static search failed - {e}")
                    return None
                await asyncio.sleep(1)
        return None

    async def search_dynamic(self, store: Store, query: str) -> Optional[str]:
        """Search a dynamic (JS-rendered) store via Playwright."""
        search_url = store.url + store.search_path.format(query=quote(query))

        if not self.context:
            await self._init_browser()

        page = await self.context.new_page()
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=self.timeout)
            await asyncio.sleep(1.5)  # Let any lazy content load
            html = await page.content()
            return html
        except PwTimeout:
            # Try to get whatever loaded
            try:
                html = await page.content()
                return html
            except:
                print(f"  ⚠️ {store.name}: Dynamic search timeout")
                return None
        except Exception as e:
            print(f"  ⚠️ {store.name}: Dynamic search error - {e}")
            return None
        finally:
            await page.close()

    async def search_store(self, store: Store, query: str) -> Optional[str]:
        """Search a single store for a product."""
        print(f"  🔍 {store.name}...", end="")
        start = time.time()

        if store.type == "static":
            html = await self.search_static(store, query)
        else:
            html = await self.search_dynamic(store, query)

        elapsed = time.time() - start
        status = "✅" if html else "❌"
        print(f" {status} ({elapsed:.1f}s)")
        return html

    async def search_all(self, raw_query: str) -> dict:
        """Search all stores for a product. Returns {store_name: html_content}."""
        query = self._parse_query(raw_query)
        print(f"\n🔎 Searching for: '{query.name}'")
        if query.volume_ml:
            print(f"   Volume detected: {query.volume_ml}ml")

        results = {}
        try:
            for store in self.stores:
                html = await self.search_store(store, query.raw)
                if html:
                    results[store.name] = {
                        "html": html,
                        "store": store,
                        "query": query.raw,
                    }
        finally:
            await self._close_browser()

        return results

    def search_all_sync(self, raw_query: str) -> dict:
        """Synchronous wrapper."""
        return asyncio.run(self.search_all(raw_query))
