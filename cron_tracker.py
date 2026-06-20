#!/usr/bin/env python3
"""Turkí Price Intelligence - Daily Watchdog Cron.

Runs the tracked queries silently. If special deals/price drops are detected
compared to Haturki's reference prices, it prints them in a beautiful cyberpunk format.
If no deals are found, it remains completely silent (watchdog pattern).
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import run
from run import search_all, build_report, PlaywrightEngine
from src.storage.sqlite_store import get_db, init_db


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
        return
        
    all_deals = []
    
    try:
        for query in queries:
            try:
                # Search all stores sequentially
                all_prices = await search_all(query)
                
                # Build the comparison report
                report = build_report(all_prices, query)
                
                # Collect special deals / savings
                if report.deals_found:
                    all_deals.extend(report.deals_found)
            except Exception:
                # Silently ignore errors during cron so it doesn't spam alerts unless necessary
                continue
    finally:
        # Ensure Playwright browser is closed
        await PlaywrightEngine.close()
        
    # Delivery: Watchdog Pattern (Silent if no deals found)
    if all_deals:
        print("💜 *טורקי פרייס אינטליג׳נס — מצאתי דילים חמים!* 🦃")
        print("=" * 55)
        for deal in all_deals[:15]:  # Cap to top 15 deals to prevent Telegram length limit
            print(f"  {deal}")
        print("=" * 55)
        print("🪽 *Hermes Price Watchdog*")


if __name__ == "__main__":
    asyncio.run(main())
