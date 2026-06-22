"""Product name cleaning and price filtering utilities."""
import html
import re
from typing import Optional


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
}

# Minimum price threshold for full-size alcohol bottles
MIN_PRICE_SHEKELS = 25


def clean_product_name(name: str) -> str:
    """Clean a product name by decoding HTML entities and normalizing whitespace.
    
    Characters like &#8217; (apostrophe), &#8221; (closing quote), &quot; (double quote)
    appear raw in product names from various stores. This function decodes them.
    """
    if not name:
        return name
    
    # Decode HTML entities (handles &#8217; &#8221; &quot; &#8220; etc.)
    cleaned = html.unescape(name)
    
    # Also handle any remaining numeric HTML entities
    # e.g., &#x2019; -> '
    cleaned = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), cleaned)
    cleaned = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), cleaned)
    
    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def is_mini_product(name: str) -> bool:
    """Check if a product name indicates a mini/small bottle.
    
    Mini bottles (50ml, 200ml) can legitimately be cheap (under 25₪),
    so we should not filter them out.
    """
    name_lower = name.lower()
    
    # Check for mini keywords
    for keyword in MINI_KEYWORDS:
        if keyword.lower() in name_lower:
            return True
    
    # Check for volume < 250ml in the name
    vol_match = re.search(r'(\d+)\s*(?:מ"?ל|ml)', name, re.IGNORECASE)
    if vol_match:
        volume = int(vol_match.group(1))
        if volume < 250:
            return True
    
    return False


def is_accessory(name: str) -> bool:
    """Check if a product name indicates a non-alcohol accessory (glasses, sets, etc.)."""
    name_lower = name.lower()
    for keyword in ACCESORY_KEYWORDS:
        if keyword.lower() in name_lower:
            return True
    return False


def is_bogus_price(price: float, product_name: str) -> bool:
    """Check if a price is suspiciously low for a full-size alcohol product.
    
    Returns True if the price appears to be bogus (e.g., 10₪ for a 700ml bottle).
    Mini bottles can legitimately be cheap, so they're excluded.
    Accessories (glasses, sets) can also be cheap, so they're excluded.
    """
    if is_accessory(product_name):
        return False
    if price < MIN_PRICE_SHEKELS and not is_mini_product(product_name):
        return True
    return False


def is_relevant_product(product_name: str, query: str, min_words: int = 1) -> bool:
    """Check if a product is relevant to the search query.
    
    Requires at least a dynamic number of significant (non-stop-word) words from the query
    to appear in the product name. For Hebrew queries with geresh (׳) or quotes,
    we normalize both the query and product name.
    
    Also filters out accessories (glasses, sets, openers) when the query
    is clearly about alcohol.
    
    CRITICAL: At least one BRAND word (non-generic, non-descriptor) must match.
    Products like "וודקה נמירוף אורגינל" must NOT match query "גלנמורנג'י 12 אורגינל"
    just because "אורגינל" appears in both.
    """
    if not product_name or not query:
        return False
    
    # Filter out accessories when searching for alcohol
    if is_accessory(product_name):
        return False
    
    # Normalize both strings: remove Hebrew diacritics, normalize quotes, and handle spelling/abbreviations
    def normalize(s: str) -> str:
        s = s.lower()
        # Decode HTML entities if any slipped through
        import html
        s = html.unescape(s)
        # Normalize Hebrew quotes/geresh variants
        s = s.replace("'", "")     # Remove apostrophes
        s = s.replace('"', '')
        s = s.replace('׳', '')     # Hebrew geresh
        s = s.replace('״', '')     # Hebrew gershayim
        s = s.replace('-', ' ')    # Replace hyphens with space
        s = s.replace('.', ' ')    # Replace periods with space for acronyms like ק.ס -> ק ס
        
        # Standardize common variations/typos/abbreviations in Israeli alcohol names
        s = s.replace('סובניון', 'סוביניון')
        s = s.replace('סביניון', 'סוביניון')
        
        # Red Wine variations: Cabernet Sauvignon (ק.ס / ק"ס / קס -> קברנה סוביניון)
        s = re.sub(r'\bק\s*ס\b|\bקס\b|\bקברנה\s+סוביניון\b', ' קברנה סוביניון ', s)
        # Cabernet Franc (ק.פ / ק"פ / קפ -> קברנה פרנק)
        s = re.sub(r'\bק\s*פ\b|\bקפ\b|\bקברנה\s+פרנק\b', ' קברנה פרנק ', s)
        # Sauvignon Blanc (ס.ב / ס"ב / סב -> סוביניון בלאן)
        s = re.sub(r'\bס\s*ב\b|\bסב\b|\bסוביניון\s+בלאן\b', ' סוביניון בלאן ', s)
        # Gewurztraminer (גוורץ / גווירץ / גוורצטרמינר -> גוורצטרמינר)
        s = re.sub(r'\bגוו?ירצ?טרמינר\b|\bגוו?ירץ\b', ' גוורצטרמינר ', s)
        
        # Prefixes to strip (common descriptors that cause false negatives)
        prefixes_to_strip = [
            r'^יין\s+', r'^בקבוק\s+של\s+', r'^בקבוק\s+', r'^מארז\s+', 
            r'^ויסקי\s+', r'^וויסקי\s+', r'^וודקה\s+', r'^בירה\s+'
        ]
        for pref in prefixes_to_strip:
            s = re.sub(pref, '', s)
            
        # Volume abbreviations
        s = s.replace('ליטר', 'ל')
        s = re.sub(r'\bml\b|\bמ"?ל\b', ' מל ', s)
        
        # Normalize whitespace
        s = re.sub(r'\s+', ' ', s).strip()
        return s
    
    norm_name = normalize(product_name)
    norm_query = normalize(query)
    
    # Direct substring match always passes
    if norm_query in norm_name or norm_name in norm_query:
        return True
    
    # Extract significant words from query (excluding stop words and very short words)
    query_words = [w for w in norm_query.split() if len(w) > 1 and w not in STOP_WORDS]
    
    if not query_words:
        # If query has no significant words, fall back to any match
        return True
    
    # Calculate a dynamic min_words threshold to prevent false positives for long queries
    # For example, searching "ירדן קברנה סוביניון 2022" should require at least 3 match words,
    # so "ירדן קברנה פרנק 2022" (2 matches) is filtered out.
    calc_min = min_words
    if len(query_words) >= 4:
        calc_min = max(min_words, 3)
    elif len(query_words) == 3:
        calc_min = max(min_words, 2)
    
    # Check how many query words appear in the product name
    matches = sum(1 for w in query_words if w in norm_name)
    
    # CRITICAL: At least one match must be a BRAND word, not a generic descriptor.
    # Brand words = query words that are NOT in STOP_WORDS and have len > 2.
    # This prevents "וודקה נמירוף אורגינל" from matching "גלנמורנג'י 12 אורגינל"
    # just because "אורגינל" (now a stop word) appears in both.
    brand_words = [w for w in query_words if len(w) > 2 and w not in STOP_WORDS]
    brand_matches = sum(1 for w in brand_words if w in norm_name)
    
    if brand_matches == 0 and len(brand_words) > 0:
        return False
    
    return matches >= min(calc_min, len(query_words))


def extract_volume_ml(name: str) -> Optional[float]:
    """Extract volume in ml from a product name, handling Hebrew and English formats.
    
    Handles standalone 'ליטר' (implies 1000ml) and 'חצי ליטר' (implies 500ml).
    """
    if not name:
        return None
    
    patterns = [
        (r'(\d+\.?\d*)\s*ליטר', 1000),
        (r'(\d+\.?\d*)\s*מ"?ל', 1),
        (r'(\d+\.?\d*)\s*ml', 1),
        (r'(\d+\.?\d*)\s*ML', 1),
        (r'(\d+\.?\d*)\s*L\b', 1000),
        # Handle the format "700 מ\"ל"
        (r'(\d+\.?\d*)\s*מ["\']ל', 1),
        # Handle just number followed by מ (implied מ״ל)
        (r'(\d{3,4})\s*מ\b', 1),
    ]
    
    for pattern, multiplier in patterns:
        m = re.search(pattern, name, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1)) * multiplier
            except ValueError:
                pass
    
    # "חצי ליטר" — implies 500ml (check BEFORE standalone ליטר)
    if re.search(r'חצי\s*ליטר', name):
        return 500.0
    
    # Standalone "ליטר" without a number prefix — implies 1000ml
    # e.g., "רוסקי סטנדרט פלטינום ליטר" or "בלוגה נובל ליטר"
    if re.search(r'\bליטר\b', name):
        return 1000.0
    
    # ── LLM Fallback ──
    # If regex failed to extract volume, try Gemini 2.5 Flash
    # This handles edge cases like "מיני", "פוקס", "מארז", etc.
    try:
        from src.utils.llm_volume import llm_extract_volume
        vol = llm_extract_volume(name)
        if vol is not None and vol > 0:
            return vol
    except Exception:
        pass
    
    return None