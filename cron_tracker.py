#!/usr/bin/env python3
"""Turkí Price Intelligence - Daily Watchdog Cron.

Runs the tracked queries silently. If special deals/price drops are detected
compared to Haturki's reference prices, it prints them in a beautiful cyberpunk format.
If no deals are found, it remains completely silent (watchdog pattern).
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import run
from run import search_all, build_report, PlaywrightEngine
from src.storage.sqlite_store import get_db, init_db

# Configure logging to file for enterprise observability
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "cron_tracker.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("turk_pi.cron_tracker")

# Overall run timeout: 30 minutes is plenty for 18 stores x a few queries.
RUN_TIMEOUT_SECONDS = 30 * 60


async def run_single_query(query: str):
    """Run a single tracked query and return deals found."""
    run.SILENT = True
    init_db()

    logger.info("Starting query: %r", query)
    try:
        all_prices = await asyncio.wait_for(search_all(query), timeout=RUN_TIMEOUT_SECONDS)
        report = build_report(all_prices, query)
        if report.deals_found:
            logger.info("Query %r: %d deals found", query, len(report.deals_found))
        else:
            logger.info("Query %r: no deals", query)
        return report.deals_found or []
    except asyncio.TimeoutError:
        logger.error("Query %r timed out after %ds", query, RUN_TIMEOUT_SECONDS)
        return []
    except Exception:
        logger.exception("Query %r failed", query)
        return []


async def main():
    # Force run.py to run in silent mode
    run.SILENT = True

    init_db()

    conn = get_db()
    try:
        rows = conn.execute("SELECT query FROM tracked_queries ORDER BY id").fetchall()
        queries = [row['query'] for row in rows]
    finally:
        conn.close()

    if not queries:
        logger.info("No tracked queries found; exiting.")
        return

    logger.info("=== Turkí Price Watchdog run started | %d queries ===", len(queries))

    all_deals = []
    try:
        for query in queries:
            deals = await run_single_query(query)
            if deals:
                all_deals.extend(deals)
    finally:
        try:
            await asyncio.wait_for(PlaywrightEngine.close(), timeout=30)
        except Exception:
            logger.exception("Failed to close PlaywrightEngine cleanly")

    unique_deals = []
    # Delivery: Watchdog Pattern (Silent if no deals found)
    if all_deals:
        # Deduplicate deals
        seen = set()
        for d in all_deals:
            if d not in seen:
                seen.add(d)
                unique_deals.append(d)

        # Print deals in clean, simple format
        print("🦃 טורקי פרייס ווטשדוג — נמצאו דילים!")
        print()
        for deal in unique_deals[:20]:
            print(f"  {deal}")
        print()
        print(f"סה״כ {len(unique_deals)} דילים · {len(queries)} מוצרים נסרקו")

    logger.info("=== Watchdog run finished | %d unique deals ===", len(unique_deals))


if __name__ == "__main__":
    asyncio.run(main())
