"""Turkí Price Intelligence - Final version with parallel store scraping."""
import asyncio
import json
import sys
from pathlib import Path
from typing import List
from datetime import datetime
import logging

sys.path.insert(0, str(Path(__file__).parent))

from src.models import PriceReport, ProductPrice
from src.scrapers.api_scrapers import HaturkiAPIScraper
from src.scrapers.unified_scraper import UnifiedScraper
from src.export.csv_export import bulk_export
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product, extract_volume_ml
from src.scrapers.playwright_scrapers import PlaywrightEngine

from src.models import Store


def progress_callback(name, count, msg):
    """Print a progress line for each store."""
    _print(f"   {name}: {msg}")


def normalize_for_matching(name: str) -> str:
    """Normalize a product name for matching/grouping.
    
    Strips volume info, brand suffixes, and normalizes Hebrew quotes
    so that similar products from different stores match together.
    Keeps the variant/type (דבש, פייר, בונדד) for accurate matching.
    """
    import re
    # Decode any remaining HTML entities
    name = clean_product_name(name)
    
    # Standardize common variations/typos/abbreviations in Israeli alcohol names
    name = name.lower()
    name = name.replace('סובניון', 'סוביניון')
    name = name.replace('סביניון', 'סוביניון')
    
    # Red Wine variations: Cabernet Sauvignon (ק.ס / ק"ס / קס -> קברנה סוביניון)
    name = re.sub(r'\bק\s*ס\b|\bקס\b|\bקברנה\s+סוביניון\b', ' קברנה סוביניון ', name)
    # Cabernet Franc (ק.פ / ק"פ / קפ -> קברנה פרנק)
    name = re.sub(r'\bק\s*פ\b|\bקפ\b|\bקברנה\s+פרנק\b', ' קברנה פרנק ', name)
    # Sauvignon Blanc (ס.ב / ס"ב / סב -> סוביניון בלאן)
    name = re.sub(r'\bס\s*ב\b|\bסב\b|\bסוביניון\s+בלאן\b', ' סוביניון בלאן ', name)
    # Gewurztraminer (גוורץ / גווירץ / גוורצטרמינר -> גוורצטרמינר)
    name = re.sub(r'\bגוו?ירצ?טרמינר\b|\bגוו?ירץ\b', ' גוורצטרמינר ', name)
    
    # Strip common prefixes
    prefixes_to_strip = [
        r'^יין\s+', r'^בקבוק\s+של\s+', r'^בקבוק\s+', r'^מארז\s+', 
        r'^ויסקי\s+', r'^וויסקי\s+', r'^וודקה\s+', r'^בירה\s+'
    ]
    for pref in prefixes_to_strip:
        name = re.sub(pref, '', name)
        
    # Remove volume suffixes like "700 מ"ל", "1 ליטר", "1.75 ליטר", "(700ml)" 
    name = re.sub(r'\s*\(?\d+[\.\d]*\s*(?:מ["\']ל|ml|ליטר|ל|L)\)?', '', name, flags=re.IGNORECASE)
    # Remove parenthetical notes (e.g., "(Jack Daniels Honey)")
    name = re.sub(r'\([^)]*\)', '', name)
    # Normalize Hebrew quotes and geresh
    name = name.replace("'", "").replace('"', '').replace('׳', '').replace('״', '').replace('.', ' ')
    
    # Remove "טנסי" anywhere (just adds noise to matching, all JD is Tennessee)
    name = name.replace('טנסי', '')
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def get_volume_key(name: str) -> float | None:
    """Get volume in ml for grouping. Returns None if volume cannot be determined.
    
    Mini products (with "מיני" in name) default to 50ml.
    When volume is unknown, returns None so downstream matching falls back
    to name-only comparison instead of assuming 700ml incorrectly.
    """
    vol = extract_volume_ml(name)
    if vol is not None:
        return vol
    name_lower = name.lower()
    if "מיני" in name_lower or "mini" in name_lower:
        return 50.0
    # Don't assume a default volume — return None so caller can handle unknown volume
    return None


def find_turki_match(name_key: str, turki_lookup: dict) -> dict:
    """Find the best matching turki product for a given normalized key.
    
    Requires exact match on normalized name (without volume).
    Falls back to prefix match only if both share the same volume category
    and the prefix is at least 10 chars.
    """
    if not turki_lookup:
        return None
    
    # Extract the name part (before the volume suffix)
    name_part = name_key.rsplit('_', 1)[0] if '_' in name_key else name_key
    
    # Try exact match first (name + volume)
    if name_key in turki_lookup:
        return turki_lookup[name_key]
    
    # Try name-only match (for products without volume info)
    if name_part in turki_lookup:
        return turki_lookup[name_part]
    
    # Extract target volume for matching
    target_vol = 0
    try:
        vol_str = name_key.rsplit('_', 1)[1]
        if vol_str != "unknown":
            target_vol = float(vol_str)
    except (ValueError, IndexError):
        pass
    
    # Try matching by name only — but ONLY if volumes are similar (±50ml)
    # This handles cases like "product 700ml" matching "product (700ml)"
    for tk, tv in turki_lookup.items():
        tk_name = tk.rsplit('_', 1)[0] if '_' in tk else tk
        if tk_name == name_part:
            # Check volume proximity
            try:
                tk_vol = float(tk.rsplit('_', 1)[1])
                if abs(tk_vol - target_vol) < 50:
                    return tv
            except (ValueError, IndexError):
                # If we can't parse volume from turki key, skip this fallback
                continue
    
    # No exact match — only match by prefix if volumes are in same ballpark
    # (±50ml) and the turki name words are a subset of the product name words
    # (i.e., product "ג׳ דניאלס מאסטר" should NOT match turki "ג׳ דניאלס" 
    #  because the turki has FEWER words — it's a different product)
    # We only allow match if the QUERY product has FEWER or EQUAL words to the turki
    # i.e., turki "ג׳ דניאלס דבש" can match product "ג׳ דניאלס דבש" but not "ג׳ דניאלס מאסטר"
    if len(name_part) >= 10 and target_vol > 0:
        for tk, tv in turki_lookup.items():
            tk_name = tk.rsplit('_', 1)[0] if '_' in tk else tk
            tk_vol = 0
            try:
                tk_vol = float(tk.rsplit('_', 1)[1])
            except (ValueError, IndexError):
                pass
            
            # Only match if volumes are similar
            if abs(tk_vol - target_vol) >= 50:
                continue
            
            # Product name words must be a subset of turki name words
            # (product can be missing words from turki, but not have extra words)
            product_words = set(name_part.split())
            turki_words = set(tk_name.split())
            if product_words.issubset(turki_words):
                return tv
    
    return None


async def search_all(query: str) -> dict:
    """Search ALL stores — Haturki API first, then rest sequentially."""
    from src.storage.sqlite_store import init_db, save_store_result, run_id_gen
    
    init_db()
    run_id = run_id_gen()
    
    # 1. Haturki API (fastest)
    _print(f"\n🦃 הטורקי (API)...")
    haturki_store = Store(name="הטורקי", url="https://haturki.com", search_path="", type="static")
    haturki = HaturkiAPIScraper(haturki_store)
    haturki_products = await haturki.search(query)
    if haturki_products:
        for p in haturki_products[:5]:
            price = p.sale_price or p.regular_price
            vol = f" ({p.volume_ml:.0f}ml)" if p.volume_ml else ""
            _print(f"   ✅ {p.product_name}{vol}: {price:.0f}₪")
        # Save Haturki results to SQLite too
        save_store_result(run_id, query, "הטורקי", haturki_products)
    else:
        _print(f"   ❌ לא נמצא")
    
    all_prices = {"הטורקי": haturki_products}
    
    # 2. All other stores SEQUENTIALLY (CloakBrowser needs full Chromium per store)
    _print(f"\n🏪 שאר החנויות (אחת אחרי שנייה)...")
    other_prices = await UnifiedScraper.search_all(query, progress_callback, run_id=run_id)
    all_prices.update(other_prices)
    
    return all_prices


def build_report(all_prices: dict, query: str) -> PriceReport:
    """Build comparison report with proper filtering and matching."""
    report = PriceReport(query=query)
    
    # First pass: clean product names and filter bogus prices across ALL stores
    filtered_prices = {}
    for store_name, products in all_prices.items():
        clean_products = []
        for p in products:
            # Clean HTML entities in product name
            p.product_name = clean_product_name(p.product_name)
            # Filter bogus prices (e.g., 10₪ for full bottles)
            price = p.sale_price or p.regular_price
            if price and is_bogus_price(price, p.product_name):
                continue
            # Filter irrelevant products (noise like wines when searching whiskey)
            if not is_relevant_product(p.product_name, query, min_words=2):
                continue
            clean_products.append(p)
        if clean_products:
            filtered_prices[store_name] = clean_products
    
    report.stores_checked = len(all_prices)
    report.stores_responded = sum(1 for p in filtered_prices.values() if p)
    
    # Build turki reference lookup — key by normalized product name + volume
    turki_products = filtered_prices.get("הטורקי", [])
    turki_lookup = {}
    for p in turki_products:
        best = p.sale_price or p.regular_price
        if best:
            norm_name = normalize_for_matching(p.product_name)
            vol_key = get_volume_key(p.product_name)
            if vol_key is not None:
                full_key = f"{norm_name}_{vol_key:.0f}"
                if full_key not in turki_lookup:
                    turki_lookup[full_key] = {"price": best, "url": p.product_url, "name": p.product_name}
            else:
                # No volume info — match by name only
                if norm_name not in turki_lookup:
                    turki_lookup[norm_name] = {"price": best, "url": p.product_url, "name": p.product_name}
    
    # Group by product — use normalized name + volume as key
    all_entries = {}
    for store_name, products in filtered_prices.items():
        for p in products:
            price = p.sale_price or p.regular_price
            if not price:
                continue
            norm_name = normalize_for_matching(p.product_name)
            vol = get_volume_key(p.product_name)
            if vol is not None:
                key = f"{norm_name}_{vol:.0f}"
            else:
                key = f"{norm_name}_unknown"
            if key not in all_entries:
                all_entries[key] = {"display_name": p.product_name, "entries": []}
            all_entries[key]["entries"].append({
                "store": store_name,
                "price": price,
                "url": p.product_url,
                "is_sale": p.is_on_sale,
                "volume_ml": p.volume_ml or vol,
            })
    
    deals = []
    lines = [f"📊 דוח השוואת מחירים: {query}"]
    lines.append(f"   נבדקו {report.stores_checked} חנויות, {report.stores_responded} מצאו תוצאות")
    lines.append("")
    
    comparison_results = []
    
    for name_key, data in sorted(all_entries.items()):
        entries = data["entries"]
        display_name = data["display_name"]
        sorted_entries = sorted(entries, key=lambda x: x["price"])
        cheapest = sorted_entries[0]
        
        # Match to turki — find turki product with same normalized name AND similar volume
        turki_match = find_turki_match(name_key, turki_lookup)
        
        lines.append(f"🏷️ {display_name}")
        price_list = [f'{e["store"]}: {e["price"]:.0f}₪' for e in sorted_entries]
        lines.append(f"   {', '.join(price_list)}")
        
        if turki_match:
            lines.append(f"   🦃 הטורקי: {turki_match['price']:.0f}₪")
        
        lines.append(f"   👇 זול: {cheapest['price']:.0f}₪ ב-{cheapest['store']}")
        
        if turki_match and cheapest["price"] < turki_match["price"]:
            savings = turki_match["price"] - cheapest["price"]
            pct = (savings / turki_match["price"]) * 100
            if pct >= 5:  # Only show meaningful savings (5%+)
                lines.append(f"   💰 חיסכון: {savings:.0f}₪ ({pct:.0f}%)")
            deals.append(
                f"💰 {display_name} — {cheapest['price']:.0f}₪ ב-{cheapest['store']} "
                f"(הטורקי {turki_match['price']:.0f}₪, חיסכון {pct:.0f}%)"
            )
        
        for e in entries:
            if e["is_sale"]:
                deals.append(f"🔥 מבצע! {display_name} ב-{e['store']}: {e['price']:.0f}₪")
        
        lines.append("")
        
        # Build ComparisonResult for CSV export
        from src.models import ComparisonResult
        cr = ComparisonResult(
            product_name=display_name,
            turki_price=turki_match["price"] if turki_match else None,
            turki_url=turki_match["url"] if turki_match else "",
            cheapest_store=cheapest["store"],
            cheapest_price=cheapest["price"],
            cheapest_url=cheapest.get("url", ""),
            savings_vs_turki=(turki_match["price"] - cheapest["price"]) if turki_match and cheapest["price"] < turki_match["price"] else None,
            savings_percent=round(((turki_match["price"] - cheapest["price"]) / turki_match["price"]) * 100, 1) if turki_match and cheapest["price"] < turki_match["price"] else None,
            all_prices=[{
                "store": e["store"],
                "price": e["price"],
                "url": e.get("url", ""),
                "is_sale": e.get("is_sale", False),
                "volume_ml": e.get("volume_ml", ""),
            } for e in entries],
        )
        comparison_results.append(cr)
    
    report.results = comparison_results
    report.deals_found = deals
    report.summary = "\n".join(lines)
    return report


def format_telegram(report: PriceReport) -> str:
    lines = ["📊 *טורקי פרייס אינטליג׳נס*"]
    lines.append(f"🔎 *{report.query}*")
    lines.append("")
    
    # Summary
    lines.append(f"*{report.stores_responded}/{report.stores_checked}* חנויות הגיבו")
    lines.append("")
    lines.append(report.summary)
    
    if report.deals_found:
        lines.append("🔥 *מבצעים וחיסכון:*")
        for d in report.deals_found[:10]:
            lines.append(f"   {d}")
        lines.append("")
    
    lines.append(f"⏱️ {report.timestamp[:16]}")
    return "\n".join(lines)


async def async_main(queries: List[str], output_dir: str = "data"):
    """Run search for all queries. Returns the last PriceReport for --json output."""
    last_report = None
    try:
        for query in queries:
            _print(f"\n{'='*50}")
            _print(f"🔎 *{query}*")
            _print(f"{'='*50}")
            
            # Search all stores
            all_prices = await search_all(query)
            
            # Build report
            _print(f"\n📊 בונים דוח...")
            report = build_report(all_prices, query)
            last_report = report
            
            # Save
            base = Path(output_dir)
            base.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = query.replace(" ", "_")[:30]
            
            # JSON
            json_path = base / f"{safe}_{ts}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
            
            # TXT summary
            txt_path = base / f"{safe}_{ts}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(report.summary)
                if report.deals_found:
                    f.write("\n🔥 מבצעים:\n")
                    for d in report.deals_found:
                        f.write(f"  {d}\n")
            
            _print(f"📁 JSON: {json_path}")
            _print(f"📄 דוח: {txt_path}")
            
            # CSV export
            all_products = []
            for products in all_prices.values():
                all_products.extend(products)
            
            if all_products:
                csv_paths = bulk_export(all_prices, report, output_dir, query=query)
            
            # Telegram format
            _print(f"\n{format_telegram(report)}")
    finally:
        # Always close Playwright browser to prevent zombie Chromium processes
        await PlaywrightEngine.close()
    
    return last_report


import argparse
import sys

SILENT = False

def _print(*args, **kwargs):
    """Print that respects --silent mode (redirects to stderr when silent)."""
    if SILENT:
        print(*args, file=sys.stderr, **kwargs)
    else:
        print(*args, **kwargs)

def main():
    parser = argparse.ArgumentParser(description="טורקי פרייס אינטליג׳נס")
    parser.add_argument("queries", nargs="+", help='מוצרים: "ג\'ק דניאלס" "וודקה אבסולוט"')
    parser.add_argument("--output", "-o", default="data")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout (implies --silent)")
    parser.add_argument("--silent", action="store_true", help="Suppress progress output to stdout")
    parser.add_argument("--agent-mode", action="store_true", help="Alias for --json --silent (for Agent consumption)")
    
    args = parser.parse_args()
    
    if args.agent_mode:
        args.json = True
        args.silent = True
    if args.json:
        args.silent = True
    
    global SILENT
    SILENT = args.silent
    
    report = asyncio.run(async_main(args.queries, args.output))
    
    if args.json:
        import json
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
