# Turkí Price Intelligence 🦃

מנוע פייתון להשוואת מחירי אלכוהול ב-19 חנויות ישראליות, עם דגש על 'הטורקי' כחנות Reference (השוואה ובדיקת כדאיות מבצעים מולם). המערכת רצה במקביל (Async) על כל החנויות ומפיקה דוחות JSON, Text ו-CSV.

## תכונות מרכזיות
- **Concurrency & Speed**: סריקה של 19 חנויות בו-זמנית בעזרת `asyncio.gather`. רוב החיפושים מסתיימים תוך 5-15 שניות.
- **REST APIs First**: זיהוי אוטומטי ושימוש ב-APIs נסתרים של אתרי החנויות (WooCommerce, Magento) במקום Web Scraping איטי.
- **Playwright Fallback**: חנויות שחוסמות גישה או דורשות אימות גיל (פופאפים של "אני מעל 18") מטופלות אוטומטית בעזרת דפדפן Headless Chromium וסקריפטים עוקפי-אימות גיל.
- **Price Heuristics Corrected**: תמיכה מושלמת במחירי אגורות/סנטים מול שקלים בעזרת קריאת ה-`currency_minor_unit` המקורי מ-WooCommerce.
- **Smart Product Matching**: פילטרים מתקדמים לניקוי שמות, חילוץ נפחים, והתאמה מדויקת בין מוצרים שנקראים אחרת בחנויות שונות.

## התקנה
```bash
git clone <repository_url>
cd turk-price-intelligence
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## הרצה בסיסית

⚠️ **חובה להשתמש ב-venv!** 
```bash
# חיפוש מוצר יחיד
./venv/bin/python3 run.py "וודקה אבסולוט"

# חיפוש מספר מוצרים ברצף
./venv/bin/python3 run.py "ג'ק דניאלס" "וודקה אבסולוט"
```

## Agent Mode (עבור כלי AI / סקריפטים אוטומטיים)
לייצור פלט נקי המשמש מערכות אחרות (הדפסת JSON בלבד והשתקת הלוגים ל-stdout):
```bash
./venv/bin/python3 run.py "בלוגה" --agent-mode
```
כל הקבצים יישמרו גם בתיקיית `data/`:
- `*.json`: נתונים גולמיים ומלאים.
- `*.txt`: דוח קריא עם אימוג'ים ומבצעים מודגשים.
- `*.csv`: דוח מעקב מחירים לאורך זמן לכל מוצר (Append mode).
- `turk_products_*.csv`: דוח בפורמט מיוחד השוואתי עבור בעלי החנות 'הטורקי'.

## הארכיטקטורה
1. **API Scrapers** (הכי מהיר: ~200ms): הטורקי, WooCommerce (כ-9 חנויות שונות), פאנקו (Magento API).
2. **HTML Scrapers**: שר המשקאות, אליאסי, לגימה, Drinks4U. משתמשים ב-`httpx` ובמידת הצורך עוברים עצמאית ל-Playwright כדי לעקוף Cloudflare / פופאפ גיל.
3. **Playwright Scrapers** (~10-15s): חנויות מורכבות יותר שדורשות JavaScript Rendering כמו Wine and More.

## מבנה הפרויקט
```text
turk-price-intelligence/
├── run.py                              ← CLI Entry point (--agent-mode)
├── config.yaml                         ← 19 חנויות + הגדרות מנועים
├── requirements.txt                    
├── src/
│   ├── models.py                       ← Pydantic: ProductPrice, Store, PriceReport
│   ├── scrapers/
│   │   ├── unified_scraper.py          ← מנוע החלוקה הראשי + WooCommerce Logic
│   │   ├── api_scrapers.py             ← API הטורקי ישירות
│   │   ├── html_scrapers.py            ← HTML Fallbacks + Playwright Stealth
│   │   └── playwright_scrapers.py      ← מחלץ נתונים בעזרת Chromium מנוהל
│   ├── export/
│   │   └── csv_export.py               ← מנגנון שמירה בטוח (FileLock) לאקסל עברי (utf-8-sig)
│   └── utils/
│       └── filters.py                  ← Smart Matching (Volumes & Names)
└── data/                               ← (נוצר אוטומטית) הפלטים נשמרים כאן
```