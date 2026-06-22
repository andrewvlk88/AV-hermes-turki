#!/usr/bin/env python3
"""Turkí Price Intelligence — Streamlit Dashboard.

Hermes Teal design system. Run with:
    cd ~/turk-price-intelligence
    ./venv/bin/streamlit run dashboard.py --server.port 8501 --server.headless true
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import sqlite3

from src.storage.sqlite_store import get_db, init_db, DB_PATH

# ── Hermes Teal Design System ──
HERMES_TEAL = "#00B5AD"
HERMES_TEAL_DARK = "#00807B"
HERMES_TEAL_LIGHT = "#E0F7F5"
HERMES_BG = "#0F1419"
HERMES_CARD = "#1A2330"
HERMES_TEXT = "#E0E0E0"
HERMES_MUTED = "#8899AA"
HERMES_GREEN = "#00D977"
HERMES_RED = "#FF4757"
HERMES_AMBER = "#FFA502"

# Page config
st.set_page_config(
    page_title="🦃 טורקי פרייס אינטליג׳נס",
    page_icon="🦃",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject CSS
st.markdown(f"""
<style>
    /* ── Global ── */
    .stApp {{
        background-color: {HERMES_BG};
        color: {HERMES_TEXT};
    }}
    .stApp > header {{ background-color: transparent; }}
    .stApp > section[data-testid="stMain"] > div {{
        padding-top: 1rem;
    }}

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {{
        background-color: {HERMES_CARD};
        border-right: 1px solid {HERMES_TEAL_DARK}33;
    }}
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stSlider label {{
        color: {HERMES_TEAL} !important;
        font-weight: 600;
    }}

    /* ── Metrics ── */
    [data-testid="stMetric"] {{
        background-color: {HERMES_CARD};
        border: 1px solid {HERMES_TEAL_DARK}22;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }}
    [data-testid="stMetricValue"] {{
        color: {HERMES_TEAL} !important;
        font-weight: 700;
    }}
    [data-testid="stMetricLabel"] {{
        color: {HERMES_MUTED} !important;
        font-size: 0.85rem;
    }}

    /* ── Headers ── */
    h1, h2, h3 {{
        color: {HERMES_TEAL} !important;
    }}
    h1 {{ font-weight: 800; letter-spacing: -0.5px; }}
    h2 {{ font-weight: 700; }}

    /* ── Tables ── */
    .stDataFrame table {{
        background-color: {HERMES_CARD} !important;
    }}
    .stDataFrame thead th {{
        color: {HERMES_TEAL} !important;
        background-color: {HERMES_CARD} !important;
    }}
    .stDataFrame tbody td {{
        color: {HERMES_TEXT} !important;
        background-color: {HERMES_CARD} !important;
    }}

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 8px;
        background-color: {HERMES_CARD};
        border-radius: 10px;
        padding: 6px;
    }}
    .stTabs [data-baseweb="tab"] {{
        color: {HERMES_MUTED};
        border-radius: 8px;
        padding: 8px 20px;
        font-weight: 600;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {HERMES_TEAL};
        color: {HERMES_BG} !important;
    }}

    /* ── Text ── */
    .stMarkdown p {{ color: {HERMES_TEXT}; }}
    .stCode block {{
        background-color: {HERMES_CARD} !important;
        border: 1px solid {HERMES_TEAL_DARK}33;
    }}

    /* ── Alerts ── */
    .stAlert {{
        background-color: {HERMES_CARD} !important;
        border: 1px solid {HERMES_TEAL_DARK}33;
    }}

    /* ── Plotly ── */
    .stPlotlyChart {{
        background-color: {HERMES_CARD};
        border: 1px solid {HERMES_TEAL_DARK}22;
        border-radius: 12px;
        padding: 8px;
    }}

    /* ── Dividers ── */
    hr {{
        border-color: {HERMES_TEAL_DARK}33;
    }}

    /* ── Custom cards ── */
    .deal-card {{
        background-color: {HERMES_CARD};
        border-left: 3px solid {HERMES_TEAL};
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }}
    .deal-card.turki {{ border-left-color: {HERMES_GREEN}; }}
    .deal-card.sale {{ border-left-color: {HERMES_AMBER}; }}
    .deal-card.anomaly {{ border-left-color: {HERMES_RED}; }}
    .deal-card .deal-type {{
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .deal-card .deal-product {{
        font-size: 1.1rem;
        font-weight: 700;
        color: {HERMES_TEXT};
    }}
    .deal-card .deal-meta {{
        font-size: 0.9rem;
        color: {HERMES_MUTED};
    }}

    /* ── Status badge ── */
    .status-badge {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }}
    .status-success {{ background: {HERMES_GREEN}22; color: {HERMES_GREEN}; }}
    .status-error {{ background: {HERMES_RED}22; color: {HERMES_RED}; }}
    .status-running {{ background: {HERMES_AMBER}22; color: {HERMES_AMBER}; }}
    .status-pending {{ background: {HERMES_MUTED}22; color: {HERMES_MUTED}; }}
</style>
""", unsafe_allow_html=True)


# ── DB helpers ──
@st.cache_data(ttl=30)
def load_data():
    """Load all relevant data from SQLite."""
    init_db()
    conn = get_db()

    # Price results (latest run per query)
    price_df = pd.read_sql_query("""
        SELECT * FROM price_results
        ORDER BY timestamp DESC
    """, conn)

    # Store status
    status_df = pd.read_sql_query("""
        SELECT * FROM store_status
        ORDER BY timestamp DESC
    """, conn)

    # Tracked queries
    tracked_df = pd.read_sql_query("""
        SELECT * FROM tracked_queries ORDER BY id
    """, conn)

    # Scraper health (if table has data)
    try:
        health_df = pd.read_sql_query("""
            SELECT * FROM scraper_health ORDER BY timestamp DESC
        """, conn)
    except Exception:
        health_df = pd.DataFrame()

    # Deal scores (if table has data)
    try:
        deals_df = pd.read_sql_query("""
            SELECT * FROM deal_scores ORDER BY score DESC LIMIT 100
        """, conn)
    except Exception:
        deals_df = pd.DataFrame()

    # Price history (if table has data)
    try:
        history_df = pd.read_sql_query("""
            SELECT * FROM price_history ORDER BY recorded_at DESC
        """, conn)
    except Exception:
        history_df = pd.DataFrame()

    conn.close()
    return price_df, status_df, tracked_df, health_df, deals_df, history_df


def get_latest_run_id(price_df: pd.DataFrame) -> str:
    """Get the most recent run_id."""
    if price_df.empty:
        return ""
    return price_df.iloc[0]["run_id"]


def plotly_layout(fig, title=""):
    """Apply Hermes Teal theme to Plotly figures."""
    fig.update_layout(
        title=dict(text=title, font=dict(color=HERMES_TEAL, size=16)),
        plot_bgcolor=HERMES_CARD,
        paper_bgcolor=HERMES_CARD,
        font=dict(color=HERMES_TEXT, family="Arial"),
        xaxis=dict(gridcolor=HERMES_TEAL_DARK + "22", color=HERMES_MUTED),
        yaxis=dict(gridcolor=HERMES_TEAL_DARK + "22", color=HERMES_MUTED),
        legend=dict(bgcolor=HERMES_CARD, font=dict(color=HERMES_TEXT)),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


# ── Main ──
def main():
    st.title("🦃 טורקי פרייס אינטליג׳נס")
    st.markdown(f'<p style="color:{HERMES_MUTED};font-size:0.9rem;">דשבורד מודיעין מחירים · עדכון אוטומטי כל 30 שניות</p>', unsafe_allow_html=True)

    price_df, status_df, tracked_df, health_df, deals_df, history_df = load_data()

    # ── Sidebar ──
    with st.sidebar:
        st.markdown(f"## ⚙️ בקרה")

        # Run selector
        if not price_df.empty:
            run_ids = price_df["run_id"].unique()[:20]
            selected_run = st.selectbox("ריצה", run_ids, format_func=lambda x: x[:19])
        else:
            selected_run = ""
            st.info("אין נתונים עדיין")

        # Query selector
        if not price_df.empty:
            queries = price_df["query"].unique()
            selected_query = st.selectbox("מוצר", ["הכל"] + list(queries))
        else:
            selected_query = "הכל"

        st.markdown("---")
        st.markdown(f'<p style="color:{HERMES_MUTED};font-size:0.8rem;">DB: {DB_PATH.name}</p>', unsafe_allow_html=True)
        st.markdown(f'<p style="color:{HERMES_MUTED};font-size:0.8rem;">עודכן: {datetime.now().strftime("%H:%M:%S")}</p>', unsafe_allow_html=True)

    if price_df.empty:
        st.warning("לא נמצאו נתונים במסד. הרץ `python run.py \"בלוגה\"` או הפעל את הקרון.")
        return

    # ── Filter data ──
    run_prices = price_df[price_df["run_id"] == selected_run]
    if selected_query != "הכל":
        run_prices = run_prices[run_prices["query"] == selected_query]
        run_status = status_df[(status_df["run_id"] == selected_run) & (status_df["query"] == selected_query)]
    else:
        run_status = status_df[status_df["run_id"] == selected_run]

    # ── KPI Row ──
    col1, col2, col3, col4 = st.columns(4)

    stores_responded = run_status[run_status["status"] == "success"]["store_name"].nunique() if not run_status.empty else 0
    stores_total = run_status["store_name"].nunique() if not run_status.empty else 0
    total_products = len(run_prices)
    on_sale = run_prices["is_on_sale"].sum() if "is_on_sale" in run_prices.columns else 0

    with col1:
        st.metric("חנויות הגיבו", f"{stores_responded}/{stores_total}")
    with col2:
        st.metric("מוצרים נמצאו", f"{total_products}")
    with col3:
        st.metric("במבצע", f"{on_sale}")
    with col4:
        if not run_prices.empty:
            avg_price = run_prices["regular_price"].dropna().mean()
            st.metric("מחיר ממוצע", f"₪{avg_price:.0f}" if avg_price else "—")
        else:
            st.metric("מחיר ממוצע", "—")

    st.markdown("---")

    # ── Tabs ──
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 סקירה",
        "🏪 חנויות",
        "💰 דילים",
        "📈 היסטוריה",
        "🩺 בריאות",
    ])

    # ── Tab 1: Overview ──
    with tab1:
        st.markdown("### מחירים לפי חנות")

        if not run_prices.empty:
            # Bar chart: avg price per store
            store_avg = run_prices.groupby("store_name").agg(
                avg_price=("regular_price", "mean"),
                count=("product_name", "count")
            ).reset_index().sort_values("avg_price")

            fig = px.bar(
                store_avg,
                x="store_name",
                y="avg_price",
                color="avg_price",
                color_continuous_scale=[HERMES_TEAL, HERMES_TEAL_DARK],
                text="avg_price",
                labels={"store_name": "חנות", "avg_price": "מחיר ממוצע (₪)"},
            )
            fig.update_traces(texttemplate="₪%{text:.0f}", textposition="outside")
            plotly_layout(fig, "מחיר ממוצע לפי חנות")
            st.plotly_chart(fig, use_container_width=True)

            # Recent products table
            st.markdown("### מוצרים אחרונים")
            display_cols = ["store_name", "product_name", "regular_price", "sale_price", "is_on_sale"]
            avail_cols = [c for c in display_cols if c in run_prices.columns]
            st.dataframe(
                run_prices[avail_cols].head(50),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("אין נתונים לריצה זו")

    # ── Tab 2: Stores ──
    with tab2:
        st.markdown("### סטטוס חנויות")

        if not run_status.empty:
            # Status breakdown
            status_counts = run_status["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]

            col_a, col_b = st.columns([1, 2])

            with col_a:
                status_colors = {
                    "success": HERMES_GREEN,
                    "error": HERMES_RED,
                    "running": HERMES_AMBER,
                    "pending": HERMES_MUTED,
                }
                fig_pie = go.Figure(data=[go.Pie(
                    labels=status_counts["status"],
                    values=status_counts["count"],
                    marker=dict(colors=[status_colors.get(s, HERMES_TEAL) for s in status_counts["status"]]),
                    hole=0.6,
                )])
                fig_pie.update_traces(textfont=dict(color=HERMES_TEXT))
                plotly_layout(fig_pie, "סטטוס ריצה")
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_b:
                # Store detail table
                status_display = run_status.copy()
                status_display["status"] = status_display["status"].apply(
                    lambda s: f'<span class="status-badge status-{s}">{s}</span>'
                )

                st.markdown("**פירוט לפי חנות:**")
                for _, row in run_status.iterrows():
                    badge = f'<span class="status-badge status-{row["status"]}">{row["status"].upper()}</span>'
                    count = row.get("product_count", 0)
                    st.markdown(
                        f'<div style="padding:4px 0;">{badge} '
                        f'<span style="color:{HERMES_TEXT};margin-right:12px;">{row["store_name"]}</span> '
                        f'<span style="color:{HERMES_MUTED};">— {count} מוצרים</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if row["status"] == "error" and row.get("error_msg"):
                        st.markdown(
                            f'<div style="color:{HERMES_RED};font-size:0.8rem;padding-right:20px;">⚠️ {row["error_msg"][:100]}</div>',
                            unsafe_allow_html=True
                        )
        else:
            st.info("אין נתוני סטטוס לריצה זו")

    # ── Tab 3: Deals ──
    with tab3:
        st.markdown("### דילים ומבצעים")

        if not deals_df.empty:
            # Deal cards
            for _, deal in deals_df.head(20).iterrows():
                dtype = deal.get("deal_type", "turki")
                icon = {"turki": "💰", "sale": "🔥", "anomaly": "⚠️"}.get(dtype, "📊")
                product = deal.get("product_name", "?")
                store = deal.get("store_name", "?")
                price = deal.get("price", 0)
                turki = deal.get("turki_price")
                savings = deal.get("savings_amount")
                pct = deal.get("savings_percent")

                meta_parts = [f"{store}"]
                if turki:
                    meta_parts.append(f"הטורקי ₪{turki:.0f}")
                if savings:
                    meta_parts.append(f"חיסכון ₪{savings:.0f} ({pct:.0f}%)")

                st.markdown(
                    f'<div class="deal-card {dtype}">'
                    f'<div class="deal-type">{icon} {dtype}</div>'
                    f'<div class="deal-product">{product}</div>'
                    f'<div class="deal-meta">{" · ".join(meta_parts)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # Score distribution
            st.markdown("### דירוג דילים")
            fig_deals = px.bar(
                deals_df.head(30),
                x="product_name",
                y="score",
                color="deal_type",
                color_discrete_map={"turki": HERMES_GREEN, "sale": HERMES_AMBER, "anomaly": HERMES_RED},
                labels={"product_name": "מוצר", "score": "ציון"},
            )
            plotly_layout(fig_deals, "דירוג דילים לפי ציון")
            st.plotly_chart(fig_deals, use_container_width=True)
        else:
            # Fallback: find deals from price_results
            st.info("טבלת deal_scores ריקה — מציג מבצעים מ-price_results")

            if not run_prices.empty:
                sales = run_prices[run_prices["is_on_sale"] == 1].copy()
                if not sales.empty:
                    sales["discount"] = sales["regular_price"] - sales["sale_price"].fillna(sales["regular_price"])
                    sales = sales[sales["discount"] > 0].sort_values("discount", ascending=False).head(20)

                    for _, row in sales.iterrows():
                        pct = (row["discount"] / row["regular_price"]) * 100 if row["regular_price"] else 0
                        st.markdown(
                            f'<div class="deal-card sale">'
                            f'<div class="deal-type">🔥 SALE</div>'
                            f'<div class="deal-product">{row["product_name"]}</div>'
                            f'<div class="deal-meta">{row["store_name"]} · ₪{row["sale_price"]:.0f} '
                            f'(במקום ₪{row["regular_price"]:.0f}, -{pct:.0f}%)</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                else:
                    st.markdown(f'<p style="color:{HERMES_MUTED};">אין מבצעים בריצה זו</p>', unsafe_allow_html=True)

    # ── Tab 4: Price History ──
    with tab4:
        st.markdown("### היסטוריית מחירים")

        if not history_df.empty:
            # Price trend chart
            product_filter = st.selectbox(
                "מוצר למעקב",
                ["הכל"] + sorted(history_df["product_name"].unique().tolist()),
                key="history_product"
            )

            if product_filter != "הכל":
                hist_filtered = history_df[history_df["product_name"] == product_filter]
            else:
                hist_filtered = history_df

            if not hist_filtered.empty:
                hist_filtered["effective_price"] = hist_filtered["sale_price"].fillna(
                    hist_filtered["regular_price"]
                )
                fig_hist = px.line(
                    hist_filtered,
                    x="recorded_at",
                    y="effective_price",
                    color="store_name",
                    line_shape="spline",
                    labels={"recorded_at": "תאריך", "effective_price": "מחיר (₪)", "store_name": "חנות"},
                )
                fig_hist.update_traces(line=dict(width=2))
                plotly_layout(fig_hist, f"מגמת מחירים — {product_filter}")
                st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("טבלת price_history ריקה — הנתונים יתחילו להצטבר בריצות הבאות")

        # Also show historical trends from price_results (fallback)
        st.markdown("### מגמת מחירים מ-price_results (כל הריצות)")
        if not price_df.empty:
            trend_df = price_df.copy()
            trend_df["effective_price"] = trend_df["sale_price"].fillna(trend_df["regular_price"])
            trend_df = trend_df.dropna(subset=["effective_price"])

            # Pick top products
            top_products = trend_df["product_name"].value_counts().head(5).index.tolist()
            trend_df = trend_df[trend_df["product_name"].isin(top_products)]

            if not trend_df.empty:
                trend_agg = trend_df.groupby(["timestamp", "product_name"])["effective_price"].mean().reset_index()
                fig_trend = px.line(
                    trend_agg,
                    x="timestamp",
                    y="effective_price",
                    color="product_name",
                    labels={"timestamp": "זמן ריצה", "effective_price": "מחיר ממוצע (₪)", "product_name": "מוצר"},
                )
                fig_trend.update_traces(line=dict(width=2))
                plotly_layout(fig_trend, "מגמת מחירים — 5 מוצרים מובילים")
                st.plotly_chart(fig_trend, use_container_width=True)

    # ── Tab 5: Scraper Health ──
    with tab5:
        st.markdown("### בריאות סקרייפרים")

        if not health_df.empty:
            col_x, col_y = st.columns(2)

            with col_x:
                fig_resp = px.line(
                    health_df.sort_values("timestamp"),
                    x="timestamp",
                    y="response_rate",
                    markers=True,
                    labels={"timestamp": "זמן", "response_rate": "אחוז תגובה"},
                )
                fig_resp.update_traces(line=dict(color=HERMES_TEAL, width=2))
                plotly_layout(fig_resp, "אחוז תגובת חנויות לאורך זמן")
                st.plotly_chart(fig_resp, use_container_width=True)

            with col_y:
                fig_deals = px.bar(
                    health_df.sort_values("timestamp"),
                    x="timestamp",
                    y="deal_count",
                    color="deal_count",
                    color_continuous_scale=[HERMES_TEAL, HERMES_GREEN],
                    labels={"timestamp": "זמן", "deal_count": "מספר דילים"},
                )
                plotly_layout(fig_deals, "דילים שנמצאו לאורך זמן")
                st.plotly_chart(fig_deals, use_container_width=True)

            # Health table
            st.markdown("### פירוט ריצות")
            st.dataframe(
                health_df[["timestamp", "query", "stores_checked", "stores_responded",
                          "response_rate", "deal_count", "anomaly_count"]].head(30),
                use_container_width=True,
                hide_index=True,
            )
        else:
            # Fallback: compute health from store_status
            st.info("טבלת scraper_health ריקה — מחשב מ-store_status")

            if not status_df.empty:
                # Success rate per store across all runs
                store_health = status_df.groupby("store_name").agg(
                    total_runs=("status", "count"),
                    successes=("status", lambda x: (x == "success").sum()),
                    errors=("status", lambda x: (x == "error").sum()),
                ).reset_index()
                store_health["success_rate"] = (store_health["successes"] / store_health["total_runs"] * 100).round(1)
                store_health = store_health.sort_values("success_rate", ascending=True)

                fig_health = px.bar(
                    store_health,
                    x="store_name",
                    y="success_rate",
                    color="success_rate",
                    color_continuous_scale=[HERMES_RED, HERMES_AMBER, HERMES_GREEN],
                    text="success_rate",
                    labels={"store_name": "חנות", "success_rate": "אחוז הצלחה"},
                )
                fig_health.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
                plotly_layout(fig_health, "אחוז הצלחה לפי חנות (כל הריצות)")
                st.plotly_chart(fig_health, use_container_width=True)

                st.dataframe(store_health, use_container_width=True, hide_index=True)

    # ── Footer ──
    st.markdown("---")
    st.markdown(
        f'<p style="color:{HERMES_MUTED};font-size:0.75rem;text-align:center;">'
        f'🪽 Hermes · Turkí Price Intelligence v2.4 · {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        f'</p>',
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()