"""Turkí Price Intelligence - Main CLI entry point."""
import asyncio
import json
import sys
from pathlib import Path
from typing import List
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.searcher import SearcherAgent
from src.agents.extractor import ExtractorAgent
from src.agents.analyzer import AnalyzerAgent
from src.models import PriceReport, ProductPrice


def save_report(report: PriceReport, output_dir: str = "data"):
    """Save report to JSON + text files."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = report.query.replace(" ", "_")[:30]

    # JSON
    json_path = base / f"{safe_name}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"\n📁 JSON saved: {json_path}")

    # Text report
    txt_path = base / f"{safe_name}_{ts}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report.summary)
        if report.deals_found:
            f.write("\n🔥 מבצעים שנמצאו:\n")
            for d in report.deals_found:
                f.write(f"  {d}\n")
        if report.anomalies:
            f.write("\n⚠️ אנומליות:\n")
            for a in report.anomalies:
                f.write(f"  {a}\n")
    print(f"📄 Report saved: {txt_path}")

    return json_path, txt_path


def format_telegram_report(report: PriceReport) -> str:
    """Format a clean Telegram-friendly report."""
    lines = []
    lines.append(f"📊 *טורקי פרייס אינטליג׳נס*")
    lines.append(f"🔎 חיפוש: *{report.query}*")
    lines.append(f"🏪 בדקתי {report.stores_checked} חנויות, {report.stores_responded} ענו")
    lines.append("")

    for r in report.results:
        lines.append(f"🏷️ *{r.product_name}*")
        if r.turki_price:
            lines.append(f"   🦃 הטורקי: *{r.turki_price:.0f}₪*")
        if r.cheapest_store and r.cheapest_price:
            if r.savings_vs_turki and r.savings_vs_turki > 0:
                lines.append(f"   👇 *הזול ביותר: {r.cheapest_price:.0f}₪* ב-{r.cheapest_store}")
                lines.append(f"   💰 חיסכון מול הטורקי: *{r.savings_vs_turki:.0f}₪* ({r.savings_percent:.0f}%)")
            else:
                lines.append(f"   ➡️ הזול ביותר: {r.cheapest_price:.0f}₪ ב-{r.cheapest_store}")
        lines.append("")

    if report.deals_found:
        lines.append("🔥 *מבצעים חמים:*")
        for d in report.deals_found:
            lines.append(f"   {d}")
        lines.append("")

    if report.anomalies:
        lines.append("⚠️ *אנומליות מחיר:*")
        for a in report.anomalies:
            lines.append(f"   {a}")
        lines.append("")

    lines.append(f"⏱️ {report.timestamp}")
    return "\n".join(lines)


async def async_main(queries: List[str], output_dir: str = "data"):
    """Main async flow."""
    if not queries:
        print("❌ No queries provided!")
        return

    searcher = SearcherAgent()
    extractor = ExtractorAgent()
    analyzer = AnalyzerAgent()

    for query in queries:
        print(f"\n{'='*50}")
        print(f"🔎 Searching for: {query}")
        print(f"{'='*50}")

        # Step 1: Search all stores
        html_results = await searcher.search_all(query)

        print(f"\n📥 Got HTML from {len(html_results)} stores")

        # Step 2: Extract prices
        all_prices = {}
        for store_name, result in html_results.items():
            products = extractor.extract_from_html(
                result["html"], result["store"], result["query"]
            )
            all_prices[store_name] = products
            if products:
                best = products[0]
                price = best.sale_price or best.regular_price
                sale_tag = f" (מבצע: {best.sale_price:.0f}₪ במקום {best.regular_price:.0f}₪)" if best.is_on_sale and best.sale_price and best.regular_price else ""
                print(f"  ✅ {store_name}: {price:.0f}₪{sale_tag}")

        # Step 3: Analyze
        print(f"\n📊 Analyzing prices...")
        report = analyzer.analyze(all_prices, query)

        # Step 4: Save
        save_report(report, output_dir)

        # Step 5: Display summary
        print(f"\n{'='*50}")
        print(format_telegram_report(report))
        print(f"{'='*50}")

    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="טורקי פרייס אינטליג׳נס - Price tracker for Israeli alcohol stores"
    )
    parser.add_argument(
        "queries", nargs="+",
        help="Product names to search (e.g., 'ג'ק דניאלס 1 ליטר', 'וודקה אבסולוט')"
    )
    parser.add_argument(
        "--output", "-o", default="data",
        help="Output directory (default: data/)"
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output raw JSON to stdout"
    )

    args = parser.parse_args()
    report = asyncio.run(async_main(args.queries, args.output))

    if args.json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
