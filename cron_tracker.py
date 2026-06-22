#!/usr/bin/env python3
"""Turkí Price Intelligence — Smart Watchdog Cron (v2.0).

Runs tracked queries silently, then runs the AnalyzerAgent for deep analysis:
  - Deal detection (cheaper than Turki by 5%+)
  - Sale detection (10%+ discount)
  - Anomaly detection (2+ std deviations from average)
  - Smart deduplication and ranking

Watchdog pattern: completely silent when no deals/anomalies found.
When deals exist, prints a structured, ranked report for the LLM to summarize.

Usage:
  python cron_tracker.py              # Run all tracked queries
  python cron_tracker.py --json       # Output JSON for agent consumption
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import run
from run import search_all, build_report, PlaywrightEngine, normalize_for_matching, get_volume_key
from src.storage.sqlite_store import get_db, init_db
from src.models import ProductPrice, PriceReport
from src.agents.analyzer import AnalyzerAgent

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

# Overall run timeout: 30 minutes for 20 stores × several queries
RUN_TIMEOUT_SECONDS = 30 * 60

# Deal thresholds
DEAL_MIN_PERCENT = 5        # Cheaper than Turki by at least 5%
SALE_MIN_PERCENT = 10        # Sale discount of at least 10%
ANOMALY_Z_THRESHOLD = 2.0   # Standard deviations for anomaly flag


class DealRanker:
    """Ranks deals by value — most impactful first."""

    @staticmethod
    def rank(deals: List[Dict]) -> List[Dict]:
        """Sort deals: Turki-beaters first (by % savings), then sales (by % off)."""
        turki_deals = [d for d in deals if d.get("type") == "turki"]
        sale_deals = [d for d in deals if d.get("type") == "sale"]
        anomaly_deals = [d for d in deals if d.get("type") == "anomaly"]

        turki_deals.sort(key=lambda d: d.get("savings_percent", 0), reverse=True)
        sale_deals.sort(key=lambda d: d.get("discount_percent", 0), reverse=True)

        return turki_deals + sale_deals + anomaly_deals


class SmartAnalyzer:
    """Wraps AnalyzerAgent with enhanced deal extraction and formatting."""

    def __init__(self):
        self.analyzer = AnalyzerAgent()
        self.turki_name = "הטורקי"

    def extract_turki_prices(self, all_prices: Dict[str, List[ProductPrice]]) -> Dict[str, float]:
        """Build a lookup of Turki prices by normalized product name + volume."""
        turki_products = all_prices.get(self.turki_name, [])
        lookup = {}
        for p in turki_products:
            best = p.sale_price or p.regular_price
            if not best:
                continue
            norm = normalize_for_matching(p.product_name)
            vol = get_volume_key(p.product_name)
            key = f"{norm}_{vol:.0f}" if vol is not None else norm
            if key not in lookup:
                lookup[key] = best
        return lookup

    def find_turki_match(self, name_key: str, turki_lookup: Dict) -> Optional[float]:
        """Match a product key against Turki lookup."""
        if name_key in turki_lookup:
            return turki_lookup[name_key]
        # Fuzzy: check if key prefix matches
        for tk, tv in turki_lookup.items():
            if name_key.startswith(tk) or tk.startswith(name_key.split("_")[0]):
                return tv
        return None

    def analyze_query(self, all_prices: Dict[str, List[ProductPrice]], query: str) -> Tuple[List[Dict], List[str]]:
        """Deep analysis of a single query's results.

        Returns:
            deals: List of deal dicts with type, product, store, prices, savings
            anomalies: List of anomaly strings
        """
        deals = []
        turki_lookup = self.extract_turki_prices(all_prices)

        # Use AnalyzerAgent for anomaly detection
        try:
            anomalies = self.analyzer._detect_anomalies(all_prices)
        except Exception:
            anomalies = []

        # Build product groups (same logic as run.py build_report)
        all_entries = {}
        for store_name, products in all_prices.items():
            for p in products:
                price = p.sale_price or p.regular_price
                if not price:
                    continue
                norm = normalize_for_matching(p.product_name)
                vol = get_volume_key(p.product_name)
                key = f"{norm}_{vol:.0f}" if vol is not None else f"{norm}_unknown"
                if key not in all_entries:
                    all_entries[key] = {"display_name": p.product_name, "entries": []}
                all_entries[key]["entries"].append({
                    "store": store_name,
                    "price": price,
                    "url": p.product_url,
                    "is_sale": p.is_on_sale,
                    "regular_price": p.regular_price,
                    "sale_price": p.sale_price,
                })

        for name_key, data in all_entries.items():
            entries = data["entries"]
            display_name = data["display_name"]
            sorted_entries = sorted(entries, key=lambda x: x["price"])
            cheapest = sorted_entries[0]

            # Check for Turki deal
            turki_price = self.find_turki_match(name_key, turki_lookup)
            if turki_price and cheapest["price"] < turki_price:
                savings = turki_price - cheapest["price"]
                pct = (savings / turki_price) * 100
                if pct >= DEAL_MIN_PERCENT:
                    deals.append({
                        "type": "turki",
                        "product": display_name,
                        "store": cheapest["store"],
                        "price": cheapest["price"],
                        "turki_price": turki_price,
                        "savings": round(savings, 1),
                        "savings_percent": round(pct, 1),
                        "url": cheapest.get("url", ""),
                    })

            # Check for sales (10%+ discount)
            for e in entries:
                if e["is_sale"] and e["regular_price"] and e["sale_price"]:
                    discount = e["regular_price"] - e["sale_price"]
                    discount_pct = (discount / e["regular_price"]) * 100
                    if discount_pct >= SALE_MIN_PERCENT:
                        deals.append({
                            "type": "sale",
                            "product": display_name,
                            "store": e["store"],
                            "price": e["sale_price"],
                            "regular_price": e["regular_price"],
                            "discount_percent": round(discount_pct, 1),
                            "url": e.get("url", ""),
                        })

        # Add anomalies as deal items (lower priority)
        for anomaly in anomalies:
            deals.append({
                "type": "anomaly",
                "message": anomaly,
            })

        ranked_deals = DealRanker.rank(deals)
        return ranked_deals, anomalies

    def format_deals(self, deals: List[Dict], query: str) -> List[str]:
        """Format deals into readable strings for the watchdog output."""
        lines = []
        seen = set()

        for deal in deals:
            dtype = deal.get("type", "")
            if dtype == "turki":
                key = f"turki_{deal.get('product', '')}_{deal.get('store', '')}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"💰 {deal['product']} — {deal['price']:.0f}₪ ב-{deal['store']} "
                    f"(הטורקי {deal['turki_price']:.0f}₪, חיסכון {deal['savings_percent']:.0f}%)"
                )
            elif dtype == "sale":
                key = f"sale_{deal.get('product', '')}_{deal.get('store', '')}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"🔥 מבצע! {deal['product']} ב-{deal['store']}: "
                    f"{deal['price']:.0f}₪ (במקום {deal['regular_price']:.0f}₪, -{deal['discount_percent']:.0f}%)"
                )
            elif dtype == "anomaly":
                msg = deal.get("message", "")
                key = f"anomaly_{msg}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(msg)

        return lines


async def run_single_query(query: str, analyzer: SmartAnalyzer, run_id: str = None) -> Tuple[List[Dict], List[str]]:
    """Run a single tracked query and return analyzed deals."""
    run.SILENT = True
    init_db()

    logger.info("Starting query: %r run_id=%s", query, run_id)
    try:
        all_prices = await asyncio.wait_for(search_all(query, run_id=run_id), timeout=RUN_TIMEOUT_SECONDS)
        deals, anomalies = analyzer.analyze_query(all_prices, query)
        logger.info("Query %r: %d deals, %d anomalies", query, len(deals), len(anomalies))
        return deals, anomalies
    except asyncio.TimeoutError:
        logger.error("Query %r timed out after %ds", query, RUN_TIMEOUT_SECONDS)
        return [], []
    except Exception:
        logger.exception("Query %r failed", query)
        return [], []


async def main(json_output: bool = False):
    """Main watchdog entry point.

    Args:
        json_output: If True, output JSON for agent consumption instead of text.
    """
    run.SILENT = True
    init_db()

    # Load tracked queries
    conn = get_db()
    try:
        rows = conn.execute("SELECT query FROM tracked_queries ORDER BY id").fetchall()
        queries = [row['query'] for row in rows]
    finally:
        conn.close()

    if not queries:
        logger.info("No tracked queries found; exiting.")
        return

    logger.info("=== Turkí Smart Watchdog run started | %d queries ===", len(queries))
    from src.storage.sqlite_store import run_id_gen
    shared_run_id = run_id_gen()

    analyzer = SmartAnalyzer()
    all_deals = []
    all_anomalies = []
    per_query_stats = []

    try:
        for query in queries:
            deals, anomalies = await run_single_query(query, analyzer, run_id=shared_run_id)
            all_deals.extend(deals)
            all_anomalies.extend(anomalies)
            per_query_stats.append({
                "query": query,
                "deals": len(deals),
                "anomalies": len(anomalies),
            })
    finally:
        try:
            await asyncio.wait_for(PlaywrightEngine.close(), timeout=30)
        except Exception:
            logger.exception("Failed to close PlaywrightEngine cleanly")

    # Deduplicate and rank
    ranked_deals = DealRanker.rank(all_deals)

    # Watchdog pattern: silent if no deals
    if not ranked_deals:
        logger.info("=== Watchdog run finished | 0 deals — silent ===")
        return

    # Format output
    formatted = analyzer.format_deals(ranked_deals, queries[0])

    if json_output:
        # JSON for agent consumption
        output = {
            "timestamp": datetime.now().isoformat(),
            "queries_scanned": len(queries),
            "total_deals": len(ranked_deals),
            "deals": ranked_deals,
            "per_query": per_query_stats,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # Text output for watchdog delivery
        print("🦃 טורקי פרייס ווטשדוג — נמצאו דילים!")
        print()
        for line in formatted[:25]:
            print(f"  {line}")
        print()
        # Summary stats
        turki_count = sum(1 for d in ranked_deals if d.get("type") == "turki")
        sale_count = sum(1 for d in ranked_deals if d.get("type") == "sale")
        anomaly_count = sum(1 for d in ranked_deals if d.get("type") == "anomaly")
        print(f"סה״כ {len(ranked_deals)} דילים · {len(queries)} מוצרים נסרקו")
        if turki_count:
            print(f"  💰 {turki_count} זול מהטורקי")
        if sale_count:
            print(f"  🔥 {sale_count} מבצעים")
        if anomaly_count:
            print(f"  ⚠️ {anomaly_count} אנומליות מחיר")

    logger.info("=== Watchdog run finished | %d deals, %d anomalies ===",
                len(ranked_deals), len(all_anomalies))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Turkí Smart Watchdog Cron")
    parser.add_argument("--json", action="store_true", help="Output JSON for agent consumption")
    args = parser.parse_args()
    asyncio.run(main(json_output=args.json))