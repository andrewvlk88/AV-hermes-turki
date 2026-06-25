# AV Hermes Turki — Turkí Price Intelligence (v2.12.0) 🦃📊

מנוע פייתון מתקדם להשוואת מחירי אלכוהול בזמן אמת ב-20 חנויות מובילות בישראל, המשתמש ב-**curl_cffi (Chrome TLS Impersonation)** כשכבת ה-fetch הראשית, עם fallback ל-**CloakBrowser (Stealth Chromium)** לאתרים כבדים, שמירה מיידית ב-**SQLite**, ומערכת **Adaptive Scraping Frequency** לחיסכון במשאבים ומניעת bans.

המערכת פותחה במיוחד עבור **הטורקי** כחנות Reference לצורך זיהוי פערי מחירים, מבצעים אגרסיביים ויצירת מודיעין תחרותי חצי-אוטומטי.

**הלוגיקה הבסיסית:** הטורקי רץ ראשון (API מהיר) → מתקבל מחיר baseline → שאר 19 החנויות נסרקות ומושוות מולו → דילים = חנות שזולה מהטורקי ב-5%+. כל ריצה = צילום רענן, אין caching, אין זיכרון מריצה קודמת.

> **Repo נוכחי:** `https://github.com/andrewvlk88/AV-hermes-turki`

---

## 🚀 תכונות מרכזיות

- **curl_cffi Chrome TLS Impersonation (v2.12+)**: שכבת ה-HTTP הראשית משתמשת ב-`curl_cffi.requests.AsyncSession(impersonate='chrome')` — שולחת TLS fingerprint אמיתי של Chrome (JA3, HTTP/2 settings, ALPN) כדי לעקוף הגנות בוטים בסיסיות (Cloudflare, Akamai, PerimeterX) **בלי להקים דפדפן**. מהיר פי 10+ מ-CloakBrowser. אם curl_cffi נכשל → fallback אוטומטי ל-CloakBrowser → LLM fallback. החליף את `httpx` בכל שכבות ה-HTTP (HTML, WooCommerce API, Magento API, Haturki API).
- **Adaptive Scraping Frequency (v2.12+)**: מנגנון חכם שמדלג סריקה של מוצרים עם מחיר יציב 30+ ימים (אלא אם עברו 24 שעות מהסריקה האחרונה — periodic re-validation). מוצרים שהמחיר שלהם השתנה לפני פחות מ-7 ימים נסרקים בכל ריצה. חוסך משאבים, מונע bans, ומאיץ ריצות קרון. לוג ברור: `⏭️ Skipping [Product Name] - Price stable for 30+ days`.
- **CloakBrowser Stealth Integration**: שימוש בדפדפן Chromium ייעודי הכולל 58 פאטצ'ים ברמת קוד המקור של C++ (ביטול `navigator.webdriver`, שינוי TLS fingerprint, הגדרת פלאגינים פיקטיביים) למעבר חלק של Cloudflare ו-reCAPTCHA באתרים מוגנים כמו פאנקו והיבואן. **כעת שכבת fallback** — רץ רק כש-curl_cffi לא מצליח לעבור.
- **SQLite Database Architecture**: כל סריקה נשמרת בזמן אמת בטבלאות `price_results`, `price_history`, `deal_scores`, ו-`scraper_health`. תוצאות חלקיות נשמרות גם אם חנויות אחרות נכשלות בריצה. SQLite3 הוא חלק מ-stdlib של פייתון — אין צורך בהתקנה נפרדת.
- **Streamlit Dashboard (`dashboard.py`)**: דשבורד RTL חי ב-`turki.avolkov.click` המציג רק את הריצה האחרונה, עם בחירת מוצר, השוואה לטורקי, וזיהוי דילים בצבע Hermes Teal.
- **Tracked Products Suite (`manage_tracker.py`)**: כלי ניהול מובנה ב-CLI למעקב, הוספה, הסרה והרצה של סוויטת מוצרים נבחרים (וודקה בלוגה, רוסקי, קברנה סוביניון, ג'וני בלאק ועוד) לאיתור מבצעי פתאום.
- **Cron Watchdog (`cron_tracker.py`)**: מנגנון עלות-אפס — סקריפט Python רץ כל שעתיים דרך Hermes Cron, שותק כשאין דילים, פורץ לטלגרם רק כשנמצא מבצע. ללא טוקנים מבוזבזים כשאין מה לדווח.
- **Progressive Querying (WooCommerce & Magento REST APIs)**: מנגנון חיפוש דו-שלבי חכם עוקף מגבלות מנועי חיפוש קשיחים: מחפש קודם לפי 2 מילים, ובמידה ואין תוצאות, מבצע פולבק למילה הבודדת הראשונה (למשל מותג) ומבצע סינון ודפליקציה בתוך קוד הפייתון.
- **Smart Hebrew Alias Normalization**: אלגוריתם ייחודי המזהה ומנרמל קיצורים ושגיאות כתיב נפוצים בעולם היין הישראלי:
  * `"ק.ס"` / `"ק"ס"` / `"קס"` ← `"קברנה סוביניון"` (התאמה מלאה של "ירדן ק.ס 2022" ל-"ירדן קברנה סוביניון 2022").
  * `"ס.ב"` / `"ס"ב"` / `"סב"` ← `"סוביניון בלאן"`.
  * `"סובניון"` / `"סביניון"` ← `"סוביניון"` (תיקון שגיאות כתיב של חנויות).
  * ניקוי קידומות מפריעות: `"יין"`, `"בקבוק של"`, `"מארז"`, `"וויסקי"`.
- **Dynamic Relevance Thresholds**: סינון אוטומטי של מוצרים לא קשורים. שאילתות של 4+ מילים דורשות לפחות 3 התאמות מדויקות (מונע מ-"יין ירדן קברנה פרנק" להתאים ל-"ירדן קברנה סוביניון").
- **Brand-Word Matching (v2.3+)**: מונע התאמות שווא מהטורקי API שמחזיר את כל המלאי (3682 מוצרים). דורש לפחות מילת מותג אחת (len > 2, לא STOP_WORD) שמתאימה. מספרים ("12", "700"), יחידות ("ml", "מל"), ותיאורים ("אורגינל", "שנים") לא נספרים כהתאמות מותג.
- **Hard Price Floor Integration (v2.6)**: מנגנון סינון קשיח ב-`is_bogus_price` המונע כניסת "מחירי זבל" ל-DB (למשל ג'וני ווקר ב-10₪). כל מחיר מתחת לרצפה מוגדרת מראש לפי מותג נפסל אוטומטית.
- **Improved Scraper Reliability**: כלים לניקוי יזום של ה-DB מרשומות חשודות שנאספו בעבר.
- **Smart Pipeline Guard**: ה-Orchestrator משלב עכשיו את סינון ה-Hard Floor כשלב מקדים לכל כתיבה ל-DB, מה שמבטיח שרק נתונים מהימנים מגיעים ל-Strategist.
- **Tavily Web Extraction (v2.5+)**: חילוץ תוכן מ-URL מהיר ואמין עבור חיפושים ברשת (לוז משחקים, מידע עדכני) — 1,000 קריאות/חודש בחינם.

---

## 📂 מבנה הפרויקט

```text
turk-price-intelligence/
├── manage_tracker.py                   ← כלי ניהול סוויטת מעקב המוצרים (list, add, remove, run)
├── run.py                              ← CLI Entry point ראשי להרצת שאילתה ידנית
├── cron_tracker.py                     ← סקריפט קרון שקט (watchdog) — רק דילים מודפסים
├── dashboard.py                        ← דשבורד Streamlit חי (turki.avolkov.click)
├── config.yaml                         ← הגדרות וקישורים ל-20 החנויות הנסרקות
├── requirements.txt                    ← תלויות פייתון
├── .gitignore                          ← דילוג venv/, data/, logs/, .env, *.png
├── src/
│   ├── models.py                       ← Pydantic Models (ProductPrice, Store, PriceReport)
│   ├── logger.py                       ← לוגר מותאם
│   ├── agents/
│   │   ├── searcher.py                 ← Searcher Agent (Playwright + requests)
│   │   ├── analyzer.py                 ← אנליזת תוצאות
│   │   └── extractor.py                ← חילוץ נתונים
│   ├── export/
│   │   └── csv_export.py               ← ייצוא CSV השוואתי ומעקב היסטורי
│   ├── scrapers/
│   │   ├── unified_scraper.py          ← מנוע הפיצול הראשי, WooCommerce/Magento APIs, HTMLFallback
│   │   ├── api_scrapers.py             ← API חנות הטורקי ישירות + GenericAPIScraper + Factory
│   │   ├── html_scrapers.py            ← Fallback HTML Scrapers (MagentoHTML, SarHascraper)
│   │   └── playwright_scrapers.py      ← סקראפרים ייעודיים ל-JS heavy (PlaywrightEngine, GenericPlaywright)
│   ├── storage/
│   │   └── sqlite_store.py             ← לוגיקת SQLite (init_db, save_store_result, deal_scores, scraper_health)
│   └── utils/
│       ├── filters.py                  ← פילטרים אלגוריתמיים, ניקוי שמות, נרמול, STOP_WORDS, volume filters
│       └── llm_volume.py               ← DeepSeek V4 Flash fallback לחילוץ נפח
├── tests/                              ← בדיקות ידניות (לא pytest — סקריפטים עצמאיים)
└── data/                               ← תיקיית תוצאות ודוחות (נוצרת אוטומטית, לא ב-git)
    ├── price_intel.db                  ← בסיס הנתונים הראשי של SQLite
    ├── *.json                          ← דוחות גולמיים
    ├── *.txt                           ← דוחות קריאים המותאמים למשלוח בטלגרם
    └── *.csv                           ← אקסלים השוואתיים ומעקב היסטורי לאורך זמן
```

---

## 🛠️ התקנה ודרישות קדם

המערכת רצה על סביבת לינוקס (Python 3.10+) ודורשת דפדפן Chromium מותקן.

### תלויות מערכת

```bash
# Ubuntu/Debian — Chromium עבור CloakBrowser/Playwright
sudo apt install -y chromium-browser
# או דרך Playwright (מומלץ):
# playwright install chromium
```

### התקנת פייתון

```bash
# שכפול הריפו וכניסה לתיקייה
git clone https://github.com/andrewvlk88/AV-hermes-turki.git
cd AV-hermes-turki

# יצירת סביבה וירטואלית והפעלתה
python3 -m venv venv
source venv/bin/activate

# התקנת כל החבילות (כולל curl_cffi, CloakBrowser, PyYAML, וכל השאר)
pip install -r requirements.txt

# התקנת מנוע Playwright ב-Venv (fallback בלבד — curl_cffi הראשי לא צריך דפדפן)
playwright install chromium

# הגדרת משתני סביבה נדרשים ב-~/.hermes/.env:
#   TAVILY_API_KEY=tvly-...
#   OLLAMA_API_KEY=...
#   GEMINI_API_KEY=... (לא בשימוש כרגע)
```

> **הערה:** SQLite3 הוא חלק מ-stdlib של פייתון מגרסה 2.5+. אין צורך ב-`pip install` או התקנה נפרדת. קובץ ה-DB (`data/price_intel.db`) נוצר אוטומטית בריצה הראשונה.

---

## 💻 הוראות שימוש והרצה

⚠️ **חובה להפעיל תמיד מתוך ה-venv של הפרויקט!**

### 1. כלי ניהול סוויטת מעקב המחירים (`manage_tracker.py`)

```bash
# הצגת רשימת המשקאות הנוכחית במעקב
python manage_tracker.py list

# הוספת משקה חדש למעקב
python manage_tracker.py add "וודקה אבסולוט ליטר"

# הסרת משקה מהמעקב (לפי ה-ID שמופיע ב-list, או לפי השם המדויק)
python manage_tracker.py remove 4
python manage_tracker.py remove "דלתון אסטייט קברנה"

# הרצת סריקת בנצ'מרק מלאה על כל מוצרי המעקב בזה אחר זה
python manage_tracker.py run
```

### 2. הרצת חיפוש חופשי ידני (`run.py`)

```bash
# הרצה רגילה (מדפיסה טבלה קריאה עם אמוג'ים)
python run.py "וודקה בלוגה ליטר"

# הרצה מושתקת עם פלט JSON נקי (מיועד לעוזרים אישיים/בוטים של AI)
python run.py "בלוגה" --agent-mode

# הרצה ב-Fast Mode — בלי דפדפנים בכלל (ראה סעיף Fast Mode למטה)
python run.py "גבעות מרלו 2022" --fast
```

### Fast Mode (v2.14+)

**מה זה:** מצב שמבטל לחלוטין את כל שיטות הסריקה מבוססות-דפדפן (Playwright/CloakBrowser). רק API, curl_cffi, ו-LLM fallback פעילים. מונע תקיעות בחנויות כבדות.

**מתי להשתמש:**
- כשהריצה הרגילה נתקעת או לוקחת יותר מ-5 דקות
- כשרוצים תוצאות מהירות (~30-60 שניות במקום 5-10 דקות)
- בבדיקות מהירות של מחירים ללא צורך בחנויות JS-heavy

**איך מפעילים:**
```bash
# דרך CLI
python run.py "וודקה בלוגה ליטר" --fast

# דרך environment variable
FAST_MODE=true python run.py "וודקה בלוגה ליטר"
```

**מה קורה ב-Fast Mode:**
- כל ה-strategies מקבלות `"playwright"` מוסר מהן (עותק חדש, המקור לא משתנה)
- חנויות שנשארות עם strategy ריק → מדלגות עם לוג `[⏩ FAST MODE] Skipping`
- חנויות playwright עם curl_cffi ב-strategy → מנסות curl_cffi בלבד
- לא נשלחים תהליכי Chromium בכלל → אין EPIPE, אין תקיעות
- `PlaywrightEngine.close()` לא נקרא (אין מה לסגור)

**חנויות שעובדות ב-Fast Mode (11):** כל חנויות WooCommerce API + פרטוש + הטורקי
**חנויות שמדלגות/מנסות curl_cffi (8):** פאנקו, היבואן, מנו וינו, אביב, Wine & More, שר המשקאות, אליאסי, לגימה, Drinks4U

### 3. דשבורד חי (`dashboard.py`)

```bash
streamlit run dashboard.py --server.port 5053
```

מופיע דרך Cloudflare Tunnel ב-`https://turki.avolkov.click`.

### 4. קרון Watchdog יומי (`cron_tracker.py`)

רץ אוטומטית כל שעתיים דרך Hermes Cron. **עקרון Watchdog**: שקט מוחלט כשאין דילים, פריצה לטלגרם רק כשנמצא מבצע.

**ארכיטקטורת עלות-אפס:**
```
[Python חינם — 0 טוקנים]
  run_daily_tracker.sh → cron_tracker.py
  סריקה → השוואה מול הטורקי → דילים
        ↓
[LLM — טוקנים]
  רק אם יש דילים → סיכום קצר בעברית → טלגרם
        ↓
[שקט מוחלט אם אין דילים]
```

---

## 🕷️ ארכיטקטורת הסקראפינג — שלוש שכבות Fallback (20 חנויות)

המערכת משתמשת בשרשרת fallback תלת-שלבית לכל fetch:

```
1. curl_cffi (Chrome TLS impersonation)     ← primary, ~200ms, no browser
       ↓ fail
2. CloakBrowser / Playwright (stealth Chromium)  ← fallback, ~5-10s, full browser
       ↓ fail
3. LLM fallback (DeepSeek V4 Flash)         ← last resort, extract price from raw HTML
```

ההפרדה בין API (קל) ו-Browser (כבד) נשמרת, אבל כעת גם חנויות ה-Browser מנסות curl_cffi קודם — מה שמקצר ריצות משמעותית.

> **מסמך ארכיטקטורה מלא:** ראה [`ARCHITECTURE.md`](./ARCHITECTURE.md) להסבר מפורט על מודולים, data flow, ו-responsibilities.

### שכבה 1 — curl_cffi (Primary HTTP Client)

כל קריאות ה-HTTP (HTML + REST APIs) עוברות דרך `curl_cffi.requests.AsyncSession(impersonate='chrome')`. הספרייה שולחת TLS fingerprint אמיתי של Chrome (JA3, HTTP/2 SETTINGS, ALPN, cipher suites) וכך עוקפת הגנות בוטים בסיסיות בלי להקים דפדפן. מהיר פי 10+ מ-CloakBrowser.

| מנוע | חנויות | הערות |
|------|--------|-------|
| **Haturki REST API** | הטורקי (reference) | API ייעודי, מחזיר את כל המלאי (3682 מוצרים) — דורש פילטרים קפדניים. |
| **WooCommerce Store API** | בנא, דרך היין, ארי, Liquor Store, אלכוהום, משקאות המשמח, Coffeco, Alcohol123, בית היין | חיפוש פרוגרסיבי דו-שלבי (2 מילים → 1 מילה), 100 מוצרים לתוצאה. |
| **HTML Scraper** (curl_cffi fetch + BeautifulSoup) | שר המשקאות, אליאסי, לגימה, Drinks4U | טעינת HTML דרך curl_cffi (מעקף Cloudflare) עם פרסור סטטי, ללא רנדור JS מלא. |

### שכבה 2 — CloakBrowser / Playwright (Browser Fallback)

סריקה דרך דפדפן Chromium חשאשי (CloakBrowser — 58 פאטצ'ים ברמת C++). נדרש לאתרים שטוענים מוצרים דינמית או דורשים אינטראקציה (פופאפ גיל). **כעת שכבת fallback** — רץ רק כש-curl_cffi נכשל.

| מנוע | חנויות | הערות |
|------|--------|-------|
| **CloakBrowser + Magento Extractor** | פאנקו, היבואן | מעקף Cloudflare, סלקטורים מותאמים ל-Magento. קיצור שאילתה ל-2 מילים. |
| **CloakBrowser JS Render** | מנו וינו (Shopify), בית המשקאות של אביב (Elementor), Wine & More (custom JS) | אתרי SPA מורכבים הדורשים המתנה ארוכה לרנדור. |

> **אזהרה:** חנויות מסלול 2 חייבות להיסרק **סדרתית בלבד** — CloakBrowser מקים תהליך Chromium שלם לכל חנות. מקביליות תגרום לנעילת קבצי Session וקריסת זיכרון.

### טבלת חנויות מלאה (20 חנויות)

| # | חנות | URL | מסלול | מנוע |
|---|------|-----|-------|------|
| 1 | הטורקי (reference) | haturki.com | API | Haturki REST API |
| 2 | פאנקו | paneco.co.il | Browser | CloakBrowser + Magento |
| 3 | בנא משקאות | banamashkaot.co.il | API | WooCommerce Store API |
| 4 | היבואן | the-importer.co.il | Browser | CloakBrowser + Magento |
| 5 | דרך היין | wineroute.co.il | API | WooCommerce Store API |
| 6 | שר המשקאות | mashkaot.co.il | API (HTML fetch) | HTML Scraper (`.product-box`) |
| 7 | אליאסי משקאות | eliasi.co.il | API (HTML fetch) | HTML Scraper (`.products__block`) |
| 8 | ארי משקאות | ari-g.co.il | API | WooCommerce Store API |
| 9 | Liquor Store | liquor-store.co.il | API | WooCommerce Store API |
| 10 | אלכוהום | alcohome.co.il | API | WooCommerce Store API |
| 11 | משקאות המשמח | hamesameach.co.il | API | WooCommerce Store API |
| 12 | מנו וינו | manovino.co.il | Browser | CloakBrowser (Shopify) |
| 13 | בית המשקאות של אביב | avivdrinks.co.il | Browser | CloakBrowser (Elementor) |
| 14 | Wine & More | wineandmore.co.il | Browser | CloakBrowser (custom JS) |
| 15 | לגימה | legima.co.il | API (HTML fetch) | HTML Scraper (`.boxItem-wrap`) |
| 16 | Coffeco | coffeco.co.il | API | WooCommerce Store API |
| 17 | Drinks4U | drinks4u.co.il | API (HTML fetch) | HTML Scraper (`.prod-box`) |
| 18 | Alcohol123 | alcohol123.co.il | API | WooCommerce Store API |
| 19 | בית היין | winehouse.co.il | API | WooCommerce Store API |

> סה"כ: **11 חנויות API** (1 REST + 9 WooCommerce + 1 HTML) · **5 חנויות Browser** · **4 חנויות HTML fetch** — מסלול ה-API וה-HTML נחשבים "ללא דפדפן מלא".

### מאמצי יציבות (Stability Improvements)

המערכת עוברת שיפורי יציבות מתמשכים. המנגנונים המרכזיים:

- **Hard timeout לכל חנות** (90-120 שניות) — חנות אחת שתקועה לא יכולה לעצור ריצה מלאה.
- **שמירה מיידית ל-SQLite** — כל חנות נשמרת בנפרד, תוצאות חלקיות שורדות כשלונות.
- **Health Gate** — ה-Orchestrator בודק response rate לפני סריקה; אם מתחת לסף, הסריקה מבוטלת.
- **Adaptive Scraping Frequency** — מוצרים עם מחיר יציב 30+ ימים מדלגים אוטומטית (ראה סעיף נפרד למעלה).
- **LLM Deal Validation** — דילים מועמדים עוברים אימות LLM למניעת false positives.
- **Strict Volume Matching** (±50ml) — מונע השוואת 200ml מול 1L.
- **Brand Hard Price Floors** — מחירים נמוכים מהרצפה לפי מותג נפסלים אוטומטית.
- **CloakBrowser Non-Persistent Context** — כל חנות מקבל קונטקסט נקי, מונע זליגת cookies בין חנויות.
- **Circuit Breaker (v2.7+)** — חנויות שנכשלות N פעמים ברצף באותו batch מדלגות אוטומטית על שאר המוצרים. בנוסף, חנויות שנכשלו ב-3 הריצות האחרונות (DB history) מדלגות מראש. חנויות קשות (פאנקו, היבואן, שר המשקאות) מקבלות 4 ניסיונות retry עם backoff מוארך (5s, 1.5x). ראה [`ARCHITECTURE.md`](./ARCHITECTURE.md) לפרטים.

---

## 🗄️ SQLite Database

- **מיקום**: `data/price_intel.db` (נוצר אוטומטית, לא ב-git)
- **טבלאות**:
  - `price_results` — מוצרים שנמצאו בסריקה האחרונה
  - `price_history` — היסטוריית מחירים מכל ריצה
  - `deal_scores` — דילים שזוהו (חנות, מחיר, חיסכון %)
  - `scraper_health` — סטטוס ריצה לכל חנות
- **מחיר אפקטיבי**: `COALESCE(sale_price, regular_price)` — אין עמודת `price` יחידה
- **מפתח ריצה**: כל ריצה מקבלת `run_id` ייחודי. shared_run_id מאחד סבב סריקה שלמה.

---

## 🔀 Concurrency Control

החל מ-v2.5.0, המערכת מריצה סריקה מקבילית חכמה במקום סדרתית, תוך הפרדה בין חנויות API (קלות) לחנויות דפדפן (כבדות).

### הבעיה

- סריקה סדרתית של 20 חנויות = ~14-15 דקות (איטי מדי).
- הרצת הכל במקביל גורמת ל-CloakBrowser לקרוס (נעילת Session + מחסנית זיכרון — 10 תהליכי Chromium בו-זמנית).

### הפתרון

`UnifiedScraper.search_all()` מפצל את החנויות לשתי קבוצות ומריץ את שתיהן ב-`asyncio.gather`:

| קבוצה | מנועים | מגבלת מקביליות | חנויות |
|-------|--------|----------------|--------|
| **API** (קלות) | `woocommerce`, `magento`, `haturki_api` | **ללא הגבלה** — כולן רצות במקביל | בנא, דרך היין, ארי, Liquor Store, אלכוהום, משקאות המשמח, Coffeco, Alcohol123, בית היין |
| **Browser** (כבדות) | `playwright*`, `magento_html`, `sar`, `prodbox_*`, HTML fallback | **`MAX_BROWSER_CONCURRENCY = 3`** — `asyncio.Semaphore` | פאנקו, היבואן, אליאסי, לגימה, שר המשקאות, Drinks4U, מנו וינו, בית המשקאות של אביב, Wine & More |

### איך זה עובד

```
search_all(query)
    │
    ├─ Split stores: API vs Browser
    │
    ├─ asyncio.gather(
    │     [api_store_1, api_store_2, ... api_store_9],      ← unlimited, all at once
    │     [browser_store_1, ... browser_store_10],         ← Semaphore(3) gates these
    │   )
    │
    └─ Each browser scraper:
         ├─ log: "waiting for semaphore slot"
         ├─ await semaphore.acquire()     ← blocks if 3 already running
         ├─ log: "acquired semaphore slot"
         ├─ scraper.search(query)         ← launches CloakBrowser/Playwright
         ├─ finally: semaphore.release()  ← ALWAYS releases, even on error
         └─ log: "released semaphore slot"
```

### ניקוי משאבים (Resource Cleanup)

- כל סקראפר דפדפן סוגר את ה-`page` וה-`context` שלו ב-`finally` block (בתוך `playwright_scrapers.py` / `html_scrapers.py`).
- ה-`_scrape_one_store` wrapper מבטיח ש-`semaphore.release()` רץ תמיד — גם אם הסקראפר קרס, גם אם היה timeout, גם אם הייתה שגיאה.
- כל חנות עטופה ב-`asyncio.wait_for(timeout)` — חנות שנתקעת לא חוסמת את השאר.

### הגדרות

```python
# unified_scraper.py — UnifiedScraper class

MAX_BROWSER_CONCURRENCY = 3   # max parallel browser scrapers
API_ENGINES = {"haturki_api", "woocommerce", "magento"}  # no-limit engines
```

### תוצאות בפועל

- חנויות API (9) מסתיימות תוך ~5-10 שניות (כולן במקביל).
- חנויות דפדפן (10) רצות ב-3 קבוצות מקביליות, כל קבוצה ~30-60 שניות.
- זמן כולל: ~4-6 דקות (לעומת 14-15 דקות סדרתי).

---

## ⚠️ Pitfalls ולקחים קריטיים

1. **מניעת קריסות מקביליות בדפדפן**: CloakBrowser מקים תהליך Chromium שלם לכל חנות מבוססת דפדפן. ניסיון להריץ את כל 10 החנויות הדפדפניות במקביל יוביל לנעילת קבצי Session, צריכת זיכרון מופרזת וקריסת המנוע. המערכת משתמשת ב-`asyncio.Semaphore` להגבלת מקביליות הדפדפנים ל-3 (ראה Concurrency Control למטה).
2. **דילוג על פופאפ גיל באתרי Magento**: פופאפ אימות הגיל ("אני מעל 18") באתרי פאנקו והיבואן גורם ללחיצה שגויה ב-JavaScript שמפנה לדפי קוקטיילים שבורים. הקוד מדלג אוטומטית על מנגנון הטיפול בפופאפ גיל בחנויות אלו.
3. **עבודה ללא persistent context**: שימוש ב-Session שמור קבוע גרם לפאנקו לטעון עוגיות ישנות ולהחזיר מוצרים לא קשורים. המנוע יוצר מופע נפרד ונקי (`launch_async`) לכל חנות וסוגר אותו מיד בסיום.
4. **www redirect בארי משקאות**: `www.ari-g.co.il` מבצע 301 redirect ל-`ari-g.co.il` (ללא www). חובה להשתמש בכתובת ללא www ב-`config.yaml`.
5. **הטורקי API מחזיר את כל המלאי (3682 מוצרים)**: ה-API לא מסנן server-side. בלי פילטרים קפדניים, "וודקה נמירוף אורגינל 700 מל" עובר כהתאמה ל"גלנמורנג'י 12 אורגינל 700 מל". הפתרון: `is_relevant_product` דורש לפחות מילת מותג אחת (len > 2, לא STOP_WORD) שמתאימה.
6. **רגקס בעברית — סוגריים לא מאוזנים**: `re.sub(r'\[^)]*\)', ...)` קורס עם `re.error: unbalanced parenthesis` כשיש תווים עבריים. התחביר הנכון: `re.sub(r'\([^)]*\)', '', name)`.
7. **אליאסי משקאות מחזיר פסולת**: ה-extractor הגנרי תופס "מארז מתנה קרטון מהודר" ב-₪12.9 כמוצר. מילים כמו "מארז מתנה", "קרטון", "סירופ", "סאקה", "מיקס", "מונין" נוספו ל-`ACCESSORY_KEYWORDS` ב-`filters.py`.
8. **תמיד להציג תוצאות מול baseline של הטורקי**: רשימת מוצרים בלי השוואה לטורקי = חסרת ערך. דיל = זול מהטורקי ב-5%+.
9. **אורך ריצה**: סריקה מלאה של 6 מוצרים × 20 חנויות = ~14-15 דקות. תכנן בהתאם ל-timeout של קרונים.
10. **מניעת שגיאות הרשאות Git**: דחיפת שינויים ל-GitHub עשויה להיכשל עם שגיאת 403 במקרה של Token פג תוקף. במקרה כזה יש לבצע רענון הרשאות באמצעות ה-GitHub CLI.
11. **סינון 200ml/500ml (v2.5+)**: בקבוקונים קטנים מסוננים ברמת ה-build_report. הם לא מופיעים בדוח ובדשבורד ולא משווים מול הטורקי — מונע דילים מזויפים מסוג "₪25 ל-200ml מול ₪65 לליטר".
12. **Hermes config — extract backend**: כדי שחיפושים ברשת יחזירו תוכן מלא במהירות, יש להגדיר `web.extract_backend: tavily` ב-`~/.hermes/config.yaml` ולשמור את `TAVILY_API_KEY` ב-`~/.hermes/.env`.

---

## 📊 Adaptive Scraping Frequency (v2.12+)

מנגנון חכם שמתאים את תדירות הסריקה לכל מוצר בנפרד, בהתבסס על יציבות המחיר ההיסטורית שלו. מטרה: חיסכון במשאבים, מניעת bans, וזמני ריצה קצרים יותר לקרון.

### איך זה עובד

לפני כל ריצה, ה-Orchestrator בודק את `price_history` ב-DB לכל מוצר tracked ומחליט אם לסרוק או לדלג:

| מצב מחיר | פעולה | לוג |
|---|---|---|
| אין היסטוריה (first run) | ✅ סרוק | `no price history yet — first scrape` |
| השתנה <7 ימים | ✅ סרוק כל פעם | `price changed Xd ago (< 7d) — scraping every run` |
| יציב 30+ ימים + <24h מסריקה אחרונה | ⏭️ **דלג** | `⏭️ Skipping [Product] - Price stable for 30+ days` |
| יציב 30+ ימים + >24h מסריקה אחרונה | ✅ סרוק (re-validation) | `price stable for Xd but Yd since last scrape — periodic re-validation` |
| השתנה 7-30 ימים | ✅ סרוק (monitoring) | `price changed Xd ago — monitoring` |

### חישוב יציבות

המנגנון (`get_query_price_stability()` ב-`sqlite_store.py`) מקבץ שורות `price_history` לפי `run_id` (כל סריקה = run אחד), מחשב את ה-best price (min) לכל run, ואז משווה בין runs רצופים כדי לזהות שינויים. זה מונע false positives מריבוי חנויות באותו run.

### איפה זה רץ

- **`turki_tools.run_full_scan()`** — מסנן queries לפני שליחה ל-`async_main()`. מחזיר `skipped_queries` בפלט.
- **`orchestrator.run_tracked()`** — מסנן queries לפני הרצת `run_query()`.

### הגדרות

```python
# OrchestratorAgent class constants
STABLE_THRESHOLD_DAYS = 30        # דלג אם יציב 30+ ימים
MIN_RESCRAPE_INTERVAL_HOURS = 24  # אבל תמיד סרוק מחדש אחרי 24 שעות
RECENT_CHANGE_DAYS = 7            # סרוק כל פעם אם השתנה <7 ימים
```

---

## 🧠 Orchestrator Agent

ה-`OrchestratorAgent` (`src/agents/orchestrator.py`) הוא ה"מוח" של המערכת — מקבל הוראות בשפה טבעית (עברית/אנגלית), מתכנן אילו כלים להפעיל ובאיזה סדר, ומחזיר תוצאה מובנית עם הסבר החלטות.

### איך זה עובד

```
execute(goal, constraints)
    │
    ├─ 1. Plan — LLM מנתח את ה-goal + constraints → Plan (JSON)
    │      ├─ intent: scan / analyze / deals / health / auto
    │      ├─ check_health: האם לבדוק בריאות סקרייפרים
    │      ├─ run_scan: האם לסרוק
    │      ├─ fetch_deals: האם לשלוף דילים
    │      └─ analyze_products: מוצרים ספציפיים לניתוח
    │
    ├─ 2. Act — קורא לכלים מ-src/tools/turki_tools.py
    │      ├─ get_scraper_health_report()  ← health gate
    │      ├─ run_full_scan() / run_tracked_products_scan()
    │      ├─ get_recent_deals(min_score)
    │      └─ analyze_deal(product_name)
    │
    └─ 3. Report — פלט מובנה: plan, steps, result, summary
```

**LLM Planning**: ה-planning משתמש ב-DeepSeek V4 Flash דרך Ollama Cloud עם few-shot examples. אם ה-LLM לא זמין או נכשל — fallback אוטומטי ל-keyword matching.

**Plan Cache**: תוכניות זהות (אותו goal + constraints) נשמרות ב-cache בזיכרון ל-30 דקות. מונע קריאות LLM מיותרות.

**Health Gate**: לפני סריקה, ה-Orchestrator בודק את response rate. אם הוא מתחת ל-`health_threshold` — הסריקה מבוטלת עם הסבר.

### שימוש

```python
from src.agents.orchestrator import OrchestratorAgent, Constraints

orch = OrchestratorAgent()

# סריקה חכמה עם health gate
result = await orch.execute(
    "check health first, if healthy scan tracked products and return strong deals",
    constraints={"min_score": 80, "health_threshold": 0.5}
)

# ניתוח מוצר ספציפי (בלי סריקה)
result = await orch.execute(
    "נתח את בלוגה ותראה דילים אחרונים",
    constraints={"min_score": 50}
)

# רק דילים מה-DB (בלי סריקה)
result = await orch.execute("show me recent deals", constraints={"min_score": 70})

# רק בדיקת בריאות
result = await orch.execute("check scraper health")
```

### דוגמאות smart goals

| Goal | מה ה-Orchestrator יעשה |
|---|---|
| `"check health first, if healthy scan"` | health check → gate → scan אם בריא |
| `"נתח את בלוגה ותראה דילים"` | analyze_deal("בלוגה") + get_recent_deals (ללא סריקה) |
| `"show me recent deals above 70"` | get_recent_deals(min_score=70) בלבד |
| `"do a smart scan"` | auto: health → scan → deals |
| `"check scraper health"` | get_scraper_health_report בלבד |

### Constraints זמינים

| פרמטר | ברירת מחדל | תיאור |
|---|---|---|
| `min_score` | 70.0 | מינימום score לדילים |
| `health_threshold` | 0.4 | מינימום response rate להרשות סריקה |
| `health_days` | 7 | חלון זמן לבדיקת בריאות (ימים) |
| `tracked_only` | True | סריקת מוצרים מ tracked_queries בלבד |
| `focus_products` | [] | מוצרים ספציפיים לניתוח (עוקף סריקה) |
| `max_deals` | 20 | מספר מקסימלי של דילים להחזרה |

### Backward Compatibility

המתודות הישנות `run_query()`, `run_tracked()`, `run_batch()` נשמרו ועובדות כמו לפני. `cron_tracker.py` לא מושפע.

---

## 🧠 Strategist Agent

ה-`StrategistAgent` (`src/agents/strategist.py`) הוא איש האסטרטגיה העסקית של המערכת — מקבל את הפלט של ה-Orchestrator (דילים, ניתוחים, בריאות סקרייפרים) ומייצר **המלצות פעולה** עבור בעל החנות (שמוליק).

**איך זה עובד:**

```
generate_recommendations(orchestrator_result)
    │
    ├─ 1. Extract — שולף דילים, ניתוחים, health מהפלט
    ├─ 2. Enrich — מוסיף הקשר (מחיר טורקי, % חיסכון, סטטיסטיקה)
    ├─ 3. LLM Reasoning — DeepSeek V4 Flash → המלצות מובנות
    └─ 4. Return — רשימת Recommendation objects
```

**סוגי המלצות:**

| סוג | מתי | דוגמה |
|---|---|---|
| **Price Action** | מתחרה זול ב-10%+ | "הורד מחיר ל-150₪ כדי להתחרות בבנא" |
| **Promotion** | מתחרה במבצע | "הצע מבצע נגדי או דחיפה שיווקית" |
| **Monitor** | פער קטן/לא ברור | "עקוב אחר המחיר — פער קטן" |
| **Ignore** | אין פער משמעותי | פעולה לא נדרשת |

**Fallback:** אם ה-LLM לא זמין, ה-Strategist מייצר המלצות rule-based (חישוב פשוט לפי % חיסכון).

**שימוש:**

```python
from src.agents.orchestrator import OrchestratorAgent
from src.agents.strategist import StrategistAgent

# Step 1: Orchestrator collects data
orch = OrchestratorAgent()
orch_result = await orch.execute("show me recent deals", constraints={"min_score": 50})

# Step 2: Strategist generates recommendations
strategist = StrategistAgent()
recs = strategist.generate_recommendations(orch_result)

for rec in recs["recommendations"]:
    print(f"[{rec['priority']}] {rec['recommendation_type']}: {rec['action']}")
    print(f"  Confidence: {rec['confidence']}%")
```

**הפרדת אחריות:** ה-Orchestrator אוסף נתונים, ה-Strategist מייצר בינה עסקית. ה-Strategist לא קורא ל-Orchestrator — הוא רק צורך את הפלט שלו.

---

## 📜 License

Personal project — Andrew Volkov (@andrewvlk88)

---

## 🔧 Playwright Stability Improvements

שיפורי יציבות למנוע ה-CloakBrowser/Playwright למניעת קריסות בזמן סריקה כבדה.

### הבעיה

בזמן סריקה מקבילית של מספר חנויות, מנוע ה-Node.js של Playwright יכול להרים שגיאת `EPIPE` (`Error: write EPIPE at PipeTransport.send`) כשה-pipe בין Python לתהליך Chromium נשבר. השגיאה הייתה מפילה את הסקראפר בלי retry ובלי ניקוי context.

### מה שונה

1. **EPIPE Error Handling** (`playwright_scrapers.py`):
   - פונקציית `_is_epipe_error()` מזהה EPIPE/BrokenPipeError בשלוש צורות: Python `BrokenPipeError`, `OSError` עם `errno.EPIPE`/`ECONNRESET`, והודעת string מה-Node driver (`"EPIPE"`, `"PipeTransport"`).
   - כל פעולות הדפדפן (launch, goto, page.content, close) עטופות ב-try/except שתופס EPIPE ומנקה context גם כשה-pipe נשבר.

2. **Retry עם Exponential Backoff** (`playwright_scrapers.py`):
   - פונקציית `_browser_retry()` — 3 ניסיונות, delay בסיס 2s, factor 2x (2s → 4s → 8s).
   - משמש לכל פעולות CloakBrowser/Playwright: `launch_async`, `chromium.launch`, `page.goto`, `page.content`.
   - רק שגיאות retriable (EPIPE, TimeoutError, ConnectionError) מנסות שוב — שגיאות logic (selector, ValueError) עולות מייד.

3. **Timeouts נפרדים לדפדפן** (`playwright_scrapers.py` + `unified_scraper.py`):
   - `BROWSER_TIMEOUTS = {"navigation": 30000, "networkidle": 45000, "store_max": 60000}` (ms).
   - 30s ל-navigation (page.goto/domcontentloaded).
   - **נפרד מקומplet מ-API timeouts** — ה-`STORE_TIMEOUTS` ב-unified_scraper (90-120s) נשארו ללא שינוי לחנויות API.

4. **Cleanup מובטח של Browser Contexts** (`playwright_scrapers.py`):
   - `GenericPlaywrightScraper.search()` עטוף ב-`try/finally` חיצוני — ה-context נסגר תמיד, גם ב-EPIPE.
   - `page.close()` ו-`context.close()` עטופים ב-try/except שלא מפיל את השגיאה המקורית.
   - `PlaywrightEngine.close()` גם הוא EPIPE-safe.

### קבצים ששונו

| קובץ | שינוי |
|------|------|
| `src/scrapers/playwright_scrapers.py` | EPIPE handling, retry logic, browser timeouts, context cleanup |
| `src/scrapers/unified_scraper.py` | Orchestration, concurrency control, per-store hard timeout (no browser timeout mirror) |
| `README.md` | סקציית תיעוד זו |
