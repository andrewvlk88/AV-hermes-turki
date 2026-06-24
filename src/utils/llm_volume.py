"""LLM-powered volume extraction fallback.

Uses DeepSeek V4 Flash via Ollama Cloud ($20 flat) to extract volume in ml
from product names when the regex-based extract_volume_ml() in filters.py
returns None.

Design:
  - Only called as a fallback (regex first, LLM second)
  - Caches results to avoid repeated calls for same product name
  - Returns None if LLM fails or is unavailable
  - Uses Ollama Cloud OpenAI-compatible API (same as Hermes main model)
"""
import os
import json
import urllib.request
import logging
from typing import Optional
from src.utils.llm_cache import cache_get, cache_set

logger = logging.getLogger("turk_pi.llm_volume")

_OLLAMA_ENV_VAR = "OLLAMA_" + "API_" + "KEY"
_ENV_PREFIX = "OLLAMA_" + "API_" + "KEY="


def _load_api_key():
    """Load Ollama API key from environment or .hermes/.env file."""
    key = os.environ.get(_OLLAMA_ENV_VAR, "")
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(_ENV_PREFIX):
                    return line.split("=", 1)[1]
    return ""


_API_KEY = _load_api_key()
_BASE_URL = "https://ollama.com/v1"
_MODEL = "deepseek-v4-flash"
_TIMEOUT = 15  # seconds per API call
_MAX_TOKENS = 256  # enough for thinking + answer


def llm_extract_volume(product_name):
    """Ask DeepSeek V4 Flash to extract volume in ml from a product name.

    Returns:
        float: Volume in ml (e.g., 1000.0, 700.0, 50.0)
        None: If LLM fails, key missing, or no volume found

    Cached with diskcache (SQLite-backed, survives restarts).
    """
    if not product_name or len(product_name) < 3:
        return None

    # Disk cache check
    cache_key = f"vol:{product_name}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for volume: %r -> %s", product_name, cached)
        return cached if cached > 0 else None

    if not _API_KEY:
        logger.debug("No Ollama API key, skipping LLM volume extraction")
        return None

    if not product_name or len(product_name) < 3:
        return None

    prompt = (
        "Extract the bottle volume in milliliters from this product name. "
        "Return ONLY a number (e.g., 700, 1000, 50). Return 0 if unknown. "
        "Note: \u05dc\u05d9\u05d8\u05e8 = 1000ml, "
        "\u05d7\u05e6\u05d9 \u05dc\u05d9\u05d8\u05e8 = 500ml, "
        "\u05de\u05d9\u05e0\u05d9/mini = 50ml.\n"
        "Product: " + product_name
    )

    url = _BASE_URL + "/chat/completions"
    payload = json.dumps({
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": "Bearer " + _API_KEY,
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            # Handle cases where model adds extra text
            # Extract just the number
            import re
            num_match = re.search(r'\d+', text)
            if not num_match:
                cache_set(cache_key, 0)  # Cache "no volume found" to avoid re-calling
                return None
            vol = float(num_match.group())
            if vol <= 0:
                cache_set(cache_key, 0)
                return None
            logger.debug("LLM volume for %r: %s ml", product_name, vol)
            cache_set(cache_key, vol)
            return vol
    except Exception as e:
        logger.debug("LLM volume extraction failed for %r: %s", product_name, e)
        return None