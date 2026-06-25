"""SQLite storage for Turkí Price Intelligence results.

Stores per-store results as they come in, so partial results survive
even if later stores fail. Also enables historical price tracking.
"""
import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.utils.filters import is_relevant_volume_by_name


DB_PATH = Path(__file__).parent.parent.parent / "data" / "price_intel.db"


def run_id_gen() -> str:
    """Generate a unique run ID."""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def get_db() -> sqlite3.Connection:
    """Get a connection to the price intelligence SQLite DB."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # wait up to 30s before failing
    return conn


def _with_retry(fn, max_attempts=5, delay=1.0):
    """Retry a DB operation with exponential backoff on OperationalError."""
    import time
    for attempt in range(max_attempts):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
                continue
            raise


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            store_name TEXT NOT NULL,
            product_name TEXT NOT NULL,
            regular_price REAL,
            sale_price REAL,
            volume_ml REAL,
            is_on_sale INTEGER DEFAULT 0,
            product_url TEXT DEFAULT '',
            store_url TEXT DEFAULT '',
            sku TEXT DEFAULT '',
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            run_id TEXT NOT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_price_query ON price_results(query);
        CREATE INDEX IF NOT EXISTS idx_price_store ON price_results(store_name);
        CREATE INDEX IF NOT EXISTS idx_price_run ON price_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_price_product ON price_results(product_name);
        
        CREATE TABLE IF NOT EXISTS store_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            query TEXT NOT NULL,
            store_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            -- pending, running, success, error
            product_count INTEGER DEFAULT 0,
            error_msg TEXT DEFAULT '',
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(run_id, store_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_status_run ON store_status(run_id);
        
        -- ── v2.4: Historical price tracking ──
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            store_name TEXT NOT NULL,
            query TEXT NOT NULL,
            regular_price REAL,
            sale_price REAL,
            volume_ml REAL,
            is_on_sale INTEGER DEFAULT 0,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
            run_id TEXT NOT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_name);
        CREATE INDEX IF NOT EXISTS idx_history_store ON price_history(store_name);
        CREATE INDEX IF NOT EXISTS idx_history_date ON price_history(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_history_query ON price_history(query);
        
        -- ── v2.4: Deal scoring (best deals across all runs) ──
        CREATE TABLE IF NOT EXISTS deal_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            store_name TEXT NOT NULL,
            query TEXT NOT NULL,
            price REAL NOT NULL,
            turki_price REAL,
            savings_amount REAL,
            savings_percent REAL,
            score REAL NOT NULL DEFAULT 0,
            -- score = savings_percent * weight (higher = better deal)
            deal_type TEXT NOT NULL DEFAULT 'turki',
            -- turki, sale, anomaly
            run_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        
        CREATE INDEX IF NOT EXISTS idx_deal_product ON deal_scores(product_name);
        CREATE INDEX IF NOT EXISTS idx_deal_store ON deal_scores(store_name);
        CREATE INDEX IF NOT EXISTS idx_deal_score ON deal_scores(score DESC);
        CREATE INDEX IF NOT EXISTS idx_deal_date ON deal_scores(recorded_at);
        
        -- ── v2.4: Scraper health metrics ──
        CREATE TABLE IF NOT EXISTS scraper_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            query TEXT NOT NULL,
            stores_checked INTEGER DEFAULT 0,
            stores_responded INTEGER DEFAULT 0,
            response_rate REAL DEFAULT 0,
            -- stores_responded / stores_checked
            deal_count INTEGER DEFAULT 0,
            anomaly_count INTEGER DEFAULT 0,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        
        CREATE INDEX IF NOT EXISTS idx_health_run ON scraper_health(run_id);
        CREATE INDEX IF NOT EXISTS idx_health_query ON scraper_health(query);
        CREATE INDEX IF NOT EXISTS idx_health_date ON scraper_health(timestamp);
        
        -- ── v2.4: Tracked queries (if not exists from manage_tracker) ──
        CREATE TABLE IF NOT EXISTS tracked_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def save_store_result(run_id: str, query: str, store_name: str, 
                       products: List[Any]) -> int:
    """Save a store's results to SQLite. Returns number of products saved.
    
    Writes to both price_results (current run) and price_history (permanent log).
    Accepts ProductPrice objects or dicts.
    """
    conn = get_db()
    try:
        # Clear previous results for this run+store (in case of retry)
        conn.execute(
            "DELETE FROM price_results WHERE run_id = ? AND store_name = ?",
            (run_id, store_name)
        )
        
        saved = 0
        for p in products:
            # Convert ProductPrice-like object to dict if needed
            if hasattr(p, 'model_dump'):
                p = p.model_dump()
            
            best_price = p.get('sale_price') or p.get('regular_price')
            if not best_price:
                continue
            
            product_name = p.get('product_name', '')[:200]
            
            # Final guard: never store 200ml/500ml products
            if not is_relevant_volume_by_name(product_name):
                continue
            
            regular_price = p.get('regular_price')
            sale_price = p.get('sale_price')
            volume_ml = p.get('volume_ml')
            is_on_sale = int(p.get('is_on_sale', False))
            
            # Write to price_results (current run data)
            conn.execute("""
                INSERT INTO price_results 
                (query, store_name, product_name, regular_price, sale_price, 
                 volume_ml, is_on_sale, product_url, store_url, sku, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query, store_name, product_name, regular_price, sale_price,
                volume_ml, is_on_sale,
                p.get('product_url', ''), p.get('store_url', ''),
                p.get('sku', ''), run_id,
            ))
            
            # Write to price_history (permanent historical log)
            conn.execute("""
                INSERT INTO price_history
                (product_name, store_name, query, regular_price, sale_price,
                 volume_ml, is_on_sale, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_name, store_name, query, regular_price, sale_price,
                volume_ml, is_on_sale, run_id,
            ))
            
            saved += 1
        
        # Update store status
        conn.execute("""
            INSERT OR REPLACE INTO store_status 
            (run_id, query, store_name, status, product_count, timestamp)
            VALUES (?, ?, ?, 'success', ?, datetime('now'))
        """, (run_id, query, store_name, saved))
        
        conn.commit()
        return saved
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def save_deal_scores(run_id: str, query: str, deals: List[Dict]) -> int:
    """Save deal scores to SQLite. Returns number of deals saved.
    
    Called from build_report() after deal detection.
    Each deal dict should have: type, product, store, price, etc.
    """
    conn = get_db()
    try:
        saved = 0
        for d in deals:
            dtype = d.get("type", "turki")
            product = d.get("product", d.get("product_name", ""))
            store = d.get("store", d.get("store_name", ""))
            price = d.get("price", 0)
            turki_price = d.get("turki_price")
            savings = d.get("savings", d.get("savings_amount"))
            pct = d.get("savings_percent", d.get("discount_percent", 0))
            
            # Score: weight savings_percent heavily, add bonus for turki deals
            if dtype == "turki":
                score = (pct or 0) * 1.5
            elif dtype == "sale":
                score = (pct or 0) * 1.0
            else:
                score = 0.5  # anomaly
            
            conn.execute("""
                INSERT INTO deal_scores
                (product_name, store_name, query, price, turki_price,
                 savings_amount, savings_percent, score, deal_type, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product[:200], store, query, price, turki_price,
                savings, pct, round(score, 2), dtype, run_id,
            ))
            saved += 1
        
        conn.commit()
        return saved
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def save_scraper_health(run_id: str, query: str, stores_checked: int,
                        stores_responded: int, deal_count: int = 0,
                        anomaly_count: int = 0) -> bool:
    """Save scraper health metrics for a single query run.
    
    Called at the end of each query scan.
    """
    conn = get_db()
    try:
        rate = round(stores_responded / max(stores_checked, 1), 2)
        conn.execute("""
            INSERT INTO scraper_health
            (run_id, query, stores_checked, stores_responded,
             response_rate, deal_count, anomaly_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (run_id, query, stores_checked, stores_responded,
              rate, deal_count, anomaly_count))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()


def mark_store_error(run_id: str, query: str, store_name: str, error_msg: str):
    """Mark a store as failed in the status table."""
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO store_status
            (run_id, query, store_name, status, product_count, error_msg, timestamp)
            VALUES (?, ?, ?, 'error', 0, ?, datetime('now'))
        """, (run_id, query, store_name, error_msg[:500]))
        conn.commit()
    finally:
        conn.close()


def mark_store_running(run_id: str, query: str, store_name: str):
    """Mark a store as currently being scraped."""
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO store_status
            (run_id, query, store_name, status, product_count, timestamp)
            VALUES (?, ?, ?, 'running', 0, datetime('now'))
        """, (run_id, query, store_name))
        conn.commit()
    finally:
        conn.close()


def get_run_results(run_id: str) -> Dict[str, List[Dict]]:
    """Get all results for a run, grouped by store."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM price_results WHERE run_id = ? ORDER BY store_name, regular_price",
        (run_id,)
    ).fetchall()
    conn.close()
    
    results = {}
    for row in rows:
        store = row['store_name']
        if store not in results:
            results[store] = []
        results[store].append({
            'product_name': row['product_name'],
            'regular_price': row['regular_price'],
            'sale_price': row['sale_price'],
            'volume_ml': row['volume_ml'],
            'is_on_sale': bool(row['is_on_sale']),
            'product_url': row['product_url'],
            'store_url': row['store_url'],
            'sku': row['sku'],
            'store_name': store,
        })
    return results


def get_run_status(run_id: str) -> List[Dict]:
    """Get status of all stores for a run."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM store_status WHERE run_id = ? ORDER BY timestamp",
        (run_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_recent_store_status(store_name: str, limit: int = 3) -> List[Dict]:
    """Get the most recent N status rows for a single store.

    Used by the Circuit Breaker to detect chronically failing stores:
    if a store has failed (status='error') in ALL of its last N runs,
    it is pre-skipped at the start of search_all() to save time.

    Args:
        store_name: Hebrew store name (matches store_status.store_name).
        limit: Number of most-recent rows to return (default 3).

    Returns:
        List of dicts (newest first) with keys: run_id, query, store_name,
        status, product_count, error_msg, timestamp. Empty list if the
        store has no history yet.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT run_id, query, store_name, status, product_count,
                   error_msg, timestamp
            FROM store_status
            WHERE store_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (store_name, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        # Table may not exist yet on a fresh DB — treat as no history.
        return []
    finally:
        conn.close()


def get_chronic_failure_stores(store_names: List[str], lookback: int = 3) -> set:
    """Return the set of stores that failed in ALL of their last `lookback` runs.

    A store is considered a chronic failure if:
      1. It has at least `lookback` status rows in store_status, AND
      2. Every one of those last `lookback` rows has status='error'.

    Stores with fewer than `lookback` rows are NOT flagged — we need
    enough history to be confident the store is genuinely broken.

    Args:
        store_names: List of store names to check.
        lookback: Minimum number of past runs required to flag a store.

    Returns:
        Set of store names that are chronic failures.
    """
    chronic = set()
    for name in store_names:
        rows = get_recent_store_status(name, limit=lookback)
        if len(rows) >= lookback and all(r.get("status") == "error" for r in rows):
            chronic.add(name)
    return chronic


# ════════════════════════════════════════════════════════════════════
#  Adaptive scraping frequency — price stability analysis
# ════════════════════════════════════════════════════════════════════

def get_query_price_stability(query: str) -> Optional[Dict[str, Any]]:
    """Analyze price stability for a tracked query across its scan history.

    Examines the ``price_history`` table to determine:
    - When the price last changed (best price per run = min of regular/sale)
    - When the last successful scrape occurred (most recent run_id)
    - How many distinct best-price points exist in the last 30 days

    Groups price_history rows by ``run_id`` (one scrape = one run), computes
    the best (minimum) price across all stores for each run, and then detects
    changes between consecutive runs. This avoids false positives from
    multiple stores reporting different prices within the same scrape.

    This powers the adaptive scraping frequency mechanism in the Orchestrator:
    queries whose price hasn't changed in 30+ days are skipped (unless 24h
    have passed since the last scrape), while queries with recent price
    changes are scraped on every run.

    Args:
        query: The tracked query string (e.g., "וודקה בלוגה ליטר").
            Matches against ``price_history.query``.

    Returns:
        Dict with keys:
            - ``query``: the query string
            - ``last_price_change``: ISO timestamp of the most recent price
              change, or ``None`` if no change detected / no history.
            - ``last_scrape_at``: ISO timestamp of the most recent
              price_history row for this query.
            - ``days_since_change``: int days since last price change,
              or ``None`` if no history.
            - ``days_since_scrape``: int days since last scrape,
              or ``None`` if no history.
            - ``distinct_prices_30d``: number of distinct best-price values
              in the last 30 days (1 = completely stable).
            - ``total_history_rows``: total price_history rows for this query.
        Returns ``None`` if the query has no history at all.
    """
    conn = get_db()
    try:
        # Group by run_id — one scrape = one run. For each run, find the
        # best (minimum) price across all stores. This is the "deal price"
        # that actually matters for change detection.
        rows = conn.execute(
            """
            SELECT run_id,
                   MIN(CASE
                       WHEN sale_price IS NOT NULL AND sale_price > 0
                            AND (regular_price IS NULL OR sale_price < regular_price)
                       THEN sale_price
                       WHEN regular_price IS NOT NULL AND regular_price > 0
                       THEN regular_price
                   END) AS best_price,
                   MAX(recorded_at) AS run_timestamp
            FROM price_history
            WHERE query = ?
              AND (regular_price > 0 OR sale_price > 0)
            GROUP BY run_id
            ORDER BY run_timestamp ASC
            """,
            (query,),
        ).fetchall()

        if not rows:
            return None

        # Build a timeline of (best_price, timestamp) per run
        runs = []
        for row in rows:
            if row["best_price"] is not None:
                runs.append((row["best_price"], row["run_timestamp"]))

        if not runs:
            return None

        # Find the last time the best price changed between consecutive runs
        last_change_at = None
        for i in range(1, len(runs)):
            if runs[i][0] != runs[i - 1][0]:
                last_change_at = runs[i][1]

        # If no change was ever detected, the price has been stable since
        # the first recorded scrape
        if last_change_at is None:
            last_change_at = runs[0][1]

        last_scrape_at = runs[-1][1]

        # Count distinct best prices in the last 30 days
        from datetime import datetime as _dt, timedelta as _td
        cutoff_30d = (_dt.now() - _td(days=30)).isoformat()
        distinct_30d = len({
            p for p, ts in runs
            if ts >= cutoff_30d
        })

        # Calculate days since each event
        now = _dt.now()
        def _days_since(ts_str: str) -> Optional[int]:
            try:
                # SQLite timestamps are "YYYY-MM-DD HH:MM:SS" — parse it
                dt = _dt.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                return (now - dt).days
            except (ValueError, TypeError):
                try:
                    dt = _dt.fromisoformat(ts_str[:19])
                    return (now - dt).days
                except (ValueError, TypeError):
                    return None

        # Total raw rows (not just grouped runs)
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE query = ?",
            (query,),
        ).fetchone()[0]

        return {
            "query": query,
            "last_price_change": last_change_at,
            "last_scrape_at": last_scrape_at,
            "days_since_change": _days_since(last_change_at),
            "days_since_scrape": _days_since(last_scrape_at),
            "distinct_prices_30d": distinct_30d,
            "total_history_rows": total_rows,
        }
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(
            "get_query_price_stability failed for %r: %s", query, e
        )
        return None
    finally:
        conn.close()