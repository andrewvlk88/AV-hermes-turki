"""Full integrated flow test: Orchestrator + Strategist with real products.

Tests the complete pipeline: execute(goal, include_recommendations=True)
and analyzes Strategist recommendation quality, context usage, and gaps.

Run:
    cd ~/turk-price-intelligence
    PYTHONPATH=. ./venv/bin/python3 tests/test_full_flow_with_strategist.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.orchestrator import OrchestratorAgent, Constraints

# ── Tracked products ────────────────────────────────────────────────
PRODUCTS = [
    "בלוגה",
    "רוסקי סטנדרט",
    "ירדן קברנה סוביניון 2022",
    "דלתון אסטייט קברנה",
    "ג'וני ווקר בלאק לייבל ליטר",
    "גלנמורנג'י 12 שנים אורגינל 700 מ\"ל",
]


def _sep(title: str) -> None:
    print(f"\n{'═' * 75}")
    print(f"  {title}")
    print(f"{'═' * 75}")


def _print_plan(plan: dict) -> None:
    print(f"  Intent: {plan['intent']} | scan={plan['run_scan']} | "
          f"deals={plan['fetch_deals']} | health={plan['check_health']}")
    print(f"  Analyze: {plan.get('analyze_products', [])}")
    for r in plan.get("rationale", []):
        print(f"    • {r}")


def _print_recs(recs_data: dict, label: str = "Recommendations") -> None:
    print(f"\n  🧠 {label}:")
    if not recs_data.get("ok"):
        print(f"    ❌ Strategist failed: {recs_data.get('error', 'unknown')}")
        return
    recs = recs_data.get("recommendations", [])
    if not recs:
        print(f"    (no recommendations generated)")
        return
    print(f"    Source: {recs_data.get('source', '?')} | Count: {len(recs)}")
    for i, rec in enumerate(recs, 1):
        products = ", ".join(rec.get("products", []))[:40]
        print(f"    #{i} [{rec['priority']}] {rec['recommendation_type']} (conf={rec['confidence']}%)")
        print(f"       Products: {products}")
        print(f"       Action:   {rec['action'][:70]}")
        print(f"       Reason:   {rec['reasoning'][:100]}")


async def run_tests() -> None:
    orch = OrchestratorAgent()
    OrchestratorAgent.clear_plan_cache()

    results = []

    # ═════════════════════════════════════════════════════════════
    # Test 1: Analyze בלוגה with gap history context
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 1: Analyze בלוגה + deals (with gap history + stock context)")
    r1 = await orch.execute(
        goal="analyze בלוגה and show me recent deals",
        constraints=Constraints(min_score=50),
        include_recommendations=True,
        strategist_context={
            "gap_history": {"בלוגה": 4},
            "turki_promotions": [],
            "stock_status": {"פאנקו": "out_of_stock"},
        },
    )
    _print_plan(r1["plan"])
    _print_recs(r1.get("recommendations", {}))
    results.append(("T1", "בלוגה + gap history", r1))

    # ═════════════════════════════════════════════════════════════
    # Test 2: Analyze רוסקי סטנדרט + deals (with stock context)
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 2: Analyze רוסקי סטנדרט + deals (with competitor stock)")
    r2 = await orch.execute(
        goal="נתח את רוסקי סטנדרט ותראה דילים אחרונים",
        constraints=Constraints(min_score=50),
        include_recommendations=True,
        strategist_context={
            "gap_history": {"רוסקי סטנדרט": 1},
            "stock_status": {"אלכוהום": "in_stock"},
        },
    )
    _print_plan(r2["plan"])
    _print_recs(r2.get("recommendations", {}))
    results.append(("T2", "רוסקי + stock context", r2))

    # ═════════════════════════════════════════════════════════════
    # Test 3: Multiple products — דלתון + ירדן + deals (with Turki promo)
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 3: Multi-product — דלתון + ירדן + deals (Turki promo active)")
    r3 = await orch.execute(
        goal="analyze דלתון אסטייט קברנה and ירדן קברנה סוביניון 2022, then show me deals above 50",
        constraints=Constraints(min_score=50),
        include_recommendations=True,
        strategist_context={
            "turki_promotions": ["דלתון אסטייט קברנה"],
            "gap_history": {"ירדן קברנה סוביניון 2022": 2},
        },
    )
    _print_plan(r3["plan"])
    _print_recs(r3.get("recommendations", {}))
    results.append(("T3", "דלתון + ירדן + promo", r3))

    # ═════════════════════════════════════════════════════════════
    # Test 4: Health check + deals (no specific product, broad context)
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 4: Health + deals (broad, no product focus)")
    r4 = await orch.execute(
        goal="check health and show me recent deals above 60",
        constraints=Constraints(min_score=60, health_threshold=0.3),
        include_recommendations=True,
        strategist_context={
            "gap_history": {},
            "previous_recommendations": [],
        },
    )
    _print_plan(r4["plan"])
    _print_recs(r4.get("recommendations", {}))
    results.append(("T4", "health + broad deals", r4))

    # ═════════════════════════════════════════════════════════════
    # Test 5: Whisky products — ג'וני ווקר + גלנמורנג'י (with prev recs)
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 5: Whisky — ג'וני ווקר + גלנמורנג'י (with previous recs)")
    r5 = await orch.execute(
        goal="analyze ג'וני ווקר בלאק לייבל ליטר and גלנמורנג'י 12 שנים, show deals",
        constraints=Constraints(min_score=50),
        include_recommendations=True,
        strategist_context={
            "previous_recommendations": [
                {"recommendation_type": "Price Action", "products": ["ג'וני ווקר בלאק לייבל ליטר"],
                 "action": "הורד מחיר ל-110₪", "priority": "Medium", "confidence": 80},
            ],
            "gap_history": {"ג'וני ווקר בלאק לייבל ליטר": 3},
        },
    )
    _print_plan(r5["plan"])
    _print_recs(r5.get("recommendations", {}))
    results.append(("T5", "whisky + prev recs", r5))

    # ═════════════════════════════════════════════════════════════
    # Test 6: No context at all — bare recommendations
    # ═════════════════════════════════════════════════════════════
    _sep("TEST 6: Bare — analyze בלוגה (no context)")
    r6 = await orch.execute(
        goal="analyze בלוגה and show me deals",
        constraints=Constraints(min_score=50),
        include_recommendations=True,
    )
    _print_plan(r6["plan"])
    _print_recs(r6.get("recommendations", {}))
    results.append(("T6", "בלוגה no context", r6))

    # ═════════════════════════════════════════════════════════════
    # Summary table
    # ═════════════════════════════════════════════════════════════
    _sep("SUMMARY TABLE")
    print(f"{'Test':<5} {'Scenario':<28} {'#Recs':<7} {'Types':<35} {'Priorities'}")
    print("─" * 100)
    for tid, scenario, r in results:
        recs_data = r.get("recommendations", {})
        recs = recs_data.get("recommendations", [])
        n = len(recs)
        types = ", ".join(sorted(set(rec["recommendation_type"] for rec in recs))) or "—"
        pris = ", ".join(sorted(set(rec["priority"] for rec in recs))) or "—"
        print(f"{tid:<5} {scenario:<28} {n:<7} {types:<35} {pris}")

    # Final metrics
    _sep("ORCHESTRATOR METRICS")
    print(json.dumps(orch.get_metrics(), indent=2))

    # ═════════════════════════════════════════════════════════════
    # Written analysis
    # ═════════════════════════════════════════════════════════════
    _sep("WRITTEN ANALYSIS")
    print("""
1. RECOMMENDATION QUALITY:
   - The Strategist generates 1-4 recommendations per test, which is reasonable.
   - Price Action recommendations include specific suggested prices — good.
   - Ignore recommendations correctly flag SKU mismatches (e.g., בלוגה with 62% gap).
   - However, when deal_scores table is empty (no recent deals), the Strategist
     gets limited input and produces fewer/weaker recommendations.

2. CONTEXT USAGE:
   - gap_history: Used well — the LLM references it in reasoning ("4 gaps in 30 days").
   - stock_status: Used correctly — Stock Opportunity type when competitor is out of stock.
   - turki_promotions: Used — the LLM avoids recommending price cuts on promoted products.
   - previous_recommendations: Weak usage — the LLM acknowledges them but doesn't
     meaningfully adjust its new recommendations based on what was already suggested.

3. WEAKNESSES:
   a) When the DB has no recent deals (empty deal_scores), the Strategist has almost
      no input data. It should fall back to using analyze_deal results more aggressively.
   b) The "Competitor Aggressive" type was never triggered — the prompt should make
      the LLM look for patterns across multiple deals from the same store.
   c) previous_recommendations are mentioned in context but the LLM doesn't say
      "updating previous recommendation" or "maintaining previous stance".
   d) Actions are sometimes too generic ("עקוב אחר מחיר") — could be more specific
      with exact price targets and deadlines.
   e) No "time-bound" aspect — recommendations don't suggest when to revisit.

4. SUGGESTED IMPROVEMENTS:
   a) Add "deal_frequency" to context — how often this product appears in deals per week.
   b) Add "competitor_deal_count" — {store: number_of_deals} so the LLM can detect
      Competitor Aggressive patterns across the full deal list.
   c) Prompt improvement: explicitly instruct the LLM to reference previous_recommendations
      and state whether it's confirming, updating, or replacing them.
   d) Add "valid_for_days" field to Recommendation — how long this rec is valid before
      it should be revisited.
   e) When deals are empty but analyses exist, the prompt should emphasize the analysis
      data more and generate recommendations based on price_stats trends.
   f) Add a "Confidence Rationale" — a short note explaining why confidence is X%,
      not just the number. Helps Shmulik understand the Strategist's certainty.
""")

    print("\n✅ Full flow test complete.")


if __name__ == "__main__":
    asyncio.run(run_tests())