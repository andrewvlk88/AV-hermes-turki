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


DB_PATH = Path(__file__).parent.parent.parent / "data" / "price_intel.db"


def run_id_gen() -> str:
    """Generate a unique run ID."""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def get_db() -> sqlite3.Connection:
    """Get a connection to the price intelligence SQLite DB."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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
            
            conn.execute("""
                INSERT INTO price_results 
                (query, store_name, product_name, regular_price, sale_price, 
                 volume_ml, is_on_sale, product_url, store_url, sku, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query,
                store_name,
                p.get('product_name', '')[:200],
                p.get('regular_price'),
                p.get('sale_price'),
                p.get('volume_ml'),
                int(p.get('is_on_sale', False)),
                p.get('product_url', ''),
                p.get('store_url', ''),
                p.get('sku', ''),
                run_id,
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