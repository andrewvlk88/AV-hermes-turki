# src/tools/ — Tool Layer for Orchestrator Agent

## Purpose

This directory provides a clean, self-contained **Tool Layer** that an
Orchestrator Agent (or any external caller) can invoke as tools. Each
function wraps existing pipeline logic from `run.py`,
`src/storage/sqlite_store.py`, and `src/agents/analyzer.py` without
duplicating it.

## Tools

All tools live in `turki_tools.py` and return a standard
`{"ok": bool, ...}` dict — JSON-serializable and ready for any agent
framework (Hermes, LangChain, OpenAI function-calling).

### `run_full_scan(queries: list[str])` → `dict`

Runs a full price scan across all 20 stores for the given product
queries. Internally delegates to `run.async_main`, which calls
`search_all` (Haturki API → 19 other stores) and `build_report`.

**Async.** Typical runtime: ~2 min per query.

Returns: `run_id`, `summary`, `deals`, `anomalies`, `stores_checked`,
`stores_responded`.

### `run_tracked_products_scan()` → `dict`

Reads all products from the `tracked_queries` table (managed by
`manage_tracker.py`) and runs a full scan on them. Delegates to
`run_full_scan`.

**Async.** Typical runtime: ~15 min for 6 tracked products.

Returns: same as `run_full_scan`, plus `tracked_queries` list.

### `get_recent_deals(min_score: float = 70.0)` → `dict`

Returns deals from the most recent run whose score ≥ `min_score`.
Queries the `deal_scores` SQLite table.

**Sync.** Fast (DB read only).

Returns: `run_id`, `min_score`, `deal_count`, `deals` (list of dicts
with product, store, price, Turki price, savings %, score).

### `get_scraper_health_report(days: int = 7)` → `dict`

Returns scraper health metrics from the last `days` days. Aggregates
the `scraper_health` table: response rates, deal counts, anomaly
counts, and per-store status from the latest run.

**Sync.** Fast (DB read only).

Returns: `period_days`, `overall_response_rate`, `per_query` (list),
`per_store` (list from latest run).

### `analyze_deal(product_name: str)` → `dict`

Historical price analysis for a single product. Pulls all rows from
`price_results` matching `product_name` (LIKE search), computes price
statistics (min/max/avg), identifies the cheapest store, and
determines whether the latest price is a meaningful deal (≥5% below
the Turki baseline).

**Sync.** Fast (DB read only).

Returns: `product`, `history_count`, `price_stats`, `cheapest_store`,
`is_meaningful_deal`, `latest_turki_price`, `latest_lowest_price`,
`savings_percent`.

## Usage

```python
import asyncio
from src.tools.turki_tools import (
    run_full_scan,
    run_tracked_products_scan,
    get_recent_deals,
    get_scraper_health_report,
    analyze_deal,
)

# Sync tools — call directly
health = get_scraper_health_report(days=7)
deals  = get_recent_deals(min_score=70.0)
info   = analyze_deal("בלוגה")

# Async tools — await them
result = await run_full_scan(["וודקה בלוגה ליטר"])
result = await run_tracked_products_scan()
```

## CLI Smoke Test

```bash
cd ~/turk-price-intelligence
./venv/bin/python3 -m src.tools.turki_tools
```

Runs the three sync tools and prints results as JSON. The async scan
tools are commented out in the example to avoid triggering a live
15-minute scrape on every run.