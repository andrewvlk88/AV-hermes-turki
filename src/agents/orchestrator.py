"""Orchestrator Agent — coordinates Searcher, Extractor, and Analyzer agents.

This is the main pipeline coordinator for Turkí Price Intelligence.
It chains the three agent types together:

    SearcherAgent → finds products across stores
         ↓
    ExtractorAgent → parses HTML, extracts structured ProductPrice data
         ↓
    AnalyzerAgent → compares prices, finds deals, detects anomalies

The Orchestrator manages the full lifecycle:
  - Load tracked queries from DB (or accept ad-hoc queries)
  - Run searches sequentially (CloakBrowser constraint)
  - Persist results to SQLite at each step (partial survival)
  - Log scraper health metrics
  - Produce final PriceReport with deals + anomalies + summary

Usage:
    from src.agents.orchestrator import OrchestratorAgent

    orch = OrchestratorAgent()
    report = await orch.run_query("וודקה בלוגה ליטר")

    # Or batch mode for all tracked products:
    reports = await orch.run_tracked()
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models import ProductPrice, PriceReport, Store, ComparisonResult
from src.storage.sqlite_store import (
    get_db, init_db, save_store_result, mark_store_error,
    mark_store_running, run_id_gen,
)
from src.agents.analyzer import AnalyzerAgent
from src.agents.extractor import ExtractorAgent
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product

logger = logging.getLogger("turk_pi.orchestrator")

# Import search engine from run.py (avoids circular imports)
# We import lazily inside methods because run.py imports from src.* too


class OrchestratorAgent:
    """Main pipeline coordinator — chains Search → Extract → Analyze.

    Replaces the procedural flow in run.py with a clean agent-based architecture
    while keeping full backward compatibility (run.py still works as-is).

    Pipeline per query:
        1. Search: Haturki API → other 19 stores (sequential)
        2. Extract: Clean + filter + normalize product names
        3. Analyze: Deal detection, anomaly detection, comparison
        4. Persist: SQLite (price_results, store_status, price_history, scraper_health)
        5. Report: PriceReport with deals + anomalies + summary
    """

    def __init__(self, timeout_per_query: int = 30 * 60):
        self.timeout = timeout_per_query
        self.analyzer = AnalyzerAgent()
        self.extractor = ExtractorAgent()

    async def run_query(self, query: str, save_to_db: bool = True) -> PriceReport:
        """Run the full pipeline for a single query.

        Args:
            query: Product search term (e.g., "וודקה בלוגה ליטר")
            save_to_db: If True, persist results to SQLite

        Returns:
            PriceReport with deals, anomalies, and per-product comparison
        """
        # Import here to avoid circular imports
        from run import search_all, build_report, PlaywrightEngine

        init_db()
        run_id = run_id_gen()

        logger.info("Orchestrator: starting query=%r run_id=%s", query, run_id)

        try:
            # Phase 1: Search
            all_prices = await asyncio.wait_for(
                search_all(query), timeout=self.timeout
            )

            # Phase 2: Extract (clean + filter — already done inside search_all,
            # but we can enhance here)
            filtered = self._filter_prices(all_prices, query)

            # Phase 3: Analyze
            report = build_report(filtered, query)

            # Phase 4: Persist health metrics
            if save_to_db:
                self._log_scraper_health(run_id, query, report)

            logger.info(
                "Orchestrator: query=%r done | %d stores responded | %d deals | %d anomalies",
                query, report.stores_responded, len(report.deals_found), len(report.anomalies),
            )

            return report

        except asyncio.TimeoutError:
            logger.error("Orchestrator: query=%r timed out after %ds", query, self.timeout)
            report = PriceReport(query=query)
            report.summary = f"⏱️ Timeout after {self.timeout}s"
            return report

        except Exception as e:
            logger.exception("Orchestrator: query=%r failed", query)
            report = PriceReport(query=query)
            report.summary = f"❌ Error: {e}"
            return report

        finally:
            try:
                await asyncio.wait_for(PlaywrightEngine.close(), timeout=30)
            except Exception:
                logger.exception("Orchestrator: failed to close Playwright engine")

    async def run_tracked(self) -> List[PriceReport]:
        """Run the full pipeline for all tracked queries from the DB.

        Returns:
            List of PriceReports, one per tracked query
        """
        init_db()
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT query FROM tracked_queries ORDER BY id"
            ).fetchall()
            queries = [row['query'] for row in rows]
        finally:
            conn.close()

        if not queries:
            logger.info("Orchestrator: no tracked queries found")
            return []

        logger.info("Orchestrator: running %d tracked queries", len(queries))
        reports = []
        for query in queries:
            report = await self.run_query(query)
            reports.append(report)

        return reports

    async def run_batch(self, queries: List[str]) -> List[PriceReport]:
        """Run the full pipeline for a custom list of queries.

        Args:
            queries: List of product search terms

        Returns:
            List of PriceReports
        """
        logger.info("Orchestrator: running batch of %d queries", len(queries))
        reports = []
        for query in queries:
            report = await self.run_query(query)
            reports.append(report)
        return reports

    def _filter_prices(
        self, all_prices: Dict[str, List[ProductPrice]], query: str
    ) -> Dict[str, List[ProductPrice]]:
        """Clean product names and filter bogus/irrelevant results.

        This is a defensive pass — search_all already filters, but
        we run it again in case scrapers returned dirty data.
        """
        filtered = {}
        for store_name, products in all_prices.items():
            clean_products = []
            for p in products:
                # Clean HTML entities
                p.product_name = clean_product_name(p.product_name)
                # Filter bogus prices
                price = p.sale_price or p.regular_price
                if price and is_bogus_price(price, p.product_name):
                    continue
                # Filter irrelevant products
                if not is_relevant_product(p.product_name, query, min_words=2):
                    continue
                clean_products.append(p)
            if clean_products:
                filtered[store_name] = clean_products
        return filtered

    def _log_scraper_health(
        self, run_id: str, query: str, report: PriceReport
    ):
        """Log scraper health metrics to the scraper_health table.

        Records per-run metrics: stores responded, response rate,
        deal count, anomaly count, execution timestamp.
        """
        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO scraper_health
                (run_id, query, stores_checked, stores_responded,
                 response_rate, deal_count, anomaly_count, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                run_id,
                query,
                report.stores_checked,
                report.stores_responded,
                round(report.stores_responded / max(report.stores_checked, 1), 2),
                len(report.deals_found),
                len(report.anomalies),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log scraper health: %s", e)

    def get_price_history(
        self, product_name: str, store_name: str = None, limit: int = 50
    ) -> List[Dict]:
        """Retrieve price history for a product across all runs.

        Args:
            product_name: Product name (or partial match)
            store_name: Optional filter by store
            limit: Max results (most recent first)

        Returns:
            List of dicts: date, store, regular_price, sale_price, is_on_sale
        """
        conn = get_db()
        try:
            if store_name:
                rows = conn.execute(
                    """SELECT ph.recorded_at, ph.store_name, ph.regular_price,
                              ph.sale_price, ph.is_on_sale
                       FROM price_history ph
                       WHERE ph.product_name LIKE ? AND ph.store_name = ?
                       ORDER BY ph.recorded_at DESC LIMIT ?""",
                    (f"%{product_name}%", store_name, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ph.recorded_at, ph.store_name, ph.regular_price,
                              ph.sale_price, ph.is_on_sale
                       FROM price_history ph
                       WHERE ph.product_name LIKE ?
                       ORDER BY ph.recorded_at DESC LIMIT ?""",
                    (f"%{product_name}%", limit)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_deal_scores(
        self, product_name: str = None, limit: int = 20
    ) -> List[Dict]:
        """Retrieve deal scores — best historical deals recorded.

        Args:
            product_name: Optional filter
            limit: Max results (highest score first)

        Returns:
            List of dicts: product, store, score, savings, percent, date
        """
        conn = get_db()
        try:
            if product_name:
                rows = conn.execute(
                    """SELECT * FROM deal_scores
                       WHERE product_name LIKE ?
                       ORDER BY score DESC LIMIT ?""",
                    (f"%{product_name}%", limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM deal_scores
                       ORDER BY score DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_scraper_health_summary(self, days: int = 7) -> List[Dict]:
        """Get scraper health summary for the last N days.

        Args:
            days: Look-back window

        Returns:
            List of dicts: query, avg_response_rate, total_runs, avg_deals
        """
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT query,
                          COUNT(*) as total_runs,
                          ROUND(AVG(response_rate), 2) as avg_response_rate,
                          ROUND(AVG(deal_count), 1) as avg_deals,
                          MAX(timestamp) as last_run
                   FROM scraper_health
                   WHERE timestamp >= datetime('now', ?)
                   GROUP BY query
                   ORDER BY last_run DESC""",
                (f"-{days} days",)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def summary(self) -> Dict:
        """Quick pipeline status summary for monitoring."""
        conn = get_db()
        try:
            # Total runs
            total_runs = conn.execute(
                "SELECT COUNT(DISTINCT run_id) FROM price_results"
            ).fetchone()[0]

            # Total products tracked
            total_tracked = conn.execute(
                "SELECT COUNT(*) FROM tracked_queries"
            ).fetchone()[0]

            # Recent response rate (last 10 runs)
            recent = conn.execute(
                """SELECT AVG(response_rate) as avg_rate
                   FROM scraper_health
                   ORDER BY timestamp DESC LIMIT 10"""
            ).fetchone()
            avg_rate = recent['avg_rate'] if recent and recent['avg_rate'] is not None else 0

            return {
                "total_runs": total_runs,
                "tracked_products": total_tracked,
                "avg_response_rate_10": round(avg_rate, 2),
                "db_path": str(getattr(__import__('src.storage.sqlite_store', fromlist=['DB_PATH']), 'DB_PATH')),
            }
        finally:
            conn.close()