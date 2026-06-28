"""Product name cleaning and price filtering utilities."""
import html
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Hebrew stop words - words that shouldn't count for relevance matching
STOP_WORDS = {
    "של", "עם", "בלי", "לא", "גם", "או", "על", "אל", "מה", "זה", "הוא", "היא",
    "את", "שלא", "רק", "עוד", "כל", "מיני", "ו", "ה", "ב", "ל", "מ", "כ",
    "the", "and", "or", "with", "for", "in", "on", "at", "a", "an",
    # Generic descriptors that appear across many products — must NOT count as brand matches
    "אורגינל", "original", "שנים", "שנה", "years", "ישראל", "israel", "כשר", "kosher",
    "טנסי", "tennessee", "קלאסי", "classic", "פרימיום", "premium",
    "בקבוק", "bottle", "ליטר", "liter", "מל", "ml", "ל", "בלנדד", "blended",
    # Numbers and volume units — these appear everywhere and must NOT count as brand matches
    "12", "15", "18", "10", "7", "8", "700", "750", "500", "1", "2", "3",
    "1l", "1l", "70", "50", "100", "200", "175", "350",
}

# Keywords indicating mini/small bottles that can legitimately be cheap
MINI_KEYWORDS = {
    "מיני", "מיניאטורה", "ניפוח", "טעימה", "סמפל",
    "50 מ\"ל", "50 מל", "50ml", "50 ml",
    "100 מ\"ל", "100 מל", "100ml", "100 ml",
    "200 מ\"ל", "200 מל", "200ml", "200 ml",
    "50 מ\"ל", "מיני", "mini", "miniature", "sample",
}

# Keywords indicating non-alcohol accessories / irrelevant items that should be filtered out
ACCESORY_KEYWORDS = {
    "כוסות", "כוס", "שוט", "סט ", "מארז כוס", "בקבוקון", "מדיח",
    "כוסית", "מתנה", "מזיגה", "פקק", "מפתח", "מגן", "אחסון", "קופסא", "מארז",
    "glasses", "glass", "shot", "set ", "opener", "gift",
    # Non-alcohol items that pollute search results
    "מארז מתנה", "קרטון", "מהודר", "סירופ", "סאקה", "מיקס", "מונין",
    "סאוור", "ביטר", "מסחרר", "תחליף", "נטול", "אלכוהול",
    # Bundle / event / promotion noise
    "אירוח בסטייל", "פותחים שולחן", "ערב יין וגבינות", "פיקניק מושקע",
    "מיניאטורה", "מיניאטורות", "מארז אירוח", "מארז יין", "סט יין",
}

# Minimum price threshold for full-size alcohol bottles
MIN_PRICE_SHEKELS = 25


def clean_product_name(name: str) -> str:
    """Clean a product name by decoding HTML entities and normalizing whitespace."""
    if not name:
        return name

    cleaned = html.unescape(name)
    cleaned = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), cleaned)
    cleaned = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def is_mini_product(name: str) -> bool:
    """Check if a product name indicates a mini/small bottle."""
    name_lower = name.lower()

    for keyword in MINI_KEYWORDS:
        if keyword.lower() in name_lower:
            return True

    vol_match = re.search(r'(\d+)\s*(?:מ"?ל|ml)', name, re.IGNORECASE)
    if vol_match:
        volume = int(vol_match.group(1))
        if volume < 250:
            return True

    return False


def is_accessory(name: str) -> bool:
    """Check if a product name indicates a non-alcohol accessory (glasses, sets, etc.)."""
    name_lower = name.lower()
    
    # Direct keyword match
    for keyword in ACCESORY_KEYWORDS:
        if keyword.lower() in name_lower:
            return True
    
    # Aggressive: any word starting with "מארז" (bundle) — catches attached words
    if re.search(r'\bמארז', name_lower):
        return True
    
    # Any word starting with "מיניאטור" (miniature)
    if re.search(r'\bמיניאטור', name_lower):
        return True
    
    # Gift box with food/glass extras
    if re.search(r'\bמתנה\b', name_lower) and re.search(r'\b(כוס|כוסות|פרלין|פרלינים|פיצוח|פיצוחים|טוניק|שוקולד|קרח)\b', name_lower):
        return True
    
    return False


# Compile a regex for is_accessory internal use
_ACCESSORY_RE = re.compile(
    r'\b(מארז|מיניאטור|כוסות?|מתנה|שוט|פקק|מפתח|מגן|אחסון|קופסא|סירופ|סאקה|מיקס|מונין|'
    r'glasses|glass|shot|opener|gift|set|box|bundle|miniature)',
    re.IGNORECASE
)


def is_bogus_price(price: float, product_name: str) -> bool:
    """Check if a price is suspiciously low for a full-size alcohol product."""
    if is_accessory(product_name):
        return False
    
    # Hard floors by brand
    HARD_FLOORS = {
        "ג'וני ווקר": 80.0,
        "בלוגה": 100.0,
        "רוסקי סטנדרט": 50.0,
        "דלתון": 35.0,
        "דלתון פמילי קולקשן": 50.0,
        "ירדן": 50.0,
        "גלנמורנג'י": 120.0
    }
    for brand, floor in HARD_FLOORS.items():
        if brand in product_name:
            if price < floor: return True

    if price < MIN_PRICE_SHEKELS and not is_mini_product(product_name):
        return True
    return False


def is_relevant_product(product_name: str, query: str, min_words: int = 1) -> bool:
    """Check if a product is relevant to the search query.

    Uses a multi-layer matching strategy:
    1. **Exact number validation** — if the query contains a specific year
       (e.g. "2022") or age/volume number (e.g. "12", "700"), the product
       name MUST contain that exact number. A 2021 wine is NOT a match for
       a 2022 query.
    2. **Fuzzy string matching** — calculates a similarity score between
       the normalized product name and the query using difflib.
       Accepts only if similarity ≥ 70%.
    3. **Word-level matching** — falls back to the original word-count
       algorithm if fuzzy matching is inconclusive.

    Args:
        product_name: Scraped product title from the store.
        query: Original full search query (e.g. "יין אדום גבעות מרלו 2022").
        min_words: Minimum brand-word matches required (default 1).
    """
    if not product_name or not query:
        return False

    if is_accessory(product_name):
        return False

    def normalize(s: str) -> str:
        s = s.lower()
        s = html.unescape(s)
        s = s.replace("'", "").replace('"', '').replace('׳', '').replace('״', '')
        s = s.replace('-', ' ').replace('.', ' ')

        s = s.replace('סובניון', 'סוביניון')
        s = s.replace('סביניון', 'סוביניון')

        s = re.sub(r'\bק\s*ס\b|\bקס\b|\bקברנה\s+סוביניון\b', ' קברנה סוביניון ', s)
        s = re.sub(r'\bק\s*פ\b|\bקפ\b|\bקברנה\s+פרנק\b', ' קברנה פרנק ', s)
        s = re.sub(r'\bס\s*ב\b|\bסב\b|\bסוביניון\s+בלאן\b', ' סוביניון בלאן ', s)
        s = re.sub(r'\bגוו?ירצ?טרמינר\b|\bגוו?ירץ\b', ' גוורצטרמינר ', s)

        prefixes_to_strip = [
            r'^יין\s+', r'^בקבוק\s+של\s+', r'^בקבוק\s+', r'^מארז\s+',
            r'^ויסקי\s+', r'^וויסקי\s+', r'^וודקה\s+', r'^בירה\s+'
        ]
        for pref in prefixes_to_strip:
            s = re.sub(pref, '', s)

        s = s.replace('ליטר', 'ל')
        s = re.sub(r'\bml\b|\bמ"?ל\b', ' מל ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    norm_name = normalize(product_name)
    norm_query = normalize(query)

    # ── Layer 1: Critical number validation ────────────────────────────
    # Extract all standalone numbers from the query (years, ages, volumes).
    # If the query has "2022", and the product also mentions a year (e.g. "2021"),
    # the years MUST match. But if the product simply doesn't mention a year,
    # we allow it through (the store might just not include the vintage in the title).
    query_numbers = set(re.findall(r'\b(\d{2,4})\b', norm_query))
    if query_numbers:
        name_numbers = set(re.findall(r'\b(\d{2,4})\b', norm_name))
        # Check for CONFLICTING numbers: a number in the query that has a
        # different value in the product name (e.g. query=2022, product=2021).
        # If the product has NO numbers at all, we let it through.
        if name_numbers:
            # Both have numbers — check for conflicts
            # A number in the query is "critical" if it looks like a year (4 digits)
            # or an age statement (2 digits like "12", "18").
            for qn in query_numbers:
                if qn not in name_numbers:
                    # Is this number a year/age that should match exactly?
                    if len(qn) == 4 or (len(qn) == 2 and int(qn) >= 10):
                        logger.debug(
                            "is_relevant_product: REJECTED — query has '%s' but product '%s' has %s",
                            qn, product_name[:50], name_numbers,
                        )
                        return False

    # ── Layer 2: Fuzzy string matching ─────────────────────────────────
    # Use difflib.SequenceMatcher for a similarity ratio between the
    # normalized product name and the normalized query.
    from difflib import SequenceMatcher
    similarity = SequenceMatcher(None, norm_query, norm_name).ratio()

    # Also check token-set ratio: how many query tokens appear in the name
    query_tokens = set(norm_query.split())
    name_tokens = set(norm_name.split())
    if query_tokens:
        token_overlap = len(query_tokens & name_tokens) / len(query_tokens)
    else:
        token_overlap = 0

    # Accept if either similarity or token overlap is high enough
    if similarity >= 0.65 or token_overlap >= 0.65:
        logger.debug("is_relevant_product: ACCEPTED via fuzzy (sim=%.2f, overlap=%.2f) for %s", similarity, token_overlap, product_name[:60])
        return True

    # ── Layer 3: Word-level matching (original algorithm) ──────────────
    if norm_query in norm_name or norm_name in norm_query:
        return True

    query_words = [w for w in norm_query.split() if len(w) > 1 and w not in STOP_WORDS]

    if not query_words:
        return True

    calc_min = min_words
    if len(query_words) >= 4:
        calc_min = max(min_words, 3)
    elif len(query_words) == 3:
        calc_min = max(min_words, 2)

    matches = sum(1 for w in query_words if w in norm_name)

    brand_words = [w for w in query_words if len(w) > 2 and w not in STOP_WORDS]
    brand_matches = sum(1 for w in brand_words if w in norm_name)

    if brand_matches == 0 and len(brand_words) > 0:
        return False

    return matches >= min(calc_min, len(query_words))


def extract_volume_ml(name: str) -> Optional[float]:
    """Extract volume in ml from a product name, handling Hebrew and English formats."""
    if not name:
        return None

    patterns = [
        (r'(\d+\.?\d*)\s*ליטר', 1000),
        (r'(\d+\.?\d*)\s*מ"?ל', 1),
        (r'(\d+\.?\d*)\s*ml', 1),
        (r'(\d+\.?\d*)\s*ML', 1),
        (r'(\d+\.?\d*)\s*L\b', 1000),
        (r'(\d+\.?\d*)\s*מ["\']ל', 1),
        (r'(\d{3,4})\s*מ\b', 1),
    ]

    for pattern, multiplier in patterns:
        m = re.search(pattern, name, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1)) * multiplier
            except ValueError:
                pass

    if re.search(r'חצי\s*ליטר', name):
        return 500.0

    if re.search(r'\bליטר\b', name):
        return 1000.0

    try:
        from src.utils.llm_volume import llm_extract_volume
        vol = llm_extract_volume(name)
        if vol is not None and vol > 0:
            return vol
    except Exception:
        pass

    return None


def is_relevant_volume(volume_ml: Optional[float]) -> bool:
    """Return True only if the volume is not in the filtered-out sizes.

    200ml and 500ml bottles are intentionally excluded from the Turki
    price-intelligence scanner because they are not relevant for comparison.
    """
    if volume_ml is None:
        return True
    return volume_ml not in {200.0, 500.0}


def is_relevant_volume_by_name(name: str) -> bool:
    """Convenience wrapper: extract volume from name and filter 200ml/500ml."""
    return is_relevant_volume(extract_volume_ml(name))
