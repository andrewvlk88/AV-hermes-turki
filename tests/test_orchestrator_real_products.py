"""Test suite for OrchestratorAgent with real tracked products.

Tests LLM planning, cache behavior, conditional logic, Hebrew NL
understanding, and metrics — using the 6 tracked products from Shmulik.

Run:
    cd ~/turk-price-intelligence
    PYTHONPATH=. ./venv/bin/python3 tests/test_orchestrator_real_products.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.orchestrator import OrchestratorAgent, Constraints

# ── Tracked products (Shmulik's list) ─────────────────────────────
PRODUCTS = [
    "בלוגה",
    "רוסקי סטנדרט",
    "ירדן קברנה סוביניון 2022",
    "דלתון אסטייט קברנה",
    "ג'וני ווקר בלאק לייבל ליטר",
    "גלנמורנג'י 12 שנים אורגינל 700 מ\"ל",
]


def _print_section(title: str) -> None:
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}")


def _print_plan(plan_dict: dict, metrics: dict) -> None:
    print(f"  Intent:          {plan_dict['intent']}")
    print(f"  check_health:    {plan_dict['check_health']}")
    print(f"  run_scan:        {plan_dict['run_scan']}")
    print(f"  scan_tool:       {plan_dict['scan_tool']}")
    print(f"  fetch_deals:     {plan_dict['fetch_deals']}")
    print(f"  analyze_products:{plan_dict['analyze_products']}")
    print(f"  Rationale:")
    for r in plan_dict.get("rationale", []):
        print(f"    • {r}")
    print(f"  Metrics:")
    print(f"    LLM calls: {metrics['llm_planning_calls']} | "
          f"Cache hits: {metrics['cache_hits']} | "
          f"Cache misses: {metrics['cache_misses']} | "
          f"Avg time: {metrics['avg_planning_time_s']}s | "
          f"Cache size: {metrics['cache_size']}")


async def run_tests() -> None:
    orch = OrchestratorAgent()

    # Clear cache for clean test run
    OrchestratorAgent.clear_plan_cache()
    print("Cache cleared. Starting tests.\n")

    results_summary = []

    # ═════════════════════════════════════════════════════════════
    # Test 1: Simple health check
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 1: Simple health check")
    goal1 = "check scraper health"
    c1 = Constraints(health_days=7)
    r1 = await orch.execute(goal1, constraints=c1)
    _print_plan(r1["plan"], r1["metrics"])
    results_summary.append(("T1", goal1, r1))

    # ═════════════════════════════════════════════════════════════
    # Test 2: Single product analysis (Hebrew)
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 2: Single product analysis — בלוגה")
    goal2 = "נתח את היסטוריית המחירים של בלוגה"
    c2 = Constraints(min_score=50)
    r2 = await orch.execute(goal2, constraints=c2)
    _print_plan(r2["plan"], r2["metrics"])
    results_summary.append(("T2", goal2, r2))

    # ═════════════════════════════════════════════════════════════
    # Test 3: Product analysis + recent deals
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 3: Product analysis + recent deals — רוסקי סטנדרט")
    goal3 = "נתח את רוסקי סטנדרט ותראה לי דילים אחרונים מעל 60"
    c3 = Constraints(min_score=60)
    r3 = await orch.execute(goal3, constraints=c3)
    _print_plan(r3["plan"], r3["metrics"])
    results_summary.append(("T3", goal3, r3))

    # ═════════════════════════════════════════════════════════════
    # Test 4: Conditional logic — health gate + scan
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 4: Conditional logic — check health, then scan")
    goal4 = "check health first, if scrapers are healthy then scan tracked products and return only strong deals above 80"
    c4 = Constraints(min_score=80, health_threshold=0.5)
    # Use _plan directly — execute() would trigger a real ~15min scan
    plan4 = orch._plan(goal4, c4)
    metrics4 = orch.get_metrics()
    _print_plan(plan4.to_dict(), metrics4)
    results_summary.append(("T4", goal4, {"plan": plan4.to_dict(), "metrics": metrics4}))

    # ═════════════════════════════════════════════════════════════
    # Test 5: Multiple products in one goal
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 5: Multiple products — דלתון + ירדן")
    goal5 = "analyze דלתון אסטייט קברנה and ירדן קברנה סוביניון 2022, then show me deals above 50"
    c5 = Constraints(min_score=50)
    r5 = await orch.execute(goal5, constraints=c5)
    _print_plan(r5["plan"], r5["metrics"])
    results_summary.append(("T5", goal5, r5))

    # ═════════════════════════════════════════════════════════════
    # Test 6: Tracked products scan with min_score constraint
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 6: Tracked products scan with min_score=70")
    goal6 = "scan tracked products and return deals above 70"
    c6 = Constraints(min_score=70, health_threshold=0.3)
    # Use _plan directly — execute() would trigger a real ~15min scan
    plan6 = orch._plan(goal6, c6)
    metrics6 = orch.get_metrics()
    _print_plan(plan6.to_dict(), metrics6)
    results_summary.append(("T6", goal6, {"plan": plan6.to_dict(), "metrics": metrics6}))

    # ═════════════════════════════════════════════════════════════
    # Test 7: Cache verification — repeat Test 2's goal
    # ═════════════════════════════════════════════════════════════
    _print_section("TEST 7: Cache verification — repeat Test 2 goal")
    r7 = await orch.execute(goal2, constraints=c2)
    _print_plan(r7["plan"], r7["metrics"])
    cached = any("cache" in r.lower() for r in r7["plan"].get("rationale", []))
    print(f"  → Cache hit detected: {cached}")
    results_summary.append(("T7", f"{goal2} (repeat)", r7))

    # ═════════════════════════════════════════════════════════════
    # Final summary table
    # ═════════════════════════════════════════════════════════════
    _print_section("SUMMARY TABLE")
    print(f"{'Test':<6} {'Intent':<10} {'Cache':<8} {'Products extracted':<30} {'Rationale quality'}")
    print("─" * 95)
    for tid, goal, r in results_summary:
        plan = r["plan"]
        cached_hit = any("cache" in x.lower() for x in plan.get("rationale", []))
        products = ", ".join(plan.get("analyze_products", [])) or "—"
        n_rationale = len(plan.get("rationale", []))
        quality = "good" if n_rationale >= 2 else "thin" if n_rationale == 1 else "none"
        print(f"{tid:<6} {plan['intent']:<10} {'✅ yes' if cached_hit else '❌ no':<8} {products:<30} {quality}")

    # Final metrics
    _print_section("FINAL METRICS")
    final = orch.get_metrics()
    print(json.dumps(final, indent=2))

    print("\n✅ All tests complete.")


if __name__ == "__main__":
    asyncio.run(run_tests())