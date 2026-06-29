"""LLM-based product matching fallback.

When regex-based normalize_for_matching + find_turki_match fail to find
a match between a store product and a Turki product, this module asks
the LLM to decide if they're the same product.

This is especially useful for wines where the Turki API returns long names
like "יין אדום יקב רמת הגולן ירדן קברנה סוביניון 2022" but stores return
short names like "ירדן קברנה סוביניון 2022" — regex normalization can't
bridge that gap, but an LLM can.

Cached with diskcache (SQLite-backed, survives restarts).
"""
import os
import json
import urllib.request
import logging
from typing import Optional, Dict, List
from src.utils.llm_cache import cache_get, cache_set

logger = logging.getLogger("turk_pi.llm_match")

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
_MAX_TOKENS = 512


def llm_match_product(
    store_product_name: str,
    store_volume_ml: Optional[float],
    turki_products: List[Dict],
) -> Optional[Dict]:
    """Ask LLM to match a store product to one of the Turki products.

    Args:
        store_product_name: Product name from the store (e.g. "ירדן קברנה סוביניון 2022")
        store_volume_ml: Volume in ml from the store (or None)
        turki_products: List of dicts with keys: name, price, url, volume_ml

    Returns:
        The matched turki product dict, or None if no match found.
    """
    if not _API_KEY or not turki_products:
        return None

    # Build cache key
    vol_key = f"{store_volume_ml:.0f}" if store_volume_ml else "u"
    turki_names = "|".join(p.get("name", "") for p in turki_products[:10])
    cache_key = f"match:{store_product_name}:{vol_key}:{turki_names[:200]}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for LLM match: %r → %r", store_product_name, cached)
        return cached

    # Build the product list for the prompt
    product_lines = []
    for i, p in enumerate(turki_products[:10]):
        vol = f" ({p.get('volume_ml', 0):.0f}ml)" if p.get("volume_ml") else ""
        product_lines.append(f"{i+1}. {p['name']}{vol} — ₪{p['price']}")

    vol_note = f"Store volume: {store_volume_ml:.0f}ml\n" if store_volume_ml else ""

    prompt = (
        "You match alcohol products between Israeli stores. "
        "Given a store product and a list of Turki (הטורקי) reference products, "
        "decide which Turki product (if any) is the SAME product.\n\n"
        f"Store product: {store_product_name}\n"
        f"{vol_note}\n"
        "Turki products:\n" + "\n".join(product_lines) + "\n\n"
        "Rules:\n"
        "- Same brand + same type + same vintage year = MATCH (even if one has extra words like 'יין אדום' or 'יקב רמת הגולן')\n"
        "- Different vintage year (2022 vs 2021) = NO MATCH\n"
        "- Different volume (±50ml is OK, more than that = NO MATCH)\n"
        "- Different brand entirely = NO MATCH\n"
        "- Accessories, glasses, gift sets = NO MATCH\n\n"
        "Return ONLY valid JSON: {\"match\": <1-based index or 0 for no match>, \"confidence\": <0-100>, \"reason\": \"short Hebrew reason\"}\n"
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

            match_idx = int(result.get("match", 0))
            confidence = int(result.get("confidence", 0))
            reason = str(result.get("reason", ""))[:200]

            if match_idx > 0 and match_idx <= len(turki_products) and confidence >= 70:
                matched = turki_products[match_idx - 1]
                logger.info(
                    "LLM match: '%s' → '%s' (confidence=%d, reason=%s)",
                    store_product_name, matched["name"], confidence, reason,
                )
                cache_set(cache_key, matched)
                return matched
            else:
                logger.info(
                    "LLM no match: '%s' (match_idx=%d, confidence=%d, reason=%s)",
                    store_product_name, match_idx, confidence, reason,
                )
                cache_set(cache_key, None)
                return None

    except Exception as e:
        logger.debug("LLM product match failed: %s", e)
        return None