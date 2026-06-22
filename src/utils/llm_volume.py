"""LLM-powered volume extraction fallback.

Uses Gemini 2.5 Flash (free tier) to extract volume in ml from product names
when the regex-based extract_volume_ml() in filters.py returns None.

Design:
  - Only called as a fallback (regex first, LLM second)
  - Caches results to avoid repeated calls for same product name
  - Returns None if LLM fails or is unavailable
"""
import os
import json
import urllib.request
import logging
from typing import Optional
from functools import lru_cache

logger = logging.getLogger("turk_pi.llm_volume")

_GEMINI_ENV_VAR = "GEMINI_" + "API_" + "KEY"
_GOOGLE_ENV_VAR = "GOOGLE_" + "API_" + "KEY"
_ENV_PREFIX = "GEMINI_" + "API_" + "KEY="


def _load_api_key():
    """Load Gemini API key from environment or .hermes/.env file."""
    key = os.environ.get(_GEMINI_ENV_VAR) or os.environ.get(_GOOGLE_ENV_VAR, "")
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
_MODEL = "gemini-2.5-flash"
_TIMEOUT = 15  # seconds per API call
_MAX_TOKENS = 256  # must be >= 100 for gemini 2.5 thinking tokens


@lru_cache(maxsize=2000)
def llm_extract_volume(product_name):
    """Ask Gemini to extract volume in ml from a product name.

    Returns:
        float: Volume in ml (e.g., 1000.0, 700.0, 50.0)
        None: If LLM fails, key missing, or no volume found

    Cached with lru_cache to avoid repeated API calls for same product.
    """
    if not _API_KEY:
        logger.debug("No API key, skipping LLM volume extraction")
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

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + _MODEL
        + ":generateContent?key="
        + _API_KEY
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": _MAX_TOKENS},
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return None
            text = parts[0].get("text", "").strip()
            vol = float(text)
            if vol <= 0:
                return None
            logger.debug("LLM volume for %r: %s ml", product_name, vol)
            return vol
    except Exception as e:
        logger.debug("LLM volume extraction failed for %r: %s", product_name, e)
        return None