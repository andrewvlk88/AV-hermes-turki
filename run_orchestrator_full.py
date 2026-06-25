#!/usr/bin/env python3
"""Run full Orchestrator + Strategist flow on 6 tracked products."""
import asyncio
import json
import sys
import os

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

from src.agents.orchestrator import OrchestratorAgent

GOAL = """
מצא דילים תחרותיים ומבצעים עבור 6 המוצרים הבאים מול כל החנויות:
1. בלוגה
2. רוסקי סטנדרט
3. ירדן קברנה סוביניון 2022
4. דלתון אסטייט קברנה
5. ג'וני ווקר בלאק לייבל ליטר
6. גלנמורנג'י 12 שנים אורגינל 700 מ"ל

השווה כל מחיר מול הטורקי (baseline). דיל = 5%+ חיסכון.
הפק המלצות עסקיות לשמוליק (בעל הטורקי).
"""

CONSTRAINTS = {
    "min_score": 5.0,
    "health_threshold": 0.3,
    "tracked_only": False,
    "max_deals": 50,
}

async def main():
    agent = OrchestratorAgent()
    result = await agent.execute(
        goal=GOAL,
        constraints=CONSTRAINTS,
        include_recommendations=True,
    )
    
    print("\n" + "="*60)
    print("ORCHESTRATOR RESULT")
    print("="*60)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    
    # Also save to file
    with open("data/orchestrator_full_run.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print("\n📁 Saved to data/orchestrator_full_run.json")

if __name__ == "__main__":
    asyncio.run(main())