"""CSV export for Turkí Price Intelligence — price tracking over time.

Design goals:
- One CSV per product (e.g., price_tracking_בלוגה.csv)
- Each run APPENDS rows to the same file — not a new file each time
- Each row has timestamp (date + time + weekday) for historical tracking
- First run creates file with headers; subsequent runs just append rows
- Excel-compatible: utf-8-sig encoding, Hebrew headers
"""
import csv
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from src.models import ProductPrice, PriceReport


def _safe_filename(query: str) -> str:
    """Make a query safe for use as a filename (no special chars)."""
    # Replace problematic chars but keep Hebrew letters together
    safe = query.replace('"', "").replace("'", "")  # remove quotes
    safe = safe.replace("/", "_").replace("\\", "_")
    # Collapse whitespace to single underscore, trim
    safe = "_".join(safe.split())[:40]
    # If empty after cleanup, use fallback
    return safe or "product"


def export_tracking_csv(
    all_prices: dict,
    report: PriceReport,
    output_dir: str = "data",
    query: str = ""
) -> str:
    """
    Export a price-tracking CSV — APPENDS to existing file per product.
    
    Filename pattern: price_tracking_בלוגה.csv (no timestamp in filename!)
    Each row has: תאריך, שעה, יום בשבוע, ... for time-series tracking.
    
    First run creates file + headers. Subsequent runs just append rows.
    """
    safe = _safe_filename(query or report.query)
    output_path = f"{output_dir}/price_tracking_{safe}.csv"
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Check if file exists and has content (to decide header vs append)
    file_exists = Path(output_path).exists() and Path(output_path).stat().st_size > 0
    
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    weekday = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"][now.weekday()]
    search_query = query or report.query
    
    # Header columns
    headers = [
        "תאריך",            # date
        "שעה",             # time
        "יום בשבוע",        # weekday
        "מוצר חיפוש",       # search query
        "שם מוצר",         # product name
        "חנות",            # store
        "מחיר (₪)",        # price
        "מחיר הטורקי (₪)",  # turki price
        "הפרש מול הטורקי (₪)",  # diff vs turki
        "חיסכון (%)",       # savings %
        "נפח (מ\"ל)",       # volume ml
        "במבצע",           # on sale
        "קישור",           # product url
    ]
    
    mode = "a" if file_exists else "w"  # append if exists, write if new
    
    with open(output_path, mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        # Only write headers if file is new
        if not file_exists:
            writer.writerow(headers)
        
        # Write rows from report.results (already grouped and matched)
        for r in report.results:
            for entry in r.all_prices:
                price = entry["price"]
                turki_price = r.turki_price or None
                diff = round(turki_price - price, 2) if turki_price is not None and price < turki_price else None
                savings_pct = round((diff / turki_price) * 100, 1) if isinstance(diff, (int, float)) and diff > 0 else None
                
                vol = entry.get("volume_ml")
                vol_val = round(vol) if vol is not None else None
                
                writer.writerow([
                    date_str,
                    time_str,
                    weekday,
                    search_query,
                    r.product_name,
                    entry["store"],
                    round(price),
                    round(turki_price) if turki_price is not None else None,
                    diff,
                    savings_pct,
                    vol_val,
                    "✅" if entry.get("is_sale") else None,
                    entry.get("url", "") or None,
                ])
    
    action = "עודכן" if file_exists else "נוצר"
    print(f"  📄 CSV מעקב: {output_path} ({action})")
    return output_path


def export_products_csv(products: List[ProductPrice], output_path: str = None) -> str:
    """
    Export raw product prices to a CSV file (all stores, raw dump).
    """
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data/turk_products_{ts}.csv"
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        writer.writerow([
            "שם מוצר",
            "חנות",
            "מחיר רגיל (₪)",
            "מחיר מבצע (₪)",
            "במבצע?",
            "נפח (מ\"ל)",
            "יחידה",
            "מק\"ט (SKU)",
            "קטגוריה",
            "קישור למוצר",
            "תאריך עדכון",
        ])
        
        for p in products:
            writer.writerow([
                p.product_name,
                p.store_name,
                round(p.regular_price, 2) if p.regular_price is not None else None,
                round(p.sale_price, 2) if p.sale_price is not None else None,
                "✅ כן" if p.is_on_sale else None,
                round(p.volume_ml) if p.volume_ml is not None else None,
                p.unit,
                p.sku or None,
                p.category or None,
                p.product_url or None,
                p.timestamp[:16],
            ])
    
    print(f"  📄 CSV saved: {output_path}")
    return output_path


def bulk_export(
    all_prices: dict,
    report: PriceReport = None,
    output_dir: str = "data",
    query: str = ""
) -> dict:
    """Export everything: tracking CSV (append) + products CSV."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    paths = {}
    
    # Flatten all products
    all_products = []
    for products in all_prices.values():
        all_products.extend(products)
    
    # 1. Price tracking CSV (PRIMARY — appends to per-product file)
    if report:
        paths["tracking_csv"] = export_tracking_csv(
            all_prices, report,
            output_dir=output_dir,
            query=query
        )
    
    # 2. Products CSV (raw dump, timestamped — for one-off snapshots)
    if all_products:
        safe = _safe_filename(query or (report.query if report else "products"))
        paths["products_csv"] = export_products_csv(
            all_products,
            f"{output_dir}/turk_products_{safe}_{ts}.csv"
        )
    
    return paths