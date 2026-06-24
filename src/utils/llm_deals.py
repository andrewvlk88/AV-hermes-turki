"""LLM reasoning for final deal validation.

Uses DeepSeek V4 Flash via Ollama Cloud to think about whether a candidate
price gap is a real deal or a false positive (wrong volume, wrong product,
accessory, bundle, etc.). Called only for candidate deals — not for every
product scanned.
"""
import os
import json
import urllib.request
import logging
from typing import Optional, Tuple
from src.utils.llm_cache import cache_get, cache_set

logger = logging.getLogger("turk_pi.llm_deals")

_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
if not _API_KEY:
    try:
        with open(os.path.expanduser("~/.hermes/.env")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("OLLAMA_API_KEY="):
                    _API_KEY = line.split("=", 1)[1]
    except Exception:
        pass

_BASE_URL = "https://ollama.com/v1"
_MODEL = "deepseek-v4-flash"
_TIMEOUT = 15
_MAX_TOKENS = 256


def llm_validate_deal(product_name: str, store_price: float, turki_price: float,
                      query: str) -> Tuple[bool, str]:
    """Ask DeepSeek to validate whether a candidate deal is real.

    Returns:
        (is_valid, reason)
        is_valid = True if this is a genuine same-product, same-volume deal
        reason = short Hebrew explanation of the decision

    Cached with diskcache (SQLite-backed, survives restarts).
    Note: Deal prices change, so we cache by product+query, not by price.
    """
    # Disk cache check — keyed by product+query (not price, which changes)
    cache_key = f"deal:{query}:{product_name}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for deal validation: %r", product_name)
        return cached[0], cached[1]

    if not _API_KEY:
        return True, "LLM לא זמין — מאשר לפי הנתונים הקיימים"

    prompt = (
        "You validate alcohol price deals. Decide if the store product is truly "
        "the SAME product and SAME bottle volume as the search query, compared "
        "against the Turki reference price.\n\n"
        f"Search query: {query}\n"
        f"Store product: {product_name}\n"
        f"Store price: ₪{store_price}\n"
        f"Turki reference price: ₪{turki_price}\n\n"
        "Rules:\n"
        "- Different volume (e.g., 200ml vs 1L) = NOT a real deal\n"
        "- Accessories, glasses, sets, gift boxes, miniatures = NOT a real deal\n"
        "- Event bundles ('ערב יין', 'פיקניק', 'אירוח בסטייל') = NOT a real deal\n"
        "- Same product, same volume, lower price = real deal\n\n"
        "Return ONLY valid JSON: {\"valid\": true/false, \"reason\": \"short Hebrew reason\"}\n"
        "No markdown, no explanation, just JSON."
    )

    url = _BASE_URL + "/chat/completions"
    payload = json.dumps({
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
            result = json.loads(content)
            valid = bool(result.get("valid", True))
            reason = str(result.get("reason", ""))[:200]
            cache_set(cache_key, (valid, reason))
            return valid, reason
    except Exception as e:
        logger.debug("LLM deal validation failed: %s", e)
        return True, "שגיאת LLM — מאשר לפי הנתונים הקיימים"
