# AV Hermes Turki — Turkí Price Intelligence (v2.5.0) 🦃📊

מנוע פייתון מתקדם להשוואת מחירי אלכוהול בזמן אמת ב-20 חנויות מובילות בישראל, המשתמש ב-**CloakBrowser (Stealth Chromium)** למעבר חומות Cloudflare/הגנות בוטים, שמירה מיידית ב-**SQLite**, ומערכת נירמול אלגוריתמית חכמה.

המערכת פותחה במיוחד עבור **הטורקי** כחנות Reference לצורך זיהוי פערי מחירים, מבצעים אגרסיביים ויצירת מודיעין תחרותי חצי-אוטומטי.

**הלוגיקה הבסיסית:** הטורקי רץ ראשון (API מהיר) → מתקבל מחיר baseline → שאר 19 החנויות נסרקות ומושוות מולו → דילים = חנות שזולה מהטורקי ב-5%+. כל ריצה = צילום רענן, אין caching, אין זיכרון מריצה קודמת.

> **Repo נוכחי:** `https://github.com/andrewvlk88/AV-hermes-turki`

---

## 🚀 תכונות מרכזיות

- **CloakBrowser Stealth Integration**: שימוש בדפדפן Chromium ייעודי הכולל 58 פאטצ'ים ברמת קוד המקור של C++ (ביטול `navigator.webdriver`, שינוי TLS fingerprint, הגדרת פלאגינים פיקטיביים) למעבר חלק של Cloudflare ו-reCAPTCHA באתרים מוגנים כמו פאנקו והיבואן.
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

# התקנת כל החבילות (כולל CloakBrowser, PyYAML, וכל השאר)
pip install -r requirements.txt

# התקנת מנוע Playwright ב-Venv
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
```

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

## 🕷️ ארכיטקטורת הסקראפינג (20 חנויות)

| רמת סריקה | מנוע טכנולוגי | חנויות נסרקות | יתרונות ושיקולים |
|-----------|---------------|---------------|------------------|
| **1. REST API** | HTTPS ישיר | **הטורקי (API)** | מהירות שיא (~200ms), אינו דורש הפעלת דפדפן. מחזיר את כל המלאי — דורש פילטרים קפדניים. |
| **2. WooCommerce Store API** | HTTP requests מנורמלים | **בנא, דרך היין, ארי משקאות, Liquor Store, אלכוהום, משקאות המשמח, Coffeco, Alcohol123, בית היין** | מהיר ויציב ביותר. חיפוש פרוגרסיבי דו-שלבי וקיבולת של 100 מוצרים לתוצאה. |
| **3. CloakBrowser + Magento Extractor** | Stealth Chromium + Beautiful Soup | **פאנקו, היבואן** | מעקף מוחלט של Cloudflare. סלקטורים מותאמים ל-Magento (`div.product-item` ו-`li.product`). |
| **4. CloakBrowser HTML Fallback** | Stealth Chromium | **אליאסי משקאות, לגימה, שר המשקאות, Drinks4U** | טעינת HTML מרונדר דרך CloakBrowser עם בידוד סשנים מלא לכל חנות. |
| **5. Playwright Render Engine** | CloakBrowser Page Context | **מנו וינו, בית המשקאות של אביב, Wine & More** | אתרי SPA מורכבים מבוססי JS/Shopify הדורשים המתנה ארוכה לרנדור. |

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

## ⚠️ Pitfalls ולקחים קריטיים

1. **הרצה סדרתית בלבד**: CloakBrowser מקים תהליך Chromium שלם לכל חנות מבוססת דפדפן. ניסיונות להריץ במקביל יובילו לנעילת קבצי Session, צריכת זיכרון מופרזת וקריסת המנוע.
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
