"""Turkí Price Intelligence - Final version with parallel store scraping."""
import asyncio
import json
import sys
from pathlib import Path
from typing import List
from datetime import datetime
import logging

logger = logging.getLogger("turk_pi.run")

sys.path.insert(0, str(Path(__file__).parent))

from src.models import PriceReport, ProductPrice
from src.scrapers.api_scrapers import HaturkiAPIScraper
from src.scrapers.unified_scraper import UnifiedScraper
from src.export.csv_export import bulk_export
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product, extract_volume_ml, is_relevant_volume
from src.utils.llm_deals import llm_validate_deal
from src.scrapers.playwright_scrapers import PlaywrightEngine

from src.models import Store


def progress_callback(name, count, msg):
    """Print a progress line for each store during a scan.

    Args:
        name: Store name (Hebrew).
        count: Number of products found (unused in output, kept for compat).
        msg: Status message or emoji (✅, ❌, ⏱️).
    """
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
    
    STRICT volume matching: if either the product or the turki entry has
    a known volume, they must be within ±50ml. If both are unknown, we
    allow name-only match (rare case where neither store specifies volume).
    
    This prevents false deals like comparing a 200ml bottle (₪25) against
    a 1L bottle (₪65) just because the names normalize the same way.
    """
    if not turki_lookup:
        return None
    
    # Extract the name part (before the volume suffix)
    name_part = name_key.rsplit('_', 1)[0] if '_' in name_key else name_key
    
    # Extract target volume
    target_vol = 0
    try:
        vol_str = name_key.rsplit('_', 1)[1]
        if vol_str != "unknown":
            target_vol = float(vol_str)
    except (ValueError, IndexError):
        pass
    
    # Try exact match first (name + volume)
    if name_key in turki_lookup:
        return turki_lookup[name_key]
    
    # Try all turki entries — STRICT volume check
    for tk, tv in turki_lookup.items():
        tk_name = tk.rsplit('_', 1)[0] if '_' in tk else tk
        if tk_name != name_part:
            continue
        
        # Parse turki volume
        tk_vol = 0
        try:
            tk_vol_str = tk.rsplit('_', 1)[1]
            if tk_vol_str != "unknown":
                tk_vol = float(tk_vol_str)
        except (ValueError, IndexError):
            pass
        
        # Volume matching rules:
        # - Both known: must be within ±50ml
        # - One known, one unknown: REJECT (can't compare 200ml vs unknown)
        # - Both unknown: allow (rare, but neither specifies volume)
        
        if target_vol > 0 and tk_vol > 0:
            # Both have volume — check proximity
            if abs(tk_vol - target_vol) < 50:
                return tv
        elif target_vol == 0 and tk_vol == 0:
            # Both unknown — allow name-only match
            return tv
        # else: one known, one unknown — REJECT (skip this turki entry)
    
    # Prefix matching with strict volume check (for slightly different name spellings)
    if len(name_part) >= 10 and target_vol > 0:
        for tk, tv in turki_lookup.items():
            tk_name = tk.rsplit('_', 1)[0] if '_' in tk else tk
            tk_vol = 0
            try:
                tk_vol_str = tk.rsplit('_', 1)[1]
                if tk_vol_str != "unknown":
                    tk_vol = float(tk_vol_str)
            except (ValueError, IndexError):
                pass
            
            # Only match if volumes are compatible
            # - Both known: must be within ±50ml
            # - Turki unknown (tk_vol==0): allow if names match (Turki often omits volume)
            # - Product unknown (target_vol==0): reject (can't verify)
            if tk_vol == 0:
                pass  # Turki didn't specify volume — allow name-based match
            elif abs(tk_vol - target_vol) >= 50:
                continue
            
            # Product name words must be a subset of turki name words
            # Strip volume/size tokens — they're already matched via volume check above
            _VOLUME_TOKENS = {"מ\"ל", "ml", "ליטר", "liter", "ל", "750", "700", "1000",
                              "500", "200", "50", "100", "175", "350", "375", "1l", "1L"}
            product_words = set(name_part.split()) - _VOLUME_TOKENS
            turki_words = set(tk_name.split()) - _VOLUME_TOKENS
            if product_words.issubset(turki_words):
                return tv
    
    return None


def filter_products_with_turki_match(all_prices: dict, query: str) -> dict:
    """Drop products from other stores if they have no matching Turki baseline.

    A match means same normalized product name and same/similar volume.
    Products that don't appear at הטורקי can't be compared, so we drop them
    from the report and DB.
    """
    turki_products = all_prices.get("הטורקי", [])
    if not turki_products:
        # No Turki baseline at all — keep everything for inspection
        return all_prices

    # Build Turki lookup exactly like build_report does
    turki_lookup = {}
    for p in turki_products:
        best = p.sale_price or p.regular_price
        if not best:
            continue
        norm_name = normalize_for_matching(p.product_name)
        vol_key = get_volume_key(p.product_name)
        if vol_key is not None:
            full_key = f"{norm_name}_{vol_key:.0f}"
            if full_key not in turki_lookup:
                turki_lookup[full_key] = {"price": best, "url": p.product_url, "name": p.product_name}
        else:
            if norm_name not in turki_lookup:
                turki_lookup[norm_name] = {"price": best, "url": p.product_url, "name": p.product_name}

    filtered = {"הטורקי": turki_products}
    for store_name, products in all_prices.items():
        if store_name == "הטורקי":
            continue
        keep = []
        for p in products:
            norm_name = normalize_for_matching(p.product_name)
            vol = get_volume_key(p.product_name)
            key = f"{norm_name}_{vol:.0f}" if vol is not None else norm_name
            if find_turki_match(key, turki_lookup):
                keep.append(p)
        if keep:
            filtered[store_name] = keep
    return filtered


async def search_all(query: str, run_id: str = None) -> dict:
    """Search ALL stores — Haturki API first, then rest sequentially."""
    from src.storage.sqlite_store import init_db, save_store_result, run_id_gen
    
    init_db()
    run_id = run_id or run_id_gen()
    
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
    
    # 3. Drop products without a Turki baseline — no comparison possible
    all_prices = filter_products_with_turki_match(all_prices, query)
    
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
            # Filter 200ml and 500ml bottles — not relevant for Turki comparison
            if not is_relevant_volume(p.volume_ml):
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
                # LLM reasoning validation — only for candidate Turki deals
                is_valid, reason = llm_validate_deal(display_name, cheapest["price"], turki_match["price"], query)
                if not is_valid:
                    lines.append(f"   ⚠️ נפסל ע" + "י LLM: " + reason)
                else:
                    lines.append(f"   💰 חיסכון: {savings:.0f}₪ ({pct:.0f}%)")
                    url_part = f" | [קישור לחנות]({cheapest['url']})" if cheapest.get("url") else ""
                    deals.append(
                        f"💰 {display_name} — {cheapest['price']:.0f}₪ ב-{cheapest['store']}{url_part} "
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
    """Format a PriceReport as a Markdown string suitable for Telegram delivery.

    Produces a concise, emoji-rich summary with the query, store response
    count, full comparison table, and a list of deals (capped at 10).

    Args:
        report: The PriceReport to format.

    Returns:
        A Markdown-formatted string ready to send via Telegram.
    """
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
    from src.storage.sqlite_store import run_id_gen
    shared_run_id = run_id_gen()
    last_report = None
    try:
        for query in queries:
            _print(f"\n{'='*50}")
            _print(f"🔎 *{query}*")
            _print(f"{'='*50}")
            
            # Search all stores with the shared run ID
            all_prices = await search_all(query, run_id=shared_run_id)
            
            # Build report
            _print(f"\n📊 בונים דוח...")
            report = build_report(all_prices, query)
            last_report = report
            
            # Save deal scores to DB
            if report.deals_found:
                try:
                    from src.storage.sqlite_store import save_deal_scores
                    # Convert string deals to structured dicts for DB
                    structured_deals = []
                    for d_str in report.deals_found:
                        if d_str.startswith("💰"):
                            structured_deals.append({
                                "type": "turki", "product": d_str,
                                "store": "", "price": 0,
                                "savings_percent": 0,
                            })
                        elif d_str.startswith("🔥"):
                            structured_deals.append({
                                "type": "sale", "product": d_str,
                                "store": "", "price": 0,
                                "discount_percent": 0,
                            })
                    if structured_deals:
                        save_deal_scores(shared_run_id, query, structured_deals)
                except Exception:
                    pass
            
            # Save scraper health
            try:
                from src.storage.sqlite_store import save_scraper_health
                save_scraper_health(
                    shared_run_id, query,
                    stores_checked=report.stores_checked,
                    stores_responded=report.stores_responded,
                    deal_count=len(report.deals_found),
                    anomaly_count=len(report.anomalies),
                )
            except Exception:
                pass
            
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
        # In Fast Mode, no browser was launched, so skip cleanup entirely
        from src.scrapers.unified_scraper import FAST_MODE
        if not FAST_MODE:
            try:
                await asyncio.wait_for(PlaywrightEngine.close(), timeout=30)
            except Exception:
                logger.exception("Failed to close PlaywrightEngine cleanly")
        else:
            logger.info("Fast Mode: skipping PlaywrightEngine cleanup (no browser was launched)")
    
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
    """CLI entry point for Turkí Price Intelligence.

    Parses command-line arguments, configures silent/JSON output modes,
    and runs ``async_main`` for all provided queries. Supports
    ``--agent-mode`` (implies --json --silent) for AI agent consumption.
    ``--fast`` enables Fast Mode (no browser scraping).
    """
    parser = argparse.ArgumentParser(description="טורקי פרייס אינטליג׳נס")
    parser.add_argument("queries", nargs="+", help='מוצרים: "ג\'ק דניאלס" "וודקה אבסולוט"')
    parser.add_argument("--output", "-o", default="data")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout (implies --silent)")
    parser.add_argument("--silent", action="store_true", help="Suppress progress output to stdout")
    parser.add_argument("--agent-mode", action="store_true", help="Alias for --json --silent (for Agent consumption)")
    parser.add_argument("--fast", action="store_true", help="Fast Mode: disable all browser scraping (Playwright/CloakBrowser). Only API, curl_cffi, and LLM methods are used.")
    
    args = parser.parse_args()
    
    if args.agent_mode:
        args.json = True
        args.silent = True
    if args.json:
        args.silent = True
    
    global SILENT
    SILENT = args.silent
    
    # ── Fast Mode activation ──────────────────────────────────────────
    # CLI flag takes precedence; also checks env var FAST_MODE=true
    if args.fast:
        import src.scrapers.unified_scraper as _us
        _us.FAST_MODE = True
        if not SILENT:
            print("🚀 Fast Mode is ACTIVE — Browser scraping is disabled. "
                  "Only API, curl_cffi, and LLM methods will be used.")
    
    report = asyncio.run(async_main(args.queries, args.output))
    
    if args.json:
        import json
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
