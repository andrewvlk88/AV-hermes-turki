# Turkí Price Intelligence 🦃

**השוואת מחירי אלכוהול בישראל — בזמן אמת, על פני 19 חנויות.**

מנוע חיפוש והשוואת מחירים אוטומטי שרץ מהטרמינל, סורק 19 חנויות אלכוהול ישראליות במקביל, ומחזיר לך דוח מחירים מאוחד — עם זיהוי המבצע הכי משתלם.

---

## 🎯 מה זה עושה?

מזינים שם של מוצר (למשל `"ג'ק דניאלס"` או `"וודקה אבסולוט"`) והכלי:

1. **סורק 19 חנויות במקביל**
2. **מזהה מחירים תואמים** (מתמודד עם שמות שונים לאותו מוצר, נ"סים שונים)
3. **מדווח מה זול יותר** — והפער מול חנות הייחוס (הטורקי)
4. **שומר CSV למעקב לאורך זמן** — אפשר לראות איך המחירים משתנים
5. **מייצא JSON** לעיבוד נוסף

**דוגמה לפלט:**
```
📊 *טורקי פרייס אינטליג׳נס*
🔎 *ג'ק דניאלס*

5/19 חנויות הגיבו

🏷️ וויסקי ג'ק דניאלס - 700 מ"ל
   הטורקי:      115₪
   בנא משקאות:  118₪
   Alcohol123:   135₪
   Wine & More:  169₪ (1 ליטר)
   
   👇 הכי זול: 115₪ ב-הטורקי
```

---

## 🏪 החניות המכוסות

| # | חנות | פלטפורמה |
|---|------|----------|
| 1 | **הטורקי** 🏆 (ייחוס) | API ישיר |
| 2 | **פאנקו** | Magento API |
| 3 | **בנא משקאות** | WooCommerce |
| 4 | **היבואן** | Magento HTML |
| 5 | **דרך היין** | WooCommerce |
| 6 | **שר המשקאות** | HTML Scraper |
| 7 | **אליאסי משקאות** | HTML Scraper |
| 8 | **ארי משקאות** | WooCommerce |
| 9 | **Liquor Store** | WooCommerce |
| 10 | **אלכוהום** | WooCommerce |
| 11 | **משקאות המשמח** | WooCommerce |
| 12 | **מנו וינו** | Playwright (Shopify) |
| 13 | **בית המשקאות של אביב** | Playwright |
| 14 | **Wine & More** | Playwright |
| 15 | **לגימה** | HTML Scraper |
| 16 | **Coffeco** | WooCommerce |
| 17 | **Drinks4U** | HTML Scraper |
| 18 | **Alcohol123** | WooCommerce |
| 19 | **בית היין** | WooCommerce |

---

## ⚙️ ארכיטקטורת מנועי החיפוש

4 שכבות שונות שמבטיחות כיסוי מירבי:

| שכבה | טכנולוגיה | מהירות | חנויות |
|------|-----------|--------|--------|
| **API ישיר** | HTTPS + JSON | ~200ms | הטורקי |
| **WooCommerce Store API** | `rest_route=/wc/store/products` | 2-5s במקביל | 8 חנויות |
| **Magento API/HTML** | REST API / BeautifulSoup | 2-3s | פאנקו, היבואן |
| **HTML Scrapers** | BeautifulSoup + regex | ~3s | 5 חנויות |
| **Playwright (Headless)** | Chromium אמיתי | ~10s | מנו וינו, אביב, Wine & More |

---

## 🚀 שימוש מהיר

```bash
# חיפוש בודד
./venv/bin/python3 run.py "ג'ק דניאלס"

# רשימת מוצרים
./venv/bin/python3 run.py "ג'ק דניאלס" "וודקה אבסולוט" "יברמה"

# פלט: JSON + TXT + CSV בספריית data/
```

---

## 📁 פלט

| פורמט | תיאור |
|-------|-------|
| `data/*.json` | פלט מלא למכונה |
| `data/*.txt` | דוח קריא לבן אדם |
| `data/turk_products_*.csv` | טבלת מוצרים (utf-8-sig, תואם Excel) |
| `data/price_tracking_*.csv` | מעקב מחירים לאורך זמן (מצטבר, append) |

---

## 🏗️ מבנה הפרויקט

```
turk-price-intelligence/
├── run.py                 ← נקודת כניסה
├── config.yaml            ← 19 חנויות + הגדרות
├── requirements.txt
├── src/
│   ├── models.py          ← Pydantic: ProductPrice, Store, PriceReport
│   ├── scrapers/
│   │   ├── api_scrapers.py         ← Haturki API (יחוס)
│   │   ├── unified_scraper.py      ← WooCommerce + Magento
│   │   ├── html_scrapers.py        ← BeautifulSoup scrapers
│   │   └── playwright_scrapers.py  ← Chromium Headless
│   ├── agents/
│   │   ├── searcher.py             ← חיפוש
│   │   ├── extractor.py            ← חילוץ מידע
│   │   └── analyzer.py             ← ניתוח והשוואת מחירים
│   ├── export/
│   │   └── csv_export.py           ← ייצוא CSV בעברית
│   └── utils/
│       └── filters.py              ← ניקוי והתאמת מוצרים
├── tests/                          ← 8 קבצי בדיקות
└── data/                           ← תפוקת ריצות
```

---

## ⚠️ הערות טכניות

- **חובה להריץ מתוך `venv`** — Pydantic v2 מותקן רק שם (`./venv/bin/python3 run.py`)
- **CSV בעברית** — utf-8-sig, נפתח נכון ב-Excel
- **מחירי WooCommerce** — חנויות ישראליות שומרות מחירים באגורות או שקלים; היוריסטיקה אוטומטית מזהה
- **Playwright** — מטפל אוטומטית ב-age verification popups (חובה בארץ לאלכוהול)

---

## 📊 מעקב לאורך זמן

כל ריצה מוסיפה שורה ל-`data/price_tracking_*.csv` עם timestamp. אפשר לעקוב אחרי מגמות מחירים לאורך ימים/שבועות.

---

## 📜 רישיון

MIT
