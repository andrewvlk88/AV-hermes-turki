#!/usr/bin/env python3
"""Turkí Price Intelligence - Tracked Products Manager.

Allows adding, removing, listing, and running a suite of tracked products
to detect special deals and price drops across 19 Israeli stores.
"""
import sys
import os
import sqlite3
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.storage.sqlite_store import get_db, init_db
from run import async_main

DEFAULT_PRODUCTS = [
    "בלוגה",
    "רוסקי סטנדרט",
    "ירדן קברנה סוביניון 2022",
    "דלתון אסטייט קברנה",
    "ג'וני ווקר בלאק לייבל ליטר",
    "גלנמורנג'י 12 שנים אורגינל 700 מ\"ל"
]


def init_tracker_db():
    """Ensure tracked_queries table exists and is seeded with defaults."""
    init_db()  # Initialize main DB tables first
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        
        # Check if table is empty
        cursor = conn.execute("SELECT COUNT(*) FROM tracked_queries")
        count = cursor.fetchone()[0]
        if count == 0:
            print("🌱 מאתחל את רשימת המעקב עם מוצרי ברירת המחדל...")
            for q in DEFAULT_PRODUCTS:
                try:
                    conn.execute("INSERT INTO tracked_queries (query) VALUES (?)", (q,))
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            print("✅ מוצרי ברירת המחדל נוספו בהצלחה.")
    finally:
        conn.close()


def list_tracked():
    """List all tracked queries."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, query, created_at FROM tracked_queries ORDER BY id").fetchall()
        if not rows:
            print("ℹ️ רשימת המעקב ריקה. השתמש ב-'add' כדי להוסיף מוצרים.")
            return []
        
        print("\n📋 *רשימת מוצרים במעקב:*")
        print("=" * 40)
        for row in rows:
            print(f"  [{row['id']}] {row['query']}")
        print("=" * 40)
        print("💡 להוספה: python manage_tracker.py add \"שם מוצר\"")
        print("💡 להסרה: python manage_tracker.py remove <מספר>")
        print("💡 להרצה: python manage_tracker.py run\n")
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_tracked(query: str):
    """Add a query to the tracker."""
    query = query.strip()
    if not query:
        print("❌ שם מוצר לא יכול להיות ריק.")
        return False
        
    conn = get_db()
    try:
        conn.execute("INSERT INTO tracked_queries (query) VALUES (?)", (query,))
        conn.commit()
        print(f"✅ המוצר '{query}' נוסף בהצלחה לרשימת המעקב.")
        return True
    except sqlite3.IntegrityError:
        print(f"ℹ️ המוצר '{query}' כבר נמצא ברשימת המעקב.")
        return False
    finally:
        conn.close()


def remove_tracked(query_id_or_name: str):
    """Remove a query from the tracker by ID or name."""
    conn = get_db()
    try:
        if query_id_or_name.isdigit():
            # Remove by ID
            cur = conn.execute("DELETE FROM tracked_queries WHERE id = ?", (int(query_id_or_name),))
        else:
            # Remove by Name
            cur = conn.execute("DELETE FROM tracked_queries WHERE query = ?", (query_id_or_name.strip(),))
            
        conn.commit()
        if cur.rowcount > 0:
            print(f"✅ המוצר הוסר בהצלחה מרשימת המעקב.")
            return True
        else:
            print(f"❌ לא נמצא מוצר מתאים להסרה ברשימת המעקב.")
            return False
    finally:
        conn.close()


async def run_tracker():
    """Retrieve all queries and execute the sequential comparison."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT query FROM tracked_queries ORDER BY id").fetchall()
        queries = [row['query'] for row in rows]
    finally:
        conn.close()
        
    if not queries:
        print("❌ אין מוצרים ברשימת המעקב. לא ניתן להריץ.")
        return
        
    print(f"🚀 מתחיל סריקת מעקב של {len(queries)} מוצרים...")
    await async_main(queries)
    print("\n🎉 סריקת המעקב הושלמה בהצלחה!")


def print_help():
    """Print the CLI help/usage text in Hebrew.

    Lists all available commands (list, add, remove, run, help) with
    example invocations.
    """
    print("""
שימוש: python manage_tracker.py [פקודה] [פרמטרים]

פקודות זמינות:
  list              הצגת כל המוצרים במעקב
  add "[שם המוצר]"   הוספת מוצר חדש לרשימת המעקב
  remove [ID/שם]    הסרת מוצר מרשימת המעקב לפי מספר או שם
  run               הרצת סריקה מלאה על כל המוצרים במעקב
  help              הצגת עזרה זו
""")


def main():
    """CLI entry point for the tracked-products manager.

    Parses sys.argv for a subcommand (list, add, remove, run, help)
    and dispatches to the appropriate handler. Initializes the tracker
    database on every invocation.
    """
    init_tracker_db()
    
    if len(sys.argv) < 2:
        list_tracked()
        print_help()
        sys.path.remove(str(Path(__file__).parent))
        return
        
    cmd = sys.argv[1].lower()
    
    if cmd == "list":
        list_tracked()
    elif cmd == "add":
        if len(sys.argv) < 3:
            print("❌ חסר שם מוצר. דוגמה: python manage_tracker.py add \"וודקה אבסולוט\"")
        else:
            add_tracked(sys.argv[2])
            list_tracked()
    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("❌ חסר מזהה להסרה. דוגמה: python manage_tracker.py remove 3")
        else:
            remove_tracked(sys.argv[2])
            list_tracked()
    elif cmd == "run":
        asyncio.run(run_tracker())
    else:
        print_help()
        
    if str(Path(__file__).parent) in sys.path:
        sys.path.remove(str(Path(__file__).parent))


if __name__ == "__main__":
    main()
