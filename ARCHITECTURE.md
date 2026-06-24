# ARCHITECTURE — Turkí Price Intelligence

System architecture, module responsibilities, and data flow for the
AV-hermes-turki price-intelligence engine.

> **Audience:** developers and AI agents working on the codebase.
> This document describes the **current** architecture. It is updated
> alongside code changes — keep it in sync.

---

## 1. High-Level Overview

The system compares alcohol prices across **20 Israeli stores**, using
**הטורקי (Turki)** as the reference/baseline store. For every tracked
query, Turki is scraped first (fast REST API), then the remaining 19
stores are scraped and their results are matched against the Turki
baseline. A "deal" is any product at least 5% cheaper than the
matching Turki product.

Two distinct scraping paths exist and are kept cleanly separated:

```
                         ┌─────────────┐
                         │   run.py    │  ← entry point (CLI / agent)
                         └──────┬──────┘
                                │
                 ┌──────────────┼──────────────┐
                 ▼              ▼              ▼
          HaturkiAPIScraper  UnifiedScraper  (report build)
          (REST API path)    (orchestrator)   run.build_report
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        API scrapers     HTML scrapers    Playwright scrapers
        (httpx + JSON)   (httpx/Cloak    (CloakBrowser + JS
                          HTML fetch)      render, full Chromium)
```

---

## 2. Scraper Hierarchy — API vs. Browser

Scrapers are divided into three layers, each in its own module. The
`UnifiedScraper` class in `unified_scraper.py` is the single dispatcher
that picks the right scraper per store based on a per-store `engine`
string in `STORE_CONFIGS`.

### Layer 1 — REST API scrapers (`api_scrapers.py` + `unified_scraper.py`)

Pure HTTP (httpx), no browser. Fastest path.

| Class | Module | Used for |
|-------|--------|----------|
| `HaturkiAPIScraper` | `api_scrapers.py` | הטורקי — custom REST API |
| `WooCommerceAPIScraper` | `unified_scraper.py` | WooCommerce Store API stores |
| `MagentoAPIScraper` | `unified_scraper.py` | Magento REST API stores (if used) |
| `GenericAPIScraper` | `api_scrapers.py` | Legacy HTML-from-API fallback (rarely used) |

These scrapers use **progressive querying**: first search by the first
2 words of the query, then fall back to the first word alone. This
bypasses strict server-side matching that returns 0 results for long
Hebrew queries (especially with brand abbreviations like ק.ס).

### Layer 2 — HTML scrapers (`html_scrapers.py`)

Fetch HTML (via CloakBrowser stealth fetch or httpx fallback) and parse
with BeautifulSoup. No full JS render — just the static HTML.

| Class | Used for |
|-------|----------|
| `MagentoHTMLScraper` | Magento 2 stores from rendered HTML |
| `SarHascraper` | שר המשקאות — custom `.product-box` structure |
| `ProdBoxScraper` | Generic `.prod-box` / `.products__block` structure (Drinks4U, אליאסי, לגימה) |
| `HTMLFallbackScraper` (in `unified_scraper.py`) | Last-resort HTML fallback |

The shared `_fetch_html()` helper in `html_scrapers.py` tries
CloakBrowser first (to bypass Cloudflare/age popups) and falls back to
plain httpx.

### Layer 3 — Playwright/CloakBrowser scrapers (`playwright_scrapers.py`)

Full headless Chromium via CloakBrowser (stealth Chromium with 58 C++
fingerprint patches) or plain Playwright as fallback. Used for JS-heavy
stores that load products dynamically or require interaction (age
verification popups).

| Class | Used for |
|-------|----------|
| `GenericPlaywrightScraper` | Base class — navigates, renders, extracts |
| `PanecoScraper` | פאנקו — Magento-based, query shortening |
| `ImporterScraper` | היבואן — Magento-based, query shortening |
| `AvivDrinksScraper` | בית המשקאות של אביב — Elementor |
| `ManoVinoScraper` | מנו וינו — Shopify |
| `WineAndMoreScraper` | Wine & More — custom JS-heavy |
| `PwScraperFactory` | Factory that returns the right Playwright scraper |

**Key constraint:** CloakBrowser instantiates a full Chromium process
per store. To avoid session lock files and memory exhaustion, browser
stores are gated by an `asyncio.Semaphore(MAX_BROWSER_CONCURRENCY=3)` —
at most 3 browser scrapers run in parallel. API stores (WooCommerce,
Magento, Haturki) run concurrently with no limit. See §7 for details.

---

## 3. Store List (20 stores) with Scraping Method

| # | Store | URL | Engine | Scraping Method |
|---|-------|-----|--------|-----------------|
| 1 | הטורקי | haturki.com | `haturki_api` | REST API (custom) — **reference store** |
| 2 | פאנקו | paneco.co.il | `playwright` | CloakBrowser + Magento extractor |
| 3 | בנא משקאות | banamashkaot.co.il | `woocommerce` | WooCommerce Store API |
| 4 | היבואן | the-importer.co.il | `playwright` | CloakBrowser + Magento extractor |
| 5 | דרך היין | wineroute.co.il | `woocommerce` | WooCommerce Store API |
| 6 | שר המשקאות | mashkaot.co.il | `sar` | HTML scraper (`.product-box`) |
| 7 | אליאסי משקאות | eliasi.co.il | `prodbox_eliasi` | HTML scraper (`.products__block`) |
| 8 | ארי משקאות | ari-g.co.il | `woocommerce` | WooCommerce Store API |
| 9 | Liquor Store | liquor-store.co.il | `woocommerce` | WooCommerce Store API |
| 10 | אלכוהום | alcohome.co.il | `woocommerce` | WooCommerce Store API |
| 11 | משקאות המשמח | hamesameach.co.il | `woocommerce` | WooCommerce Store API |
| 12 | מנו וינו | manovino.co.il | `playwright_manovino` | CloakBrowser (Shopify) |
| 13 | בית המשקאות של אביב | avivdrinks.co.il | `playwright_aviv` | CloakBrowser (Elementor) |
| 14 | Wine & More | wineandmore.co.il | `playwright_wineandmore` | CloakBrowser (custom JS) |
| 15 | לגימה | legima.co.il | `prodbox_legima` | HTML scraper (`.boxItem-wrap`) |
| 16 | Coffeco | coffeco.co.il | `woocommerce` | WooCommerce Store API |
| 17 | Drinks4U | drinks4u.co.il | `prodbox_drinks4u` | HTML scraper (`.prod-box`) |
| 18 | Alcohol123 | alcohol123.co.il | `woocommerce` | WooCommerce Store API |
| 19 | בית היין | winehouse.co.il | `woocommerce` | WooCommerce Store API |

> **Note:** The `STORE_CONFIGS` list in `unified_scraper.py` is the
> single source of truth for this table. It is auto-generated from
> `config.yaml`.

### Method summary

| Method | Count | Stores |
|--------|-------|--------|
| REST API (Haturki custom) | 1 | הטורקי |
| WooCommerce Store API | 9 | בנא, דרך היין, ארי, Liquor Store, אלכוהום, משקאות המשמח, Coffeco, Alcohol123, בית היין |
| HTML scraper (CloakBrowser/httpx fetch) | 4 | שר המשקאות, אליאסי, לגימה, Drinks4U |
| CloakBrowser + Playwright (JS render) | 5 | פאנקו, היבואן, מנו וינו, אביב, Wine & More |

---

## 4. Data Flow: query → scrape → filter → compare → report

```
┌──────────────────────────────────────────────────────────────────────┐
│  1. QUERY                                                            │
│     User provides a product query (Hebrew), e.g. "וודקה בלוגה ליטר" │
│     Source: CLI (run.py), cron_tracker.py, or OrchestratorAgent       │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2. SCRAPE                                                           │
│     run.search_all() orchestrates:                                   │
│       a. HaturkiAPIScraper → Turki baseline (fast, ~200ms)          │
│       b. UnifiedScraper.search_all() → 19 stores concurrently       │
│          Split: API stores (unlimited) + browser stores (Semaphore  │
│          = 3). Each store → get_scraper() → right engine → search()│
│          Per-store hard timeout (90-120s) via asyncio.wait_for      │
│     Results saved to SQLite immediately (partial progress survives) │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  3. FILTER                                                           │
│     In UnifiedScraper.search_all() and again in build_report():     │
│       - clean_product_name() — decode HTML entities                 │
│       - is_bogus_price() — reject prices below brand hard floors   │
│       - is_relevant_product() — require brand-word match           │
│       - is_relevant_volume_by_name() — drop 200ml/500ml            │
│       - is_accessory() — drop glasses, gift sets, syrups           │
│     filter_products_with_turki_match() — drop products with no     │
│     matching Turki baseline (can't compare → no value)             │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  4. COMPARE                                                          │
│     build_report() in run.py:                                        │
│       - normalize_for_matching() — Hebrew alias normalization       │
│         (ק.ס → קברנה סוביניון, etc.)                                 │
│       - get_volume_key() — extract volume for grouping              │
│       - Group products by normalized_name + volume                  │
│       - find_turki_match() — strict volume matching (±50ml)        │
│       - llm_validate_deal() — LLM validates candidate deals        │
│       - Identify cheapest store per product group                   │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  5. REPORT                                                           │
│     PriceReport (Pydantic model):                                    │
│       - Per-product ComparisonResult (all stores, cheapest, savings)│
│       - deals_found list (💰 Turki-beaters, 🔥 sales)               │
│       - anomalies (2+ std deviations)                               │
│     Output formats:                                                  │
│       - JSON file (data/*.json)                                     │
│       - TXT summary (data/*.txt) — Telegram-ready                   │
│       - CSV export (src/export/csv_export.py)                       │
│       - SQLite tables (price_results, deal_scores, scraper_health) │
│       - Telegram format (format_telegram)                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. Key Modules and Their Responsibilities

### Entry points (project root)

| File | Responsibility |
|------|----------------|
| `run.py` | Main CLI entry point. Orchestrates search_all → build_report → export. Contains `normalize_for_matching()`, `find_turki_match()`, `filter_products_with_turki_match()`, and `build_report()`. |
| `cron_tracker.py` | Silent watchdog cron. Runs tracked queries, uses `SmartAnalyzer` for deal/sale/anomaly detection. Silent when no deals; prints ranked report when deals exist. |
| `manage_tracker.py` | CLI tool for managing tracked products (list, add, remove, run). Seeds default products on first run. |
| `dashboard.py` | Streamlit live dashboard (RTL) showing latest run results. |

### Scrapers (`src/scrapers/`)

| File | Responsibility |
|------|----------------|
| `unified_scraper.py` | **Main orchestrator.** `UnifiedScraper` dispatches to the right scraper per store via `STORE_CONFIGS`. Contains `WooCommerceAPIScraper`, `MagentoAPIScraper`, `HTMLFallbackScraper`. `search_all()` splits stores into API (unlimited concurrency) and browser (`asyncio.Semaphore(3)`) groups, dispatches both via `asyncio.gather`. Per-store hard timeout (90-120s) via `asyncio.wait_for`. |
| `api_scrapers.py` | `HaturkiAPIScraper` (custom REST API for Turki), `GenericAPIScraper` (legacy HTML-from-API), `StoreScraperFactory`. |
| `html_scrapers.py` | HTML-based scrapers for stores without APIs. `MagentoHTMLScraper`, `SarHascraper`, `ProdBoxScraper`, `StoreMatcher`. Shared `_fetch_html()` helper (CloakBrowser → httpx fallback). |
| `playwright_scrapers.py` | CloakBrowser/Playwright scrapers for JS-heavy stores. `PlaywrightEngine` (shared browser pool), `GenericPlaywrightScraper` (base), store-specific subclasses (Paneco, Importer, Aviv, ManoVino, WineAndMore), `PwScraperFactory`. Includes EPIPE detection (`_is_epipe_error`), retry with backoff (`_browser_retry`), separate browser timeouts (`BROWSER_TIMEOUTS`), and guaranteed context/page cleanup in `finally` blocks. |

### Agents (`src/agents/`)

| File | Responsibility |
|------|----------------|
| `orchestrator.py` | `OrchestratorAgent` — intelligent coordinator. Accepts natural-language goals, plans via LLM (DeepSeek V4 Flash) or keyword fallback, executes tools, returns structured result. Single-pass planner (not ReAct). |
| `strategist.py` | `StrategistAgent` — business intelligence. Consumes Orchestrator output, generates actionable recommendations (Price Action, Promotion, Monitor, Ignore, Competitor Aggressive, Stock Opportunity) via LLM. |
| `analyzer.py` | `AnalyzerAgent` — price comparison, deal detection (5%+ below Turki), sale detection (10%+ discount), anomaly detection (2+ std dev). |
| `extractor.py` | `ExtractorAgent` — parses HTML from store pages, extracts structured product data (JSON-LD first, HTML elements fallback). |
| `searcher.py` | `SearcherAgent` — legacy searcher using Playwright + httpx. Loads store config from `config.yaml`. |

### Tools (`src/tools/`)

| File | Responsibility |
|------|----------------|
| `turki_tools.py` | Tool layer for the Orchestrator. Self-contained functions: `run_full_scan()`, `run_tracked_products_scan()`, `get_recent_deals()`, `get_scraper_health_report()`, `analyze_deal()`. Each returns `{"ok": bool, ...}`. |

### Utils (`src/utils/`)

| File | Responsibility |
|------|----------------|
| `filters.py` | Product name cleaning, relevance matching, bogus price detection, volume extraction (regex → LLM fallback), accessory filtering, STOP_WORDS, volume filtering (200ml/500ml exclusion). |
| `llm_volume.py` | LLM-powered volume extraction fallback (DeepSeek V4 Flash via Ollama Cloud). Called only when regex-based `extract_volume_ml()` returns None. Cached with `lru_cache`. |
| `llm_deals.py` | LLM-powered deal validation — validates candidate Turki deals to reject false positives. |

### Storage (`src/storage/`)

| File | Responsibility |
|------|----------------|
| `sqlite_store.py` | All SQLite logic: `init_db()`, `save_store_result()`, `mark_store_error()`, `mark_store_running()`, `save_deal_scores()`, `save_scraper_health()`, `run_id_gen()`, `get_db()`. Tables: `price_results`, `price_history`, `deal_scores`, `scraper_health`, `store_status`, `tracked_queries`. |

### Export (`src/export/`)

| File | Responsibility |
|------|----------------|
| `csv_export.py` | CSV export for comparative reports and historical tracking. |

### Models (`src/models.py`)

Pydantic models: `Store`, `ProductPrice`, `ComparisonResult`, `SearchQuery`, `PriceReport`.

---

## 6. Agent Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OrchestratorAgent                        │
│                                                             │
│  execute(goal, constraints)                                 │
│    │                                                        │
│    ├─ 1. Plan (LLM or keyword fallback)                     │
│    │      intent: scan / analyze / deals / health / auto    │
│    │                                                        │
│    ├─ 2. Act — calls tools via turki_tools.py                │
│    │      ├─ get_scraper_health_report()  ← health gate     │
│    │      ├─ run_full_scan() / run_tracked_products_scan()  │
│    │      ├─ get_recent_deals(min_score)                    │
│    │      └─ analyze_deal(product_name)                     │
│    │                                                        │
│    └─ 3. Report — structured output with decisions            │
│                                                             │
│  (optional) ──→ StrategistAgent.generate_recommendations()  │
│                   │                                         │
│                   └─ LLM → business recommendations          │
└─────────────────────────────────────────────────────────────┘
```

**Separation of concerns:**
- **Orchestrator** = data collection + tool execution
- **Strategist** = business intelligence + recommendations
- The Strategist never calls the Orchestrator — it only consumes its output.

**LLM planning:** DeepSeek V4 Flash via Ollama Cloud. Falls back to
keyword matching if LLM is unavailable. Plans are cached in-memory for
30 minutes to avoid redundant LLM calls.

---

## 7. Stability and Reliability Mechanisms

| Mechanism | Location | Purpose |
|-----------|----------|---------|
| Per-store hard timeout (90-120s) | `UnifiedScraper.STORE_TIMEOUTS` | One hanging store can't stall the whole run |
| Browser concurrency limit (Semaphore) | `UnifiedScraper.search_all()` — `asyncio.Semaphore(3)` | At most 3 CloakBrowser/Playwright scrapers in parallel; avoids Chromium memory exhaustion and session lock contention. API stores run unlimited. |
| EPIPE / BrokenPipeError handling | `playwright_scrapers._is_epipe_error()` | Detects IPC pipe breaks from the Node.js Playwright driver in 3 forms: Python `BrokenPipeError`, `OSError` with `errno.EPIPE`/`ECONNRESET`, and string-form `"EPIPE"`/`"PipeTransport"` messages. |
| Browser retry with exponential backoff | `playwright_scrapers._browser_retry()` | Retries transient browser ops (EPIPE, TimeoutError, ConnectionError) up to 3 attempts with 2s→4s→8s backoff. Uses a coro_factory so each attempt re-executes the work. Non-retriable errors propagate immediately. |
| Separate browser timeouts (ms) | `playwright_scrapers.BROWSER_TIMEOUTS` | `navigation`=30s (page.goto/domcontentloaded). Separate from the API-level `STORE_TIMEOUTS` (90-120s) so browser and API phases are tuned independently. |
| Guaranteed context cleanup | `GenericPlaywrightScraper.search()` | Outer `try/finally` closes browser context even on EPIPE; inner `try/finally` closes each page. Cleanup errors are swallowed so they never mask the original failure. |
| Partial progress to SQLite | `save_store_result()` per store | Failed stores don't lose successful ones |
| Health gate before scan | `OrchestratorAgent.execute()` | Skip scan if response rate < threshold |
| LLM deal validation | `run.build_report()` → `llm_validate_deal()` | Reject false-positive deals |
| Strict volume matching (±50ml) | `run.find_turki_match()` | Prevent 200ml vs 1L false deals |
| Brand hard price floors | `filters.is_bogus_price()` | Reject ₪10 "Johnny Walker" noise |
| Accessory filtering | `filters.is_accessory()` | Drop glasses, gift sets, syrups |
| 200ml/500ml exclusion | `filters.is_relevant_volume()` | Small bottles not comparable to Turki |
| Progressive querying (WooCommerce/Magento) | API scrapers | Bypass strict server-side matching for Hebrew |
| CloakBrowser non-persistent context | `playwright_scrapers._create_cloak_context()` | Avoid cookie/session interference between stores |
| Age popup skip for Magento | `GenericPlaywrightScraper.search()` | Paneco/Importer age click caused wrong redirects |

### Concurrency Model in Detail

`UnifiedScraper.search_all()` splits stores into two groups at dispatch
time:

```
asyncio.gather(
    [api_store_1, api_store_2, … api_store_9],      ← unlimited, all at once
    [browser_store_1, … browser_store_10],           ← Semaphore(3) gates these
)
```

- **API group** (`woocommerce`, `magento`, `haturki_api`): lightweight
  httpx calls, no concurrency limit.
- **Browser group** (everything else — `playwright*`, `magento_html`,
  `sar`, `prodbox_*`, HTML fallback): each `_scrape_one_store()` call
  acquires the shared `asyncio.Semaphore(3)` before launching a browser
  and releases it in a `finally` block — even on error.

A fresh `Semaphore` is created per `search_all()` call so a long-running
run cannot bleed semaphore slots into the next one.

### Browser Retry and EPIPE Handling

The Node.js Playwright driver communicates with Chromium over an IPC
pipe. Under heavy concurrent load this pipe can break, surfacing as
`BrokenPipeError` or a string `"Error: write EPIPE at PipeTransport…"`.
The module handles this in three layers:

1. **`_is_epipe_error(exc)`** — classifies an exception as EPIPE-related
   (covers all three forms above).
2. **`_is_browser_retriable(exc)`** — extends EPIPE detection with
   `PwTimeout`, `asyncio.TimeoutError`, and `ConnectionError`.
3. **`_browser_retry(coro_factory, store_name, op_desc)`** — wraps a
   browser operation in up to 3 attempts with exponential backoff
   (2s → 4s). Used for `launch_async`, `chromium.launch`, `page.goto`,
   and `page.content`.

---

## 8. Configuration

- **`config.yaml`** — store definitions (name, url, search_path, type). The `STORE_CONFIGS` in `unified_scraper.py` is auto-generated from this.
- **`~/.hermes/.env`** — API keys: `OLLAMA_API_KEY`, `TAVILY_API_KEY`.
- **`requirements.txt`** — Python dependencies (CloakBrowser, Playwright, httpx, BeautifulSoup, Pydantic, etc.).
- **Python venv** — `~/turk-price-intelligence/venv`.

---

## 9. Testing

Tests are in `tests/` — standalone scripts (not pytest), run manually:

| Test | Purpose |
|------|---------|
| `test_20_stores.py` | Verify all 20 stores respond |
| `test_missing_stores.py` | Check for missing/unreachable stores |
| `test_playwright_products.py` | Playwright scraper product extraction |
| `test_playwright_interact.py` | Playwright interaction (age popups, etc.) |
| `test_haturki_html.py` | Haturki HTML structure validation |
| `test_html_structure.py` | HTML structure checks for various stores |
| `test_scrape.py` / `test_scrape_v2.py` | Basic scraping tests |
| `test_deep.py` | Deep scraping test |
| `test_accessible_stores.py` | Check which stores are accessible |
| `test_full_flow_with_strategist.py` | Full pipeline including Strategist |
| `test_orchestrator_real_products.py` | Orchestrator with real products |