"""Analyzer Agent - compares prices, finds deals and anomalies."""
from typing import List, Dict, Optional
from src.models import ProductPrice, ComparisonResult, PriceReport
import json


class AnalyzerAgent:
    """Analyzes extracted prices, compares to turki price, finds deals."""

    def __init__(self):
        self.turki_name = "הטורקי"

    def _find_turki_price(self, all_prices: Dict[str, List[ProductPrice]]) -> Optional[float]:
        """Find the reference price in הטורקי."""
        for name, products in all_prices.items():
            if self.turki_name in name and products:
                return products[0].regular_price or products[0].sale_price
        return None

    def _find_turki_products(self, all_prices: Dict[str, List[ProductPrice]]) -> List[ProductPrice]:
        """Find all products from הטורקי."""
        for name, products in all_prices.items():
            if self.turki_name in name:
                return products
        return []

    def _calculate_savings(self, turki_price: float, other_price: float) -> tuple:
        """Calculate absolute savings and percentage."""
        savings = round(turki_price - other_price, 2)
        if turki_price > 0:
            percent = round((savings / turki_price) * 100, 1)
        else:
            percent = 0
        return savings, percent

    def _detect_anomalies(self, all_prices: Dict[str, List[ProductPrice]]) -> List[str]:
        """Detect price anomalies."""
        anomalies = []

        # Collect all prices
        all_reg_prices = []
        for store_name, products in all_prices.items():
            for p in products:
                if p.regular_price:
                    all_reg_prices.append((store_name, p.product_name, p.regular_price))

        if len(all_reg_prices) < 3:
            return anomalies

        # Calculate stats
        prices_only = [p[2] for p in all_reg_prices]
        avg = sum(prices_only) / len(prices_only)
        std = (sum((x - avg) ** 2 for x in prices_only) / len(prices_only)) ** 0.5

        # Flag prices that are 2+ std deviations away
        for store_name, product_name, price in all_reg_prices:
            if std > 0:
                z_score = abs(price - avg) / std
                if z_score > 2.0:
                    direction = "גבוה משמעותית" if price > avg else "נמוך משמעותית"
                    anomalies.append(
                        f"⚠️ {product_name} ב-{store_name}: {price}₪ — "
                        f"{direction} מהממוצע ({avg:.0f}₪, סטיית תקן {std:.0f}₪)"
                    )

        return anomalies

    def _find_deals(self, all_prices: Dict[str, List[ProductPrice]],
                    turki_price: Optional[float]) -> List[str]:
        """Find good deals and discounts."""
        deals = []

        # Check for sale items
        for store_name, products in all_prices.items():
            for p in products:
                if p.is_on_sale and p.regular_price and p.sale_price:
                    savings = p.regular_price - p.sale_price
                    percent = (savings / p.regular_price) * 100
                    if percent >= 10:
                        deals.append(
                            f"🔥 מבצע! {p.product_name} ב-{store_name}: "
                            f"{p.sale_price:.0f}₪ (במקום {p.regular_price:.0f}₪, "
                            f"חיסכון של {percent:.0f}%)"
                        )

        # Compare with turki
        if turki_price:
            for store_name, products in all_prices.items():
                if self.turki_name in store_name:
                    continue
                for p in products:
                    best_price = p.regular_price or p.sale_price
                    if best_price and turki_price > best_price:
                        savings, percent = self._calculate_savings(turki_price, best_price)
                        if percent >= 5:
                            deals.append(
                                f"💰 זול מהטורקי! {p.product_name} ב-{store_name}: "
                                f"{best_price:.0f}₪ (הטורקי: {turki_price:.0f}₪, "
                                f"חיסכון {percent:.0f}%)"
                            )

        return deals

    def analyze(self, all_prices: Dict[str, List[ProductPrice]], query: str) -> PriceReport:
        """Full analysis of all collected prices."""
        report = PriceReport(query=query)
        report.stores_checked = len(all_prices)
        report.stores_responded = sum(
            1 for products in all_prices.values() if products
        )

        turki_products = self._find_turki_products(all_prices)
        turki_price = self._find_turki_price(all_prices)
        turki_url = turki_products[0].product_url if turki_products else ""

        anomalies = self._detect_anomalies(all_prices)

        # Build per-product comparison
        all_product_names = set()
        for products in all_prices.values():
            for p in products:
                all_product_names.add(p.product_name)

        for product_name in sorted(all_product_names):
            result = ComparisonResult(
                product_name=product_name,
                turki_price=turki_price,
                turki_url=turki_url,
            )

            product_prices = []
            for store_name, products in all_prices.items():
                for p in products:
                    if p.product_name == product_name or product_name in p.product_name:
                        best_price = p.regular_price or p.sale_price
                        if best_price:
                            product_prices.append({
                                "store": store_name,
                                "price": best_price,
                                "url": p.product_url,
                                "is_sale": p.is_on_sale,
                            })

            # Sort by price
            product_prices.sort(key=lambda x: x["price"])

            if product_prices:
                cheapest = product_prices[0]
                result.cheapest_store = cheapest["store"]
                result.cheapest_price = cheapest["price"]
                result.cheapest_url = cheapest["url"]

                if turki_price and cheapest["price"] < turki_price:
                    result.savings_vs_turki = round(turki_price - cheapest["price"], 2)
                    result.savings_percent = round(
                        ((turki_price - cheapest["price"]) / turki_price) * 100, 1
                    )

            result.all_prices = product_prices
            result.deals_found = deals
            result.anomalies = anomalies
            report.results.append(result)

        deals = self._find_deals(all_prices, turki_price)

        # Generate summary
        report.summary = self._generate_summary(report)
        report.deals_found = deals
        report.anomalies = anomalies

        return report

    def _generate_summary(self, report: PriceReport) -> str:
        """Generate a readable summary."""
        lines = []
        lines.append(f"📊 דוח השוואת מחירים: {report.query}")
        lines.append(f"   נבדקו {report.stores_checked} חנויות, {report.stores_responded} הגיבו")
        lines.append("")

        for r in report.results:
            lines.append(f"🏷️ {r.product_name}")
            if r.turki_price:
                lines.append(f"   הטורקי: {r.turki_price:.0f}₪")
            if r.cheapest_store and r.cheapest_price:
                arrow = "👇" if r.savings_vs_turki and r.savings_vs_turki > 0 else "➡️"
                lines.append(f"   {arrow} הזול ביותר: {r.cheapest_price:.0f}₪ ב-{r.cheapest_store}")
                if r.savings_vs_turki and r.savings_vs_turki > 0:
                    lines.append(f"   💰 חיסכון מול הטורקי: {r.savings_vs_turki:.0f}₪ ({r.savings_percent:.0f}%)")
            lines.append("")

        return "\n".join(lines)
