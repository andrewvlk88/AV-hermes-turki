"""LLM Fallback price extraction — safety net for when standard scrapers fail.

Only called when a store's standard scraping method (API, HTML, Playwright)
returns None, 0, or fails to find a valid numeric price.

Uses GLM-5.2 via Ollama Cloud to extract price from cleaned HTML.
Cleans HTML (strips CSS/JS/tags) before sending to LLM to save tokens.
"""
import os
import re
import json
import urllib.request
import logging
from typing import Optional, List
from bs4 import BeautifulSoup

logger = logging.getLogger("turk_pi.llm_price_fallback")

_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
if not _API_KEY:
    try:
        with open(os.path.expanduser("~/.hermes/.env")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("OLLAMA_API_KEY="):
                    _API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

_BASE_URL = "https://ollama.com/v1"
_MODEL = "glm-5.2"
_TIMEOUT = 30
_MAX_TOKENS = 256


def _clean_html(raw_html: str, max_chars: int = 8000) -> str:
    """Strip CSS/JS/scripts/styles from HTML, keep only text + price-relevant elements.
    
    Returns compact text suitable for LLM consumption.
    """
    if not raw_html:
        return ""
    
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # Remove non-content tags entirely
    for tag in soup.find_all(["script", "style", "noscript", "svg", "link", "meta", "head"]):
        tag.decompose()
    
    # Remove CSS/class attributes (saves tokens)
    for tag in soup.find_all():
        tag.attrs = {}
    
    # Extract text, focusing on product/price areas
    text = soup.get_text(separator="\n", strip=True)
    
    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    
    # Truncate to save tokens — LLM only needs price-relevant portions
    if len(text) > max_chars:
        # Try to find price-relevant section
        price_idx = text.find("₪")
        if price_idx > 0:
            start = max(0, price_idx - max_chars // 2)
            end = min(len(text), start + max_chars)
            text = text[start:end]
        else:
            text = text[:max_chars]
    
    return text


def llm_extract_price(product_name: str, raw_html: str, store_name: str = "") -> Optional[float]:
    """Ask GLM-5.2 to extract the price for a product from cleaned HTML.
    
    Only called as a fallback when standard scrapers failed to find a valid price.
    
    Args:
        product_name: The product name to find in the HTML
        raw_html: Raw HTML source from the store's search/product page
        store_name: Store name for logging
    
    Returns:
        float: Price in shekels (e.g., 199.99)
        None: If LLM fails, no price found, or API unavailable
    """
    if not _API_KEY:
        logger.debug("LLM price fallback skipped: no API key")
        return None
    
    if not raw_html or len(raw_html) < 50:
        return None
    
    # Clean HTML to save tokens
    clean_text = _clean_html(raw_html)
    if not clean_text or len(clean_text) < 20:
        logger.debug("LLM price fallback: cleaned HTML too short for %s", product_name)
        return None
    
    prompt = (
        f"Extract the price in Israeli shekels (₪) for this product: {product_name}\n"
        f"From this store page content (from {store_name}):\n\n"
        f"{clean_text}\n\n"
        "Return ONLY the raw numeric price value (e.g., 199.99 or 349 or 59.90). "
        "No currency symbol, no text, no markdown, no explanation. "
        "If the product is not found or no price exists, return 0."
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
        headers={
            "Authorization": f"Bearer {_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = content.strip()
            
            # Strip markdown/markers if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            # Extract just the number — LLM should return only a number but be safe
            num_match = re.search(r'(\d+[\d,]*\.?\d*)', content)
            if not num_match:
                logger.debug("LLM price fallback: no number in response for %s: %r", product_name, content)
                return None
            
            price = float(num_match.group().replace(",", ""))
            
            if price <= 0:
                logger.debug("LLM price fallback: price is 0 for %s (not found)", product_name)
                return None
            
            logger.info("LLM price fallback: extracted %s₪ for %s from %s", price, product_name, store_name)
            return price
    
    except Exception as e:
        logger.debug("LLM price fallback failed for %s: %s", product_name, e)
        return None