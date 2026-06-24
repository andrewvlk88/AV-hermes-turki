"""Persistent disk-based cache for LLM API calls.

Uses diskcache (SQLite-backed) to survive process restarts.
Shared across all LLM utility modules (llm_volume, llm_deals).

Cache location: data/llm_cache/
Default TTL: 7 days (product volumes don't change often)
"""
import os
import logging
from pathlib import Path
from typing import Optional

try:
    import diskcache
except ImportError:
    diskcache = None

logger = logging.getLogger("turk_pi.llm_cache")

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "llm_cache"
_CACHE: Optional["diskcache.Cache"] = None
_DEFAULT_TTL = 7 * 24 * 3600  # 7 days in seconds


def _get_cache() -> Optional["diskcache.Cache"]:
    """Get or create the singleton diskcache instance."""
    global _CACHE
    if diskcache is None:
        logger.debug("diskcache not installed — cache disabled")
        return None
    if _CACHE is None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE = diskcache.Cache(str(_CACHE_DIR), size_limit=50 * 1024 * 1024)  # 50MB
            logger.debug("LLM disk cache initialized at %s", _CACHE_DIR)
        except Exception as e:
            logger.warning("Failed to init disk cache: %s", e)
            return None
    return _CACHE


def cache_get(key: str) -> Optional[object]:
    """Retrieve a value from cache, or None if not found/expired."""
    cache = _get_cache()
    if cache is None:
        return None
    try:
        return cache.get(key, default=None)
    except Exception as e:
        logger.debug("Cache get failed for key %r: %s", key, e)
        return None


def cache_set(key: str, value: object, ttl: int = _DEFAULT_TTL) -> None:
    """Store a value in cache with TTL (default 7 days)."""
    cache = _get_cache()
    if cache is None:
        return
    try:
        cache.set(key, value, expire=ttl)
    except Exception as e:
        logger.debug("Cache set failed for key %r: %s", key, e)


def cache_stats() -> dict:
    """Return cache statistics for monitoring."""
    cache = _get_cache()
    if cache is None:
        return {"enabled": False}
    try:
        return {
            "enabled": True,
            "size": len(cache),
            "volume_mb": round(cache.volume() / 1024 / 1024, 2),
            "dir": str(_CACHE_DIR),
        }
    except Exception:
        return {"enabled": True, "error": "stats unavailable"}


def cache_clear() -> int:
    """Clear all cached entries. Returns count of removed entries."""
    cache = _get_cache()
    if cache is None:
        return 0
    count = len(cache)
    cache.clear()
    return count