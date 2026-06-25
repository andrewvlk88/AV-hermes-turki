#!/usr/bin/env python3
"""Run Strategist on the latest scan results from all tracked products."""
import asyncio
import json
import sys
import os
import glob
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env
env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")

from src.agents.strategist import StrategistAgent

PRODUCTS = [
    "בלוגה",
    "רוסקי סטנדרט",
    "ירדן קברנה סוביניון 2022",
    "דלתון אסטייט קברנה",
    "ג'וני ווקר בלאק לייבל ליטר",
    "גלנמורנג'י 12 שנים אורגינל 700 מ\"ל",
]

async def main():
    # Load all recent JSON results
    all_deals = []
    all_analyses = []
    
    # Get latest run_id from DB
    db_path = "data/price_intel.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get the latest run_id
    cursor.execute("SELECT MAX(run_id) FROM price_results")
    latest_run = cursor.fetchone()[0]
    print(f"Latest run_id: {latest_run}")
    
    # Get all results from the latest run
    cursor.execute("""
        SELECT product_name, store_name, regular_price, sale_price, is_on_sale, query
        FROM price_results 
        WHERE run_id = ?
        ORDER BY query, product_name
    """, (latest_run,))
    rows = cursor.fetchall()
    
    # Get Turki baseline prices
    cursor.execute("""
        SELECT product_name, regular_price, sale_price
        FROM price_results 
        WHERE run_id = ? AND store_name = 'הטורקי'
    """, (latest_run,))
    turki_prices = {}
    for name, reg, sale in cursor.fetchall():
        turki_prices[name] = float(sale) if sale else float(reg) if reg else None
    
    # Build deals: products cheaper than Turki by 5%+
    from src.utils.filters import clean_product_name, extract_volume_ml, is_relevant_product, is_accessory, is_relevant_volume_by_name
    
    seen = set()
    for prod_name, store_name, reg_price, sale_price, is_sale, query in rows:
        if store_name == 'הטורקי':
            continue
        price = float(sale_price) if sale_price else float(reg_price) if reg_price else None
        if not price or price < 10:
            continue
        
        clean_name = clean_product_name(prod_name)
        if is_accessory(clean_name):
            continue
        if not is_relevant_volume_by_name(clean_name):
            continue
        if not is_relevant_product(clean_name, query or PRODUCTS[0], min_words=1):
            continue
        
        # Find Turki match
        turki_price = None
        for t_name, t_price in turki_prices.items():
            t_clean = clean_product_name(t_name)
            if is_relevant_product(t_clean, clean_name, min_words=1):
                vol1 = extract_volume_ml(clean_name)
                vol2 = extract_volume_ml(t_clean)
                if vol1 and vol2:
                    if abs(vol1 - vol2) > 50:
                        continue
                turki_price = t_price
                break
        
        if turki_price and turki_price > 0:
            savings_pct = ((turki_price - price) / turki_price) * 100
            if savings_pct >= 5.0:
                key = f"{clean_name}|{store_name}"
                if key not in seen:
                    seen.add(key)
                    all_deals.append({
                        "product": clean_name,
                        "store": store_name,
                        "price": price,
                        "turki_price": turki_price,
                        "savings_percent": round(savings_pct, 1),
                        "savings_amount": round(turki_price - price, 1),
                        "type": "turki",
                        "is_sale": bool(is_sale),
                    })
    
    conn.close()
    
    # Sort by savings percent descending
    all_deals.sort(key=lambda x: x["savings_percent"], reverse=True)
    
    print(f"\nFound {len(all_deals)} deals (5%+ savings vs Turki)")
    for d in all_deals[:20]:
        print(f"  💰 {d['product'][:40]} — {d['price']}₪ ב-{d['store']} (טורקי {d['turki_price']}₪, חיסכון {d['savings_percent']}%)")
    
    # Build orchestrator-like result for Strategist
    orchestrator_result = {
        "ok": True,
        "result": {
            "deals": all_deals,
            "deal_count": len(all_deals),
            "analyses": [],
        },
        "summary": f"נמצאו {len(all_deals)} דילים מול הטורקי בריצה האחרונה",
    }
    
    # Run Strategist
    strategist = StrategistAgent()
    recs_result = strategist.generate_recommendations(orchestrator_result, context=None)
    
    print("\n" + "="*60)
    print("STRATEGIST RECOMMENDATIONS")
    print("="*60)
    print(json.dumps(recs_result, ensure_ascii=False, indent=2, default=str))
    
    # Save
    with open("data/strategist_recommendations.json", "w", encoding="utf-8") as f:
        json.dump({
            "deals": all_deals,
            "recommendations": recs_result,
            "run_id": latest_run,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\n📁 Saved to data/strategist_recommendations.json")

asyncio.run(main())