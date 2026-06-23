"""Turkí Price Intelligence — Tool Layer for Orchestrator Agent.

Clean, self-contained functions that wrap existing pipeline logic.
Each tool returns a typed dict (JSON-serializable) so any agent
framework (Hermes, LangChain, OpenAI function-calling) can consume
the output directly.

Design principles:
  - Reuse, don't duplicate — calls into run.py, sqlite_store, analyzer
  - Every function is async-aware (scan tools) or sync (DB query tools)
  - Every function returns {"ok": bool, ...} — no raw exceptions
  - Type hints + docstrings on every signature
  - Project root auto-injected into sys.path for CLI use
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project root on sys.path ──────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage.sqlite_store import (
    DB_PATH,
    get_db,
    init_db,
    run_id_gen,
    save_deal_scores,
    save_scraper_health,
)
from src.logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════

def _err(msg: str, **extra: Any) -> Dict[str, Any]:
    """Build a standard error response."""
    return {"ok": False, "error": msg, **extra}


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a standard success response."""
    return {"ok": True, **data}


def _latest_run_ids() -> Dict[str, str]:
    """Return {query: latest_run_id} for every query in the DB."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT query, MAX(run_id) as rid FROM price_results GROUP BY query"
        ).fetchall()
        return {r["query"]: r["rid"] for r in rows if r["rid"]}
    finally:
        conn.close()


def _effective_price(row: sqlite3.Row | Dict[str, Any]) -> Optional[float]:
    """Sale price if present, else regular price. Returns None if both absent."""
    sp = row["sale_price"] if isinstance(row, dict) else row["sale_price"]
    rp = row["regular_price"] if isinstance(row, dict) else row["regular_price"]
    return sp if sp is not None else rp


import sqlite3  # noqa: E402 — needed for type hint above


# ════════════════════════════════════════════════════════════════════
#  Tool 1: run_full_scan
# ════════════════════════════════════════════════════════════════════

async def run_full_scan() -> Dict[str, Any]:
    """Run a full price scan across all stores using tracked queries.

    Reads the tracked product list from ``tracked_queries`` (same table
    that ``manage_tracker.py`` manages), then delegates to
    ``run.async_main`` which internally calls ``search_all``
    (Haturki API → 19 other stores) and ``build_report``.

    No parameters required — the tool is self-contained.

    Returns:
        ``{"ok": True, "run_id": str, "queries": [...], "summary": str,
           "deals": [...], "stores_checked": int, "stores_responded": int}``
        on success, or ``{"ok": False, "error": str}`` on failure.
    """
    # Ensure tracked_queries table exists
    try:
        from manage_tracker import init_tracker_db
        init_tracker_db()
    except ImportError as exc:
        return _err(f"cannot import manage_tracker: {exc}")

    # Read tracked queries from DB
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT query FROM tracked_queries ORDER BY id"
        ).fetchall()
        queries = [r["query"] for r in rows]
    finally:
        conn.close()

    if not queries:
        return _err("no tracked products found in tracked_queries table")

    try:
        from run import async_main  # lazy import — run.py is at project root
    except ImportError as exc:
        return _err(f"cannot import run.async_main: {exc}")

    try:
        # async_main generates its own shared_run_id internally
        report = await async_main(queries)
        run_ids = _latest_run_ids()
        # The run_id for these queries is the newest one
        run_id = ""
        for q in queries:
            if q in run_ids:
                run_id = run_ids[q]
                break

        return _ok({
            "run_id": run_id,
            "queries": queries,
            "summary": report.summary if report else "",
            "deals": report.deals_found if report else [],
            "anomalies": report.anomalies if report else [],
            "stores_checked": report.stores_checked if report else 0,
            "stores_responded": report.stores_responded if report else 0,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as exc:
        logger.exception("run_full_scan failed")
        return _err(f"scan failed: {exc}")


# ════════════════════════════════════════════════════════════════════
#  Tool 2: run_tracked_products_scan
# ════════════════════════════════════════════════════════════════════

async def run_tracked_products_scan() -> Dict[str, Any]:
    """Run a scan on all products in the ``tracked_queries`` table.

    This is now a thin alias for :func:`run_full_scan` — both read from
    the same ``tracked_queries`` table. Kept as a separate tool for
    semantic clarity (an orchestrator may want to explicitly signal
    "scan tracked products" vs a generic full scan in the future).

    Returns:
        Same shape as :func:`run_full_scan`.
    """
    return await run_full_scan()


# ════════════════════════════════════════════════════════════════════
#  Tool 3: get_recent_deals
# ════════════════════════════════════════════════════════════════════

def get_recent_deals(min_score: float = 70.0) -> Dict[str, Any]:
    """Return deals from the most recent run whose score ≥ ``min_score``.

    Queries the ``deal_scores`` SQLite table. Each deal includes
    product name, store, price, Turki baseline, savings %, and score.

    Args:
        min_score: Minimum deal score (0–100 scale). Default 70.

    Returns:
        ``{"ok": True, "run_id": str, "deal_count": int, "deals": [...]}``
    """
    latest = _latest_run_ids()
    if not latest:
        return _err("no runs found in database")

    # Use the single most recent run_id across all queries
    # (in batch mode all queries share the same run_id)
    run_id = max(latest.values())

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT product_name, store_name, query, price, turki_price,
                   savings_amount, savings_percent, score, deal_type,
                   run_id, recorded_at
            FROM deal_scores
            WHERE run_id = ? AND score >= ?
            ORDER BY score DESC
            """,
            (run_id, min_score),
        ).fetchall()

        deals = [dict(r) for r in rows]
        return _ok({
            "run_id": run_id,
            "min_score": min_score,
            "deal_count": len(deals),
            "deals": deals,
        })
    except Exception as exc:
        logger.exception("get_recent_deals failed")
        return _err(f"query failed: {exc}")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
#  Tool 4: get_scraper_health_report
# ════════════════════════════════════════════════════════════════════

def get_scraper_health_report(days: int = 7) -> Dict[str, Any]:
    """Return scraper health metrics from the last ``days`` days.

    Aggregates the ``scraper_health`` table: response rates,
    deal counts, anomaly counts, and per-store status from the
    latest run.

    Args:
        days: Look-back window in days. Default 7.

    Returns:
        ``{"ok": True, "period_days": int, "overall_response_rate": float,
           "per_query": [...], "per_store": [...]}``
    """
    conn = get_db()
    try:
        # Per-query health summary
        rows = conn.execute(
            """
            SELECT run_id, query, stores_checked, stores_responded,
                   response_rate, deal_count, anomaly_count, timestamp
            FROM scraper_health
            WHERE timestamp > datetime('now', ?)
            ORDER BY timestamp DESC
            """,
            (f"-{days} days",),
        ).fetchall()

        per_query = [dict(r) for r in rows]

        # Per-store status from the latest run_id
        latest_run = ""
        if per_query:
            latest_run = per_query[0]["run_id"]

        per_store: List[Dict[str, Any]] = []
        if latest_run:
            store_rows = conn.execute(
                """
                SELECT store_name, status, product_count, error_msg, timestamp
                FROM store_status
                WHERE run_id = ?
                ORDER BY store_name
                """,
                (latest_run,),
            ).fetchall()
            per_store = [dict(r) for r in store_rows]

        # Overall response rate
        total_checked = sum(r["stores_checked"] for r in per_query)
        total_responded = sum(r["stores_responded"] for r in per_query)
        overall_rate = (
            round(total_responded / total_checked, 3) if total_checked else 0.0
        )

        return _ok({
            "period_days": days,
            "latest_run_id": latest_run,
            "overall_response_rate": overall_rate,
            "per_query": per_query,
            "per_store": per_store,
        })
    except Exception as exc:
        logger.exception("get_scraper_health_report failed")
        return _err(f"query failed: {exc}")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
#  Tool 5: analyze_deal
# ════════════════════════════════════════════════════════════════════

def analyze_deal(product_name: str) -> Dict[str, Any]:
    """Historical price analysis for a single product.

    Pulls all historical rows from ``price_results`` for products
    whose name contains ``product_name`` (case-insensitive LIKE),
    computes price statistics, identifies the cheapest store, and
    determines whether the latest price is a meaningful deal (≥5%
    below the Turki baseline for the same product).

    Args:
        product_name: Product name or partial name to search for.

    Returns:
        ``{"ok": True, "product": str, "history_count": int,
           "price_stats": {...}, "cheapest_store": str,
           "is_meaningful_deal": bool, "latest_turki_price": float|None,
           "latest_lowest_price": float|None, "savings_percent": float|None}``
    """
    if not product_name or not product_name.strip():
        return _err("product_name must not be empty")

    conn = get_db()
    try:
        # Fetch all historical rows for this product
        rows = conn.execute(
            """
            SELECT run_id, query, store_name, product_name,
                   regular_price, sale_price, volume_ml, is_on_sale,
                   product_url, timestamp
            FROM price_results
            WHERE product_name LIKE ?
            ORDER BY timestamp DESC
            """,
            (f"%{product_name}%",),
        ).fetchall()

        if not rows:
            return _ok({
                "product": product_name,
                "history_count": 0,
                "price_stats": {},
                "cheapest_store": None,
                "is_meaningful_deal": False,
                "latest_turki_price": None,
                "latest_lowest_price": None,
                "savings_percent": None,
                "message": "no historical data found for this product",
            })

        # Compute effective prices
        prices: List[float] = []
        for r in rows:
            p = _effective_price(r)
            if p and p > 0:
                prices.append(p)

        if not prices:
            return _ok({
                "product": product_name,
                "history_count": len(rows),
                "price_stats": {},
                "cheapest_store": None,
                "is_meaningful_deal": False,
                "latest_turki_price": None,
                "latest_lowest_price": None,
                "savings_percent": None,
                "message": "rows found but all have null prices",
            })

        price_stats = {
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "avg": round(sum(prices) / len(prices), 2),
            "count": len(prices),
        }

        # Latest run info
        latest_run = rows[0]["run_id"]

        # Get Turki price from latest run
        latest_turki: Optional[float] = None
        for r in rows:
            if r["run_id"] == latest_run and r["store_name"] and "הטורקי" in r["store_name"].lower():
                latest_turki = _effective_price(r)
                break

        # Get cheapest non-Turki price from latest run
        latest_lowest: Optional[float] = None
        cheapest_store: Optional[str] = None
        for r in rows:
            if r["run_id"] != latest_run:
                continue
            if r["store_name"] and "הטורקי" in r["store_name"].lower():
                continue
            p = _effective_price(r)
            if p and p > 0:
                if latest_lowest is None or p < latest_lowest:
                    latest_lowest = p
                    cheapest_store = r["store_name"]

        # Determine if it's a meaningful deal (≥5% below Turki)
        is_meaningful_deal = False
        savings_pct: Optional[float] = None
        if latest_turki and latest_lowest and latest_turki > 0:
            savings_pct = round((latest_turki - latest_lowest) / latest_turki * 100, 1)
            is_meaningful_deal = savings_pct >= 5.0

        return _ok({
            "product": product_name,
            "history_count": len(rows),
            "price_stats": price_stats,
            "cheapest_store": cheapest_store,
            "is_meaningful_deal": is_meaningful_deal,
            "latest_turki_price": latest_turki,
            "latest_lowest_price": latest_lowest,
            "savings_percent": savings_pct,
            "latest_run_id": latest_run,
        })
    except Exception as exc:
        logger.exception("analyze_deal failed")
        return _err(f"analysis failed: {exc}")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
#  CLI / Example
# ════════════════════════════════════════════════════════════════════

def _print_json(label: str, result: Dict[str, Any]) -> None:
    """Pretty-print a tool result as JSON."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def _example() -> None:
    """Run all five tools as a smoke test / usage example."""

    # 1. get_scraper_health_report (sync — no scan needed)
    health = get_scraper_health_report(days=7)
    _print_json("Tool 4: get_scraper_health_report", health)

    # 2. get_recent_deals (sync — reads from DB)
    deals = get_recent_deals(min_score=0.0)
    _print_json("Tool 3: get_recent_deals", deals)

    # 3. analyze_deal (sync — historical lookup)
    analysis = analyze_deal("בלוגה")
    _print_json("Tool 5: analyze_deal('בלוגה')", analysis)

    # 4. run_full_scan (async — triggers live scraping)
    #    Uncomment to run a live scan (~15 min for tracked products):
    # scan = await run_full_scan()
    # _print_json("Tool 1: run_full_scan", scan)

    # 5. run_tracked_products_scan (async — thin alias of run_full_scan)
    #    Uncomment to run a live scan:
    # tracked = await run_tracked_products_scan()
    # _print_json("Tool 2: run_tracked_products_scan", tracked)

    print("\n✅ Smoke test complete (sync tools only).")
    print("   Uncomment the async scan calls above to run live scraping.")


if __name__ == "__main__":
    asyncio.run(_example())