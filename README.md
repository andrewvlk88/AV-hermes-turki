# Turkí Price Intelligence (v2.1.0) 🦃📊

מנוע פייתון מתקדם להשוואת מחירי אלכוהול בזמן אמת ב-19 חנויות מובילות בישראל, המשתמש ב-**CloakBrowser (Stealth Chromium)** למעבר חומות Cloudflare/הגנות בוטים, שמירה מיידית ב-**SQLite**, ומערכת נירמול אלגוריתמית חכמה.

המערכת פותחה במיוחד עבור **הטורקי** כחנות Reference לצורך זיהוי פערי מחירים, מבצעים אגרסיביים ויצירת מודיעין תחרותי חצי-אוטומטי.

---

## 🚀 תכונות מרכזיות (שדרוג 2.1.0)

- **CloakBrowser Stealth Integration**: שימוש בדפדפן Chromium ייעודי הכולל 58 פאטצ'ים ברמת קוד המקור של C++ (ביטול `navigator.webdriver`, שינוי TLS fingerprint, הגדרת פלאגינים פיקטיביים) למעבר חלק של Cloudflare ו-reCAPTCHA באתרים מוגנים כמו פאנקו והיבואן.
- **SQLite Database Architecture**: כל סריקה נשמרת בזמן אמת בטבלאות `price_results` ו-`store_status`. תוצאות חלקיות נשמרות גם אם חנויות אחרות נכשלות בריצה.
- **Tracked Products Suite (`manage_tracker.py`)**: כלי ניהול מובנה ב-CLI למעקב, הוספה, הסרה והרצה של סוויטת מוצרים נבחרים (וודקה בלוגה, רוסקי, קברנה סוביניון, ג'וני בלאק ועוד) לאיתור מבצעי פתאום.
- **Progressive Querying (WooCommerce & Magento REST APIs)**: מנגנון חיפוש דו-שלבי חכם עוקף מגבלות מנועי חיפוש קשיחים: מחפש קודם לפי 2 מילים, ובמידה ואין תוצאות, מבצע פולבק למילה הבודדת הראשונה (למשל מותג) ומבצע סינון ודפליקציה בתוך קוד הפייתון.
- **Smart Hebrew Alias Normalization**: אלגוריתם ייחודי המזהה ומנרמל קיצורים ושגיאות כתיב נפוצים בעולם היין הישראלי:
  * `"ק.ס"` / `"ק"ס"` / `"קס"` $\leftarrow$ `"קברנה סוביניון"` (התאמה מלאה של "ירדן ק.ס 2022" ל-"ירדן קברנה סוביניון 2022").
  * `"ס.ב"` / `"ס"ב"` / `"סב"` $\leftarrow$ `"סוביניון בלאן"`.
  * `"סובניון"` / `"סביניון"` $\leftarrow$ `"סוביניון"` (תיקון שגיאות כתיב של חנויות).
  * ניקוי קידומות מפריעות: `"יין"`, `"בקבוק של"`, `"מארז"`, `"וויסקי"`.
- **Dynamic Relevance Thresholds**: סינון אוטומטי של מוצרים לא קשורים. שאילתות של 4+ מילים דורשות לפחות 3 התאמות מדויקות (מונע מ-"יין ירדן קברנה פרנק" להתאים ל-"ירדן קברנה סוביניון").

---

## 📂 מבנה הפרויקט

```text
turk-price-intelligence/
├── manage_tracker.py                   ← כלי ניהול סוויטת מעקב המוצרים (list, add, remove, run)
├── run.py                              ← CLI Entry point ראשי להרצת שאילתה ידנית
├── config.yaml                         ← הגדרות וקישורים ל-19 החנויות הנסרקות
├── requirements.txt                    ← תלויות פייתון
├── src/
│   ├── models.py                       ← Pydantic Models (ProductPrice, Store, PriceReport)
│   ├── logger.py                       
│   ├── scrapers/
│   │   ├── unified_scraper.py          ← מנוע הפיצול הראשי, פילטרים, ו-WooCommerce/Magento APIs
│   │   ├── api_scrapers.py             ← API חנות הטורקי ישירות
│   │   ├── html_scrapers.py            ← Fallback HTML Scrapers המבוססים על CloakBrowser
│   │   └── playwright_scrapers.py      ← סקראפרים ייעודיים ל-Magento (פאנקו, היבואן) ו-JS heavy
│   ├── storage/
│   │   └── sqlite_store.py             ← לוגיקת SQLite (חיבור, יצירת טבלאות ושמירת נתונים)
│   └── utils/
│       └── filters.py                  ← פילטרים אלגוריתמיים, ניקוי שמות, נרמול וסינון
└── data/                               ← תיקיית תוצאות ודוחות (נוצרת אוטומטית)
    ├── price_intel.db                  ← בסיס הנתונים הראשי של SQLite
    ├── *.json                          ← דוחות גולמיים
    ├── *.txt                           ← דוחות קריאים המותאמים למשלוח בטלגרם
    └── *.csv                           ← אקסלים השוואתיים ומעקב היסטורי לאורך זמן
```

---

## 🛠️ התקנה ודרישות קדם

המערכת רצה על סביבת לינוקס ודורשת דפדפן Chromium מותקן.

```bash
# שכפול הריפו וכניסה לתיקייה
git clone https://github.com/andrewvlk88/turk-price-intelligence.git
cd turk-price-intelligence

# יצירת סביבה וירטואלית והפעלתה
python3 -m venv venv
source venv/bin/activate

# התקנת חבילות פייתון (כולל CloakBrowser)
pip install -r requirements.txt
pip install cloakbrowser

# התקנת מנוע Playwright ב-Venv
playwright install chromium
```

---

## 💻 הוראות שימוש והרצה

⚠️ **חובה להפעיל תמיד מתוך ה-venv של הפרויקט!**

### 1. כלי ניהול סוויטת מעקב המחירים (`manage_tracker.py`)

מנהל את רשימת המוצרים הקבועה שאתה רוצה לנטר לאיתור מבצעים.

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

סריקת השוואת מחירים למוצר ספציפי מחוץ לרשימת המעקב:

```bash
# הרצה רגילה (מדפיסה טבלה קריאה עם אמוג'ים)
python run.py "וודקה בלוגה ליטר"

# הרצה מושתקת עם פלט JSON נקי (מיועד לעוזרים אישיים/בוטים של AI)
python run.py "בלוגה" --agent-mode
```

---

## 🕷️ ארכיטקטורת הסקראפינג (19 חנויות)

| רמת סריקה | מנוע טכנולוגי | חנויות נסרקות | יתרונות ושיקולים |
|-----------|---------------|---------------|------------------|
| **1. REST API** | HTTPS ישיר | **הטורקי (API)** | מהירות שיא (~200ms), אינו דורש הפעלת דפדפן. |
| **2. WooCommerce Store API** | HTTP requests מנורמלים | **בנא, דרך היין, ארי משקאות, Liquor Store, אלכוהום, משקאות המשמח, Coffeco, Alcohol123, בית היין** | מהיר ויציב ביותר. עבר שדרוג לתמיכה בחיפוש פרוגרסיבי דו-שלבי וקיבולת של 100 מוצרים לתוצאה. |
| **3. CloakBrowser + Magento Extractor** | Stealth Chromium + Beautiful Soup | **פאנקו, היבואן** | מעקף מוחלט של Cloudflare. שימוש במחלץ סלקטורים מותאם אישית למבנה Magento (תומך ב-`div.product-item` וב-`li.product`). |
| **4. CloakBrowser HTML Fallback** | Stealth Chromium | **אליאסי משקאות, לגימה, שר המשקאות, Drinks4U** | טעינה בטוחה של ה-HTML המרונדר דרך דפדפן CloakBrowser עם בידוד סשנים מלא לכל חנות. |
| **5. Playwright Render Engine** | CloakBrowser Page Context | **מנו וינו, בית המשקאות של אביב, Wine & More** | אתרי SPA מורכבים במיוחד מבוססי JS/Shopify הדורשים המתנה ארוכה לרנדור הנתונים. |

---

## ⚠️ Pitfalls ולקחים קריטיים

1. **הרצה סדרתית בלבד**: CloakBrowser מקים תהליך Chromium שלם לכל חנות מבוססת דפדפן. ניסיונות להריץ במקביל יובילו לנעילת קבצי Session, צריכת זיכרון מופרזת וקריסת המנוע.
2. **דילוג על פופאפ גיל באתרי Magento**: פופאפ אימות הגיל ("אני מעל 18") באתרי פאנקו והיבואן גורם ללחיצה שגויה ב-JavaScript שמפנה לדפי קוקטיילים שבורים. הקוד מדלג אוטומטית על מנגנון הטיפול בפופאפ גיל בחנויות אלו.
3. **עבודה ללא persistent context**: שימוש ב-Session שמור קבוע גרם לפאנקו לטעון עוגיות ישנות ולהחזיר מוצרים לא קשורים. המנוע יוצר מופע נפרד ונקי (`launch_async`) לכל חנות וסוגר אותו מיד בסיום.
4. **מניעת שגיאות הרשאות Git**: דחיפת שינויים ל-GitHub עשויה להיכשל עם שגיאת 403 במקרה של Token פג תוקף. במקרה כזה יש לבצע רענון הרשאות באמצעות ה-GitHub CLI.
