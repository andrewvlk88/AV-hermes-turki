# src/tools/ — Tool Layer for Orchestrator Agent

## Purpose

This directory provides a clean, self-contained **Tool Layer** that an
Orchestrator Agent (or any external caller) can invoke as tools. Each
function wraps existing pipeline logic from `run.py`,
`src/storage/sqlite_store.py`, and `src/agents/analyzer.py` without
duplicating it.

All tools return a standard `{"ok": bool, ...}` dict — JSON-serializable
and ready for any agent framework (Hermes, LangChain, OpenAI
function-calling).

## Tools

### `run_full_scan()` → `dict`

Runs a full price scan across all 20 stores using the tracked product
list from the `tracked_queries` table. Internally delegates to
`run.async_main`, which calls `search_all` (Haturki API → 19 other
stores) and `build_report`.

**Async.** No parameters required. Typical runtime: ~15 min for 6
tracked products.

Returns: `run_id`, `queries`, `summary`, `deals`, `anomalies`,
`stores_checked`, `stores_responded`.

### `run_tracked_products_scan()` → `dict`

Thin alias for `run_full_scan`. Kept as a separate tool for semantic
clarity — an orchestrator may want to explicitly signal "scan tracked
products" vs a generic full scan in the future.

**Async.** No parameters required.

Returns: same shape as `run_full_scan`.

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

## Usage Examples

```python
import asyncio
from src.tools.turki_tools import (
    run_full_scan,
    run_tracked_products_scan,
    get_recent_deals,
    get_scraper_health_report,
    analyze_deal,
)

# ── run_full_scan ──────────────────────────────────────
# Scan all tracked products across all stores (~15 min)
result = await run_full_scan()
print(result["run_id"])     # e.g. "20260623_153457_8b0e311a"
print(result["deals"])       # list of deal strings
print(result["queries"])     # ["בלוגה", "רוסקי סטנדרט", ...]

# ── run_tracked_products_scan ──────────────────────────
# Thin alias — same result, different semantic intent
tracked = await run_tracked_products_scan()
print(tracked["ok"])         # True

# ── get_recent_deals ───────────────────────────────────
# Get all deals from the latest run with score ≥ 70
deals = get_recent_deals(min_score=70.0)
print(deals["deal_count"])   # e.g. 4
for d in deals["deals"]:
    print(d["product_name"], d["savings_percent"])

# Lower threshold to catch more deals
all_deals = get_recent_deals(min_score=0.0)
print(all_deals["deal_count"])

# ── get_scraper_health_report ──────────────────────────
# Check scraper health for the last 7 days
health = get_scraper_health_report(days=7)
print(health["overall_response_rate"])  # e.g. 0.585
for s in health["per_store"]:
    print(s["store_name"], s["status"])

# Check last 24 hours only
today = get_scraper_health_report(days=1)

# ── analyze_deal ───────────────────────────────────────
# Analyze price history for a specific product
info = analyze_deal("בלוגה")
print(info["price_stats"])          # {"min": 119.9, "max": 889.9, ...}
print(info["is_meaningful_deal"])   # True/False
print(info["savings_percent"])      # e.g. 62.4

# Analyze a different product
whisky = analyze_deal("ג'וני ווקר")
print(whisky["cheapest_store"])
print(whisky["latest_turki_price"])
```

## CLI Smoke Test

```bash
cd ~/turk-price-intelligence
./venv/bin/python3 -m src.tools.turki_tools
```

Runs the three sync tools and prints results as JSON. The async scan
tools are commented out in the example to avoid triggering a live
15-minute scrape on every run.