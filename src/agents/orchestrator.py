"""Orchestrator Agent — intelligent coordinator for Turkí Price Intelligence.

This is the "brain" that decides how and when to use the available
tools from src/tools/turki_tools.py. Instead of running fixed
procedural flows, it accepts high-level goals and constraints, checks
system health, and makes decisions about what to run.

Design:
    ┌─────────────────────────────────────────────────────┐
    │                  OrchestratorAgent                   │
    │                                                      │
    │  execute(goal, constraints)  ← main entry point      │
    │       │                                              │
    │       ├─ 1. Plan: decide what to do                  │
    │       │      ├─ check health threshold?               │
    │       │      ├─ tracked-only or full scan?            │
    │       │      └─ what min_score / filters?            │
    │       │                                              │
    │       ├─ 2. Act: call tools via ToolRegistry         │
    │       │      ├─ get_scraper_health_report()           │
    │       │      ├─ run_full_scan() / run_tracked_*()     │
    │       │      ├─ get_recent_deals(min_score)           │
    │       │      └─ analyze_deal(product_name)            │
    │       │                                              │
    │       └─ 3. Report: structured output                 │
    │              ├─ decisions taken (why)                │
    │              ├─ tool results                          │
    │              └─ final summary                         │
    └─────────────────────────────────────────────────────┘

The Orchestrator is NOT a ReAct agent — it doesn't loop on
observations. It's a single-pass planner + executor that makes smart
decisions up front, calls the right tools, and returns everything.

Compatibility:
    - run_query() / run_tracked() / run_batch() preserved for
      backward compat with any existing callers.
    - cron_tracker.py is unaffected — it imports from run.py directly.

Usage:
    from src.agents.orchestrator import OrchestratorAgent

    orch = OrchestratorAgent()

    # Simple: scan tracked products, return strong deals
    result = await orch.execute("scan and report strong deals")

    # Advanced: with constraints
    result = await orch.execute(
        "scan tracked products, but only if scrapers are healthy",
        constraints={
            "min_score": 80,
            "health_threshold": 0.5,
            "days": 7,
        }
    )

    # Just analyze (no scan)
    result = await orch.execute(
        "analyze בלוגה and check recent deals",
        constraints={"min_score": 50}
    )
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ── project root on sys.path ──────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.models import ProductPrice, PriceReport, Store, ComparisonResult
from src.storage.sqlite_store import (
    get_db,
    init_db,
    save_store_result,
    mark_store_error,
    mark_store_running,
    run_id_gen,
)
from src.agents.analyzer import AnalyzerAgent
from src.agents.extractor import ExtractorAgent
from src.utils.filters import clean_product_name, is_bogus_price, is_relevant_product
from src.logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
#  Constraints dataclass
# ════════════════════════════════════════════════════════════════════

@dataclass
class Constraints:
    """User-provided constraints that shape the Orchestrator's decisions.

    Attributes:
        min_score: Minimum deal score to include in results (0–100). Default 70.
        health_threshold: Minimum overall response rate (0–1) required to
            proceed with a scan. If the recent health is below this,
            the Orchestrator will warn and skip the scan. Default 0.4.
        health_days: Look-back window (days) for health check. Default 7.
        focus_products: Specific product names to analyze (no scan, just DB
            lookup). If provided, the Orchestrator skips scanning.
        tracked_only: If True, only scan tracked products. Default True.
        max_deals: Maximum number of deals to return (top-N by score).
            Default 20. Set to 0 for unlimited.
        scan_timeout: Timeout in seconds for the entire scan. Default 1800 (30 min).
    """
    min_score: float = 70.0
    health_threshold: float = 0.4
    health_days: int = 7
    focus_products: List[str] = field(default_factory=list)
    tracked_only: bool = True
    max_deals: int = 20
    scan_timeout: int = 1800


# ════════════════════════════════════════════════════════════════════
#  Plan (internal decision structure)
# ════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    """Internal plan representing what the Orchestrator decided to do."""
    # High-level intent parsed from the goal string
    intent: str  # "scan", "analyze", "deals", "health", "auto"
    # Should we check scraper health first?
    check_health: bool = True
    # Should we run a scan?
    run_scan: bool = False
    # Which scan tool to call
    scan_tool: str = ""  # "run_full_scan" / "run_tracked_products_scan"
    # Should we fetch recent deals?
    fetch_deals: bool = False
    # Should we analyze specific products?
    analyze_products: List[str] = field(default_factory=list)
    # Human-readable decision rationale
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "check_health": self.check_health,
            "run_scan": self.run_scan,
            "scan_tool": self.scan_tool,
            "fetch_deals": self.fetch_deals,
            "analyze_products": self.analyze_products,
            "rationale": self.rationale,
        }


# ════════════════════════════════════════════════════════════════════
#  OrchestratorAgent
# ════════════════════════════════════════════════════════════════════

class OrchestratorAgent:
    """Intelligent coordinator that decides how to use the tool layer.

    The Orchestrator receives a natural-language goal (or a structured
    constraint set), plans what tools to call, executes them, and
    returns a structured result with full transparency about its
    decisions.

    Key design decisions:
    - Single-pass planner (not ReAct). The plan is decided up front
      based on the goal + constraints, then executed without looping.
    - Tool calls are delegated to src/tools/turki_tools.py — the
      Orchestrator never re-implements tool logic.
    - All output follows the {"ok": bool, ...} convention.
    - Backward-compatible: run_query / run_tracked / run_batch still
      work for existing callers.
    """

    # ── LLM planning config ───────────────────────────────────────
    _LLM_BASE_URL = "https://ollama.com/v1"
    _LLM_MODEL = "deepseek-v4-flash"
    _LLM_TIMEOUT = 30
    _LLM_MAX_TOKENS = 1024

    def __init__(self, timeout_per_query: int = 30 * 60):
        self.timeout = timeout_per_query
        self.analyzer = AnalyzerAgent()
        self.extractor = ExtractorAgent()

    # ═════════════════════════════════════════════════════════════
    #  Main entry point: execute()
    # ═════════════════════════════════════════════════════════════

    async def execute(
        self,
        goal: str = "",
        constraints: Optional[Constraints | Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a high-level goal with optional constraints.

        This is the main entry point for agent-style calls. The
        Orchestrator parses the goal, builds a plan, executes it via
        tools, and returns a structured result.

        Args:
            goal: Natural-language instruction. Examples:
                - "scan and report strong deals"
                - "check health, then scan if healthy"
                - "analyze בלוגה and check recent deals"
                - "just show me recent deals"
            constraints: Either a Constraints dataclass or a dict with
                any of: min_score, health_threshold, health_days,
                focus_products, tracked_only, max_deals, scan_timeout.

        Returns:
            ``{"ok": True, "goal": str, "plan": {...}, "steps": [...],
               "result": {...}, "summary": str}``
        """
        # Normalize constraints
        c = self._normalize_constraints(constraints)

        # Phase 1: Plan
        plan = self._plan(goal, c)
        logger.info("Orchestrator plan: %s", plan.to_dict())

        # Phase 2: Execute plan
        steps: List[Dict[str, Any]] = []
        health_data: Optional[Dict[str, Any]] = None

        # Step 2a: Health check (if planned)
        if plan.check_health:
            health_data = self._call_tool_sync(
                "get_scraper_health_report", days=c.health_days
            )
            steps.append({
                "step": "health_check",
                "tool": "get_scraper_health_report",
                "result": health_data,
            })

            # Gate: if health is below threshold, skip scan
            if plan.run_scan and health_data.get("ok"):
                rate = health_data.get("overall_response_rate", 1.0)
                if rate < c.health_threshold:
                    plan.run_scan = False
                    plan.rationale.append(
                        f"Skipped scan: response rate {rate:.0%} < "
                        f"threshold {c.health_threshold:.0%}"
                    )

        # Step 2b: Scan (if planned and not skipped)
        scan_data: Optional[Dict[str, Any]] = None
        if plan.run_scan:
            if plan.scan_tool == "run_tracked_products_scan":
                scan_data = await self._call_tool_async("run_tracked_products_scan")
            else:
                scan_data = await self._call_tool_async("run_full_scan")
            steps.append({
                "step": "scan",
                "tool": plan.scan_tool,
                "result": self._summarize_scan_result(scan_data),
            })

        # Step 2c: Fetch deals (if planned)
        deals_data: Optional[Dict[str, Any]] = None
        if plan.fetch_deals:
            deals_data = self._call_tool_sync(
                "get_recent_deals", min_score=c.min_score
            )
            # Apply max_deals limit
            if deals_data.get("ok") and c.max_deals > 0:
                deals_data["deals"] = deals_data["deals"][:c.max_deals]
                deals_data["deal_count"] = len(deals_data["deals"])
            steps.append({
                "step": "deals",
                "tool": "get_recent_deals",
                "result": deals_data,
            })

        # Step 2d: Analyze specific products (if planned)
        analyses: List[Dict[str, Any]] = []
        for product in plan.analyze_products:
            analysis = self._call_tool_sync("analyze_deal", product_name=product)
            analyses.append({"product": product, "result": analysis})
        if analyses:
            steps.append({
                "step": "analyze",
                "tool": "analyze_deal",
                "result": analyses,
            })

        # Phase 3: Build final result
        result: Dict[str, Any] = {}
        if deals_data and deals_data.get("ok"):
            result["deals"] = deals_data["deals"]
            result["deal_count"] = deals_data["deal_count"]
            result["run_id"] = deals_data.get("run_id")
        if scan_data and scan_data.get("ok"):
            result["scan_run_id"] = scan_data.get("run_id")
            result["scan_summary"] = scan_data.get("summary", "")
        if health_data and health_data.get("ok"):
            result["health"] = {
                "overall_response_rate": health_data.get("overall_response_rate"),
                "latest_run_id": health_data.get("latest_run_id"),
            }
        if analyses:
            result["analyses"] = analyses

        summary = self._build_summary(plan, steps, result)

        return {
            "ok": True,
            "goal": goal,
            "plan": plan.to_dict(),
            "steps": steps,
            "result": result,
            "summary": summary,
            "timestamp": datetime.now().isoformat(),
        }

    # ═════════════════════════════════════════════════════════════
    #  Planning logic
    # ═════════════════════════════════════════════════════════════

    # ── Keywords for fallback intent parsing ─────────────────────
    _SCAN_KEYWORDS = {"scan", "סריקה", "סרוק", "run", "הרץ", "הפעל"}
    _ANALYZE_KEYWORDS = {"analyze", "נתח", "ניתוח", "בדוק מוצר", "היסטוריה"}
    _DEALS_KEYWORDS = {"deal", "deals", "דיל", "דילים", "מבצע", "מבצעים", "חיסכון"}
    _HEALTH_KEYWORDS = {"health", "בריאות", "סטטוס", "status", "מצב"}

    def _plan(self, goal: str, c: Constraints) -> Plan:
        """Decide what to do based on the goal string and constraints.

        Uses LLM reasoning (DeepSeek V4 Flash via Ollama Cloud) to
        understand the natural-language goal and produce a structured
        plan. If the LLM is unavailable or returns invalid output,
        falls back to keyword-based planning.

        Args:
            goal: Natural-language instruction (Hebrew or English).
            c: Structured constraints from the caller.

        Returns:
            A Plan dataclass with decisions and rationale.
        """
        # Try LLM planning first
        plan = self._llm_plan(goal, c)
        if plan is not None:
            logger.info("Orchestrator: plan via LLM — intent=%s", plan.intent)
            return plan

        # Fallback: keyword-based planning
        logger.info("Orchestrator: LLM planning failed, falling back to keywords")
        plan = self._keyword_plan(goal, c)
        plan.rationale.insert(0, "Fallback: LLM unavailable, using keyword matching")
        return plan

    def _llm_plan(self, goal: str, c: Constraints) -> Optional[Plan]:
        """Use LLM to analyze the goal and produce a structured Plan.

        Sends a focused prompt to DeepSeek V4 Flash with the goal,
        available tools, and current constraints. The LLM returns JSON
        that maps directly to the Plan dataclass.

        Returns:
            Plan if LLM succeeded, None to signal fallback.
        """
        import os
        import json as _json
        import urllib.request

        # Load API key (same pattern as llm_deals.py / llm_volume.py)
        api_key = os.environ.get("OLLAMA_API_KEY", "")
        if not api_key:
            try:
                with open(os.path.expanduser("~/.hermes/.env")) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OLLAMA_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except Exception:
                pass

        if not api_key:
            logger.debug("LLM planning skipped: no API key")
            return None

        # Build a compact system prompt describing available tools
        tool_descriptions = [
            "1. get_scraper_health_report(days) — sync, checks scraper response rates and store status from DB",
            "2. run_full_scan() — async, ~15 min, scans all tracked products across 20 stores",
            "3. run_tracked_products_scan() — async, thin alias of run_full_scan",
            "4. get_recent_deals(min_score) — sync, returns deals from latest DB run above score threshold",
            "5. analyze_deal(product_name) — sync, historical price analysis + whether current price is a meaningful deal",
        ]

        constraints_desc = (
            f"min_score={c.min_score}, health_threshold={c.health_threshold}, "
            f"health_days={c.health_days}, tracked_only={c.tracked_only}, "
            f"max_deals={c.max_deals}, focus_products={c.focus_products}"
        )

        prompt = (
            "You are a planning agent for a price intelligence system.\n"
            "Given a user goal and constraints, decide which tools to call and in what order.\n\n"
            f"Goal: \"{goal}\"\n"
            f"Constraints: {constraints_desc}\n\n"
            "Available tools:\n" + "\n".join(tool_descriptions) + "\n\n"
            "Rules:\n"
            "- If the goal mentions scanning, set run_scan=true.\n"
            "- If scanning, always set check_health=true (health gate runs before scan).\n"
            "- If the goal asks for deals or after a scan, set fetch_deals=true.\n"
            "- If the goal mentions analyzing specific products, extract their names into analyze_products.\n"
            "- If the goal only asks for health, set run_scan=false, fetch_deals=false.\n"
            "- If the goal only asks for deals (no scan), set run_scan=false, fetch_deals=true.\n"
            "- If the goal is empty or vague, default to: check_health=true, run_scan=true, fetch_deals=true.\n"
            "- scan_tool should be 'run_tracked_products_scan' if tracked_only=true, else 'run_full_scan'.\n"
            "- Provide a short rationale (1-3 items) explaining your decisions.\n\n"
            "Return ONLY valid JSON (no markdown, no explanation):\n"
            '{\n'
            '  "intent": "scan|analyze|deals|health|auto",\n'
            '  "check_health": true|false,\n'
            '  "run_scan": true|false,\n'
            '  "scan_tool": "run_tracked_products_scan|run_full_scan",\n'
            '  "fetch_deals": true|false,\n'
            '  "analyze_products": ["product name", ...],\n'
            '  "rationale": ["reason 1", "reason 2"]\n'
            '}'
        )

        url = self._LLM_BASE_URL + "/chat/completions"
        payload = _json.dumps({
            "model": self._LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self._LLM_MAX_TOKENS,
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._LLM_TIMEOUT) as resp:
                data = _json.loads(resp.read())
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                content = content.strip()

                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                parsed = _json.loads(content)

                # Validate and build Plan
                plan = Plan(
                    intent=str(parsed.get("intent", "auto")),
                    check_health=bool(parsed.get("check_health", False)),
                    run_scan=bool(parsed.get("run_scan", False)),
                    scan_tool=str(parsed.get("scan_tool", "run_tracked_products_scan")),
                    fetch_deals=bool(parsed.get("fetch_deals", False)),
                    analyze_products=list(parsed.get("analyze_products", [])),
                    rationale=[str(r) for r in parsed.get("rationale", [])],
                )

                # Post-validation: if scanning, force health check on
                if plan.run_scan:
                    plan.check_health = True
                # Ensure scan_tool matches tracked_only constraint
                if plan.run_scan:
                    plan.scan_tool = (
                        "run_tracked_products_scan" if c.tracked_only
                        else "run_full_scan"
                    )

                logger.info("LLM plan rationale: %s", plan.rationale)
                return plan

        except Exception as exc:
            logger.warning("LLM planning failed: %s", exc)
            return None

    def _keyword_plan(self, goal: str, c: Constraints) -> Plan:
        """Keyword-based fallback planning (original logic).

        Used when the LLM is unavailable or returns invalid output.
        """
        goal_lower = goal.lower().strip()
        rationale: List[str] = []

        wants_scan = any(k in goal_lower for k in self._SCAN_KEYWORDS)
        wants_analyze = any(k in goal_lower for k in self._ANALYZE_KEYWORDS)
        wants_deals = any(k in goal_lower for k in self._DEALS_KEYWORDS)
        wants_health = any(k in goal_lower for k in self._HEALTH_KEYWORDS)

        focus_products = c.focus_products.copy()

        if wants_analyze and not focus_products:
            for marker in ("analyze", "נתח", "בדוק מוצר", "היסטוריה"):
                if marker in goal_lower:
                    after = goal_lower.split(marker, 1)[-1].strip()
                    for sep in [" and ", " ולבדוק", " ובדוק", " and check", ",", " ו"]:
                        if sep in after:
                            after = after.split(sep, 1)[0].strip()
                            break
                    if after and len(after) > 2:
                        focus_products.append(after)
                    break

        if not any([wants_scan, wants_analyze, wants_deals, wants_health]):
            rationale.append("No specific intent detected — defaulting to auto mode")
            wants_scan = True
            wants_deals = True
            wants_health = True

        plan = Plan(
            intent="scan" if wants_scan else ("analyze" if wants_analyze else
                   ("deals" if wants_deals else ("health" if wants_health else "auto"))),
            check_health=wants_health or wants_scan,
            run_scan=wants_scan,
            scan_tool="run_tracked_products_scan" if c.tracked_only else "run_full_scan",
            fetch_deals=wants_deals or wants_scan,
            analyze_products=focus_products,
            rationale=rationale,
        )

        if focus_products and not wants_scan:
            plan.run_scan = False
            plan.check_health = False
            plan.fetch_deals = wants_deals

        if plan.run_scan:
            plan.rationale.append(
                f"Will scan via {plan.scan_tool} (tracked_only={c.tracked_only})"
            )
        if plan.fetch_deals:
            plan.rationale.append(f"Will fetch deals with min_score={c.min_score}")
        if plan.analyze_products:
            plan.rationale.append(f"Will analyze: {', '.join(plan.analyze_products)}")

        return plan

    # ═════════════════════════════════════════════════════════════
    #  Tool execution helpers
    # ═════════════════════════════════════════════════════════════

    def _normalize_constraints(
        self, constraints: Optional[Constraints | Dict[str, Any]]
    ) -> Constraints:
        """Accept either a Constraints dataclass or a plain dict."""
        if constraints is None:
            return Constraints()
        if isinstance(constraints, Constraints):
            return constraints
        if isinstance(constraints, dict):
            return Constraints(**{k: v for k, v in constraints.items()
                                   if k in Constraints.__dataclass_fields__})
        return Constraints()

    def _call_tool_sync(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Call a sync tool from turki_tools by name."""
        from src.tools.turki_tools import (
            get_recent_deals,
            get_scraper_health_report,
            analyze_deal,
        )
        tools = {
            "get_recent_deals": get_recent_deals,
            "get_scraper_health_report": get_scraper_health_report,
            "analyze_deal": analyze_deal,
        }
        fn = tools.get(tool_name)
        if not fn:
            return {"ok": False, "error": f"unknown sync tool: {tool_name}"}
        try:
            return fn(**kwargs)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return {"ok": False, "error": str(exc)}

    async def _call_tool_async(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Call an async tool from turki_tools by name."""
        from src.tools.turki_tools import (
            run_full_scan,
            run_tracked_products_scan,
        )
        tools = {
            "run_full_scan": run_full_scan,
            "run_tracked_products_scan": run_tracked_products_scan,
        }
        fn = tools.get(tool_name)
        if not fn:
            return {"ok": False, "error": f"unknown async tool: {tool_name}"}
        try:
            return await fn(**kwargs)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return {"ok": False, "error": str(exc)}

    def _summarize_scan_result(self, scan: Dict[str, Any]) -> Dict[str, Any]:
        """Slim down scan result for the steps log (don't repeat full summary)."""
        if not scan.get("ok"):
            return scan
        return {
            "ok": True,
            "run_id": scan.get("run_id"),
            "queries": scan.get("queries"),
            "deal_count": len(scan.get("deals", [])),
            "stores_checked": scan.get("stores_checked"),
            "stores_responded": scan.get("stores_responded"),
        }

    # ═════════════════════════════════════════════════════════════
    #  Summary builder
    # ═════════════════════════════════════════════════════════════

    def _build_summary(
        self, plan: Plan, steps: List[Dict[str, Any]], result: Dict[str, Any]
    ) -> str:
        """Build a human-readable summary of what happened."""
        lines: List[str] = []

        # Decisions
        if plan.rationale:
            lines.append("📋 Decisions:")
            for r in plan.rationale:
                lines.append(f"  • {r}")

        # Health
        for step in steps:
            if step["step"] == "health_check":
                r = step["result"]
                if r.get("ok"):
                    rate = r.get("overall_response_rate", 0)
                    lines.append(f"🩺 Health: {rate:.0%} response rate (last {r.get('period_days')}d)")

        # Scan
        for step in steps:
            if step["step"] == "scan":
                r = step["result"]
                if r.get("ok"):
                    lines.append(
                        f"🔎 Scan: {r.get('stores_responded', 0)}/{r.get('stores_checked', 0)} "
                        f"stores responded, {r.get('deal_count', 0)} deals found"
                    )
                else:
                    lines.append(f"❌ Scan failed: {r.get('error', 'unknown')}")

        # Deals
        deal_count = result.get("deal_count", 0)
        if deal_count:
            lines.append(f"💰 Deals: {deal_count} deals above threshold")

        # Analyses
        analyses = result.get("analyses", [])
        for a in analyses:
            r = a["result"]
            if r.get("ok"):
                deal = "✅ meaningful deal" if r.get("is_meaningful_deal") else "❌ not a deal"
                lines.append(f"📊 {a['product']}: {deal} ({r.get('savings_percent')}% vs Turki)")

        if not lines:
            lines.append("No actions taken.")

        return "\n".join(lines)

    # ═════════════════════════════════════════════════════════════
    #  Backward-compatible methods (unchanged API)
    # ═════════════════════════════════════════════════════════════

    async def run_query(self, query: str, save_to_db: bool = True) -> PriceReport:
        """Run the full pipeline for a single query.

        Backward-compatible with the old OrchestratorAgent. Delegates
        to run.py's search_all + build_report internally.

        Args:
            query: Product search term (e.g., "וודקה בלוגה ליטר")
            save_to_db: If True, persist results to SQLite

        Returns:
            PriceReport with deals, anomalies, and per-product comparison
        """
        from run import search_all, build_report, PlaywrightEngine

        init_db()
        run_id = run_id_gen()

        logger.info("Orchestrator: starting query=%r run_id=%s", query, run_id)

        try:
            all_prices = await asyncio.wait_for(
                search_all(query), timeout=self.timeout
            )
            filtered = self._filter_prices(all_prices, query)
            report = build_report(filtered, query)

            if save_to_db:
                self._log_scraper_health(run_id, query, report)

            logger.info(
                "Orchestrator: query=%r done | %d stores responded | %d deals | %d anomalies",
                query, report.stores_responded, len(report.deals_found), len(report.anomalies),
            )
            return report

        except asyncio.TimeoutError:
            logger.error("Orchestrator: query=%r timed out after %ds", query, self.timeout)
            report = PriceReport(query=query)
            report.summary = f"⏱️ Timeout after {self.timeout}s"
            return report

        except Exception as e:
            logger.exception("Orchestrator: query=%r failed", query)
            report = PriceReport(query=query)
            report.summary = f"❌ Error: {e}"
            return report

        finally:
            try:
                await asyncio.wait_for(PlaywrightEngine.close(), timeout=30)
            except Exception:
                logger.exception("Orchestrator: failed to close Playwright engine")

    async def run_tracked(self) -> List[PriceReport]:
        """Run the full pipeline for all tracked queries from the DB.

        Backward-compatible method.

        Returns:
            List of PriceReports, one per tracked query
        """
        init_db()
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT query FROM tracked_queries ORDER BY id"
            ).fetchall()
            queries = [row['query'] for row in rows]
        finally:
            conn.close()

        if not queries:
            logger.info("Orchestrator: no tracked queries found")
            return []

        logger.info("Orchestrator: running %d tracked queries", len(queries))
        reports = []
        for query in queries:
            report = await self.run_query(query)
            reports.append(report)
        return reports

    async def run_batch(self, queries: List[str]) -> List[PriceReport]:
        """Run the full pipeline for a custom list of queries.

        Backward-compatible method.

        Args:
            queries: List of product search terms

        Returns:
            List of PriceReports
        """
        logger.info("Orchestrator: running batch of %d queries", len(queries))
        reports = []
        for query in queries:
            report = await self.run_query(query)
            reports.append(report)
        return reports

    # ═════════════════════════════════════════════════════════════
    #  Legacy helper methods (unchanged)
    # ═════════════════════════════════════════════════════════════

    def _filter_prices(
        self, all_prices: Dict[str, List[ProductPrice]], query: str
    ) -> Dict[str, List[ProductPrice]]:
        """Clean product names and filter bogus/irrelevant results.

        Defensive pass — search_all already filters, but we run it
        again in case scrapers returned dirty data.
        """
        filtered = {}
        for store_name, products in all_prices.items():
            clean_products = []
            for p in products:
                p.product_name = clean_product_name(p.product_name)
                price = p.sale_price or p.regular_price
                if price and is_bogus_price(price, p.product_name):
                    continue
                if not is_relevant_product(p.product_name, query, min_words=2):
                    continue
                clean_products.append(p)
            if clean_products:
                filtered[store_name] = clean_products
        return filtered

    def _log_scraper_health(self, run_id: str, query: str, report: PriceReport):
        """Log scraper health metrics to the scraper_health table."""
        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO scraper_health
                (run_id, query, stores_checked, stores_responded,
                 response_rate, deal_count, anomaly_count, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                run_id, query,
                report.stores_checked,
                report.stores_responded,
                round(report.stores_responded / max(report.stores_checked, 1), 2),
                len(report.deals_found),
                len(report.anomalies),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log scraper health: %s", e)

    def get_price_history(
        self, product_name: str, store_name: str = None, limit: int = 50
    ) -> List[Dict]:
        """Retrieve price history for a product across all runs."""
        conn = get_db()
        try:
            if store_name:
                rows = conn.execute(
                    """SELECT ph.recorded_at, ph.store_name, ph.regular_price,
                              ph.sale_price, ph.is_on_sale
                       FROM price_history ph
                       WHERE ph.product_name LIKE ? AND ph.store_name = ?
                       ORDER BY ph.recorded_at DESC LIMIT ?""",
                    (f"%{product_name}%", store_name, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ph.recorded_at, ph.store_name, ph.regular_price,
                              ph.sale_price, ph.is_on_sale
                       FROM price_history ph
                       WHERE ph.product_name LIKE ?
                       ORDER BY ph.recorded_at DESC LIMIT ?""",
                    (f"%{product_name}%", limit)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_deal_scores(
        self, product_name: str = None, limit: int = 20
    ) -> List[Dict]:
        """Retrieve deal scores — best historical deals recorded."""
        conn = get_db()
        try:
            if product_name:
                rows = conn.execute(
                    """SELECT * FROM deal_scores
                       WHERE product_name LIKE ?
                       ORDER BY score DESC LIMIT ?""",
                    (f"%{product_name}%", limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM deal_scores
                       ORDER BY score DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_scraper_health_summary(self, days: int = 7) -> List[Dict]:
        """Get scraper health summary for the last N days."""
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT query,
                          COUNT(*) as total_runs,
                          ROUND(AVG(response_rate), 2) as avg_response_rate,
                          ROUND(AVG(deal_count), 1) as avg_deals,
                          MAX(timestamp) as last_run
                   FROM scraper_health
                   WHERE timestamp >= datetime('now', ?)
                   GROUP BY query
                   ORDER BY last_run DESC""",
                (f"-{days} days",)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def summary(self) -> Dict:
        """Quick pipeline status summary for monitoring."""
        conn = get_db()
        try:
            total_runs = conn.execute(
                "SELECT COUNT(DISTINCT run_id) FROM price_results"
            ).fetchone()[0]

            total_tracked = conn.execute(
                "SELECT COUNT(*) FROM tracked_queries"
            ).fetchone()[0]

            recent = conn.execute(
                """SELECT AVG(response_rate) as avg_rate
                   FROM scraper_health
                   ORDER BY timestamp DESC LIMIT 10"""
            ).fetchone()
            avg_rate = recent['avg_rate'] if recent and recent['avg_rate'] is not None else 0

            return {
                "total_runs": total_runs,
                "tracked_products": total_tracked,
                "avg_response_rate_10": round(avg_rate, 2),
                "db_path": str(getattr(
                    __import__('src.storage.sqlite_store', fromlist=['DB_PATH']),
                    'DB_PATH'
                )),
            }
        finally:
            conn.close()


# ════════════════════════════════════════════════════════════════════
#  CLI example
# ════════════════════════════════════════════════════════════════════

async def _example() -> None:
    """Demonstrate the new Orchestrator with several scenarios."""
    import json
    orch = OrchestratorAgent()

    def _print(label: str, result: Dict[str, Any]) -> None:
        print(f"\n{'═' * 60}")
        print(f"  {label}")
        print(f"{'═' * 60}")
        print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])

    # Scenario 1: Health check only (no scan)
    print("\n" + "█" * 60)
    print("  Scenario 1: Check health only")
    print("█" * 60)
    r1 = await orch.execute("check scraper health", constraints={"health_days": 7})
    _print("Result", r1)

    # Scenario 2: Get recent deals (no scan)
    print("\n" + "█" * 60)
    print("  Scenario 2: Get recent deals")
    print("█" * 60)
    r2 = await orch.execute("show me recent deals", constraints={"min_score": 0})
    _print("Result", r2)

    # Scenario 3: Analyze a product (no scan)
    print("\n" + "█" * 60)
    print("  Scenario 3: Analyze בלוגה")
    print("█" * 60)
    r3 = await orch.execute("analyze בלוגה and check recent deals", constraints={"min_score": 50})
    _print("Result", r3)

    # Scenario 4: Full smart flow (health gate + scan + deals)
    # Uncomment to run a live ~15 min scan:
    # print("\n" + "█" * 60)
    # print("  Scenario 4: Full smart scan")
    # print("█" * 60)
    # r4 = await orch.execute("scan tracked products and report strong deals",
    #     constraints={"min_score": 70, "health_threshold": 0.4})
    # _print("Result", r4)

    print("\n✅ Orchestrator smoke test complete.")
    print("   Uncomment Scenario 4 to run a live scan.")


if __name__ == "__main__":
    asyncio.run(_example())