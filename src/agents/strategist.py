"""Strategist Agent — generates business recommendations from Orchestrator output.

Receives the structured result from OrchestratorAgent.execute() (or a similar
dict with deals, analyses, health, etc.) and produces actionable pricing &
merchandising recommendations for the store owner (Shmulik).

Design:
    ┌─────────────────────────────────────────────────────┐
    │                  StrategistAgent                     │
    │                                                      │
    │  generate_recommendations(orchestrator_result)       │
    │       │                                              │
    │       ├─ 1. Extract: pull deals + analyses from input│
    │       │                                              │
    │       ├─ 2. Enrich: add context (Turki baseline,     │
    │       │      savings %, price history stats)         │
    │       │                                              │
    │       ├─ 3. LLM Reasoning: send enriched data to     │
    │       │      DeepSeek V4 Flash → structured JSON     │
    │       │                                              │
    │       └─ 4. Return: list of recommendations          │
    │              ├─ Price Action (lower/raise price)     │
    │              ├─ Promotion (push a deal)              │
    │              ├─ Monitor (watch but don't act)        │
    │              └─ Ignore (no action needed)            │
    └─────────────────────────────────────────────────────┘

The Strategist does NOT call the Orchestrator. It only consumes its output.
This separation allows the Orchestrator to focus on data collection while
the Strategist focuses on business intelligence.

Usage:
    from src.agents.strategist import StrategistAgent

    strategist = StrategistAgent()
    result = strategist.generate_recommendations(orchestrator_output)
    for rec in result["recommendations"]:
        print(f"[{rec['priority']}] {rec['recommendation_type']}: {rec['action']}")
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project root on sys.path ──────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
#  Recommendation dataclass
# ════════════════════════════════════════════════════════════════════

@dataclass
class Recommendation:
    """A single business recommendation for the store owner.

    Attributes:
        recommendation_type: One of: Price Action, Promotion, Monitor, Ignore
        products: List of product names this recommendation applies to
        action: Clear, actionable instruction (Hebrew or English)
        reasoning: Short explanation of why this recommendation was made
        priority: High / Medium / Low
        confidence: 0-100, how confident the Strategist is in this recommendation
    """
    recommendation_type: str
    products: List[str]
    action: str
    reasoning: str
    priority: str  # High / Medium / Low
    confidence: int  # 0-100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_type": self.recommendation_type,
            "products": self.products,
            "action": self.action,
            "reasoning": self.reasoning,
            "priority": self.priority,
            "confidence": self.confidence,
        }


# ════════════════════════════════════════════════════════════════════
#  StrategistAgent
# ════════════════════════════════════════════════════════════════════

class StrategistAgent:
    """Generates actionable business recommendations from Orchestrator output.

    Receives the structured result from ``OrchestratorAgent.execute()`` (or
    a similar dict) and uses LLM reasoning to produce pricing, promotion,
    monitoring, and ignore recommendations.

    The agent does NOT call the Orchestrator — it only consumes its output.
    This keeps data collection (Orchestrator) and business intelligence
    (Strategist) cleanly separated.

    Recommendation types:
        - **Price Action**: Competitor is significantly cheaper → suggest
          lowering Turki's price to stay competitive.
        - **Promotion**: A product is on sale at a competitor → suggest a
          counter-promotion or marketing push.
        - **Monitor**: Price gap is small or uncertain → watch the product
          but don't act yet.
        - **Ignore**: No meaningful price difference or product not relevant.
    """

    # ── LLM config (same Ollama Cloud pattern as llm_deals.py) ──────
    _LLM_BASE_URL = "https://ollama.com/v1"
    _LLM_MODEL = "deepseek-v4-flash"
    _LLM_TIMEOUT = 60
    _LLM_MAX_TOKENS = 4096

    def __init__(self):
        self._api_key = self._load_api_key()

    # ═════════════════════════════════════════════════════════════
    #  Main entry point
    # ═════════════════════════════════════════════════════════════

    def generate_recommendations(
        self, orchestrator_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate business recommendations from Orchestrator output.

        Args:
            orchestrator_result: The dict returned by
                ``OrchestratorAgent.execute()``. Must contain at least a
                ``"result"`` key with deals and/or analyses. Can also
                include ``"health"`` and ``"plan"`` for context.

        Returns:
            ``{"ok": True, "recommendations": [...], "summary": str,
               "input_products": int, "input_deals": int}`` on success,
            or ``{"ok": False, "error": str}`` on failure.
        """
        # Phase 1: Extract relevant data from orchestrator output
        extracted = self._extract_input(orchestrator_result)
        if not extracted["has_data"]:
            return {
                "ok": True,
                "recommendations": [],
                "summary": "אין נתונים מספיקים להמלצות — ה-Orchestrator לא החזיר דילים או ניתוחים.",
                "input_products": 0,
                "input_deals": 0,
            }

        # Phase 2: Build LLM prompt with enriched context
        prompt = self._build_prompt(extracted)

        # Phase 3: Call LLM for recommendations
        llm_result = self._call_llm(prompt)

        if llm_result is None:
            # Fallback: rule-based recommendations without LLM
            logger.info("Strategist: LLM failed, using rule-based fallback")
            recs = self._rule_based_recommendations(extracted)
            return {
                "ok": True,
                "recommendations": [r.to_dict() for r in recs],
                "summary": self._build_summary(recs, fallback=True),
                "input_products": extracted["product_count"],
                "input_deals": extracted["deal_count"],
                "source": "fallback",
            }

        # Phase 4: Parse LLM output into Recommendation objects
        recs = self._parse_recommendations(llm_result)

        return {
            "ok": True,
            "recommendations": [r.to_dict() for r in recs],
            "summary": self._build_summary(recs, fallback=False),
            "input_products": extracted["product_count"],
            "input_deals": extracted["deal_count"],
            "source": "llm",
        }

    # ═════════════════════════════════════════════════════════════
    #  Phase 1: Extract input data
    # ═════════════════════════════════════════════════════════════

    def _extract_input(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Pull deals, analyses, and health from orchestrator output.

        Normalizes the data into a compact format for the LLM prompt.
        """
        inner = result.get("result", result)  # support both shapes
        deals = inner.get("deals", [])
        analyses = inner.get("analyses", [])
        health = inner.get("health", {})
        plan = result.get("plan", {})

        # Collect all product names mentioned
        products_seen = set()
        for d in deals:
            name = d.get("product_name", d.get("product", ""))
            if name:
                products_seen.add(name)
        for a in analyses:
            products_seen.add(a.get("product", ""))

        # Build compact deal summaries for the prompt
        deal_summaries = []
        for d in deals[:30]:  # cap at 30 to keep prompt manageable
            name = d.get("product_name", d.get("product", "unknown"))
            store = d.get("store_name", d.get("store", ""))
            price = d.get("price", 0)
            turki = d.get("turki_price", 0)
            savings_pct = d.get("savings_percent", 0)
            score = d.get("score", 0)
            deal_summaries.append({
                "product": name,
                "store": store,
                "store_price": price,
                "turki_price": turki,
                "savings_percent": savings_pct,
                "score": score,
            })

        # Build compact analysis summaries
        analysis_summaries = []
        for a in analyses:
            r = a.get("result", {})
            if not r.get("ok"):
                continue
            analysis_summaries.append({
                "product": a.get("product", ""),
                "cheapest_store": r.get("cheapest_store", ""),
                "latest_turki_price": r.get("latest_turki_price"),
                "latest_lowest_price": r.get("latest_lowest_price"),
                "savings_percent": r.get("savings_percent"),
                "is_meaningful_deal": r.get("is_meaningful_deal", False),
                "price_stats": r.get("price_stats", {}),
            })

        has_data = bool(deal_summaries or analysis_summaries)

        return {
            "has_data": has_data,
            "deals": deal_summaries,
            "analyses": analysis_summaries,
            "health": health,
            "plan_intent": plan.get("intent", ""),
            "products_seen": sorted(products_seen),
            "product_count": len(products_seen),
            "deal_count": len(deal_summaries),
        }

    # ═════════════════════════════════════════════════════════════
    #  Phase 2: Build LLM prompt
    # ═════════════════════════════════════════════════════════════

    def _build_prompt(self, extracted: Dict[str, Any]) -> str:
        """Build a focused prompt for DeepSeek with enriched deal/analysis data.

        The prompt includes:
        - Role description (business advisor for Israeli liquor store)
        - Compact deal data (product, store, prices, savings %)
        - Analysis data (price history stats, cheapest store)
        - Few-shot example of expected output
        - Structured JSON output requirement
        """
        deals_json = json.dumps(extracted["deals"], ensure_ascii=False, indent=2)
        analyses_json = json.dumps(extracted["analyses"], ensure_ascii=False, indent=2)
        health = extracted.get("health", {})

        # Use a triple-quoted template to avoid string escaping issues
        example = (
            '[\n'
            '  {\n'
            '    "recommendation_type": "Price Action",\n'
            '    "products": ["וודקה בלוגה אלור 750 מל"],\n'
            '    "action": "הורד מחיר ל-150₪ כדי להתחרות בבנא משקאות",\n'
            '    "reasoning": "בנא משקאות sells at 150₪ vs Turki 229₪ (34% cheaper). Significant gap threatens market share.",\n'
            '    "priority": "High",\n'
            '    "confidence": 95\n'
            '  },\n'
            '  {\n'
            '    "recommendation_type": "Monitor",\n'
            '    "products": ["גוני ווקר בלאק לייבל 700 מל"],\n'
            '    "action": "עקוב אחר מחיר בנא משקאות — הפער קטן אך יכול לגדול",\n'
            '    "reasoning": "Competitor is only 8% cheaper. Not urgent but worth monitoring for further drops.",\n'
            '    "priority": "Low",\n'
            '    "confidence": 70\n'
            '  }\n'
            ']'
        )

        return f"""You are a business strategist for 'הטורקי' (Turki), a major Israeli liquor store chain.
Given pricing data from competitor scans, generate actionable recommendations for the store owner (Shmulik).

## Input Data

### Deals (competitor prices cheaper than Turki):
{deals_json}

### Product Analyses (price history + current status):
{analyses_json}

### Scraper Health: response_rate={health.get('overall_response_rate', 'N/A')}

## Recommendation Types
- **Price Action**: A competitor is significantly cheaper (>10%). Suggest lowering Turki's price to match or beat them.
- **Promotion**: A competitor has a sale. Suggest a counter-promotion or marketing push.
- **Monitor**: Price gap is small (<10%) or uncertain. Watch but don't act yet.
- **Ignore**: No meaningful price difference. No action needed.

## Rules
- Generate 1 recommendation per significant product or group of similar products.
- Don't generate more than 8 recommendations total.
- Be specific: include exact prices, store names, and savings percentages in the reasoning.
- Priority: High = competitor is >20% cheaper. Medium = 10-20% cheaper. Low = <10% or monitor only.
- Confidence: 90+ for clear price gaps. 70-89 for moderate. Below 70 for uncertain/monitor.
- Action should be a clear, short instruction in Hebrew (Shmulik reads Hebrew).
- Reasoning can be in English (internal team analysis).

## Example Output
{example}

Return ONLY a valid JSON array of recommendation objects. No markdown, no explanation."""

    # ═════════════════════════════════════════════════════════════
    #  Phase 3: Call LLM
    # ═════════════════════════════════════════════════════════════

    def _call_llm(self, prompt: str) -> Optional[List[Dict]]:
        """Send prompt to DeepSeek V4 Flash and parse the JSON response.

        Returns:
            List of recommendation dicts if successful, None on failure.
        """
        if not self._api_key:
            logger.debug("Strategist: no API key, skipping LLM")
            return None

        url = self._LLM_BASE_URL + "/chat/completions"
        payload = json.dumps({
            "model": self._LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self._LLM_MAX_TOKENS,
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._LLM_TIMEOUT) as resp:
                data = json.loads(resp.read())
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                content = content.strip()

                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                parsed = json.loads(content)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict) and "recommendations" in parsed:
                    return parsed["recommendations"]
                else:
                    logger.warning("Strategist: unexpected LLM response shape: %s", type(parsed))
                    return None

        except Exception as exc:
            logger.warning("Strategist: LLM call failed: %s", exc)
            return None

    # ═════════════════════════════════════════════════════════════
    #  Phase 4: Parse + validate
    # ═════════════════════════════════════════════════════════════

    def _parse_recommendations(self, llm_output: List[Dict]) -> List[Recommendation]:
        """Parse raw LLM JSON output into validated Recommendation objects."""
        valid_types = {"Price Action", "Promotion", "Monitor", "Ignore"}
        valid_priorities = {"High", "Medium", "Low"}

        recs = []
        for item in llm_output[:10]:  # cap at 10 recommendations
            try:
                rec_type = str(item.get("recommendation_type", "Monitor"))
                if rec_type not in valid_types:
                    rec_type = "Monitor"

                priority = str(item.get("priority", "Medium"))
                if priority not in valid_priorities:
                    priority = "Medium"

                confidence = int(item.get("confidence", 50))
                confidence = max(0, min(100, confidence))

                recs.append(Recommendation(
                    recommendation_type=rec_type,
                    products=[str(p) for p in item.get("products", [])],
                    action=str(item.get("action", ""))[:500],
                    reasoning=str(item.get("reasoning", ""))[:500],
                    priority=priority,
                    confidence=confidence,
                ))
            except Exception as exc:
                logger.warning("Strategist: failed to parse recommendation: %s", exc)
                continue

        return recs

    # ═════════════════════════════════════════════════════════════
    #  Fallback: rule-based recommendations (no LLM)
    # ═════════════════════════════════════════════════════════════

    def _rule_based_recommendations(self, extracted: Dict[str, Any]) -> List[Recommendation]:
        """Generate simple rule-based recommendations when LLM is unavailable.

        Rules:
        - savings > 20% → Price Action, High priority
        - savings 10-20% → Price Action, Medium priority
        - savings 5-10% → Monitor, Low priority
        - No deal data but analyses exist → per-analysis recommendation
        """
        recs = []

        for d in extracted["deals"]:
            savings = d.get("savings_percent", 0)
            product = d.get("product", "")
            store = d.get("store", "")
            price = d.get("store_price", 0)
            turki = d.get("turki_price", 0)

            if savings >= 20:
                recs.append(Recommendation(
                    recommendation_type="Price Action",
                    products=[product],
                    action=f"שקול הורדת מחיר ל-{price:.0f}₪ כדי להתחרות ב-{store}",
                    reasoning=f"{store} sells at {price:.0f}₪ vs Turki {turki:.0f}₪ ({savings:.0f}% cheaper).",
                    priority="High",
                    confidence=90,
                ))
            elif savings >= 10:
                recs.append(Recommendation(
                    recommendation_type="Price Action",
                    products=[product],
                    action=f"בחן תמחור מחדש מול {store} — פער של {savings:.0f}%",
                    reasoning=f"{store} is {savings:.0f}% cheaper ({price:.0f}₪ vs {turki:.0f}₪).",
                    priority="Medium",
                    confidence=80,
                ))
            elif savings >= 5:
                recs.append(Recommendation(
                    recommendation_type="Monitor",
                    products=[product],
                    action=f"עקוב אחר מחיר {store} — פער קטן",
                    reasoning=f"Small gap: {savings:.0f}% cheaper. Not urgent.",
                    priority="Low",
                    confidence=60,
                ))

        # If no deals but analyses exist
        if not recs and extracted["analyses"]:
            for a in extracted["analyses"]:
                if a.get("is_meaningful_deal"):
                    recs.append(Recommendation(
                        recommendation_type="Monitor",
                        products=[a.get("product", "")],
                        action="בדוק מתחרים — ייתכן דיל משמעותי",
                        reasoning=f"Analysis flags a meaningful deal ({a.get('savings_percent')}% vs Turki).",
                        priority="Medium",
                        confidence=70,
                    ))

        return recs[:8]  # cap at 8

    # ═════════════════════════════════════════════════════════════
    #  Helpers
    # ═════════════════════════════════════════════════════════════

    def _build_summary(self, recs: List[Recommendation], fallback: bool) -> str:
        """Build a human-readable summary of the recommendations."""
        if not recs:
            return "אין המלצות להצגה."

        lines = []
        source = "rule-based fallback" if fallback else "LLM"
        lines.append(f"🧠 Strategist ({source}): {len(recs)} המלצות")

        # Group by priority
        by_priority = {"High": [], "Medium": [], "Low": []}
        for r in recs:
            by_priority.setdefault(r.priority, []).append(r)

        for pri in ["High", "Medium", "Low"]:
            items = by_priority.get(pri, [])
            if items:
                icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}[pri]
                lines.append(f"\n{icon} {pri} ({len(items)}):")
                for r in items:
                    products = ", ".join(r.products[:2])
                    lines.append(f"  [{r.recommendation_type}] {products} — {r.action[:60]}")

        return "\n".join(lines)

    @staticmethod
    def _load_api_key() -> str:
        """Load Ollama API key from env or ~/.hermes/.env."""
        key = os.environ.get("OLLAMA_API_KEY", "")
        if key:
            return key
        try:
            with open(os.path.expanduser("~/.hermes/.env")) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OLLAMA_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
        return ""


# ════════════════════════════════════════════════════════════════════
#  CLI example
# ════════════════════════════════════════════════════════════════════

async def _example() -> None:
    """Demonstrate the Strategist with a simulated Orchestrator output."""
    import asyncio

    # Simulated orchestrator output with real deal data
    mock_orchestrator_output = {
        "ok": True,
        "goal": "analyze deals",
        "plan": {"intent": "deals"},
        "result": {
            "deals": [
                {"product_name": "וודקה בלוגה אלור 750 מ\"ל", "store_name": "בנא משקאות",
                 "price": 150, "turki_price": 229, "savings_percent": 34, "score": 51},
                {"product_name": "ג'וני ווקר רד לייבל 700 מ\"ל", "store_name": "בנא משקאות",
                 "price": 85, "turki_price": 125, "savings_percent": 32, "score": 48},
                {"product_name": "בלוגה סלבריישן 1 ליטר", "store_name": "Liquor Store",
                 "price": 129, "turki_price": 155, "savings_percent": 17, "score": 25},
            ],
            "analyses": [
                {"product": "בלוגה", "result": {
                    "ok": True, "cheapest_store": "פאנקו",
                    "latest_turki_price": 319, "latest_lowest_price": 119.9,
                    "savings_percent": 62.4, "is_meaningful_deal": True,
                    "price_stats": {"min": 119.9, "max": 889.9, "avg": 231.45, "count": 2245},
                }},
            ],
            "health": {"overall_response_rate": 0.585, "latest_run_id": "20260623_142825"},
        },
        "metrics": {"llm_planning_calls": 1, "cache_hits": 0, "cache_misses": 1},
    }

    strategist = StrategistAgent()
    result = strategist.generate_recommendations(mock_orchestrator_output)

    print(f"\n{'═' * 60}")
    print(f"  Strategist Agent — Example Output")
    print(f"{'═' * 60}")
    print(f"\nSource: {result.get('source', 'unknown')}")
    print(f"Input deals: {result.get('input_deals', 0)}")
    print(f"Input products: {result.get('input_products', 0)}")
    print(f"\n{result.get('summary', '')}")

    print(f"\n{'─' * 60}")
    print("  Detailed Recommendations:")
    print(f"{'─' * 60}")
    for i, rec in enumerate(result.get("recommendations", []), 1):
        print(f"\n  #{i} [{rec['priority']}] {rec['recommendation_type']} (confidence: {rec['confidence']}%)")
        print(f"  Products: {', '.join(rec['products'])}")
        print(f"  Action:   {rec['action']}")
        print(f"  Reason:   {rec['reasoning']}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_example())