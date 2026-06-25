"""Smart query optimization for store search engines.

Many products in our domain have long names (e.g. "יין אדום גבעות מרלו 2022").
WooCommerce and Magento stores search by the first 1-2 words, which often returns
irrelevant results when the query starts with generic words like "יין אדום".

This module strips domain-specific stop-words and returns the core 2-3 meaningful
keywords (usually Brand + Type/Variety), dramatically improving search hit rates.

Examples:
    "יין אדום גבעות מרלו 2022"   → "גבעות מרלו"
    "וודקה בלוגה ליטר"          → "בלוגה"
    "ג'וני ווקר בלאק לייבל ליטר" → "ג'וני ווקר בלאק"
    "דלתון אסטייט קברנה 2022"    → "דלתון אסטייט קברנה"
"""
import functools
import re


# Domain-specific stop-words that add noise to search queries.
# These are generic descriptors, category labels, volume/age units, and
# common prefixes that WooCommerce/Magento can't use for meaningful matching.
QUERY_STOP_WORDS = {
    # Category labels
    "יין", "אדום", "לבן", "רוזה", "rosé", "red", "white",
    "וודקה", "וויסקי", "ויסקי", "וויסקי", "whisky", "whiskey", "vodka",
    "ג'ין", "ג´ין", "gin", "רום", "rum", "טקילה", "tequila",
    "ערק", "arak", "ליקר", "liqueur", "בירה", "beer",
    "שמפנייה", "champagne", "ספרקלינג", "sparkling",
    # Volume / packaging
    "מ\"ל", "מ״ל", "ml", "ליטר", "liter", "litre", "בקבוק", "bottle",
    "מארז", "יחידות", "קופסא", "בקבוקון",
    # Generic descriptors
    "כשר", "kosher", "ישראל", "israel", "טבעי", "organic",
    "אורגינל", "original", "קלאסי", "classic", "פרימיום", "premium",
    "רזרב", "reserve", "מיוחד", "special",
}


@functools.lru_cache(maxsize=256)
def optimize_search_query(full_name: str) -> str:
    """Optimize a full product name into a short search query.

    Strips domain-specific stop-words and returns the core 2-3 meaningful
    keywords. Results are cached via ``lru_cache`` for performance.

    Args:
        full_name: The full product name (e.g. "יין אדום גבעות מרלו 2022").

    Returns:
        Optimized short query (e.g. "גבעות מרלו").
        If the full name is already short (≤2 meaningful words), returns it as-is.
        Never returns an empty string — falls back to the original if all words
        are stop-words.
    """
    if not full_name:
        return full_name

    # Split into words
    words = full_name.strip().split()
    if not words:
        return full_name

    # Filter out stop-words (case-insensitive comparison)
    meaningful = []
    for w in words:
        w_clean = w.strip('.,;:\'"()[]{}')
        if not w_clean:
            continue
        if w_clean.lower() in QUERY_STOP_WORDS:
            continue
        # Also strip pure numbers (years like 2022, ages like 12, volumes like 700)
        # from the SEARCH query — they cause strict matching failures on stores
        # that don't carry the exact same vintage/year.
        if re.match(r'^\d+$', w_clean):
            continue
        meaningful.append(w_clean)

    # If we stripped everything, fall back to the original (better than empty)
    if not meaningful:
        return full_name.strip()

    # Cap at 3 meaningful words — enough for Brand + Type/Variety
    result = " ".join(meaningful[:3])
    return result