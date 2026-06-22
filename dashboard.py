#!/usr/bin/env python3
"""Turkí Price Intelligence — Streamlit Dashboard (Hermes Teal RTL).

A gorgeous, highly customized cyberpunk teal dashboard for Andrew Volkov's
Turkí Price Intelligence system. Integrated with SQLite DB and Analyzer.
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from src.storage.sqlite_store import get_db, init_db, DB_PATH
from src.utils.filters import is_relevant_volume, extract_volume_ml

# ── Hermes Teal (Large) Cyberpunk Palette ──
HERMES_BG = "#070D14"          # Deep cosmic black-blue
HERMES_CARD = "#0F1C26"        # Tech-panel dark teal-gray
HERMES_TEAL = "#00FFC4"        # Neon glowing teal
HERMES_TEAL_DIM = "#00A383"    # Muted teal for borders and labels
HERMES_TEXT = "#CCFCF9"        # Soft cyan-white text
HERMES_MUTED = "#80A8A6"       # Steel-blue-teal helper text
HERMES_GREEN = "#00FF66"       # Toxic green for profits/deals
HERMES_RED = "#FF3B30"         # Crimson red for errors/anomalies
HERMES_AMBER = "#FFCC00"       # Cyberpunk yellow for sales

st.set_page_config(
    page_title="🦃 טורקי פרייס אינטליג׳נס",
    page_icon="🦃",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom Cyberpunk CSS for Hermes Teal ──
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Varela+Round&display=swap');

    /* ── Global Styles ── */
    .stApp {{
        background: linear-gradient(180deg, {HERMES_BG} 0%, #03060a 100%);
        color: {HERMES_TEXT};
        font-family: 'Varela Round', 'Share Tech Mono', sans-serif;
        direction: rtl;
    }}
    .stApp > header {{ background-color: transparent; }}
    
    /* ── Headers ── */
    h1, h2, h3, h4, h5, h6 {{
        color: {HERMES_TEAL} !important;
        text-shadow: 0 0 15px rgba(0, 255, 196, 0.4);
        font-family: 'Varela Round', sans-serif;
        font-weight: 700;
        text-align: right;
    }}
    h1 {{
        font-size: 2.8rem !important;
        letter-spacing: -0.5px;
    }}

    /* ── Sidebar (RTL) ── */
    section[data-testid="stSidebar"] {{
        background-color: {HERMES_CARD} !important;
        border-left: 2px solid {HERMES_TEAL_DIM}44 !important;
        border-right: none !important;
        direction: rtl;
    }}
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stSlider label {{
        color: {HERMES_TEAL} !important;
        font-weight: 600;
        text-align: right;
        display: block;
        text-shadow: 0 0 5px rgba(0, 255, 196, 0.2);
    }}

    /* ── Metrics ── */
    [data-testid="stMetric"] {{
        background-color: {HERMES_CARD};
        border: 1px solid {HERMES_TEAL_DIM}33;
        border-radius: 8px;
        padding: 16px 20px;
        box-shadow: 0 0 15px rgba(0, 255, 196, 0.05);
        direction: rtl;
    }}
    [data-testid="stMetricValue"] {{
        color: {HERMES_TEAL} !important;
        font-family: 'Share Tech Mono', monospace;
        font-weight: 700;
        font-size: 2rem !important;
        text-shadow: 0 0 10px rgba(0, 255, 196, 0.3);
    }}
    [data-testid="stMetricLabel"] {{
        color: {HERMES_MUTED} !important;
        font-size: 0.9rem;
        font-weight: 600;
        text-align: right;
    }}

    /* ── Tables ── */
    .stDataFrame table {{
        background-color: {HERMES_CARD} !important;
        direction: rtl;
    }}
    .stDataFrame thead th {{
        color: {HERMES_TEAL} !important;
        background-color: {HERMES_CARD} !important;
        text-align: right !important;
        font-weight: 700 !important;
    }}
    .stDataFrame tbody td {{
        color: {HERMES_TEXT} !important;
        background-color: {HERMES_CARD} !important;
        text-align: right !important;
    }}

    /* ── Tabs (RTL) ── */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 12px;
        background-color: {HERMES_CARD};
        border-radius: 8px;
        padding: 8px;
        border: 1px solid {HERMES_TEAL_DIM}22;
        direction: rtl;
    }}
    .stTabs [data-baseweb="tab"] {{
        color: {HERMES_MUTED};
        border-radius: 6px;
        padding: 10px 24px;
        font-weight: 600;
        font-size: 1rem;
        transition: all 0.25s;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {HERMES_TEAL};
        color: {HERMES_BG} !important;
        box-shadow: 0 0 12px rgba(0, 255, 196, 0.5);
        font-weight: 700;
    }}

    /* ── Buttons ── */
    .stButton>button {{
        background-color: transparent !important;
        color: {HERMES_TEAL} !important;
        border: 1px solid {HERMES_TEAL} !important;
        border-radius: 4px !important;
        font-weight: 600;
        transition: all 0.2s;
    }}
    .stButton>button:hover {{
        background-color: {HERMES_TEAL} !important;
        color: {HERMES_BG} !important;
        box-shadow: 0 0 15px rgba(0, 255, 196, 0.6);
    }}

    /* ── Custom Cards ── */
    .deal-card {{
        background-color: {HERMES_CARD};
        border-right: 4px solid {HERMES_TEAL};
        border-radius: 6px;
        padding: 14px 20px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        direction: rtl;
        transition: transform 0.2s;
    }}
    .deal-card:hover {{
        transform: scale(1.01);
    }}
    .deal-card.turki {{ border-right-color: {HERMES_GREEN}; }}
    .deal-card.sale {{ border-right-color: {HERMES_AMBER}; }}
    .deal-card.anomaly {{ border-right-color: {HERMES_RED}; }}
    
    .deal-card .deal-type {{
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 1px;
        text-align: right;
        margin-bottom: 4px;
    }}
    .deal-card.turki .deal-type {{ color: {HERMES_GREEN}; }}
    .deal-card.sale .deal-type {{ color: {HERMES_AMBER}; }}
    .deal-card.anomaly .deal-type {{ color: {HERMES_RED}; }}

    .deal-card .deal-product {{
        font-size: 1.15rem;
        font-weight: 700;
        color: {HERMES_TEXT};
        text-align: right;
    }}
    .deal-card .deal-meta {{
        font-size: 0.9rem;
        color: {HERMES_MUTED};
        text-align: right;
        margin-top: 6px;
    }}

    /* ── Store Rows (RTL) ── */
    .store-row {{
        padding: 8px 12px;
        background-color: {HERMES_CARD};
        border-right: 2px solid {HERMES_TEAL_DIM}22;
        border-radius: 4px;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        direction: rtl;
    }}
    .store-row .store-name {{
        color: {HERMES_TEXT};
        font-weight: 600;
        font-size: 1rem;
    }}
    .store-row .store-count {{
        color: {HERMES_MUTED};
        font-family: 'Share Tech Mono', monospace;
    }}
    .store-row .store-error {{
        color: {HERMES_RED};
        font-size: 0.85rem;
    }}

    /* ── Status Badges ── */
    .status-badge {{
        display: inline-block;
        padding: 4px 12px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        font-family: 'Share Tech Mono', monospace;
    }}
    .status-success {{ background: rgba(0, 255, 102, 0.12); color: {HERMES_GREEN}; border: 1px solid {HERMES_GREEN}33; }}
    .status-error {{ background: rgba(255, 59, 48, 0.12); color: {HERMES_RED}; border: 1px solid {HERMES_RED}33; }}
    .status-running {{ background: rgba(255, 204, 0, 0.12); color: {HERMES_AMBER}; border: 1px solid {HERMES_AMBER}33; }}
    .status-pending {{ background: rgba(128, 168, 166, 0.12); color: {HERMES_MUTED}; border: 1px solid {HERMES_MUTED}33; }}

    /* Scrollbars */
    ::-webkit-scrollbar {{
        width: 8px;
        height: 8px;
    }}
    ::-webkit-scrollbar-track {{
        background: {HERMES_BG};
    }}
    ::-webkit-scrollbar-thumb {{
        background: {HERMES_TEAL_DIM};
        border-radius: 4px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: {HERMES_TEAL};
    }}
</style>
""", unsafe_allow_html=True)


# ── Data loader with cache ──
@st.cache_data(ttl=15)
def load_data():
    """Load all relevant tables atomically."""
    init_db()
    conn = get_db()

    price_df = pd.read_sql_query("SELECT * FROM price_results ORDER BY timestamp DESC", conn)
    
    # Final guard: drop 200ml/500ml products from dashboard display
    try:
        price_df = price_df[price_df.apply(
            lambda row: is_relevant_volume(row['volume_ml']) if pd.notna(row['volume_ml']) else is_relevant_volume(extract_volume_ml(row['product_name'])),
            axis=1
        )]
    except Exception:
        pass
    
    status_df = pd.read_sql_query("SELECT * FROM store_status ORDER BY timestamp DESC", conn)
    tracked_df = pd.read_sql_query("SELECT * FROM tracked_queries ORDER BY id", conn)

    try:
        health_df = pd.read_sql_query("SELECT * FROM scraper_health ORDER BY timestamp DESC", conn)
    except Exception:
        health_df = pd.DataFrame()
    try:
        deals_df = pd.read_sql_query("SELECT * FROM deal_scores ORDER BY score DESC LIMIT 100", conn)
    except Exception:
        deals_df = pd.DataFrame()
    try:
        history_df = pd.read_sql_query("SELECT * FROM price_history ORDER BY recorded_at DESC", conn)
    except Exception:
        history_df = pd.DataFrame()

    conn.close()
    return price_df, status_df, tracked_df, health_df, deals_df, history_df


def load_data_with_retry(max_attempts=5, delay=0.5):
    """Load data with retry on database lock (WAL readers may clash)."""
    import time
    last_error = None
    for attempt in range(max_attempts):
        try:
            return load_data.__wrapped__()
        except Exception as e:
            last_error = e
            if "locked" in str(e).lower() and attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
                continue
            raise
    raise last_error


# Apply the retry wrapper over the cached loader
load_data = st.cache_data(ttl=15)(load_data_with_retry)


def apply_cyber_theme(fig, title=""):
    """Apply unified Hermes Teal design theme to Plotly charts."""
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(color=HERMES_TEAL, size=18, family="Varela Round"),
            x=1.0,
            xanchor="right"
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 28, 38, 0.5)",
        font=dict(color=HERMES_TEXT, family="Varela Round"),
        xaxis=dict(
            gridcolor="rgba(0,128,123,0.13)",
            zerolinecolor="rgba(0, 163, 131, 0.13)",
            tickfont=dict(color=HERMES_MUTED),
            automargin=True
        ),
        yaxis=dict(
            gridcolor="rgba(0,128,123,0.13)",
            zerolinecolor="rgba(0, 163, 131, 0.13)",
            tickfont=dict(color=HERMES_MUTED),
            automargin=True
        ),
        legend=dict(
            bgcolor=HERMES_CARD,
            bordercolor="rgba(0, 163, 131, 0.13)",
            borderwidth=1,
            font=dict(color=HERMES_TEXT)
        ),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def main():
    st.markdown("""
    <h1 style='text-align: right; font-size: 3rem; margin-bottom: 0;'>
        🦾 טורקי פרייס אינטליג׳נס
    </h1>
    <p style='text-align: right; color: #00ffc4; letter-spacing: 2px; margin-top: -5px; font-size: 0.95rem; font-family: \"Share Tech Mono\", monospace;'>
        HERMES CELESTIAL PRICE CONTROL v2.4
    </p>
    """, unsafe_allow_html=True)

    price_df, status_df, tracked_df, health_df, deals_df, history_df = load_data()

    if price_df.empty:
        st.warning("לא נמצאו נתונים במסד. הרץ `python run.py \"בלוגה\"` או הפעל את הקרון.")
        return

    # ── Sidebar Controls ──
    with st.sidebar:
        st.markdown("## ⚙️ קומנד סנטר")

        # Latest run only — no selector, just display it
        latest_run = price_df["run_id"].iloc[0]
        st.markdown(
            f'<p style="color:{HERMES_TEAL};font-size:0.9rem;text-align:right;font-weight:600;">'
            f'סבב סריקה: {latest_run[:19]}</p>',
            unsafe_allow_html=True,
        )
        selected_run = latest_run

        # Product Selector — only products from the latest run
        run_queries = sorted(
            price_df[price_df["run_id"] == selected_run]["query"].unique()
        )
        if not run_queries:
            st.warning("אין מוצרים בסבב האחרון")
            return
        selected_query = st.selectbox("מוצר נבחר", run_queries)

        st.markdown("---")
        st.markdown(
            f'<p style="color:{HERMES_MUTED};font-size:0.8rem;text-align:right;">'
            f'בסיס נתונים: {DB_PATH.name}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p style="color:{HERMES_MUTED};font-size:0.8rem;text-align:right;">'
            f'עדכון אחרון: {datetime.now().strftime("%H:%M:%S")}</p>',
            unsafe_allow_html=True,
        )

    # ── Filtered Datasets with Smart Fallback ──
    run_prices = price_df[
        (price_df["run_id"] == selected_run) &
        (price_df["query"] == selected_query)
    ]
    
    is_fallback = False
    fallback_run_name = ""
    run_status = pd.DataFrame()
    
    if run_prices.empty:
        query_runs = price_df[price_df["query"] == selected_query]["run_id"].unique()
        if len(query_runs) > 0:
            fallback_run = query_runs[0]
            fallback_run_name = fallback_run[:19]
            run_prices = price_df[
                (price_df["run_id"] == fallback_run) &
                (price_df["query"] == selected_query)
            ]
            run_status = status_df[
                (status_df["run_id"] == fallback_run) &
                (status_df["query"] == selected_query)
            ]
            is_fallback = True
    else:
        run_status = status_df[
            (status_df["run_id"] == selected_run) &
            (status_df["query"] == selected_query)
        ]

    # Show fallback info banner if needed
    if is_fallback:
        st.info(f"ℹ️ המוצר לא נסרק בסבב שנבחר. מציג נתונים מסבב אחרון זמין: {fallback_run_name}")

    # Find Haturki Baseline price
    turki_price_row = run_prices[run_prices["store_name"] == "הטורקי"]
    turki_price = None
    if not turki_price_row.empty:
        turki_price = turki_price_row.iloc[0]["sale_price"] or turki_price_row.iloc[0]["regular_price"]

    # Find cheapest store (excluding Turki itself)
    other_stores = run_prices[run_prices["store_name"] != "הטורקי"]
    cheapest_row = None
    cheapest_price = None
    cheapest_store_name = "N/A"
    
    if not other_stores.empty:
        other_stores = other_stores.copy()
        other_stores["effective_price"] = other_stores["sale_price"].fillna(other_stores["regular_price"])
        cheapest_row = other_stores.sort_values("effective_price").iloc[0]
        cheapest_price = cheapest_row["effective_price"]
        cheapest_store_name = cheapest_row["store_name"]

    # ── KPIs Row ──
    col1, col2, col3, col4 = st.columns(4)

    stores_responded = (
        run_status[run_status["status"] == "success"]["store_name"].nunique()
        if not run_status.empty else 0
    )
    stores_total = (
        run_status["store_name"].nunique() if not run_status.empty else 0
    )

    with col1:
        st.metric(
            "מחיר הטורקי (Baseline)",
            f"₪{turki_price:.0f}" if turki_price else "—",
        )
    with col2:
        st.metric(
            f"הכי זול בשוק ({cheapest_store_name})",
            f"₪{cheapest_price:.0f}" if cheapest_price else "—",
        )
    with col3:
        if turki_price and cheapest_price and cheapest_price < turki_price:
            savings_amount = turki_price - cheapest_price
            savings_percent = (savings_amount / turki_price) * 100
            st.metric(
                "חיסכון מירבי מול הטורקי",
                f"₪{savings_amount:.0f} (-{savings_percent:.0f}%)",
            )
        else:
            st.metric("חיסכון מירבי מול הטורקי", "—")
    with col4:
        st.metric(
            "סטטוס סריקת חנויות",
            f"{stores_responded}/{stores_total}",
        )

    st.markdown("---")

    # ── Sub-Sections Tabs (RTL) ──
    tab_overview, tab_deals, tab_history, tab_health = st.tabs([
        "📊 השוואת מחירים",
        "💰 דילים ומבצעים",
        "📈 היסטוריית מוצר",
        "🩺 בריאות הסריקה",
    ])

    # ── Tab 1: Price Comparison ──
    with tab_overview:
        st.markdown(f"### מחירים בכל החנויות עבור: **{selected_query}**")

        if not run_prices.empty:
            run_prices = run_prices.copy()
            run_prices["effective_price"] = run_prices["sale_price"].fillna(
                run_prices["regular_price"]
            )

            # Bar Chart
            store_avg = run_prices.groupby("store_name").agg(
                price=("effective_price", "mean"),
            ).reset_index().sort_values("price", ascending=True)

            # Color scale with Haturki marked differently
            colors = [
                HERMES_GREEN if row["store_name"] == cheapest_store_name
                else HERMES_TEAL_DIM if row["store_name"] == "הטורקי"
                else HERMES_TEAL
                for _, row in store_avg.iterrows()
            ]

            fig = px.bar(
                store_avg,
                x="store_name",
                y="price",
                labels={"store_name": "חנות", "price": "מחיר אפקטיבי (₪)"},
            )
            fig.update_traces(
                marker_color=colors,
                texttemplate="₪%{y:.0f}",
                textposition="outside",
                textfont=dict(color=HERMES_TEXT, size=11),
            )
            apply_cyber_theme(fig, "מפת מחירים תחרותית (מחיר זול בירוק, הטורקי בכחול-כהה)")
            st.plotly_chart(fig, use_container_width=True)

            # Details Table
            st.markdown("### טבלת נתונים מפורטת")
            st.dataframe(
                run_prices.sort_values("effective_price")[[
                    "store_name", "product_name", "regular_price",
                    "sale_price", "is_on_sale", "product_url"
                ]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "store_name": "חנות",
                    "product_name": "שם מוצר בחנות",
                    "regular_price": st.column_config.NumberColumn("מחיר רגיל", format="₪%.0f"),
                    "sale_price": st.column_config.NumberColumn("מחיר מבצע", format="₪%.0f"),
                    "is_on_sale": st.column_config.CheckboxColumn("במבצע?"),
                    "product_url": st.column_config.LinkColumn("קישור ישיר"),
                },
            )
        else:
            st.info("אין נתונים למוצר זה")

    # ── Tab 2: Deals & Sales ──
    with tab_deals:
        st.markdown(f"### דילים חמים עבור: **{selected_query}**")

        # 1. Turki Beaters (Cheaper than Turki by 5%+)
        turki_deals = []
        if turki_price and not other_stores.empty:
            for _, row in other_stores.iterrows():
                best = row["effective_price"]
                if best and best < turki_price:
                    diff = turki_price - best
                    pct = (diff / turki_price) * 100
                    if pct >= 5:
                        turki_deals.append({
                            "product": row["product_name"],
                            "store": row["store_name"],
                            "price": best,
                            "turki_price": turki_price,
                            "savings": diff,
                            "percent": pct,
                        })

        # 2. General Sales (10%+ off)
        general_sales = []
        for _, row in run_prices.iterrows():
            if row["is_on_sale"] == 1 and row["regular_price"] and row["sale_price"]:
                diff = row["regular_price"] - row["sale_price"]
                pct = (diff / row["regular_price"]) * 100
                if pct >= 10:
                    general_sales.append({
                        "product": row["product_name"],
                        "store": row["store_name"],
                        "price": row["sale_price"],
                        "regular": row["regular_price"],
                        "percent": pct,
                    })

        col_deals_left, col_deals_right = st.columns(2)

        with col_deals_left:
            st.markdown("#### 💰 מוצרים זולים מהטורקי (חיסכון 5%+)")
            if turki_deals:
                # Sort by highest savings %
                turki_deals.sort(key=lambda x: x["percent"], reverse=True)
                for d in turki_deals:
                    st.markdown(f"""
                    <div class="deal-card turki">
                        <div class="deal-type">💰 זול מהטורקי ב-{d['percent']:.0f}%</div>
                        <div class="deal-product">{d['product']}</div>
                        <div class="deal-meta">
                            חנות: <b>{d['store']}</b> | 
                            מחיר: <b>₪{d['price']:.0f}</b> (הטורקי: ₪{d['turki_price']:.0f}) | 
                            חיסכון: <span style='color: {HERMES_GREEN}; font-weight: 700;'>₪{d['savings']:.0f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("לא נמצאו מוצרים הזולים מהטורקי בסבב זה.")

        with col_deals_right:
            st.markdown("#### 🔥 מבצעים חזקים (הנחה של 10%+)")
            if general_sales:
                general_sales.sort(key=lambda x: x["percent"], reverse=True)
                for d in general_sales:
                    st.markdown(f"""
                    <div class="deal-card sale">
                        <div class="deal-type">🔥 הנחה של {d['percent']:.0f}%</div>
                        <div class="deal-product">{d['product']}</div>
                        <div class="deal-meta">
                            חנות: <b>{d['store']}</b> | 
                            מחיר מבצע: <b>₪{d['price']:.0f}</b> (במקום ₪{d['regular']:.0f})
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("לא נמצאו מבצעים מיוחדים של 10%+ בסבב זה.")

    # ── Tab 3: Historical Trends ──
    with tab_history:
        st.markdown(f"### מגמת מחירים לאורך זמן: **{selected_query}**")

        # Load trends for the specific query across ALL run_ids
        trend_data = price_df[price_df["query"] == selected_query].copy()
        if not trend_data.empty:
            trend_data["effective_price"] = trend_data["sale_price"].fillna(
                trend_data["regular_price"]
            )
            trend_data = trend_data.dropna(subset=["effective_price"])

            # Group by run date/timestamp and store to show average price per store over time
            trend_agg = trend_data.groupby(["timestamp", "store_name"])["effective_price"].mean().reset_index()
            trend_agg = trend_agg.sort_values("timestamp")

            fig_trend = px.line(
                trend_agg,
                x="timestamp",
                y="effective_price",
                color="store_name",
                line_shape="spline",
                labels={
                    "timestamp": "זמן סריקה",
                    "effective_price": "מחיר ממוצע (₪)",
                    "store_name": "חנות",
                },
            )
            fig_trend.update_traces(line=dict(width=2.5))
            apply_cyber_theme(fig_trend, f"השתנות המחיר לפי חנות (היסטוריית ריצות)")
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("אין מספיק נתונים היסטוריים להצגת מגמה.")

    # ── Tab 4: Scraper Health ──
    with tab_health:
        st.markdown("### ניטור ובריאות מערכת הסריקה")

        if not run_status.empty:
            col_h1, col_h2 = st.columns([1, 2])

            with col_h1:
                status_counts = run_status["status"].value_counts().reset_index()
                status_counts.columns = ["status", "count"]
                
                status_colors = {
                    "success": HERMES_GREEN,
                    "error": HERMES_RED,
                    "running": HERMES_AMBER,
                    "pending": HERMES_MUTED,
                }
                
                fig_health = go.Figure(data=[go.Pie(
                    labels=status_counts["status"],
                    values=status_counts["count"],
                    marker=dict(colors=[
                        status_colors.get(s, HERMES_TEAL)
                        for s in status_counts["status"]
                    ]),
                    hole=0.6,
                )])
                fig_health.update_traces(textfont=dict(color=HERMES_TEXT))
                apply_cyber_theme(fig_health, "התפלגות סטטוסים בריצה הנוכחית")
                st.plotly_chart(fig_health, use_container_width=True)

            with col_h2:
                st.markdown("#### סטטוס ריצה מפורט")
                for _, row in run_status.sort_values("store_name").iterrows():
                    badge = (
                        f'<span class="status-badge status-{row["status"]}">'
                        f'{row["status"].upper()}</span>'
                    )
                    count = row.get("product_count", 0)
                    st.markdown(
                        f'<div class="store-row">{badge} '
                        f'<span class="store-name">{row["store_name"]}</span> '
                        f'<span class="store-count">— {count} מוצרים נמצאו</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if row["status"] == "error" and row.get("error_msg"):
                        st.markdown(
                            f'<div style="color:{HERMES_RED};font-size:0.8rem;padding-right:32px;text-align:right;">'
                            f'⚠️ שגיאה: {row["error_msg"][:150]}</div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.info("אין נתוני סטטוס לריצה זו.")


if __name__ == "__main__":
    main()