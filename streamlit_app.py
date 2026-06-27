# streamlit_app.py
# Professional Chartink stock screening dashboard.

from __future__ import annotations

import json
import re
import time
import hashlib
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:  # Plotly is required for the custom chart engine page.
    go = None
    make_subplots = None

try:
    import yfinance as yf
except ImportError:  # Optional dependency for local OHLCV enrichment.
    yf = None


APP_TITLE = "IQ-5000 NSE Intelligence Platform"
TOKEN_URL = "https://chartink.com/screener/"
PROCESS_URL = "https://chartink.com/screener/process"
REQUEST_TIMEOUT = 20
RETRY_TIMES = 3
RETRY_SLEEP_SECONDS = 1.25
DEFAULT_ROWS_PER_SCAN = 15
NUMERIC_COLUMNS = ("close", "per_chg", "volume", "market_cap")
HIGH_ACCURACY_MIN_SCREENERS = 6
HIGH_ACCURACY_MIN_CATEGORIES = 3


st.set_page_config(
    page_title=APP_TITLE,
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def arrow_safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-safe dataframe for Streamlit/Arrow mixed-value tables."""
    if df.empty:
        return df

    def safe_cell(value: Any) -> Any:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, default=str)
        if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
            try:
                converted = value.tolist()
                if isinstance(converted, list):
                    return ", ".join(str(item) for item in converted)
                return str(converted)
            except Exception:
                return str(value)
        try:
            missing = pd.isna(value)
            if isinstance(missing, (bool, type(pd.NA))) and missing:
                return "Unavailable"
        except Exception:
            pass
        return str(value)

    safe = df.copy()
    for column in safe.columns:
        if safe[column].dtype == "object":
            safe[column] = safe[column].apply(safe_cell)
    return safe


def display_dataframe(df: pd.DataFrame, *, hide_index: bool = True, height: int | None = None) -> None:
    kwargs: dict[str, Any] = {"width": "stretch", "hide_index": hide_index}
    if height is not None:
        kwargs["height"] = height
    st.dataframe(arrow_safe_dataframe(df), **kwargs)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --muted: #64748b;
            --text: #0f172a;
            --border: #e2e8f0;
            --accent: #0f4c81;
            --accent-dark: #08375f;
            --accent-soft: #e0f2fe;
            --success: #10b981;
            --danger: #e11d48;
            --warning: #f59e0b;
            --bg: #f3f6fa;
            --shadow: 0 16px 42px rgba(15, 23, 42, .08);
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(14, 165, 233, .10), transparent 34rem),
                linear-gradient(180deg, #f8fafc 0%, var(--bg) 38%, #eef3f8 100%);
            color: var(--text);
        }

        .block-container {
            padding-top: 1.15rem;
            padding-bottom: 2.3rem;
            max-width: 1480px;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #111827 56%, #0b1120 100%);
            border-right: 1px solid rgba(148, 163, 184, .22);
        }

        section[data-testid="stSidebar"] * {
            color: #e5e7eb;
        }

        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] small {
            color: #cbd5e1 !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"] > div,
        section[data-testid="stSidebar"] textarea,
        section[data-testid="stSidebar"] input {
            background: rgba(255,255,255,.08) !important;
            border-color: rgba(148, 163, 184, .28) !important;
            color: #f8fafc !important;
            border-radius: 10px !important;
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
            color: #f8fafc;
        }

        .sidebar-brand {
            border: 1px solid rgba(148, 163, 184, .24);
            border-radius: 14px;
            padding: 14px 14px 12px;
            margin: 4px 0 14px;
            background: linear-gradient(135deg, rgba(14, 165, 233, .18), rgba(16, 185, 129, .10));
        }

        .sidebar-brand-title {
            font-size: 1rem;
            font-weight: 850;
            letter-spacing: .05em;
            text-transform: uppercase;
            color: #ffffff;
        }

        .sidebar-brand-subtitle {
            font-size: .78rem;
            color: #cbd5e1;
            margin-top: 4px;
            line-height: 1.35;
        }

        .sidebar-status {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 14px;
        }

        .sidebar-status div {
            border: 1px solid rgba(148, 163, 184, .22);
            border-radius: 12px;
            padding: 8px;
            background: rgba(255,255,255,.06);
        }

        .sidebar-status strong {
            display: block;
            font-size: .78rem;
            color: #ffffff;
        }

        .sidebar-status span {
            font-size: .7rem;
            color: #94a3b8;
        }

        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button {
            border-radius: 10px;
            border: 1px solid rgba(15, 76, 129, .24);
            font-weight: 750;
            box-shadow: 0 8px 18px rgba(15, 23, 42, .07);
        }

        div[data-testid="stButton"] > button[kind="primary"] {
            background: linear-gradient(135deg, var(--accent) 0%, #2563eb 100%);
            border-color: transparent;
        }

        [data-testid="stMetric"] {
            background: rgba(255,255,255,.82);
            border: 1px solid rgba(226, 232, 240, .95);
            border-radius: 12px;
            padding: 12px 14px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, .05);
        }

        [data-testid="stMetricLabel"] p {
            color: var(--muted);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .04em;
            text-transform: uppercase;
        }

        [data-testid="stMetricValue"] {
            font-size: 1.28rem;
            font-weight: 800;
            color: var(--text);
        }

        [data-testid="stDataFrame"] {
            border: 1px solid rgba(226, 232, 240, .95);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(15, 23, 42, .04);
        }

        [data-testid="stExpander"] {
            border: 1px solid rgba(226, 232, 240, .95);
            border-radius: 12px;
            background: rgba(255,255,255,.78);
            box-shadow: 0 8px 24px rgba(15, 23, 42, .035);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            border-bottom: 1px solid var(--border);
        }

        .stTabs [data-baseweb="tab"] {
            border-radius: 10px 10px 0 0;
            padding: 10px 14px;
            font-weight: 750;
            color: var(--muted);
        }

        .stTabs [aria-selected="true"] {
            background: #ffffff;
            color: var(--accent) !important;
            border: 1px solid var(--border);
            border-bottom: 1px solid #ffffff;
        }

        h1, h2, h3 {
            color: var(--text);
            letter-spacing: -.01em;
        }

        h2 {
            margin-top: .4rem;
        }

        .dashboard-hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            gap: 18px;
            border: 1px solid rgba(226, 232, 240, .96);
            border-radius: 18px;
            padding: 22px 24px;
            margin-bottom: 18px;
            background:
                linear-gradient(135deg, rgba(255,255,255,.96) 0%, rgba(248,250,252,.94) 58%, rgba(224,242,254,.75) 100%);
            box-shadow: var(--shadow);
        }

        .dashboard-kicker {
            color: var(--accent);
            font-size: .78rem;
            font-weight: 850;
            letter-spacing: .12em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .dashboard-title {
            font-size: clamp(1.7rem, 2.4vw, 2.35rem);
            font-weight: 900;
            line-height: 1.1;
            color: var(--text);
            margin: 0 0 .35rem;
        }

        .dashboard-subtitle {
            color: var(--muted);
            font-size: .98rem;
            margin: 0;
            max-width: 900px;
            line-height: 1.5;
        }

        .hero-status {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 8px;
            min-width: 260px;
        }

        .hero-chip {
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 7px 11px;
            background: rgba(255,255,255,.82);
            color: #334155;
            font-size: .78rem;
            font-weight: 750;
            white-space: nowrap;
        }

        .hero-chip.primary {
            background: var(--accent);
            border-color: var(--accent);
            color: #ffffff;
        }

        .professional-callout {
            border: 1px solid rgba(15, 76, 129, .18);
            border-left: 4px solid var(--accent);
            border-radius: 12px;
            padding: 12px 14px;
            background: rgba(224, 242, 254, .48);
            color: #0f172a;
            margin: 8px 0 18px;
        }

        .professional-callout strong {
            color: var(--accent-dark);
        }

        @media (max-width: 900px) {
            .dashboard-hero {
                grid-template-columns: 1fr;
                padding: 18px;
            }

            .hero-status {
                justify-content: flex-start;
                min-width: 0;
            }
        }

        .scan-heading {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: .75rem;
            margin-bottom: .35rem;
        }

        .scan-heading h3 {
            margin: 0;
            font-size: 1rem;
            color: #0f172a;
        }

        .scan-count {
            color: var(--muted);
            font-size: .85rem;
            white-space: nowrap;
        }

        .footer-note {
            color: var(--muted);
            text-align: center;
            font-size: .85rem;
            margin-top: 1.2rem;
            border-top: 1px solid var(--border);
            padding-top: 1rem;
        }

        .analysis-shell {
            max-width: 760px;
            margin: 0 auto;
        }

        .analysis-tabs {
            display: flex;
            gap: 34px;
            border-bottom: 1px solid #dbe3ec;
            margin: 12px 0 22px;
            padding: 0 4px;
            color: #64748b;
            font-size: 1.1rem;
            font-weight: 650;
        }

        .analysis-tab {
            padding: 14px 0 12px;
            border-bottom: 3px solid transparent;
            letter-spacing: .04em;
        }

        .analysis-tab.active {
            color: #0f4c81;
            border-color: #0f4c81;
        }

        .mobile-card {
            background: #fff;
            border: 1px solid #dbe3ec;
            border-radius: 10px;
            padding: 24px;
            box-shadow: 0 1px 8px rgba(15, 23, 42, .05);
            margin-bottom: 18px;
        }

        .phone-card {
            max-width: 760px;
            margin: 0 auto 18px;
        }

        .gauge-wrap {
            display: flex;
            justify-content: center;
            width: 100%;
        }

        .price-center {
            text-align: center;
            font-size: 1.7rem;
            font-weight: 500;
            color: #0f172a;
        }

        .price-center .down {
            color: #e11d48;
        }

        .price-center .up {
            color: #10b981;
        }

        .metric-label {
            text-align: center;
            color: #1f2937;
            font-weight: 800;
            letter-spacing: .05em;
            margin-bottom: 20px;
        }

        .ma-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            font-size: 1.05rem;
            padding: 8px 0;
        }

        .swatch {
            width: 22px;
            height: 22px;
            display: inline-block;
            border-radius: 5px;
            margin-right: 12px;
            vertical-align: middle;
        }

        .action-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin-top: 18px;
            max-width: 760px;
            margin-left: auto;
            margin-right: auto;
        }

        .buy-button, .sell-button {
            border-radius: 16px;
            padding: 22px;
            color: #fff;
            text-align: center;
            font-size: 1.35rem;
            font-weight: 700;
        }

        .buy-button {
            background: #07539f;
        }

        .sell-button {
            background: #ef3b22;
        }

        .swot-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 22px;
            align-items: center;
        }

        .swot-legend-row {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            font-size: 1.05rem;
            margin: 14px 0;
        }

        .swot-nav {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            margin: 26px 0 16px;
            border-bottom: 1px solid #e2e8f0;
        }

        .swot-nav span {
            padding-bottom: 10px;
            font-weight: 800;
            letter-spacing: .06em;
            color: #1f2937;
        }

        .swot-nav span:first-child {
            color: #10b981;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@dataclass(frozen=True)
class Scan:
    key: str
    title: str
    clause: str
    category: str = "Technical"
    description: str = ""


def clean_scan_clause(raw: str) -> str:
    return raw.replace("+", " ")


SCAN_CLAUSE_17 = clean_scan_clause(
    "(+{cash}+(+latest+close+>+latest+supertrend(+7,3+)+and+latest+close+>+latest+supertrend(+7,2+)+and+latest+close+>+latest+supertrend(+10,4+)+and+latest+close+>=+200+and+latest+volume+>=+1000000+and+latest+close+>+latest+supertrend(+15,3+)+and+latest+close+>+latest+supertrend(+30,2+)+)+)"
)
SCAN_CLAUSE_19 = clean_scan_clause(
    "(+{cash}+(+monthly+high+=+monthly+max(+12,+monthly+high+)+and+earning+per+share[eps]+>+prev+year+eps+and+latest+rsi(+14+)+>+60+and+latest+high+=+latest+max(+3,+latest+high+)+)+)"
)
HIGH_ACCURACY_CLAUSE = (
    "( {cash} ( latest close >= latest max ( 252 , latest high ) * 0.96 "
    "and latest close <= latest max ( 252 , latest high ) "
    "and latest adx ( 14 ) > 25 "
    "and latest volume > latest sma ( volume,20 ) * 1.5 "
    "and latest obv > 5 days ago obv "
    "and latest close * latest volume > 200000000 "
    "and latest close >= 200 ) )"
)
INSTITUTIONAL_SETUP_CLAUSE = (
    "( {cash} ( latest ema ( close,20 ) > latest ema ( close,50 ) "
    "and latest ema ( close,50 ) > latest ema ( close,100 ) "
    "and latest close > latest ema ( close,200 ) "
    "and latest close >= latest max ( 252 , latest high ) * 0.97 "
    "and latest volume > latest sma ( volume,20 ) * 1.2 "
    "and latest volume < latest sma ( volume,20 ) * 2 "
    "and latest close * latest volume > 500000000 "
    "and latest close >= 200 ) )"
)
BREAKOUT_PROBABILITY_CLAUSE = (
    "( {cash} ( latest close > latest ema ( close,50 ) "
    "and latest close > latest ema ( close,100 ) "
    "and latest close > latest ema ( close,200 ) "
    "and latest ema ( close,20 ) > latest ema ( close,50 ) "
    "and latest ema ( close,50 ) > latest ema ( close,100 ) "
    "and latest ema ( close,100 ) > latest ema ( close,200 ) "
    "and latest ema ( close,200 ) > 10 days ago ema ( close,200 ) "
    "and latest close >= latest max ( 252 , latest high ) * 0.97 "
    "and latest close <= latest max ( 120 , latest high ) * 1.10 "
    "and latest volume > latest sma ( volume,20 ) * 1.2 "
    "and latest close * latest volume > 500000000 "
    "and latest close >= 100 ) )"
)
HEDGE_FUND_MODEL_CLAUSE = (
    "( {cash} ( latest close > latest ema ( close,50 ) "
    "and latest close > latest ema ( close,100 ) "
    "and latest close > latest ema ( close,200 ) "
    "and latest ema ( close,20 ) > latest ema ( close,50 ) "
    "and latest ema ( close,50 ) > latest ema ( close,100 ) "
    "and latest ema ( close,100 ) > latest ema ( close,200 ) "
    "and latest ema ( close,200 ) > 10 days ago ema ( close,200 ) "
    "and latest close >= latest max ( 252 , latest high ) * 0.97 "
    "and latest close <= latest max ( 120 , latest high ) * 1.10 "
    "and latest volume > latest sma ( volume,20 ) "
    "and latest close * latest volume > 500000000 "
    "and latest close >= 100 ) )"
)
LAUNCH_PAD_200_CLAUSE = (
    "( {cash} ( "
    "( ( latest close < latest ema ( close,200 ) and latest close >= latest ema ( close,190 ) ) "
    "or ( latest close < latest sma ( close,200 ) and latest close >= latest sma ( close,190 ) ) ) "
    "and latest close > latest ema ( close,50 ) "
    "and latest close > latest ema ( close,100 ) "
    "and latest ema ( close,20 ) > 5 days ago ema ( close,20 ) "
    "and latest ema ( close,50 ) > 5 days ago ema ( close,50 ) "
    "and latest ema ( close,100 ) > 5 days ago ema ( close,100 ) "
    "and latest close * latest volume > 100000000 "
    "and latest close >= 20 ) )"
)
AI_EARLY_BREAKOUT_CLAUSE = (
    "( {cash} ( latest close > latest ema ( close,50 ) "
    "and latest close > latest ema ( close,100 ) "
    "and latest close <= latest max ( 120 , latest high ) * 1.08 "
    "and latest close >= latest max ( 252 , latest high ) * 0.90 "
    "and latest volume > latest sma ( volume,20 ) * 0.8 "
    "and latest close * latest volume > 500000000 "
    "and latest close >= 50 ) )"
)
AI_OVERNIGHT_OPPORTUNITY_CLAUSE = (
    "( {cash} ( latest close > latest ema ( close,20 ) "
    "and latest close > latest ema ( close,50 ) "
    "and latest volume > latest sma ( volume,20 ) * 0.8 "
    "and latest close * latest volume > 200000000 "
    "and latest close >= 50 ) )"
)
AI_CHART_READING_CLAUSE = (
    "( {cash} ( latest close > latest ema ( close,20 ) "
    "and latest close > latest ema ( close,50 ) "
    "and latest close >= latest max ( 252 , latest high ) * 0.80 "
    "and latest close * latest volume > 200000000 "
    "and latest close >= 50 ) )"
)

OVERNIGHT_SCORE_WEIGHTS = {
    "closing_strength_score": 15,
    "closing_auction_score": 10,
    "delivery_score": 15,
    "volume_profile_score": 15,
    "relative_strength_score": 10,
    "options_score": 5,
    "compression_score": 10,
    "news_catalyst_score": 5,
    "historical_behaviour_score": 5,
    "liquidity_score": 10,
}

CHART_QUALITY_WEIGHTS = {
    "trend_clarity_score": 15,
    "structure_quality_score": 15,
    "volume_confirmation_score": 15,
    "pattern_reliability_score": 15,
    "multi_timeframe_alignment_score": 15,
    "institutional_footprints_score": 10,
    "risk_reward_quality_score": 10,
    "false_breakout_risk_score": 5,
}

IQ5000_MASTER_WEIGHTS = {
    "market_regime_score": 100,
    "ai_intraday_score": 150,
    "ai_swing_score": 150,
    "ai_institutional_score": 200,
    "ai_early_breakout_score": 200,
    "smart_money_score": 50,
    "swot_advantage_score": 50,
    "fundamental_score": 50,
    "trade_probability": 50,
    "risk_management_score": 50,
}

IQ5000_TRADE_LOG_COLUMNS = [
    "Trade ID",
    "Date",
    "Stock Name",
    "Sector",
    "Market Regime",
    "Entry Price",
    "Exit Price",
    "Stop Loss",
    "Target",
    "Actual Profit/Loss",
    "Holding Time",
    "Quantity",
    "Capital Used",
    "Risk Amount",
    "Reward Amount",
    "AI IQ Score",
    "AI Intraday Score",
    "AI Swing Score",
    "AI Institutional Score",
    "AI Early Breakout Score",
    "Smart Money Score",
    "SWOT Advantage Score",
    "Trade Probability Score",
    "Pattern Detected",
    "Delivery Percentage",
    "Delivery Trend",
    "OBV Trend",
    "Relative Strength",
    "Sector Strength",
    "VCP Status",
    "Darvas Status",
    "Pocket Pivot Status",
    "ATR",
    "Bollinger Width",
    "200 EMA Distance",
    "52 Week High Distance",
    "Reason For Entry",
    "Reason For Exit",
]

IQ5000_MARKET_MEMORY_COLUMNS = [
    "Date",
    "Stock",
    "Sector",
    "Market Regime",
    "Pattern Type",
    "Delivery Percentage",
    "OBV Trend",
    "Relative Strength",
    "VCP",
    "Darvas Box",
    "Pocket Pivot",
    "200 EMA Distance",
    "52 Week High Distance",
    "AI IQ Score",
    "Trade Outcome",
    "Similarity Score",
    "Market DNA Score",
]

INSTITUTIONAL_RULES = [
    "EMA20 > EMA50 > EMA100",
    "Price > EMA200",
    "Darvas Box formed",
    "Bollinger width in the lowest 20% of the last 6 months",
    "ATR falling for 5 days",
    "OBV rising for 10 days",
    "RVOL between 1.2 and 2.0",
    "Delivery > 50%",
    "Within 3% of 52-week high",
    "Sector relative strength > Nifty",
    "No major resistance above",
    "Turnover > 50 crore",
    "Weekly breakout pending",
    "Quarterly earnings growth > 20%",
]

BREAKOUT_PHASE_WEIGHTS = {
    "trend_template_score": 15,
    "vcp_score": 15,
    "darvas_score": 15,
    "wyckoff_score": 10,
    "pocket_pivot_score": 10,
    "institutional_score": 15,
    "relative_strength_score": 10,
    "sector_strength_score": 5,
    "earnings_score": 5,
}

BREAKOUT_PHASES = [
    "Trend template: close above EMA50/100/200, EMA20 > EMA50 > EMA100 > EMA200, rising EMA200.",
    "VCP: contracting pullbacks, falling ATR, low Bollinger width, shrinking daily ranges.",
    "Darvas: box near completion, price within 0-3% of box high, repeated resistance tests.",
    "Wyckoff: sideways accumulation, higher lows, volume dry-up, absorption behavior.",
    "Pocket pivot: up-volume greater than prior down-volume near breakout area.",
    "Institutional accumulation: delivery > 50%, OBV/A-D line rising, up-day volume expansion.",
    "Relative strength: outperforming Nifty/sector and RS line leading price.",
    "Sector rotation: sector momentum and sector outperformance.",
    "Earnings momentum: quarterly earnings growth, sales growth, surprise, guidance.",
]

HEDGE_FUND_MODEL_WEIGHTS = {
    "trend_score": 10,
    "breakout_score": 15,
    "vcp_score": 10,
    "darvas_score": 10,
    "wyckoff_score": 10,
    "institutional_phase_score": 15,
    "delivery_score": 10,
    "relative_strength_score": 10,
    "sector_score": 5,
    "fundamental_score": 5,
}

LAUNCH_PAD_200_WEIGHTS = {
    "near_200_ema_score": 20,
    "near_200_sma_score": 20,
    "delivery_score": 10,
    "obv_score": 10,
    "darvas_score": 10,
    "vcp_score": 10,
    "volume_score": 5,
    "relative_strength_score": 5,
    "sector_strength_score": 5,
    "institutional_score": 5,
}

PROMPT_REFERENCE_TEXT = """
ACT AS A WORLD-CLASS HEDGE FUND MANAGER, CHART READER, FUNDAMENTAL ANALYST,
QUANTITATIVE RESEARCHER, AND INSTITUTIONAL STOCK PICKER.

Objective:
Identify NSE stocks likely to generate superior returns over the next 1-20 trading
sessions while minimizing risk. Do not chase stocks already extended. Find stocks
under active institutional accumulation before major breakouts occur.

PHASE 1 - TREND AND STRUCTURE FILTER
Only consider stocks where:
- Price > EMA50
- Price > EMA100
- Price > EMA200
- EMA20 > EMA50 > EMA100 > EMA200
- 200 EMA rising
- Weekly trend bullish

Reject all others.

PHASE 2 - PRE-BREAKOUT DETECTION
Identify:
- Darvas Box formation
- Price within 0-3% of breakout level
- Bollinger Band Width in lowest 20% of last 120 days
- ATR contraction during last 5 sessions
- VCP (Volatility Contraction Pattern)
- Tight consolidations
- No significant resistance overhead

Assign Breakout Score.

PHASE 3 - WYCKOFF ACCUMULATION
Detect:
- Accumulation range
- Higher lows
- Volume dry-up
- Spring and recovery
- Absorption candles

Assign Accumulation Score.

PHASE 4 - INSTITUTIONAL ACCUMULATION
Analyze Delivery Percentage:
- Delivery > 60% = Excellent
- Delivery 50-60% = Strong
- Delivery 40-50% = Neutral
- Delivery < 40% = Weak

Also evaluate:
- OBV making 30-day highs
- Accumulation/Distribution line rising
- Volume expansion on up days
- Volume contraction on down days
- Block deal activity
- Promoter buying
- Institutional buying

Assign Institutional Score.

PHASE 5 - POCKET PIVOT DETECTION
Identify:
- Pocket Pivot Volume
- Volume > highest down-volume of previous 10 sessions
- Price near breakout point

Assign Pocket Pivot Score.

PHASE 6 - RELATIVE STRENGTH ANALYSIS
Evaluate:
- Relative Strength vs Nifty
- Relative Strength vs Sector
- Relative Strength line making new highs before price

Assign RS Score.

PHASE 7 - SECTOR LEADERSHIP
Prioritize sectors showing:
- Strong momentum
- Sector above 20 EMA
- Sector outperforming Nifty

Assign Sector Score.

PHASE 8 - FUNDAMENTAL QUALITY
Analyze:
- Revenue Growth
- Profit Growth
- ROE
- ROCE
- Debt to Equity
- Cash Flow
- Promoter Holding
- Institutional Holding

Assign Fundamental Score.

PHASE 9 - INVESTOR SWOT ANALYSIS
Strengths:
- Earnings Growth
- Revenue Growth
- Strong Margins
- Sector Leadership
- Relative Strength
- Institutional Buying
- Delivery Percentage
- Strong Technical Structure

Strength Score = 0-25

Weaknesses:
- High Debt
- Weak Cash Flow
- Falling Margins
- Poor Governance
- Low Delivery Percentage
- Weak Volume Structure
- Overvaluation

Weakness Score = 0-25

Opportunities:
- Near Breakout
- Sector Tailwind
- Government Support
- Capacity Expansion
- New Product Launches
- Positive Earnings Outlook
- Institutional Accumulation
- Industry Growth

Opportunity Score = 0-25

Threats:
- Major Resistance Above
- Regulatory Risk
- Competitive Pressure
- Commodity Risk
- Earnings Risk
- Market Weakness
- Sector Weakness

Threat Score = 0-25

PHASE 10 - SWOT DECISION RULE
SWOT Advantage Score = (Strength Score + Opportunity Score) - (Weakness Score + Threat Score)

Buy only if:
- Strength + Opportunity >= 40
- Weakness + Threat <= 20
- SWOT Advantage Score >= 20
- Delivery Percentage >= 50%
- Institutional Score >= 70

Otherwise reject.

PHASE 11 - FINAL PROBABILITY MODEL
- Trend Score = 10
- Breakout Score = 15
- VCP Score = 10
- Darvas Score = 10
- Wyckoff Score = 10
- Institutional Score = 15
- Delivery Score = 10
- Relative Strength Score = 10
- Sector Score = 5
- Fundamental Score = 5

Total Score = 100

OUTPUT FORMAT
For every stock provide:
1. Stock Name
2. Sector
3. Current Price
4. Delivery Percentage
5. Breakout Level
6. Entry Zone
7. Stop Loss
8. Intraday Target
9. Swing Target
10. Total Score /100

SWOT Analysis:
- Strength Score
- Weakness Score
- Opportunity Score
- Threat Score
- SWOT Advantage Score
- Institutional Score
- Expected Breakout Window
- Risk/Reward Ratio
- Reason for Selection

FINAL FILTER
Display only stocks satisfying:
- Total Score > 85
- SWOT Advantage Score > 20
- Delivery Percentage > 50%
- Institutional Score > 70
- Turnover > Rs 50 Crore

Rank highest probability to lowest probability.

Highlight:
- Best Intraday Candidate
- Best Swing Candidate
- Best Institutional Accumulation Candidate
- Best Low-Risk Candidate
- Best Hidden Gem Candidate
- Highest Probability Breakout Candidate
""".strip()


SCANS: list[Scan] = [
    Scan("condition_1", "Positive Close With Liquidity Filter", '( {cash} ( latest close >= 1 day ago close and latest "close - 1 candle ago close / 1 candle ago close * 100" > 0 and latest low > 20 and latest volume > 10000 ) )', "Momentum", "Close is positive versus the prior candle, with minimum price and volume filters."),
    Scan("condition_2", "Near 52-Week Low Support Zone", "( {cash} ( latest low > 10 and ( {cash} ( latest low <= weekly min ( 52 , weekly low ) or latest close <= ( weekly min ( 52 , weekly low ) + ( weekly min ( 52 , weekly low ) * 5 / 100 ) ) ) ) ) )", "Risk", "Stocks trading at, or within 5 percent of, the 52-week weekly low area."),
    Scan("condition_3", "Near 200-Day High With Volume Expansion", "( {cash} ( latest close * 1.05 > latest max ( 200 , latest high ) and latest max ( 30 , latest high ) <= 30 days ago max ( 200 , latest high ) and latest volume > latest sma ( volume,50 ) and latest close > 90 ) )", "Breakout", "Price is within 5 percent of the 200-day high with volume above the 50-day average."),
    Scan("condition_4", "Custom 52-Week High Universe: Price and Volume", "( {33489} ( ( {cash} ( latest close > 50 and latest close < 6000 and latest volume > 10000 ) ) ) )", "Breakout", "Saved Chartink universe filtered by price range and minimum traded volume."),
    Scan("condition_5", "Wide-Range Bullish Price-Volume Action", "( {cash} ( abs ( latest high - latest low ) > abs ( 1 day ago high - 1 day ago low ) and abs ( latest high - latest low ) > abs ( 2 days ago high - 2 days ago low ) and abs ( latest high - latest low ) > abs ( 3 days ago high - 3 days ago low ) and abs ( latest high - latest low ) > abs ( 4 days ago high - 4 days ago low ) and latest close > latest open and latest close > weekly open and latest close > monthly open and latest low > 1 day ago close - abs ( 1 day ago close / 222 ) and latest volume >= latest ema ( latest volume , 20 ) ) )", "Volume", "Current range exceeds the prior four sessions, closes bullish, and volume is above its EMA."),
    Scan("condition_6", "Four-Session Rising Volume Trend", "( {cash} ( latest volume > latest sma ( volume,10 ) and latest volume > 1 day ago volume and 1 day ago volume > 2 days ago volume and 2 days ago volume > 3 days ago volume ) )", "Volume", "Volume is rising for four sessions and is above the 10-day volume average."),
    Scan("condition_7", "Monthly High, EPS Growth and RSI Strength", SCAN_CLAUSE_19, "Technical", "Monthly high breakout condition with EPS growth and RSI above 60."),
    Scan("condition_8", "120-Day Range Breakout With Volume", "( {cash} ( latest max ( 5 , latest close ) > 6 days ago max ( 120 , latest close ) * 1.05 and latest volume > latest sma ( volume,5 ) and latest close > 1 day ago close ) )", "Breakout", "Latest five-day close breaks above the prior 120-day range with volume confirmation."),
    Scan("condition_9", "Price Near 200 EMA With Market-Cap Filter", "( {cash} ( latest close > latest ema ( close,200 ) * 0.95 and latest close <= latest ema ( close,200 ) * 1.05 and market cap >= 5000 and latest close >= 200 ) )", "Breakout", "Price is within 5 percent of the 200 EMA, with minimum market-cap and price filters."),
    Scan("condition_10", "Custom Universe: High-Volume 5 Percent Move", "( {57960} ( latest volume > latest sma ( volume,10 ) * 2 and ( {cash} ( latest close > 1 day ago close * 1.05 or latest close < 1 day ago close * 0.95 ) ) ) )", "Volume", "Saved Chartink universe with volume above 2x the 10-day average and a 5 percent price move."),
    Scan("condition_11", "Price Up With Volume Above Prior 3 Days", "( {cash} ( latest close > 1 day ago close * 1.01 and 1 day ago close < 2 days ago close * 1.03 and latest volume >= 100000 and latest close > 20 and ( 1 day ago volume + 2 days ago volume + 3 days ago volume ) < latest volume ) )", "Volume", "Latest volume exceeds the combined volume of the prior three days while price is positive."),
    Scan("condition_12", "Volume Spike With 2 Percent Price Gain", "( {cash} ( latest volume > latest sma ( volume,10 ) * 2 and latest close > 1 day ago close * 1.02 ) )", "Volume", "Volume is above 2x the 10-day average and price is up more than 2 percent."),
    Scan("condition_13", "High-Volume SMA 190/200 Bullish Bias", "( {cash} ( latest volume > 5000000 and latest sma ( latest close , 190 ) > latest sma ( latest close , 200 ) ) )", "Volume", "High-volume names where the 190-period average is above the 200-period average."),
    Scan("condition_14", "EMA Bullish Crossover Cluster", "( {cash} ( latest ema ( close,7 ) > latest ema ( close,9 ) and 1 day ago  ema ( close,7 )<= 1 day ago  ema ( close,9 ) and latest ema ( close,5 ) > latest ema ( close,7 ) and 1 day ago  ema ( close,5 )<= 1 day ago  ema ( close,7 ) and latest ema ( close,7 ) > latest ema ( close,13 ) and 1 day ago  ema ( close,7 )<= 1 day ago  ema ( close,13 ) ) )", "Technical", "Multiple short-term EMA bullish crossovers occurring together."),
    Scan("condition_15", "Growth Quality Above 200 EMA", "( {cash} ( latest close > latest ema ( latest close , 200 ) and yearly net sales > 1 year ago net sales and 1 year ago net sales > 2 years ago net sales and 2 years ago net sales > 3 years ago net sales and yearly net profit/reported profit after tax > 1 year ago net profit/reported profit after tax and 1 year ago net profit/reported profit after tax > 2 years ago net profit/reported profit after tax ) )", "Fundamental", "Price is above the 200 EMA with multi-year sales and profit growth."),
    Scan("condition_16", "55-Day Fibonacci Retracement Strength", "( {cash} ( ( latest close - latest open ) / ( latest high - latest low ) > .50 and latest low > ( latest min ( 55 , latest low ) + ( latest max ( 55 , latest high ) - latest min ( 55 , latest low ) * 0.382 ) ) * 0.99 and 1 day ago  low <= ( 1 day ago  min ( 55 , latest low )+ ( 1 day ago  max ( 55 , latest high )- 1 day ago  min ( 55 , latest low )* 0.382 ) ) * 0.99 and latest volume > 100000 ) )", "Technical", "Bullish candle strength near a 55-day Fibonacci retracement zone with volume filter."),
    Scan("condition_17", "Multi-Supertrend Bullish Alignment", SCAN_CLAUSE_17, "Technical", "Close is above several Supertrend settings with price and liquidity filters."),
    Scan("condition_18", "Short-Term 120-Day Breakout Confirmation", "( {cash} ( latest max ( 5 , latest close ) > 6 days ago max ( 120 , latest close ) * 1.05 and latest volume > latest sma ( volume,5 ) and latest close > 1 day ago close ) )", "Breakout", "Short-term breakout confirmation using the same 120-day range and volume logic."),
    Scan("condition_19", "Darvas-Style Monthly High With EPS/RSI", SCAN_CLAUSE_19, "Technical", "Darvas-style monthly high condition supported by EPS growth and RSI above 60."),
    Scan("condition_20", "Weekly Volume Breakout Across Lookbacks", "( {cash} ( weekly volume > 1 week ago volume or weekly volume > 1 week ago max ( 2 , weekly volume ) or weekly volume > 1 week ago max ( 4 , weekly volume ) or weekly volume > 1 week ago max ( 12 , weekly volume ) or weekly volume > 1 week ago max ( 24 , weekly volume ) or weekly volume > 1 week ago max ( 52 , weekly volume ) or weekly volume > 1 week ago max ( 104 , weekly volume ) or weekly volume > 1 week ago max ( 156 , weekly volume ) or weekly volume > 1 week ago max ( 260 , weekly volume ) ) )", "Volume", "Weekly volume is breaking out against one or more historical lookback windows."),
    Scan("condition_21", "High-Conviction 52-Week Breakout Setup", HIGH_ACCURACY_CLAUSE, "High Conviction", "Near 52-week high with ADX, relative volume, OBV, turnover, and price filters."),
]


@st.cache_resource(ttl=15 * 60, show_spinner=False)
def get_chartink_client() -> tuple[requests.Session, dict[str, str]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": TOKEN_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    response = session.get(TOKEN_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "lxml")
    token = soup.find("meta", {"name": "csrf-token"})
    if not token or not token.get("content"):
        raise RuntimeError("Chartink CSRF token was not found.")

    headers = {"x-csrf-token": token["content"]}
    return session, headers


def post_with_retries(scan_clause: str) -> requests.Response:
    session, headers = get_chartink_client()
    last_error: Exception | None = None

    for attempt in range(RETRY_TIMES):
        try:
            response = session.post(
                PROCESS_URL,
                headers=headers,
                data={"scan_clause": scan_clause},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 429:
                time.sleep(RETRY_SLEEP_SECONDS * (attempt + 1))
                continue

            response.raise_for_status()
            return response
        except Exception as exc:  # requests raises several concrete subclasses.
            last_error = exc
            time.sleep(RETRY_SLEEP_SECONDS * (attempt + 1))

    if last_error:
        raise last_error
    raise RuntimeError("Chartink request failed.")


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    normalized = df.copy()
    preferred = ["nsecode", "name", "close", "per_chg", "volume", "market_cap", "sector"]

    for column in NUMERIC_COLUMNS:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    first_columns = [column for column in preferred if column in normalized.columns]
    other_columns = [column for column in normalized.columns if column not in first_columns]
    return normalized[first_columns + other_columns]


@st.cache_data(ttl=5 * 60, show_spinner=False)
def run_scan(scan_clause: str) -> tuple[pd.DataFrame, str | None]:
    try:
        response = post_with_retries(scan_clause)
        payload: dict[str, Any] = response.json()
    except json.JSONDecodeError:
        return pd.DataFrame(), "Chartink returned a non-JSON response."
    except Exception as exc:
        return pd.DataFrame(), str(exc)

    rows = payload.get("data")
    if rows is None:
        return pd.DataFrame(), payload.get("error") or "The response did not include a data field."

    return normalize_dataframe(pd.DataFrame(rows)), None


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return value.strip("_") or "chartink_scan"


def maybe_autorefresh(enabled: bool, seconds: int) -> None:
    if not enabled:
        return

    components.html(
        f"""
        <script>
        setTimeout(function() {{
            window.parent.location.reload();
        }}, {seconds * 1000});
        </script>
        """,
        height=0,
    )


def render_header() -> None:
    today_label = date.today().strftime("%d %b %Y")
    st.markdown(
        f"""
        <div class="dashboard-hero">
            <div>
                <div class="dashboard-kicker">IQ-5000 Research Workstation</div>
                <div class="dashboard-title">{APP_TITLE}</div>
                <div class="dashboard-subtitle">
                    Professional NSE screening, AI chart reading, market-memory scoring, risk planning, replay validation, and institutional-style decision support in one Streamlit cockpit.
                </div>
            </div>
            <div class="hero-status">
                <span class="hero-chip primary">Research Mode</span>
                <span class="hero-chip">Updated {today_label}</span>
                <span class="hero-chip">No forced trades</span>
                <span class="hero-chip">{len(ADVANCED_IQ_MODULES)} IQ modules</span>
            </div>
        </div>
        <div class="professional-callout">
            <strong>Decision standard:</strong> use these screens as evidence, not prediction. Capital deployment should wait for liquidity, market regime, live confirmation, and clean risk/reward.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_scan_card(scan: Scan, df: pd.DataFrame, error: str | None, rows_per_scan: int) -> None:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="scan-heading">
                <h3>{scan.title}</h3>
                <span class="scan-count">{len(df):,} rows</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"{scan.category} | {scan.description}")

        if error:
            st.warning(error)
            return

        if df.empty:
            st.info("No matching stocks found.")
            return

        display_dataframe(df.head(rows_per_scan), height=min(420, 72 + (rows_per_scan * 35)))

        page_csv = df.head(rows_per_scan).to_csv(index=False).encode("utf-8")
        all_csv = df.to_csv(index=False).encode("utf-8")
        left, right = st.columns(2)
        with left:
            st.download_button(
                "Download visible rows",
                page_csv,
                file_name=f"{slugify(scan.title)}_visible.csv",
                mime="text/csv",
                width="stretch",
            )
        with right:
            st.download_button(
                "Download all rows",
                all_csv,
                file_name=f"{slugify(scan.title)}_all.csv",
                mime="text/csv",
                width="stretch",
            )


def sidebar_controls() -> tuple[list[Scan], str, bool, bool, int, int]:
    categories = sorted({scan.category for scan in SCANS})

    with st.sidebar:
        st.header("Screening Controls")

        category_filter = st.multiselect(
            "Categories",
            categories,
            default=categories,
        )

        available_scans = [scan for scan in SCANS if scan.category in category_filter]
        selected_titles = st.multiselect(
            "Scanner modules",
            [scan.title for scan in available_scans],
            default=[scan.title for scan in available_scans],
        )

        sort_column = st.selectbox("Sort table results by", ["close", "per_chg", "volume", "market_cap", "nsecode"], index=0)
        descending = st.toggle("Sort descending", value=True)
        rows_per_scan = st.slider("Rows shown per scanner", 5, 100, DEFAULT_ROWS_PER_SCAN, 5)

        st.divider()
        auto_refresh = st.toggle("Auto-refresh data", value=False)
        refresh_seconds = st.slider("Refresh interval", 30, 300, 60, 30, disabled=not auto_refresh)

        if st.button("Refresh now", type="primary", width="stretch"):
            run_scan.clear()
            get_chartink_client.clear()
            st.rerun()

    selected_scans = [scan for scan in available_scans if scan.title in selected_titles]
    return selected_scans, sort_column, descending, auto_refresh, refresh_seconds, rows_per_scan


def sidebar_page_choice() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-title">IQ-5000 Console</div>
                <div class="sidebar-brand-subtitle">Screeners, chart intelligence, risk engines, and professional research modules.</div>
            </div>
            <div class="sidebar-status">
                <div><strong>Mode</strong><span>Research</span></div>
                <div><strong>Source</strong><span>Chartink + OHLCV</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        page_groups = {
            "Core Dashboards": [
                "Multi-Screener Dashboard",
                "Institutional Breakout Setup",
                "Breakout Probability Model",
                "Hedge Fund Stock Picker",
                "IQ-5000 AI Trading Platform",
                "AI Overnight Opportunity",
            ],
            "Chart Workstation": [
                "AI Chart Reading Engine",
                "AI Custom Chart Engine",
                "AI Professional Chart Interpretation",
                "AI Interactive Chart Teacher",
                "AI Chart Reading & Replay",
                "Stock Technicals & SWOT Card",
            ],
            "Breakout Models": [
                "AI Early Breakout Score",
                "200 EMA/SMA Launch Pad",
            ],
            "IQ Modules 23-40": list(ADVANCED_IQ_MODULES.values()),
        }
        group = st.selectbox("Workspace group", list(page_groups), index=0, key="workspace_group")
        pages = page_groups[group]
        page_key = f"workspace_page_{re.sub(r'[^a-z0-9]+', '_', group.lower()).strip('_')}"
        selected_page = st.selectbox("Module", pages, index=0, key=page_key)
        st.caption("Tip: start with Core Dashboards, then validate a symbol in Chart Workstation.")
        return selected_page


def sort_results(df: pd.DataFrame, column: str, descending: bool = True) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df

    try:
        return df.sort_values(column, ascending=not descending, kind="mergesort", na_position="last")
    except Exception:
        return df


def find_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    normalized = {re.sub(r"[^a-z0-9]+", "", str(column).lower()): column for column in df.columns}
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]+", "", alias.lower())
        if key in normalized:
            return str(normalized[key])
    return None


def scan_signal_id(scan: Scan) -> str:
    normalized_clause = re.sub(r"\s+", " ", scan.clause.strip().lower())
    return hashlib.sha1(normalized_clause.encode("utf-8")).hexdigest()[:12]


def build_overlap_table(
    selected_scans: list[Scan],
    results: dict[str, tuple[pd.DataFrame, str | None]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for scan in selected_scans:
        df, error = results.get(scan.key, (pd.DataFrame(), None))
        if error or df.empty:
            continue

        identity_column = "nsecode" if "nsecode" in df.columns else "name" if "name" in df.columns else None
        if not identity_column:
            continue

        for _, row in df.dropna(subset=[identity_column]).drop_duplicates(identity_column).iterrows():
            item: dict[str, Any] = {
                "stock_key": str(row[identity_column]).strip(),
                "screener": scan.title,
                "signal_id": scan_signal_id(scan),
                "scanner_category": scan.category,
            }
            for column in df.columns:
                if column not in item:
                    item[str(column)] = row.get(column)
            rows.append(item)

    if not rows:
        return pd.DataFrame()

    raw = pd.DataFrame(rows)
    overlap_counts = raw.groupby("stock_key")["signal_id"].nunique()
    repeated_keys = overlap_counts[overlap_counts > 1].index
    if repeated_keys.empty:
        return pd.DataFrame()

    repeated = raw[raw["stock_key"].isin(repeated_keys)].copy()
    aggregations: dict[str, tuple[str, str] | tuple[str, Any]] = {
        "screeners_count": ("signal_id", "nunique"),
        "categories_count": ("scanner_category", "nunique"),
        "categories_present": ("scanner_category", lambda values: ", ".join(sorted(set(values)))),
        "present_in": ("screener", lambda values: ", ".join(sorted(set(values)))),
    }
    for column in repeated.columns:
        if column not in {"stock_key", "screener", "signal_id", "scanner_category"}:
            aggregations[column] = (column, "first")

    summary = repeated.groupby("stock_key", as_index=False).agg(**aggregations)
    sort_columns = ["screeners_count"]
    sort_ascending = [False]
    if "nsecode" in summary.columns:
        sort_columns.append("nsecode")
        sort_ascending.append(True)
    elif "name" in summary.columns:
        sort_columns.append("name")
        sort_ascending.append(True)
    summary = summary.sort_values(sort_columns, ascending=sort_ascending, kind="mergesort")

    return summary


def preferred_overlap_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "screeners_count",
        "categories_count",
        "nsecode",
        "name",
        "close",
        "per_chg",
        "volume",
        "market_cap",
        "sector",
        "categories_present",
        "present_in",
    ]
    return [column for column in columns if column in df.columns]


def matched_any(present_in: str, keywords: list[str]) -> bool:
    text = present_in.lower()
    return any(keyword.lower() in text for keyword in keywords)


def numeric_series(df: pd.DataFrame, aliases: list[str]) -> pd.Series | None:
    column = find_column(df, aliases)
    if not column:
        return None
    return pd.to_numeric(df[column], errors="coerce")


def confidence_tier(score: float) -> str:
    if score >= 90:
        return "A+ Institutional Watchlist"
    if score >= 75:
        return "A High Conviction"
    if score >= 60:
        return "B+ Strong Candidate"
    return "B Qualified Candidate"


def build_high_accuracy_table(overlap_df: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"present_in", "screeners_count", "categories_count"}
    if overlap_df.empty or not required_columns.issubset(overlap_df.columns):
        return pd.DataFrame()

    candidates = overlap_df[
        (overlap_df["screeners_count"] >= HIGH_ACCURACY_MIN_SCREENERS)
        & (overlap_df["categories_count"] >= HIGH_ACCURACY_MIN_CATEGORIES)
    ].copy()
    if candidates.empty:
        return candidates

    setup_checks = {
        "darvas_or_monthly_high": ["darvas", "monthly high", "high-conviction"],
        "range_breakout_or_squeeze": ["range breakout", "fibonacci", "potential", "high-conviction"],
        "obv_or_volume_expansion": ["volume", "price-volume", "weekly volume", "high-conviction"],
        "near_52w_or_200d_high": ["52-week", "200-day high", "high-conviction"],
        "trend_alignment": ["supertrend", "ema bullish", "200 ema", "high-conviction"],
        "quality_or_eps_support": ["eps", "growth quality", "fundamental", "high-conviction"],
    }

    for column, keywords in setup_checks.items():
        candidates[column] = candidates["present_in"].apply(lambda value: matched_any(str(value), keywords))

    strict_filter_notes: list[str] = []
    close = numeric_series(candidates, ["close", "latest close"])
    darvas_level = numeric_series(candidates, ["darvas_breakout_level", "darvas breakout level", "box breakout level"])
    high_52w = numeric_series(candidates, ["52_week_high", "52 week high", "year high", "latest max 252 high"])
    adx = numeric_series(candidates, ["adx", "adx_14", "latest adx 14"])
    rvol = numeric_series(candidates, ["rvol", "relative volume", "relative_volume"])
    delivery = numeric_series(candidates, ["delivery", "delivery_percent", "delivery percentage", "delivery_pct"])
    turnover = numeric_series(candidates, ["turnover", "turnover_cr", "turnover crore", "value traded"])
    atr_compression = numeric_series(candidates, ["atr_compression", "atr compression"])

    strict_mask = pd.Series(True, index=candidates.index)
    available_strict_filters = 0
    passed_strict_filters = pd.Series(0, index=candidates.index, dtype="int64")
    missing_filters: list[str] = []
    if close is not None and darvas_level is not None:
        distance = (darvas_level - close) / darvas_level * 100
        passed = distance.between(0, 3, inclusive="both")
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["darvas_breakout_gap_pct"] = distance.round(2)
        strict_filter_notes.append("Darvas breakout gap 0-3%")
    else:
        missing_filters.append("Darvas breakout level")
    if close is not None and high_52w is not None:
        distance = (high_52w - close) / high_52w * 100
        passed = distance.lt(4)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["52w_high_distance_pct"] = distance.round(2)
        strict_filter_notes.append("52-week high distance < 4%")
    else:
        missing_filters.append("52-week high")
    if adx is not None:
        passed = adx.gt(25)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["adx_filter"] = adx
        strict_filter_notes.append("ADX > 25")
    else:
        missing_filters.append("ADX")
    if rvol is not None:
        passed = rvol.gt(1.5)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["rvol_filter"] = rvol
        strict_filter_notes.append("RVOL > 1.5")
    else:
        missing_filters.append("RVOL")
    if delivery is not None:
        passed = delivery.gt(50)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["delivery_filter"] = delivery
        strict_filter_notes.append("Delivery > 50%")
    else:
        missing_filters.append("Delivery %")
    if turnover is not None:
        passed = turnover.gt(20)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["turnover_filter"] = turnover
        strict_filter_notes.append("Turnover > 20 crore")
    else:
        missing_filters.append("Turnover")
    if atr_compression is not None:
        passed = atr_compression.gt(0)
        strict_mask &= passed
        passed_strict_filters += passed.fillna(False).astype(int)
        available_strict_filters += 1
        candidates["atr_compression_filter"] = atr_compression
        strict_filter_notes.append("ATR compression")
    else:
        missing_filters.append("ATR compression")

    candidates = candidates[strict_mask].copy()
    if candidates.empty:
        return candidates

    check_columns = list(setup_checks)
    candidates["setup_confirmation_count"] = candidates[check_columns].sum(axis=1)
    candidates["strict_filter_pass_count"] = passed_strict_filters.loc[candidates.index]
    candidates["strict_filter_available_count"] = available_strict_filters
    candidates["accuracy_score"] = (
        candidates["screeners_count"] * 8
        + candidates["categories_count"] * 7
        + candidates["setup_confirmation_count"] * 5
        + candidates["strict_filter_pass_count"] * 6
    ).clip(upper=100)
    candidates["confidence_tier"] = candidates["accuracy_score"].apply(confidence_tier)
    candidates["matched_setups"] = candidates.apply(
        lambda row: ", ".join(column.replace("_", " ") for column in check_columns if bool(row[column])),
        axis=1,
    )
    candidates["strict_filters_applied"] = ", ".join(strict_filter_notes) if strict_filter_notes else "Overlap/setup confirmation only"
    candidates["missing_data_for_strict_filters"] = ", ".join(missing_filters) if missing_filters else "None"

    preferred_columns = [
        "accuracy_score",
        "confidence_tier",
        "screeners_count",
        "categories_count",
        "setup_confirmation_count",
        "strict_filter_pass_count",
        "nsecode",
        "name",
        "close",
        "per_chg",
        "volume",
        "market_cap",
        "sector",
        "darvas_breakout_gap_pct",
        "52w_high_distance_pct",
        "adx_filter",
        "rvol_filter",
        "delivery_filter",
        "turnover_filter",
        "atr_compression_filter",
        "matched_setups",
        "categories_present",
        "strict_filters_applied",
        "missing_data_for_strict_filters",
        "present_in",
    ]
    sort_columns = ["accuracy_score", "screeners_count", "categories_count"]
    sort_ascending = [False, False, False]
    if "nsecode" in candidates.columns:
        sort_columns.append("nsecode")
        sort_ascending.append(True)
    elif "name" in candidates.columns:
        sort_columns.append("name")
        sort_ascending.append(True)
    candidates = candidates.sort_values(sort_columns, ascending=sort_ascending, kind="mergesort")
    return candidates[[column for column in preferred_columns if column in candidates.columns]]


def setup_status(row: pd.Series) -> str:
    score = float(row.get("accuracy_score", 0) or 0)
    setup_count = float(row.get("setup_confirmation_count", 0) or 0)
    strict_count = float(row.get("strict_filter_pass_count", 0) or 0)
    present_in = str(row.get("present_in", "")).lower()

    if score >= 85 and strict_count >= 3:
        return "Priority watch: confirmed multi-factor setup"
    if score >= 75 and ("breakout" in present_in or "52-week" in present_in or "darvas" in present_in):
        return "Breakout watch: wait for clean trigger"
    if score >= 65 and setup_count >= 4:
        return "Strong setup: monitor price-volume follow-through"
    return "Qualified setup: needs stronger confirmation"


def setup_plan(row: pd.Series) -> str:
    parts: list[str] = []
    if "darvas_breakout_gap_pct" in row and pd.notna(row.get("darvas_breakout_gap_pct")):
        parts.append(f"{row['darvas_breakout_gap_pct']:.2f}% below breakout zone")
    if "52w_high_distance_pct" in row and pd.notna(row.get("52w_high_distance_pct")):
        parts.append(f"{row['52w_high_distance_pct']:.2f}% below 52-week high")
    if "rvol_filter" in row and pd.notna(row.get("rvol_filter")):
        parts.append(f"RVOL {row['rvol_filter']:.2f}")
    if "adx_filter" in row and pd.notna(row.get("adx_filter")):
        parts.append(f"ADX {row['adx_filter']:.1f}")

    if parts:
        return "; ".join(parts)
    return "Use breakout close, volume expansion, and risk level before entry."


def first_numeric_value(row: pd.Series, aliases: list[str]) -> float | None:
    normalized = {re.sub(r"[^a-z0-9]+", "", str(column).lower()): column for column in row.index}
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]+", "", alias.lower())
        column = normalized.get(key)
        if column is None:
            continue
        value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
        if pd.notna(value):
            return float(value)
    return None


def bounded_score(value: float, maximum: int) -> int:
    return int(max(0, min(maximum, round(value))))


def percent_gap(reference: float | None, current: float | None) -> float | None:
    if reference is None or current is None or reference == 0:
        return None
    return (reference - current) / reference * 100


def coerce_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return default
    if pd.isna(number):
        return default
    return float(number)


def safe_sort_dataframe(
    df: pd.DataFrame,
    columns: list[str],
    ascending: list[bool] | bool,
) -> pd.DataFrame:
    if df.empty:
        return df

    available = [column for column in columns if column in df.columns]
    if not available:
        return df

    sortable = df.copy()
    for column in available:
        numeric = pd.to_numeric(sortable[column], errors="coerce")
        if numeric.notna().any():
            sortable[column] = numeric

    if isinstance(ascending, list):
        available_ascending = [ascending[columns.index(column)] for column in available]
    else:
        available_ascending = ascending

    try:
        return sortable.sort_values(available, ascending=available_ascending, kind="mergesort")
    except Exception:
        return df


def ensure_ai_overnight_columns(model: pd.DataFrame) -> pd.DataFrame:
    if model.empty:
        return model

    safe = model.copy()

    def numeric_series(source: str, default: float = 0) -> pd.Series:
        if source in safe.columns:
            return pd.to_numeric(safe[source], errors="coerce").fillna(default)
        return pd.Series(default, index=safe.index)

    numeric_defaults: dict[str, pd.Series | float] = {
        "tomorrow_intraday_probability": 0,
        "similarity_based_probability": numeric_series("tomorrow_intraday_probability", 0),
        "module16_consensus_score": numeric_series("tomorrow_intraday_probability", 0) * 0.80,
        "delivery_pct": 0,
        "liquidity_score": 0,
        "volume_profile_score": 0,
        "closing_strength_score": 0,
        "risk_to_reward_estimate": 0,
        "turnover_cr": 0,
        "market_memory_score": numeric_series("historical_behaviour_score", 0),
        "market_dna_score": numeric_series("similarity_based_probability", 0),
        "historical_win_rate": numeric_series("similarity_based_probability", 0),
        "number_of_similar_historical_setups": 0,
        "gap_up_probability": 0,
        "opening_range_breakout_probability": 0,
        "vwap_hold_probability": 0,
        "intraday_trend_probability": 0,
        "expected_intraday_volatility_pct": 0,
        "delivery_score": 0,
        "relative_strength_score": 0,
        "options_score": 0,
        "compression_score": 0,
        "news_catalyst_score": 0,
        "historical_behaviour_score": 0,
    }
    text_defaults = {
        "module16_votes": "Unavailable",
        "module16_decision": "Consensus unavailable - use live confirmation",
        "final_trade_gate": "Watchlist only until live checks pass",
        "live_confirmation_checklist": "Confirm VWAP, ORB, RVOL, selling pressure, market regime, and smart-money score.",
        "classification": "Watchlist",
        "best_entry_time_window": "After opening range confirmation",
        "reason_for_selection": "Overnight setup scored with partial data.",
    }

    for column, default in numeric_defaults.items():
        if column not in safe.columns:
            safe[column] = default
        safe[column] = pd.to_numeric(safe[column], errors="coerce").fillna(0)

    for column, default in text_defaults.items():
        if column not in safe.columns:
            safe[column] = default
        safe[column] = safe[column].fillna(default)

    return safe


def normalize_ohlcv_columns(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history

    normalized = history.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [
            "_".join(str(part) for part in column if str(part) and str(part) != "nan")
            for column in normalized.columns
        ]

    normalized = normalized.reset_index()
    normalized.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).lower()).strip("_")
        for column in normalized.columns
    ]

    rename_map: dict[str, str] = {}
    for target, candidates in {
        "date": ["date", "datetime"],
        "open": ["open"],
        "high": ["high"],
        "low": ["low"],
        "close": ["close", "adj_close", "adjclose"],
        "volume": ["volume"],
    }.items():
        for column in normalized.columns:
            compact = re.sub(r"[^a-z0-9]+", "", column)
            if any(
                compact == re.sub(r"[^a-z0-9]+", "", candidate)
                or compact.startswith(re.sub(r"[^a-z0-9]+", "", candidate))
                or f"_{candidate}_" in f"_{column}_"
                for candidate in candidates
            ):
                rename_map[column] = target
                break

    normalized = normalized.rename(columns=rename_map)
    normalized = normalized.loc[:, ~normalized.columns.duplicated()]
    return normalized


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_nse_delivery_snapshot(nsecode: str) -> dict[str, Any]:
    symbol = str(nsecode).strip().upper().replace(".NS", "")
    if not symbol:
        return {}

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}",
        }
    )
    try:
        session.get("https://www.nseindia.com", timeout=8)
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=trade_info"
        payload = session.get(url, timeout=10).json()
    except Exception:
        return {}

    security = payload.get("securityWiseDP", {}) if isinstance(payload, dict) else {}
    if not security:
        return {}

    def parse_number(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "").replace("%", "").strip())
        except ValueError:
            return None

    return {
        "delivery_quantity": parse_number(security.get("deliveryQuantity")),
        "traded_quantity": parse_number(security.get("quantityTraded")),
        "delivery_percentage": parse_number(security.get("deliveryToTradedQuantity")),
        "delivery_value_cr": parse_number(security.get("deliveryValue")) / 10_000_000 if parse_number(security.get("deliveryValue")) else None,
    }


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_ohlcv_history(nsecode: str, lookback_days: int = 365) -> pd.DataFrame:
    if yf is None or not nsecode:
        return pd.DataFrame()

    symbol = str(nsecode).strip().upper()
    if not symbol.startswith("^") and not symbol.endswith(".NS"):
        symbol = f"{symbol}.NS"

    start = date.today() - timedelta(days=lookback_days)
    try:
        history = yf.download(symbol, start=start.isoformat(), progress=False, auto_adjust=False, threads=False)
    except Exception:
        return pd.DataFrame()

    if history.empty:
        return pd.DataFrame()

    return normalize_ohlcv_columns(history)


@st.cache_data(ttl=60 * 15, show_spinner=False)
def fetch_interval_ohlcv_history(nsecode: str, period: str = "60d", interval: str = "60m") -> pd.DataFrame:
    if yf is None or not nsecode:
        return pd.DataFrame()

    symbol = str(nsecode).strip().upper()
    if not symbol.startswith("^") and not symbol.endswith(".NS"):
        symbol = f"{symbol}.NS"

    try:
        history = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
    except Exception:
        return pd.DataFrame()

    if history.empty:
        return pd.DataFrame()

    return normalize_ohlcv_columns(history)


def enrich_with_ohlcv_indicators(row: pd.Series) -> dict[str, Any]:
    nsecode = str(row.get("nsecode") or "").strip()
    history = fetch_ohlcv_history(nsecode)
    if history.empty or len(history) < 120:
        return {"ohlcv_status": "historical data unavailable"}

    required = {"close", "high", "low", "volume"}
    if not required.issubset(history.columns):
        return {"ohlcv_status": "historical data missing OHLCV columns"}

    df = history.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.rolling(14).mean()

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bollinger_width = ((sma20 + 2 * std20) - (sma20 - 2 * std20)) / sma20
    bb_rank_6m = bollinger_width.iloc[-1] <= bollinger_width.tail(126).quantile(0.20)

    direction = close.diff().fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    obv = (direction * volume.fillna(0)).cumsum()

    down_volume = volume.where(close < previous_close, 0)
    pocket_pivot = bool(volume.iloc[-1] > down_volume.shift(1).rolling(10).max().iloc[-1] and close.iloc[-1] > previous_close.iloc[-1])

    range_pct = (high - low) / close
    latest_range = range_pct.tail(5).mean()
    prior_range = range_pct.shift(5).tail(5).mean()

    recent_high_20 = high.tail(20).max()
    recent_high_55 = high.tail(55).max()
    high_52w = high.tail(252).max()
    latest_close = close.iloc[-1]
    breakout_level = max(recent_high_20, recent_high_55)

    atr_falling_5d = bool(atr14.tail(5).is_monotonic_decreasing)
    obv_rising_10d = bool(obv.iloc[-1] > obv.shift(10).iloc[-1])
    ema_stack = bool(latest_close > ema50.iloc[-1] > ema100.iloc[-1] > ema200.iloc[-1] and ema20.iloc[-1] > ema50.iloc[-1])
    ema200_rising = bool(ema200.iloc[-1] > ema200.shift(10).iloc[-1])
    vcp_proxy = bool(latest_range < prior_range and atr_falling_5d and bb_rank_6m)

    return {
        "ohlcv_status": "historical data enriched",
        "hist_close": round(float(latest_close), 2),
        "hist_breakout_level": round(float(breakout_level), 2),
        "hist_52w_high": round(float(high_52w), 2),
        "hist_atr14": round(float(atr14.iloc[-1]), 2) if pd.notna(atr14.iloc[-1]) else None,
        "hist_bb_width_lowest_20pct_6m": bool(bb_rank_6m),
        "hist_atr_falling_5d": atr_falling_5d,
        "hist_obv_rising_10d": obv_rising_10d,
        "hist_pocket_pivot": pocket_pivot,
        "hist_range_contracting": bool(latest_range < prior_range),
        "hist_vcp_proxy": vcp_proxy,
        "hist_ema_stack": ema_stack,
        "hist_ema200_rising": ema200_rising,
        "hist_within_3pct_52w_high": bool(0 <= percent_gap(float(high_52w), float(latest_close)) <= 3),
        "hist_not_extended_gt_10pct": bool(latest_close <= breakout_level * 1.10),
    }


def build_best_setup_watchlist(high_accuracy_df: pd.DataFrame) -> pd.DataFrame:
    if high_accuracy_df.empty:
        return pd.DataFrame()

    watchlist = high_accuracy_df.copy()
    min_score = 70 if watchlist["accuracy_score"].max() >= 70 else watchlist["accuracy_score"].max()
    watchlist = watchlist[watchlist["accuracy_score"] >= min_score].copy()
    if watchlist.empty:
        return watchlist

    watchlist["setup_status"] = watchlist.apply(setup_status, axis=1)
    watchlist["setup_plan"] = watchlist.apply(setup_plan, axis=1)
    watchlist["risk_note"] = "Not a buy call. Confirm breakout, liquidity, stop-loss, and market trend before acting."

    display_columns = [
        "accuracy_score",
        "confidence_tier",
        "setup_status",
        "nsecode",
        "name",
        "close",
        "per_chg",
        "volume",
        "screeners_count",
        "categories_count",
        "setup_confirmation_count",
        "strict_filter_pass_count",
        "setup_plan",
        "matched_setups",
        "risk_note",
    ]
    return watchlist[[column for column in display_columns if column in watchlist.columns]].head(25)


def render_overlap_table(overlap_df: pd.DataFrame) -> None:
    with st.container(border=True):
        st.subheader("Stocks Present in Multiple Screeners")

        if overlap_df.empty:
            st.info("No stocks are repeated across the selected unique scanner logic.")
            return

        st.caption("Sorted by unique scanner logic count. Duplicate scanner clauses are counted once to avoid inflated confirmation.")
        display_df = overlap_df[preferred_overlap_columns(overlap_df)]
        display_dataframe(display_df, height=420)
        st.download_button(
            "Download repeated stocks CSV",
            display_df.to_csv(index=False).encode("utf-8"),
            file_name="stocks_present_in_multiple_screeners.csv",
            mime="text/csv",
            width="stretch",
        )


def render_best_setup_watchlist(best_setup_df: pd.DataFrame) -> None:
    with st.container(border=True):
        st.subheader("Best Setup Watchlist")
        st.caption(
            "Ranks the strongest setups from the high-accuracy layer. This is a research watchlist, not automatic buy advice."
        )

        if best_setup_df.empty:
            st.info("No best-setup candidates are available yet. Run more scanners or wait for stronger confirmation.")
            return

        display_dataframe(best_setup_df, height=420)
        st.download_button(
            "Download best setup watchlist CSV",
            best_setup_df.to_csv(index=False).encode("utf-8"),
            file_name="best_setup_watchlist.csv",
            mime="text/csv",
            width="stretch",
        )


def institutional_recommendation_status(row: pd.Series) -> str:
    score = float(row.get("institutional_score", 0) or 0)
    if score >= 85:
        return "Top setup candidate"
    if score >= 70:
        return "High-quality watchlist candidate"
    if score >= 55:
        return "Developing setup"
    return "Needs more confirmation"


def build_institutional_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    candidates = df.copy()
    close = numeric_series(candidates, ["close", "latest close"])
    volume = numeric_series(candidates, ["volume", "latest volume"])
    high_52w = numeric_series(candidates, ["52_week_high", "52 week high", "year high", "latest max 252 high"])
    rvol = numeric_series(candidates, ["rvol", "relative volume", "relative_volume"])
    delivery = numeric_series(candidates, ["delivery", "delivery_percent", "delivery percentage", "delivery_pct"])
    turnover = numeric_series(candidates, ["turnover", "turnover_cr", "turnover crore", "value traded"])
    earnings_growth = numeric_series(candidates, ["quarterly earnings growth", "qtr profit growth", "quarterly profit growth"])
    sector_rs = numeric_series(candidates, ["sector relative strength", "sector rs", "relative strength vs nifty"])

    score = pd.Series(40, index=candidates.index, dtype="float64")
    evidence: dict[str, pd.Series] = {}
    missing: list[str] = []

    if close is not None and high_52w is not None:
        distance = (high_52w - close) / high_52w * 100
        candidates["52w_high_distance_pct"] = distance.round(2)
        evidence["within_3pct_52w_high"] = distance.between(0, 3, inclusive="both")
    else:
        missing.append("52-week high distance")

    if rvol is not None:
        evidence["rvol_1_2_to_2_0"] = rvol.between(1.2, 2.0, inclusive="both")
        candidates["rvol_filter"] = rvol
    else:
        missing.append("RVOL")

    if delivery is not None:
        evidence["delivery_above_50"] = delivery.gt(50)
        candidates["delivery_filter"] = delivery
    else:
        missing.append("Delivery %")

    if turnover is not None:
        evidence["turnover_above_50cr"] = turnover.gt(50)
        candidates["turnover_filter"] = turnover
    elif close is not None and volume is not None:
        computed_turnover_cr = close * volume / 10_000_000
        candidates["computed_turnover_cr"] = computed_turnover_cr.round(2)
        evidence["turnover_above_50cr"] = computed_turnover_cr.gt(50)
    else:
        missing.append("Turnover")

    if earnings_growth is not None:
        evidence["quarterly_growth_above_20"] = earnings_growth.gt(20)
        candidates["earnings_growth_filter"] = earnings_growth
    else:
        missing.append("Quarterly earnings growth")

    if sector_rs is not None:
        evidence["sector_rs_above_nifty"] = sector_rs.gt(0)
        candidates["sector_rs_filter"] = sector_rs
    else:
        missing.append("Sector relative strength")

    for name, passed in evidence.items():
        candidates[name] = passed.fillna(False)
        score += passed.fillna(False).astype(int) * 8

    candidates["institutional_score"] = score.clip(upper=100).round(0)
    candidates["recommendation_status"] = candidates.apply(institutional_recommendation_status, axis=1)
    candidates["missing_confirmation_data"] = ", ".join(missing) if missing else "None"
    candidates["recommendation_note"] = (
        "Research candidate only. Confirm breakout trigger, market direction, stop-loss, and position sizing before any trade."
    )

    sort_columns = ["institutional_score"]
    sort_ascending = [False]
    if "volume" in candidates.columns:
        sort_columns.append("volume")
        sort_ascending.append(False)
    candidates = candidates.sort_values(sort_columns, ascending=sort_ascending, kind="mergesort")

    display_columns = [
        "institutional_score",
        "recommendation_status",
        "nsecode",
        "name",
        "close",
        "per_chg",
        "volume",
        "computed_turnover_cr",
        "52w_high_distance_pct",
        "rvol_filter",
        "delivery_filter",
        "turnover_filter",
        "earnings_growth_filter",
        "sector_rs_filter",
        "missing_confirmation_data",
        "recommendation_note",
    ]
    return candidates[[column for column in display_columns if column in candidates.columns]]


def render_institutional_setup_page() -> None:
    st.subheader("Institutional Breakout Setup")
    st.caption(
        "A separate page for your 14-condition institutional-style breakout checklist. The table ranks candidates, but it is not automatic buy advice."
    )

    with st.expander("14-point setup checklist", expanded=True):
        checklist_df = pd.DataFrame({"Rule": range(1, len(INSTITUTIONAL_RULES) + 1), "Condition": INSTITUTIONAL_RULES})
        display_dataframe(checklist_df, height=420)

    with st.sidebar:
        st.header("Institutional Setup Controls")
        institutional_rows = st.slider("Rows shown", 5, 100, 25, 5)
        if st.button("Refresh institutional setup", type="primary", width="stretch"):
            run_scan.clear()
            get_chartink_client.clear()
            st.rerun()

    with st.spinner("Fetching institutional setup candidates..."):
        df, error = run_scan(INSTITUTIONAL_SETUP_CLAUSE)

    if error:
        st.error(error)
        st.caption("If Chartink rejects an indicator name, adjust the clause directly in INSTITUTIONAL_SETUP_CLAUSE.")
        return

    candidates = build_institutional_candidates(df)
    if candidates.empty:
        st.info("No candidates currently match the institutional setup pre-filter.")
        return

    st.metric("Recommended setup candidates", len(candidates))
    display_dataframe(candidates.head(institutional_rows), height=520)
    st.download_button(
        "Download institutional setup candidates CSV",
        candidates.to_csv(index=False).encode("utf-8"),
        file_name="institutional_breakout_setup_candidates.csv",
        mime="text/csv",
        width="stretch",
    )


def score_breakout_candidate(row: pd.Series) -> dict[str, Any]:
    close = first_numeric_value(row, ["close", "latest close"]) or 0
    high_52w = first_numeric_value(row, ["hist_52w_high", "52_week_high", "52 week high", "year high", "latest max 252 high"])
    darvas_high = first_numeric_value(row, ["hist_breakout_level", "darvas breakout level", "darvas_breakout_level", "box high", "box_high"])
    resistance = first_numeric_value(row, ["resistance", "resistance level", "nearest resistance"])
    atr = first_numeric_value(row, ["hist_atr14", "atr", "atr_14", "latest atr 14"])
    rvol = first_numeric_value(row, ["rvol", "relative volume", "relative_volume"])
    delivery = first_numeric_value(row, ["delivery", "delivery_percent", "delivery percentage", "delivery_pct"])
    turnover = first_numeric_value(row, ["turnover", "turnover_cr", "turnover crore", "value traded"])
    volume = first_numeric_value(row, ["volume", "latest volume"])
    earnings_growth = first_numeric_value(row, ["quarterly earnings growth", "qtr profit growth", "quarterly profit growth"])
    sector_rs = first_numeric_value(row, ["sector relative strength", "sector rs", "relative strength vs nifty"])
    rs_rating = first_numeric_value(row, ["rs rating", "relative strength rating", "rs_rating"])

    if turnover is None and close and volume:
        turnover = close * volume / 10_000_000

    breakout_level = darvas_high or resistance or high_52w or (close * 1.03 if close else None)
    breakout_gap = percent_gap(breakout_level, close)
    high_gap = percent_gap(high_52w, close)

    trend_score = BREAKOUT_PHASE_WEIGHTS["trend_template_score"]
    if row.get("hist_ema_stack") is False or row.get("hist_ema200_rising") is False:
        trend_score = 8

    vcp_score = 9
    if row.get("hist_vcp_proxy") is True:
        vcp_score = 15
    elif row.get("hist_range_contracting") is True:
        vcp_score += 2
    if row.get("hist_atr_falling_5d") is True:
        vcp_score += 2
    if row.get("hist_bb_width_lowest_20pct_6m") is True:
        vcp_score += 2
    if rvol is not None and 1.2 <= rvol <= 2.0:
        vcp_score += 3
    if atr is not None:
        vcp_score += 2
    if breakout_gap is not None and 0 <= breakout_gap <= 5:
        vcp_score += 1
    vcp_score = bounded_score(vcp_score, BREAKOUT_PHASE_WEIGHTS["vcp_score"])

    darvas_score = 7
    if breakout_gap is not None:
        if 0 <= breakout_gap <= 3:
            darvas_score = 15
        elif 3 < breakout_gap <= 5:
            darvas_score = 12
    darvas_score = bounded_score(darvas_score, BREAKOUT_PHASE_WEIGHTS["darvas_score"])

    wyckoff_score = 5
    if row.get("hist_obv_rising_10d") is True:
        wyckoff_score += 2
    if rvol is not None and rvol < 2.0:
        wyckoff_score += 2
    if delivery is not None and delivery > 50:
        wyckoff_score += 3
    wyckoff_score = bounded_score(wyckoff_score, BREAKOUT_PHASE_WEIGHTS["wyckoff_score"])

    pocket_pivot_score = 5
    if row.get("hist_pocket_pivot") is True:
        pocket_pivot_score = 10
    if rvol is not None and rvol >= 1.2:
        pocket_pivot_score += 3
    if close and breakout_level and close < breakout_level:
        pocket_pivot_score += 2
    pocket_pivot_score = bounded_score(pocket_pivot_score, BREAKOUT_PHASE_WEIGHTS["pocket_pivot_score"])

    institutional_score = 7
    if row.get("hist_obv_rising_10d") is True:
        institutional_score += 2
    if delivery is not None and delivery > 50:
        institutional_score += 4
    if turnover is not None and turnover > 50:
        institutional_score += 4
    institutional_score = bounded_score(institutional_score, BREAKOUT_PHASE_WEIGHTS["institutional_score"])

    relative_strength_score = 5
    if row.get("hist_within_3pct_52w_high") is True:
        relative_strength_score = 8
    if rs_rating is not None and rs_rating >= 80:
        relative_strength_score = 10
    elif sector_rs is not None and sector_rs > 0:
        relative_strength_score = 8
    elif high_gap is not None and 0 <= high_gap <= 3:
        relative_strength_score = 7
    relative_strength_score = bounded_score(relative_strength_score, BREAKOUT_PHASE_WEIGHTS["relative_strength_score"])

    sector_strength_score = 3
    if sector_rs is not None and sector_rs > 0:
        sector_strength_score = 5
    sector_strength_score = bounded_score(sector_strength_score, BREAKOUT_PHASE_WEIGHTS["sector_strength_score"])

    earnings_score = 2
    if earnings_growth is not None and earnings_growth > 20:
        earnings_score = 5
    earnings_score = bounded_score(earnings_score, BREAKOUT_PHASE_WEIGHTS["earnings_score"])

    total_score = sum(
        [
            trend_score,
            vcp_score,
            darvas_score,
            wyckoff_score,
            pocket_pivot_score,
            institutional_score,
            relative_strength_score,
            sector_strength_score,
            earnings_score,
        ]
    )

    entry_low = close
    entry_high = breakout_level if breakout_level and breakout_level > close else close * 1.02
    stop_loss = close - (atr * 1.5) if atr and close else close * 0.94
    intraday_target = breakout_level * 1.015 if breakout_level else close * 1.025
    swing_target = breakout_level * 1.08 if breakout_level else close * 1.10
    risk = max(entry_high - stop_loss, 0.01)
    reward = max(swing_target - entry_high, 0.01)
    risk_reward = reward / risk

    missing = []
    for label, value in [
        ("Darvas box high", darvas_high),
        ("ATR", atr),
        ("RVOL", rvol),
        ("Delivery %", delivery),
        ("Relative strength", rs_rating or sector_rs),
        ("Sector strength", sector_rs),
        ("Earnings growth", earnings_growth),
    ]:
        if value is None:
            missing.append(label)
    if row.get("ohlcv_status") != "historical data enriched":
        missing.append(str(row.get("ohlcv_status", "historical data unavailable")))

    reason_parts = [
        "trend template passed",
        f"breakout gap {breakout_gap:.2f}%" if breakout_gap is not None else "breakout level estimated",
        f"turnover {turnover:.1f} crore" if turnover is not None else "turnover unavailable",
    ]
    if delivery is not None:
        reason_parts.append(f"delivery {delivery:.1f}%")
    if rvol is not None:
        reason_parts.append(f"RVOL {rvol:.2f}")

    return {
        "breakout_level": round(breakout_level, 2) if breakout_level else None,
        "entry_zone": f"{entry_low:.2f} - {entry_high:.2f}" if close else "",
        "stop_loss": round(stop_loss, 2),
        "intraday_target": round(intraday_target, 2),
        "swing_target": round(swing_target, 2),
        "probability_score": bounded_score(total_score, 100),
        "vcp_score": vcp_score,
        "darvas_score": darvas_score,
        "wyckoff_score": wyckoff_score,
        "pocket_pivot_score": pocket_pivot_score,
        "institutional_score": institutional_score,
        "relative_strength_score": relative_strength_score,
        "sector_strength_score": sector_strength_score,
        "earnings_score": earnings_score,
        "expected_breakout_window": "1-5 trading sessions" if total_score >= 80 else "Watchlist only",
        "risk_reward_ratio": round(risk_reward, 2),
        "reason_for_selection": "; ".join(reason_parts),
        "missing_model_data": ", ".join(missing) if missing else "None",
    }


def enrich_candidates_with_history(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    if df.empty or "nsecode" not in df.columns:
        return df

    enriched_rows: list[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        current = row.to_dict()
        current.update(enrich_with_ohlcv_indicators(row))
        enriched_rows.append(current)

    return pd.DataFrame(enriched_rows)


def build_breakout_probability_model(df: pd.DataFrame, use_history: bool = True, history_limit: int = 80) -> pd.DataFrame:
    if df.empty:
        return df

    if use_history:
        df = enrich_candidates_with_history(df, history_limit)

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        scored = score_breakout_candidate(row)
        current = row.to_dict()
        current.update(scored)
        rows.append(current)

    model = pd.DataFrame(rows)
    if model.empty:
        return model

    turnover = numeric_series(model, ["turnover", "turnover_cr", "turnover crore", "computed_turnover_cr", "value traded"])
    close = numeric_series(model, ["close", "latest close"])
    volume = numeric_series(model, ["volume", "latest volume"])
    if turnover is None and close is not None and volume is not None:
        model["computed_turnover_cr"] = (close * volume / 10_000_000).round(2)
        turnover = model["computed_turnover_cr"]

    if turnover is not None:
        model = model[turnover >= 50]
    model = model[model["probability_score"] > 80]
    if model.empty:
        return model

    model = model.sort_values(["probability_score", "risk_reward_ratio"], ascending=[False, False], kind="mergesort")
    model["candidate_highlight"] = ""
    if not model.empty:
        model.loc[model.index[0], "candidate_highlight"] = "Highest Probability Breakout Candidate"
        model.loc[model["risk_reward_ratio"].idxmax(), "candidate_highlight"] += "; Best Swing Candidate"
        model.loc[model["pocket_pivot_score"].idxmax(), "candidate_highlight"] += "; Best Intraday Candidate"
        model.loc[model["institutional_score"].idxmax(), "candidate_highlight"] += "; Best Institutional Accumulation Candidate"
        hidden_gem_idx = model.sort_values(["probability_score", "volume"], ascending=[False, True], kind="mergesort").index[0]
        model.loc[hidden_gem_idx, "candidate_highlight"] += "; Hidden Gem Candidate"
        model["candidate_highlight"] = model["candidate_highlight"].str.strip("; ")

    display_columns = [
        "candidate_highlight",
        "name",
        "nsecode",
        "sector",
        "close",
        "breakout_level",
        "entry_zone",
        "stop_loss",
        "intraday_target",
        "swing_target",
        "probability_score",
        "vcp_score",
        "darvas_score",
        "wyckoff_score",
        "institutional_score",
        "relative_strength_score",
        "sector_strength_score",
        "expected_breakout_window",
        "risk_reward_ratio",
        "reason_for_selection",
        "ohlcv_status",
        "hist_vcp_proxy",
        "hist_atr_falling_5d",
        "hist_bb_width_lowest_20pct_6m",
        "hist_obv_rising_10d",
        "hist_pocket_pivot",
        "missing_model_data",
    ]
    return model[[column for column in display_columns if column in model.columns]]


def render_breakout_probability_page() -> None:
    st.subheader("Breakout Probability Model")
    st.caption(
        "Ranks NSE stocks most likely to attempt a breakout within 1-5 trading sessions using trend, VCP, Darvas, Wyckoff, pocket pivot, accumulation, relative strength, sector, and earnings factors."
    )

    with st.expander("10-phase model and weights", expanded=True):
        phase_df = pd.DataFrame(
            {
                "Phase": range(1, len(BREAKOUT_PHASES) + 1),
                "Model Component": BREAKOUT_PHASES,
                "Weight": list(BREAKOUT_PHASE_WEIGHTS.values()),
            }
        )
        display_dataframe(phase_df, height=380)

    with st.sidebar:
        st.header("Breakout Model Controls")
        breakout_rows = st.slider("Rows shown", 5, 100, 25, 5, key="breakout_rows")
        use_history = st.toggle("Use historical OHLCV indicators", value=True)
        history_limit = st.slider("Candidates to enrich with OHLCV", 10, 150, 60, 10, disabled=not use_history)
        if st.button("Refresh breakout probability model", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            get_chartink_client.clear()
            st.rerun()

    with st.spinner("Fetching breakout probability candidates..."):
        df, error = run_scan(BREAKOUT_PROBABILITY_CLAUSE)

    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust BREAKOUT_PROBABILITY_CLAUSE.")
        return

    if use_history and yf is None:
        st.warning("Install yfinance to enable historical OHLCV enrichment: pip install yfinance")

    model = build_breakout_probability_model(df, use_history=use_history and yf is not None, history_limit=history_limit)
    if model.empty:
        st.info("No stocks currently pass the probability model threshold: score > 80 and turnover > 50 crore.")
        return

    best = model.iloc[0]
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Qualified candidates", len(model))
    metric_b.metric("Top probability score", int(best["probability_score"]))
    metric_c.metric("Top candidate", str(best.get("nsecode") or best.get("name") or "N/A"))

    display_dataframe(model.head(breakout_rows), height=560)
    st.download_button(
        "Download breakout probability candidates CSV",
        model.to_csv(index=False).encode("utf-8"),
        file_name="breakout_probability_candidates.csv",
        mime="text/csv",
        width="stretch",
    )


def delivery_quality_score(delivery: float | None) -> int:
    if delivery is None:
        return 0
    if delivery > 60:
        return 100
    if delivery >= 50:
        return 80
    if delivery >= 40:
        return 50
    return 20


def score_hedge_fund_candidate(row: pd.Series) -> dict[str, Any]:
    close = first_numeric_value(row, ["hist_close", "close", "latest close"]) or 0
    volume = first_numeric_value(row, ["volume", "latest volume"])
    breakout_level = first_numeric_value(row, ["hist_breakout_level", "darvas breakout level", "box high", "resistance"])
    high_52w = first_numeric_value(row, ["hist_52w_high", "52_week_high", "52 week high", "year high"])
    atr = first_numeric_value(row, ["hist_atr14", "atr", "atr_14"])
    rvol = first_numeric_value(row, ["rvol", "relative volume", "relative_volume"])
    delivery = first_numeric_value(row, ["delivery", "delivery_percent", "delivery percentage", "delivery_pct"])
    turnover = first_numeric_value(row, ["turnover", "turnover_cr", "turnover crore", "computed_turnover_cr", "value traded"])
    earnings_growth = first_numeric_value(row, ["quarterly earnings growth", "qtr profit growth", "quarterly profit growth"])
    revenue_growth = first_numeric_value(row, ["revenue growth", "sales growth", "quarterly sales growth"])
    roe = first_numeric_value(row, ["roe", "return on equity"])
    roce = first_numeric_value(row, ["roce", "return on capital employed"])
    debt_equity = first_numeric_value(row, ["debt to equity", "debt_equity"])
    sector_rs = first_numeric_value(row, ["sector relative strength", "sector rs", "relative strength vs nifty"])
    rs_rating = first_numeric_value(row, ["rs rating", "relative strength rating", "rs_rating"])

    if turnover is None and close and volume:
        turnover = close * volume / 10_000_000
    if breakout_level is None and high_52w is not None:
        breakout_level = high_52w
    if breakout_level is None and close:
        breakout_level = close * 1.03

    breakout_gap = percent_gap(breakout_level, close)
    high_gap = percent_gap(high_52w, close)

    trend_score = 10 if row.get("hist_ema_stack") is not False and row.get("hist_ema200_rising") is not False else 6

    breakout_score = 7
    if breakout_gap is not None and 0 <= breakout_gap <= 3:
        breakout_score = 15
    elif breakout_gap is not None and 3 < breakout_gap <= 5:
        breakout_score = 12
    if row.get("hist_not_extended_gt_10pct") is False:
        breakout_score = 0

    vcp_score = 4
    if row.get("hist_vcp_proxy") is True:
        vcp_score = 10
    else:
        vcp_score += 2 if row.get("hist_atr_falling_5d") is True else 0
        vcp_score += 2 if row.get("hist_bb_width_lowest_20pct_6m") is True else 0
        vcp_score += 2 if row.get("hist_range_contracting") is True else 0
    vcp_score = bounded_score(vcp_score, 10)

    darvas_score = 5
    if breakout_gap is not None and 0 <= breakout_gap <= 3:
        darvas_score = 10
    elif breakout_gap is not None and 3 < breakout_gap <= 5:
        darvas_score = 8

    wyckoff_score = 4
    if row.get("hist_obv_rising_10d") is True:
        wyckoff_score += 3
    if rvol is not None and rvol <= 2:
        wyckoff_score += 2
    if delivery is not None and delivery >= 50:
        wyckoff_score += 1
    wyckoff_score = bounded_score(wyckoff_score, 10)

    pocket_pivot_score = 10 if row.get("hist_pocket_pivot") is True else 5
    if rvol is not None and rvol >= 1.2:
        pocket_pivot_score += 2
    pocket_pivot_score = bounded_score(pocket_pivot_score, 10)

    delivery_score = bounded_score(delivery_quality_score(delivery) / 10, 10)
    institutional_quality_score = 30
    institutional_quality_score += 25 if delivery is not None and delivery >= 50 else 0
    institutional_quality_score += 20 if turnover is not None and turnover >= 50 else 0
    institutional_quality_score += 15 if row.get("hist_obv_rising_10d") is True else 0
    institutional_quality_score += 10 if row.get("hist_pocket_pivot") is True else 0
    institutional_quality_score = bounded_score(institutional_quality_score, 100)
    institutional_phase_score = bounded_score(institutional_quality_score / 100 * 15, 15)

    relative_strength_score = 5
    if rs_rating is not None and rs_rating >= 80:
        relative_strength_score = 10
    elif sector_rs is not None and sector_rs > 0:
        relative_strength_score = 8
    elif high_gap is not None and 0 <= high_gap <= 3:
        relative_strength_score = 7

    sector_score = 5 if sector_rs is not None and sector_rs > 0 else 3

    fundamental_score = 1
    if earnings_growth is not None and earnings_growth > 20:
        fundamental_score += 2
    if revenue_growth is not None and revenue_growth > 15:
        fundamental_score += 1
    if (roe is not None and roe > 15) or (roce is not None and roce > 15):
        fundamental_score += 1
    fundamental_score = bounded_score(fundamental_score, 5)

    total_score = sum(
        [
            trend_score,
            breakout_score,
            vcp_score,
            darvas_score,
            wyckoff_score,
            institutional_phase_score,
            delivery_score,
            relative_strength_score,
            sector_score,
            fundamental_score,
        ]
    )

    strength_score = bounded_score(
        trend_score * 0.8
        + relative_strength_score * 0.7
        + institutional_phase_score * 0.5
        + fundamental_score,
        25,
    )
    weakness_score = 5
    weakness_score += 6 if delivery is None or delivery < 50 else 0
    weakness_score += 5 if debt_equity is not None and debt_equity > 1 else 0
    weakness_score += 5 if row.get("hist_not_extended_gt_10pct") is False else 0
    weakness_score = bounded_score(weakness_score, 25)

    opportunity_score = bounded_score(breakout_score * 0.8 + vcp_score * 0.6 + sector_score + pocket_pivot_score * 0.4, 25)
    threat_score = 5
    threat_score += 5 if breakout_gap is not None and breakout_gap < 0 else 0
    threat_score += 5 if high_gap is not None and high_gap < -10 else 0
    threat_score += 5 if turnover is None or turnover < 50 else 0
    threat_score = bounded_score(threat_score, 25)
    swot_advantage_score = (strength_score + opportunity_score) - (weakness_score + threat_score)

    entry_low = close
    entry_high = breakout_level if breakout_level and breakout_level > close else close * 1.02
    stop_loss = close - (atr * 1.5) if atr and close else close * 0.94
    intraday_target = breakout_level * 1.015 if breakout_level else close * 1.025
    swing_target = breakout_level * 1.08 if breakout_level else close * 1.10
    risk = max(entry_high - stop_loss, 0.01)
    reward = max(swing_target - entry_high, 0.01)

    expected_window = "1-5 days" if total_score >= 90 else "5-20 days"
    reason = [
        "trend structure passed",
        f"breakout gap {breakout_gap:.2f}%" if breakout_gap is not None else "breakout level estimated",
        "VCP proxy confirmed" if row.get("hist_vcp_proxy") is True else "VCP proxy partial",
        "OBV rising" if row.get("hist_obv_rising_10d") is True else "OBV not verified",
    ]
    if delivery is not None:
        reason.append(f"delivery {delivery:.1f}%")
    if turnover is not None:
        reason.append(f"turnover {turnover:.1f} crore")

    return {
        "delivery_percentage": round(delivery, 2) if delivery is not None else None,
        "breakout_level": round(breakout_level, 2) if breakout_level else None,
        "entry_zone": f"{entry_low:.2f} - {entry_high:.2f}" if close else "",
        "stop_loss": round(stop_loss, 2),
        "intraday_target": round(intraday_target, 2),
        "swing_target": round(swing_target, 2),
        "total_score": bounded_score(total_score, 100),
        "trend_score": trend_score,
        "breakout_score": breakout_score,
        "vcp_score": vcp_score,
        "darvas_score": darvas_score,
        "wyckoff_score": wyckoff_score,
        "pocket_pivot_score": pocket_pivot_score,
        "institutional_score": institutional_quality_score,
        "institutional_phase_score": institutional_phase_score,
        "delivery_score": delivery_score,
        "relative_strength_score": relative_strength_score,
        "sector_score": sector_score,
        "fundamental_score": fundamental_score,
        "strength_score": strength_score,
        "weakness_score": weakness_score,
        "opportunity_score": opportunity_score,
        "threat_score": threat_score,
        "swot_advantage_score": swot_advantage_score,
        "expected_breakout_window": expected_window,
        "risk_reward_ratio": round(reward / risk, 2),
        "reason_for_selection": "; ".join(reason),
        "turnover_cr": round(turnover, 2) if turnover is not None else None,
    }


def hedge_fund_display_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "candidate_highlight",
        "name",
        "nsecode",
        "sector",
        "close",
        "delivery_percentage",
        "breakout_level",
        "entry_zone",
        "stop_loss",
        "intraday_target",
        "swing_target",
        "total_score",
        "strength_score",
        "weakness_score",
        "opportunity_score",
        "threat_score",
        "swot_advantage_score",
        "institutional_score",
        "expected_breakout_window",
        "risk_reward_ratio",
        "reason_for_selection",
        "turnover_cr",
        "trend_score",
        "breakout_score",
        "vcp_score",
        "darvas_score",
        "wyckoff_score",
        "delivery_score",
        "relative_strength_score",
        "sector_score",
        "fundamental_score",
        "ohlcv_status",
    ]
    return [column for column in columns if column in df.columns]


def add_candidate_highlights(model: pd.DataFrame) -> pd.DataFrame:
    if model.empty:
        return model

    highlighted = model.copy()
    highlighted["candidate_highlight"] = ""
    highlighted.loc[highlighted.index[0], "candidate_highlight"] = "Highest Probability Breakout Candidate"
    highlighted.loc[highlighted["risk_reward_ratio"].idxmax(), "candidate_highlight"] += "; Best Swing Candidate"
    highlighted.loc[highlighted["institutional_score"].idxmax(), "candidate_highlight"] += "; Best Institutional Accumulation Candidate"
    if "pocket_pivot_score" in highlighted.columns:
        highlighted.loc[highlighted["pocket_pivot_score"].idxmax(), "candidate_highlight"] += "; Best Intraday Candidate"
    low_risk_idx = highlighted.sort_values(["threat_score", "weakness_score", "total_score"], ascending=[True, True, False], kind="mergesort").index[0]
    highlighted.loc[low_risk_idx, "candidate_highlight"] += "; Best Low-Risk Candidate"
    hidden_gem_idx = highlighted.sort_values(["total_score", "volume"], ascending=[False, True], kind="mergesort").index[0] if "volume" in highlighted.columns else highlighted.index[0]
    highlighted.loc[hidden_gem_idx, "candidate_highlight"] += "; Best Hidden Gem Candidate"
    highlighted["candidate_highlight"] = highlighted["candidate_highlight"].str.strip("; ")
    return highlighted


def apply_hedge_fund_filters(
    model: pd.DataFrame,
    min_total_score: int,
    min_swot_advantage: int,
    min_delivery: int,
    min_institutional: int,
    min_turnover: int,
) -> pd.DataFrame:
    if model.empty:
        return model

    filtered = model[
        (pd.to_numeric(model["total_score"], errors="coerce") >= min_total_score)
        & (pd.to_numeric(model["swot_advantage_score"], errors="coerce") >= min_swot_advantage)
        & (pd.to_numeric(model["delivery_percentage"], errors="coerce").fillna(0) >= min_delivery)
        & (pd.to_numeric(model["institutional_score"], errors="coerce") >= min_institutional)
        & (pd.to_numeric(model["turnover_cr"], errors="coerce").fillna(0) >= min_turnover)
    ].copy()

    filtered = filtered.sort_values(["total_score", "swot_advantage_score", "risk_reward_ratio"], ascending=[False, False, False], kind="mergesort")
    return add_candidate_highlights(filtered)


def build_single_stock_swot(symbol: str) -> pd.DataFrame:
    symbol = symbol.strip().upper().replace(".NS", "")
    if not symbol:
        return pd.DataFrame()

    base_row = pd.Series({"nsecode": symbol, "name": symbol})
    enriched = base_row.to_dict()
    enriched.update(enrich_with_ohlcv_indicators(base_row))
    if enriched.get("hist_close") is not None:
        enriched["close"] = enriched["hist_close"]
    scored = score_hedge_fund_candidate(pd.Series(enriched))
    enriched.update(scored)
    result = pd.DataFrame([enriched])
    return result[hedge_fund_display_columns(result)]


def get_stock_analysis_snapshot(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper().replace(".NS", "")
    if not symbol:
        return {}

    history = fetch_ohlcv_history(symbol)
    snapshot: dict[str, Any] = {"symbol": symbol, "name": symbol, "history_status": "historical data unavailable"}
    if history.empty:
        return snapshot
    if "close" not in history.columns:
        history = normalize_ohlcv_columns(history)
    if "close" not in history.columns:
        snapshot["history_status"] = f"historical data missing close column: {', '.join(map(str, history.columns))}"
        return snapshot

    close = pd.to_numeric(history["close"], errors="coerce")
    close = close.dropna()
    if close.empty:
        snapshot["history_status"] = "historical close data unavailable"
        return snapshot
    volume = pd.to_numeric(history["volume"], errors="coerce") if "volume" in history.columns else pd.Series(dtype="float64")
    latest_close = float(close.iloc[-1])
    previous_close = float(close.iloc[-2]) if len(close) > 1 and pd.notna(close.iloc[-2]) else latest_close
    pct_change = (latest_close - previous_close) / previous_close * 100 if previous_close else 0
    latest_volume = float(volume.iloc[-1]) if not volume.empty and pd.notna(volume.iloc[-1]) else None
    avg_volume_20 = float(volume.tail(20).mean()) if not volume.empty else None
    computed_turnover_cr = latest_close * latest_volume / 10_000_000 if latest_volume else None
    delivery_snapshot = fetch_nse_delivery_snapshot(symbol)

    periods = [5, 10, 20, 26, 50, 100, 150, 200]
    ema_values = {period: float(close.ewm(span=period, adjust=False).mean().iloc[-1]) for period in periods}
    sma_values = {period: float(close.rolling(period).mean().iloc[-1]) for period in periods if len(close) >= period}
    bullish_ema = sum(1 for value in ema_values.values() if latest_close > value)
    bearish_ema = len(ema_values) - bullish_ema
    bullish_sma = sum(1 for value in sma_values.values() if latest_close > value)
    bearish_sma = len(sma_values) - bullish_sma

    swot_df = build_single_stock_swot(symbol)
    if not swot_df.empty:
        swot_row = swot_df.iloc[0]
        strength = int(swot_row.get("strength_score", 0) or 0)
        weakness = int(swot_row.get("weakness_score", 0) or 0)
        opportunity = int(swot_row.get("opportunity_score", 0) or 0)
        threat = int(swot_row.get("threat_score", 0) or 0)
    else:
        strength = weakness = opportunity = threat = 0

    snapshot.update(
        {
            "history_status": "historical data available",
            "current_price": latest_close,
            "pct_change": pct_change,
            "latest_volume": latest_volume,
            "avg_volume_20": avg_volume_20,
            "computed_turnover_cr": computed_turnover_cr,
            "delivery_snapshot": delivery_snapshot,
            "ema_values": ema_values,
            "sma_values": sma_values,
            "bullish_ema": bullish_ema,
            "bearish_ema": bearish_ema,
            "bullish_sma": bullish_sma,
            "bearish_sma": bearish_sma,
            "strength_score": strength,
            "weakness_score": weakness,
            "opportunity_score": opportunity,
            "threat_score": threat,
            "swot_df": swot_df,
        }
    )
    return snapshot


def render_ma_gauge(bullish: int, bearish: int) -> str:
    total = max(bullish + bearish, 1)
    bars = []
    for index in range(total):
        if index < bearish:
            color = "#f43f5e"
        elif index < bearish + max(1, total // 5):
            color = "#2563eb"
        else:
            color = "#10b981"
        bars.append(f'<span style="display:inline-block;width:10px;height:{46 + index}px;border-radius:8px;background:{color};margin:0 5px;"></span>')

    marker_pct = max(0, min(100, bearish / total * 100))
    gauge_width = max(180, total * 22)
    return f"""
    <div class="gauge-wrap">
    <div style="position:relative;margin:34px 0 28px;width:{gauge_width}px;max-width:100%;padding-left:0;">
        <div style="position:absolute;left:{marker_pct}%;top:-8px;width:5px;height:92px;background:#111827;border-radius:5px;"></div>
        <div style="position:absolute;left:calc({marker_pct}% - 11px);top:34px;width:22px;height:22px;border:5px solid #111827;border-radius:50%;background:#fff;"></div>
        <div style="white-space:nowrap;overflow:hidden;">{''.join(bars)}</div>
    </div>
    </div>
    """


def render_swot_donut(strength: int, weakness: int, opportunity: int, threat: int) -> str:
    total = max(strength + weakness + opportunity + threat, 1)
    s = strength / total * 100
    w = weakness / total * 100
    o = opportunity / total * 100
    t = threat / total * 100
    return f"""
    <div style="width:260px;height:260px;border-radius:50%;background:
        conic-gradient(#10b981 0 {s}%,
        #fbbf24 {s}% {s + w}%,
        #475569 {s + w}% {s + w + o}%,
        #ef4444 {s + w + o}% 100%);
        position:relative;margin:0 auto;">
        <div style="position:absolute;inset:70px;background:white;border-radius:50%;"></div>
    </div>
    """


def build_swot_details(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    swot_df = snapshot.get("swot_df", pd.DataFrame())
    row = swot_df.iloc[0] if isinstance(swot_df, pd.DataFrame) and not swot_df.empty else pd.Series(dtype="object")

    details = {
        "Strengths": [],
        "Weakness": [],
        "Opportunity": [],
        "Threats": [],
    }

    bullish_ema = int(snapshot.get("bullish_ema", 0) or 0)
    bearish_ema = int(snapshot.get("bearish_ema", 0) or 0)
    turnover = snapshot.get("computed_turnover_cr")
    avg_volume_20 = snapshot.get("avg_volume_20")
    latest_volume = snapshot.get("latest_volume")

    if bullish_ema > bearish_ema:
        details["Strengths"].append(f"Price is above {bullish_ema} tracked EMA levels, showing trend support.")
    else:
        details["Weakness"].append(f"Price is below {bearish_ema} tracked EMA levels, so trend confirmation is weak.")

    if row.get("hist_ema_stack") is True:
        details["Strengths"].append("EMA trend template is bullish.")
    if row.get("hist_obv_rising_10d") is True:
        details["Strengths"].append("OBV is rising over the last 10 sessions, indicating accumulation pressure.")
    if row.get("hist_vcp_proxy") is True:
        details["Opportunity"].append("Volatility contraction pattern proxy is active.")
    if row.get("hist_pocket_pivot") is True:
        details["Opportunity"].append("Pocket pivot proxy is present near the setup zone.")
    if row.get("hist_within_3pct_52w_high") is True:
        details["Opportunity"].append("Price is close to its 52-week high zone.")
    if turnover is not None:
        if turnover >= 50:
            details["Strengths"].append(f"Computed turnover is strong at about Rs {turnover:.1f} crore.")
        else:
            details["Weakness"].append(f"Computed turnover is below institutional threshold at about Rs {turnover:.1f} crore.")
    if latest_volume is not None and avg_volume_20:
        volume_ratio = latest_volume / avg_volume_20
        if volume_ratio >= 1.2:
            details["Opportunity"].append(f"Volume is {volume_ratio:.2f}x the 20-day average.")
        elif volume_ratio < 0.8:
            details["Threats"].append(f"Volume is muted at {volume_ratio:.2f}x the 20-day average.")

    delivery = row.get("delivery_percentage")
    if pd.isna(delivery):
        details["Threats"].append("True delivery percentage is unavailable from the current data provider.")
    elif delivery >= 50:
        details["Strengths"].append(f"Delivery is healthy at {delivery:.1f}%.")
    else:
        details["Weakness"].append(f"Delivery is weak at {delivery:.1f}%.")

    if not details["Strengths"]:
        details["Strengths"].append("No major strength confirmed from available data.")
    if not details["Weakness"]:
        details["Weakness"].append("No major weakness detected from available data.")
    if not details["Opportunity"]:
        details["Opportunity"].append("No near-term opportunity trigger confirmed yet.")
    if not details["Threats"]:
        details["Threats"].append("No major threat detected from available data.")

    return details


def render_swot_text_sections(snapshot: dict[str, Any]) -> None:
    details = build_swot_details(snapshot)
    labels = ["Strengths", "Weakness", "Opportunity", "Threats"]
    columns = st.columns(4)
    for label, column in zip(labels, columns):
        with column:
            st.markdown(f"**{label.upper()}**")
            for item in details[label]:
                st.markdown(f"- {item}")


def render_stock_technicals_card(snapshot: dict[str, Any], ma_mode: str) -> None:
    values = snapshot["ema_values"] if ma_mode == "EMA" else snapshot["sma_values"]
    bullish = snapshot["bullish_ema"] if ma_mode == "EMA" else snapshot["bullish_sma"]
    bearish = snapshot["bearish_ema"] if ma_mode == "EMA" else snapshot["bearish_sma"]
    pct = snapshot["pct_change"]
    pct_class = "up" if pct >= 0 else "down"
    arrow = "up" if pct >= 0 else "down"

    st.markdown('<div class="phone-card">', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"### {snapshot['symbol']} {ma_mode} & SMA")
        st.markdown(
            f"""
            <div class="price-center">{snapshot['current_price']:.2f} <span class="{pct_class}">{arrow} {pct:.2f}%</span></div>
            <div class="metric-label">CURRENT PRICE</div>
            {render_ma_gauge(bullish, bearish)}
            """,
            unsafe_allow_html=True,
        )
        row_a, row_b = st.columns([5, 1])
        with row_a:
            st.markdown('<span class="swatch" style="background:#10b981;"></span>Bullish Moving Averages', unsafe_allow_html=True)
        with row_b:
            st.markdown(f"**{bullish}**")
        row_c, row_d = st.columns([5, 1])
        with row_c:
            st.markdown('<span class="swatch" style="background:#f43f5e;"></span>Bearish Moving Averages', unsafe_allow_html=True)
        with row_d:
            st.markdown(f"**{bearish}**")
    st.markdown('</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    short_period = 5
    long_period = 26
    with col_a:
        st.metric(f"{short_period} Day {ma_mode}", f"{values.get(short_period, 0):.2f}")
    with col_b:
        st.metric(f"{long_period} Day {ma_mode}", f"{values.get(long_period, 0):.2f}")


def render_stock_swot_card(snapshot: dict[str, Any]) -> None:
    strength = snapshot["strength_score"]
    weakness = snapshot["weakness_score"]
    opportunity = snapshot["opportunity_score"]
    threat = snapshot["threat_score"]
    st.markdown(
        f"""
        <div class="mobile-card">
            <div class="swot-grid">
                <div>{render_swot_donut(strength, weakness, opportunity, threat)}</div>
                <div>
                    <div class="swot-legend-row"><span><span class="swatch" style="background:#10b981;"></span>Strengths</span><strong>{strength}</strong></div>
                    <div class="swot-legend-row"><span><span class="swatch" style="background:#fbbf24;"></span>Weakness</span><strong>{weakness}</strong></div>
                    <div class="swot-legend-row"><span><span class="swatch" style="background:#475569;"></span>Opportunity</span><strong>{opportunity}</strong></div>
                    <div class="swot-legend-row"><span><span class="swatch" style="background:#ef4444;"></span>Threats</span><strong>{threat}</strong></div>
                </div>
            </div>
            <div class="swot-nav"><span>STRENGTHS</span><span>WEAKNESS</span><span>OPPORTUNITY</span><span>THREATS</span></div>
            <p>Trend structure, price behavior, volatility contraction, and historical momentum are translated into SWOT-style scores.</p>
            <p>Use the detailed Hedge Fund Stock Picker page for full model scores, entry zone, stop loss, targets, and risk/reward.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_swot_text_sections(snapshot)


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_ticker_info(symbol: str) -> dict[str, Any]:
    if yf is None:
        return {}
    ticker = symbol.strip().upper().replace(".NS", "")
    if not ticker:
        return {}
    try:
        return dict(yf.Ticker(f"{ticker}.NS").info or {})
    except Exception:
        return {}


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_calendar_events(symbol: str) -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()
    ticker = symbol.strip().upper().replace(".NS", "")
    if not ticker:
        return pd.DataFrame()
    try:
        calendar = yf.Ticker(f"{ticker}.NS").calendar
    except Exception:
        return pd.DataFrame()
    if calendar is None:
        return pd.DataFrame()
    if isinstance(calendar, pd.DataFrame):
        return calendar.reset_index()
    if isinstance(calendar, dict):
        return pd.DataFrame([calendar])
    return pd.DataFrame()


def build_delivery_trend(snapshot: dict[str, Any]) -> pd.DataFrame:
    swot_df = snapshot.get("swot_df", pd.DataFrame())
    delivery_snapshot = snapshot.get("delivery_snapshot", {}) or {}
    delivery = None
    turnover = None
    obv_rising = "Unavailable"
    pocket_pivot = "Unavailable"
    if isinstance(swot_df, pd.DataFrame) and not swot_df.empty:
        row = swot_df.iloc[0]
        delivery = row.get("delivery_percentage")
        turnover = row.get("turnover_cr")
        if "hist_obv_rising_10d" in swot_df.columns:
            obv_rising = row.get("hist_obv_rising_10d")
        if "hist_pocket_pivot" in swot_df.columns:
            pocket_pivot = row.get("hist_pocket_pivot")
    if pd.isna(turnover) or turnover is None:
        turnover = snapshot.get("computed_turnover_cr")
    if pd.isna(delivery) or delivery is None:
        delivery = delivery_snapshot.get("delivery_percentage")
    delivery_quantity = delivery_snapshot.get("delivery_quantity")
    traded_quantity = delivery_snapshot.get("traded_quantity")
    delivery_value_cr = delivery_snapshot.get("delivery_value_cr")
    if (pd.isna(delivery) or delivery is None) and delivery_quantity and traded_quantity:
        delivery = delivery_quantity / traded_quantity * 100
    delivery_source = "NSE trade-info API" if delivery_snapshot else "NSE delivery data unavailable or blocked"

    latest_volume = snapshot.get("latest_volume")
    avg_volume_20 = snapshot.get("avg_volume_20")
    volume_ratio = latest_volume / avg_volume_20 if latest_volume and avg_volume_20 else None

    return pd.DataFrame(
        [
            {"Metric": "Delivery %", "Value": f"{delivery:.2f}%" if pd.notna(delivery) else "Unavailable"},
            {"Metric": "Delivery Source", "Value": delivery_source},
            {"Metric": "Delivery Quantity", "Value": f"{delivery_quantity:,.0f}" if pd.notna(delivery_quantity) else "Unavailable"},
            {"Metric": "Traded Quantity", "Value": f"{traded_quantity:,.0f}" if pd.notna(traded_quantity) else "Unavailable"},
            {"Metric": "Delivery Value (Cr)", "Value": round(delivery_value_cr, 2) if pd.notna(delivery_value_cr) else "Unavailable"},
            {"Metric": "Computed Turnover (Cr)", "Value": round(turnover, 2) if pd.notna(turnover) else "Unavailable"},
            {"Metric": "Latest Volume", "Value": int(latest_volume) if latest_volume else "Unavailable"},
            {"Metric": "Volume / 20D Avg", "Value": round(volume_ratio, 2) if volume_ratio else "Unavailable"},
            {"Metric": "OBV Rising 10D", "Value": obv_rising},
            {"Metric": "Pocket Pivot", "Value": pocket_pivot},
        ]
    )


def build_sector_rs(snapshot: dict[str, Any]) -> pd.DataFrame:
    symbol = str(snapshot.get("symbol", "")).strip().upper()
    stock_history = fetch_ohlcv_history(symbol)
    nifty_history = fetch_ohlcv_history("^NSEI")
    rs_20d = "Unavailable"
    rs_status = "Unavailable"
    if not stock_history.empty and not nifty_history.empty and "close" in stock_history.columns and "close" in nifty_history.columns:
        stock_close = pd.to_numeric(stock_history["close"], errors="coerce").dropna()
        nifty_close = pd.to_numeric(nifty_history["close"], errors="coerce").dropna()
        if len(stock_close) > 20 and len(nifty_close) > 20:
            stock_return = stock_close.iloc[-1] / stock_close.iloc[-21] - 1
            nifty_return = nifty_close.iloc[-1] / nifty_close.iloc[-21] - 1
            rs_20d_value = (stock_return - nifty_return) * 100
            rs_20d = round(rs_20d_value, 2)
            rs_status = "Outperforming Nifty" if rs_20d_value > 0 else "Underperforming Nifty"

    swot_df = snapshot.get("swot_df", pd.DataFrame())
    if isinstance(swot_df, pd.DataFrame) and not swot_df.empty:
        row = swot_df.iloc[0]
        return pd.DataFrame(
            [
                {"Metric": "Relative Strength Score", "Value": row.get("relative_strength_score", "Unavailable")},
                {"Metric": "Sector Score", "Value": row.get("sector_score", "Unavailable")},
                {"Metric": "20D RS vs Nifty", "Value": rs_20d},
                {"Metric": "RS Status", "Value": rs_status},
                {"Metric": "52W High Proximity", "Value": "Within 3%" if row.get("hist_within_3pct_52w_high") is True else "Not confirmed"},
                {"Metric": "Trend Status", "Value": "Bullish" if row.get("hist_ema_stack") is True else "Not confirmed"},
            ]
        )
    return pd.DataFrame()


def render_financials_section(symbol: str, snapshot: dict[str, Any]) -> None:
    info = fetch_ticker_info(symbol)
    financial_rows = [
        {"Metric": "Market Cap", "Value": info.get("marketCap", "Unavailable")},
        {"Metric": "Trailing PE", "Value": info.get("trailingPE", "Unavailable")},
        {"Metric": "Forward PE", "Value": info.get("forwardPE", "Unavailable")},
        {"Metric": "ROE", "Value": info.get("returnOnEquity", "Unavailable")},
        {"Metric": "Debt to Equity", "Value": info.get("debtToEquity", "Unavailable")},
        {"Metric": "Revenue Growth", "Value": info.get("revenueGrowth", "Unavailable")},
        {"Metric": "Earnings Growth", "Value": info.get("earningsGrowth", "Unavailable")},
    ]
    display_dataframe(pd.DataFrame(financial_rows))

    swot_df = snapshot.get("swot_df", pd.DataFrame())
    if isinstance(swot_df, pd.DataFrame) and not swot_df.empty:
        st.caption("Model score details")
        display_dataframe(swot_df)


def render_more_section(symbol: str, snapshot: dict[str, Any]) -> None:
    info = fetch_ticker_info(symbol)
    def fmt_percent(value: Any) -> str:
        if value in (None, "Unavailable"):
            return "Unavailable"
        try:
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return str(value)

    def fmt_number(value: Any) -> str:
        if value in (None, "Unavailable"):
            return "Unavailable"
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    shareholding = pd.DataFrame(
        [
            {"Holder Type": "Institutional Ownership", "Value": fmt_percent(info.get("heldPercentInstitutions"))},
            {"Holder Type": "Insider / Promoter Proxy", "Value": fmt_percent(info.get("heldPercentInsiders"))},
            {"Holder Type": "Float Shares", "Value": fmt_number(info.get("floatShares"))},
            {"Holder Type": "Shares Outstanding", "Value": fmt_number(info.get("sharesOutstanding"))},
        ]
    )

    st.subheader("Shareholding")
    display_dataframe(shareholding)

    st.subheader("Delivery Trend")
    display_dataframe(build_delivery_trend(snapshot))

    st.subheader("Sector Relative Strength")
    sector_df = build_sector_rs(snapshot)
    if sector_df.empty:
        st.info("Sector RS data unavailable from the current data provider.")
    else:
        display_dataframe(sector_df)

    st.subheader("Event Calendar")
    calendar_df = fetch_calendar_events(symbol)
    if calendar_df.empty:
        st.info("No upcoming event calendar data found.")
    else:
        display_dataframe(calendar_df)


def render_stock_analysis_card_page() -> None:
    st.subheader("Stock Technicals & SWOT Card")
    st.caption("Mobile-style technical and SWOT view inspired by your reference images.")

    with st.sidebar:
        st.header("Stock Card Controls")
        symbol = st.text_input("NSE symbol", value="RELIANCE", key="stock_card_symbol").strip().upper()
        section = st.radio("Section", ["Overview", "SWOT", "Financials", "More"], horizontal=False)
        ma_mode = st.radio("Moving average mode", ["EMA", "SMA"], horizontal=True)

    if yf is None:
        st.warning("Install yfinance to enable this stock card page: pip install yfinance")
        return

    snapshot = get_stock_analysis_snapshot(symbol)
    if not snapshot or snapshot.get("history_status") != "historical data available":
        st.info("No historical data found for this NSE symbol.")
        return

    st.markdown(
        f"""
        <div class="analysis-shell">
            <div class="analysis-tabs">
                <div class="analysis-tab {'active' if section == 'Overview' else ''}">OVERVIEW</div>
                <div class="analysis-tab {'active' if section == 'SWOT' else ''}">SWOT</div>
                <div class="analysis-tab {'active' if section == 'Financials' else ''}">FINANCIALS</div>
                <div class="analysis-tab {'active' if section == 'More' else ''}">MORE</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if section == "SWOT":
        render_stock_swot_card(snapshot)
    elif section == "Financials":
        render_financials_section(symbol, snapshot)
    elif section == "More":
        render_more_section(symbol, snapshot)
    else:
        render_stock_technicals_card(snapshot, ma_mode)

    st.markdown(
        """
        <div class="action-row">
            <div class="buy-button">Buy</div>
            <div class="sell-button">Sell</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_hedge_fund_model(df: pd.DataFrame, use_history: bool = True, history_limit: int = 80) -> pd.DataFrame:
    if df.empty:
        return df
    if use_history:
        df = enrich_candidates_with_history(df, history_limit)

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        current = row.to_dict()
        current.update(score_hedge_fund_candidate(pd.Series(current)))
        rows.append(current)

    model = pd.DataFrame(rows)
    if model.empty:
        return model

    model = model.sort_values(["total_score", "swot_advantage_score", "risk_reward_ratio"], ascending=[False, False, False], kind="mergesort")
    return model


def render_hedge_fund_model_page() -> None:
    st.subheader("Hedge Fund Stock Picker Model")
    st.caption(
        "Implements the prompt as a strict 1-20 trading session NSE stock-selection model with SWOT gating and institutional accumulation filters."
    )

    with st.sidebar:
        st.header("Hedge Fund Model Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="hedge_rows")
        use_history = st.toggle("Use historical OHLCV enrichment", value=True, key="hedge_use_history")
        history_limit = st.slider("Candidates to enrich", 10, 150, 80, 10, disabled=not use_history, key="hedge_history_limit")
        st.divider()
        st.subheader("Final Filter Parameters")
        min_total_score = st.slider("Minimum total score", 0, 100, 85, 1)
        min_swot_advantage = st.slider("Minimum SWOT advantage", -25, 50, 20, 1)
        min_delivery = st.slider("Minimum delivery %", 0, 100, 50, 1)
        min_institutional = st.slider("Minimum institutional score", 0, 100, 70, 1)
        min_turnover = st.slider("Minimum turnover crore", 0, 200, 50, 5)
        st.divider()
        st.subheader("Stock SWOT Search")
        search_symbol = st.text_input("NSE symbol", placeholder="Example: RELIANCE, TCS, HDFCBANK")
        if st.button("Refresh hedge fund model", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            get_chartink_client.clear()
            st.rerun()

    with st.expander("Implemented prompt rules", expanded=False):
        st.text(PROMPT_REFERENCE_TEXT)

    with st.spinner("Fetching and scoring hedge fund model candidates..."):
        df, error = run_scan(HEDGE_FUND_MODEL_CLAUSE)

    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust HEDGE_FUND_MODEL_CLAUSE.")
        return
    if use_history and yf is None:
        st.warning("Install yfinance to enable historical OHLCV enrichment: pip install yfinance")

    if search_symbol:
        st.divider()
        st.subheader(f"SWOT Search: {search_symbol.strip().upper().replace('.NS', '')}")
        if yf is None:
            st.warning("Install yfinance to enable direct symbol SWOT search: pip install yfinance")
        else:
            swot_df = build_single_stock_swot(search_symbol)
            if swot_df.empty:
                st.info("No historical data found for this symbol.")
            else:
                display_dataframe(swot_df, height=260)

    model = build_hedge_fund_model(df, use_history=use_history and yf is not None, history_limit=history_limit)
    if model.empty:
        st.info("No candidates were returned by the Chartink pre-filter.")
        return

    filtered_model = apply_hedge_fund_filters(
        model,
        min_total_score=min_total_score,
        min_swot_advantage=min_swot_advantage,
        min_delivery=min_delivery,
        min_institutional=min_institutional,
        min_turnover=min_turnover,
    )

    top_source = filtered_model if not filtered_model.empty else model
    top = top_source.iloc[0]
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Qualified stocks", len(filtered_model))
    metric_b.metric("Top total score", int(top["total_score"]))
    metric_c.metric("Top SWOT advantage", int(top["swot_advantage_score"]))
    metric_d.metric("Top candidate", str(top.get("nsecode") or top.get("name") or "N/A"))

    if filtered_model.empty:
        st.warning("No stocks pass the current final filter parameters. Loosen the sliders in the sidebar or review the scored universe below.")
    else:
        st.subheader("Filtered Recommendations")
        display_dataframe(filtered_model[hedge_fund_display_columns(filtered_model)].head(rows_shown), height=620)
        st.download_button(
            "Download filtered hedge fund candidates CSV",
            filtered_model[hedge_fund_display_columns(filtered_model)].to_csv(index=False).encode("utf-8"),
            file_name="hedge_fund_stock_picker_candidates.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored universe before final filters", expanded=filtered_model.empty):
        display_dataframe(model[hedge_fund_display_columns(model)].head(rows_shown), height=520)

    st.download_button(
        "Download scored universe CSV",
        model[hedge_fund_display_columns(model)].to_csv(index=False).encode("utf-8"),
        file_name="hedge_fund_scored_universe.csv",
        mime="text/csv",
        width="stretch",
    )


def score_launch_pad_candidate(row: pd.Series) -> dict[str, Any]:
    symbol = str(row.get("nsecode") or "").strip().upper()
    history = fetch_ohlcv_history(symbol)
    if history.empty or len(history) < 220 or not {"close", "high", "low", "volume"}.issubset(history.columns):
        return {
            "total_score": 0,
            "reason_for_selection": "Historical OHLCV data unavailable or insufficient for 200 EMA/SMA launch pad model.",
        }

    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    high = pd.to_numeric(history["high"], errors="coerce").dropna()
    low = pd.to_numeric(history["low"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    if len(close) < 220 or len(high) < 220 or len(low) < 220 or len(volume) < 60:
        return {"total_score": 0, "reason_for_selection": "Not enough clean historical rows for model."}

    latest_close = float(close.iloc[-1])
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema190 = close.ewm(span=190, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    sma190 = close.rolling(190).mean()
    sma200 = close.rolling(200).mean()

    latest_ema200 = float(ema200.iloc[-1])
    latest_sma200 = float(sma200.iloc[-1])
    latest_ema190 = float(ema190.iloc[-1])
    latest_sma190 = float(sma190.iloc[-1])
    distance_ema = (latest_ema200 - latest_close) / latest_ema200 * 100 if latest_ema200 else None
    distance_sma = (latest_sma200 - latest_close) / latest_sma200 * 100 if latest_sma200 else None

    previous_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + 2 * std20) - (sma20 - 2 * std20)) / sma20
    bb_low_30 = bool(bb_width.iloc[-1] <= bb_width.tail(120).quantile(0.30))
    direction = close.diff().fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    obv = (direction * volume.fillna(0)).cumsum()
    obv_30d_high = bool(obv.iloc[-1] >= obv.tail(30).max())
    atr_contracting = bool(atr14.iloc[-1] < atr14.shift(5).iloc[-1]) if pd.notna(atr14.shift(5).iloc[-1]) else False
    range_contracting = bool(((high - low) / close).tail(5).mean() < ((high - low) / close).shift(5).tail(5).mean())
    vcp_detected = bool(bb_low_30 and atr_contracting and range_contracting)
    recent_resistance = float(high.tail(55).max())
    darvas_detected = bool(0 <= (recent_resistance - latest_close) / recent_resistance * 100 <= 5)
    higher_lows = bool(low.tail(20).min() > low.shift(20).tail(20).min())
    volume_ratio = float(volume.iloc[-1] / volume.tail(20).mean()) if volume.tail(20).mean() else 0
    volume_expanding = bool(volume_ratio >= 1.1)
    ema_improving = bool(
        ema20.iloc[-1] > ema20.shift(5).iloc[-1]
        and ema50.iloc[-1] > ema50.shift(5).iloc[-1]
        and ema100.iloc[-1] > ema100.shift(5).iloc[-1]
        and ema200.iloc[-1] >= ema200.shift(10).iloc[-1] * 0.995
        and latest_close > ema50.iloc[-1]
        and latest_close > ema100.iloc[-1]
    )

    delivery_snapshot = fetch_nse_delivery_snapshot(symbol)
    delivery = delivery_snapshot.get("delivery_percentage")
    delivery_qty = delivery_snapshot.get("delivery_quantity")
    traded_qty = delivery_snapshot.get("traded_quantity")
    if (delivery is None or pd.isna(delivery)) and delivery_qty and traded_qty:
        delivery = delivery_qty / traded_qty * 100

    near_ema = distance_ema is not None and 0 <= distance_ema <= 5 and latest_close >= latest_ema190
    near_sma = distance_sma is not None and 0 <= distance_sma <= 5 and latest_close >= latest_sma190
    near_195_ema = distance_ema is not None and 0 <= distance_ema <= ((latest_ema200 - close.ewm(span=195, adjust=False).mean().iloc[-1]) / latest_ema200 * 100 if latest_ema200 else 2.5)
    near_195_sma = distance_sma is not None and 0 <= distance_sma <= ((latest_sma200 - close.rolling(195).mean().iloc[-1]) / latest_sma200 * 100 if latest_sma200 else 2.5)

    near_200_ema_score = 20 if near_ema else 0
    near_200_sma_score = 20 if near_sma else 0
    delivery_score = 10 if delivery is not None and delivery > 50 else 0
    obv_score = 10 if obv_30d_high else 0
    darvas_score = 10 if darvas_detected else 0
    vcp_score = 10 if vcp_detected else 0
    volume_score = 5 if volume_expanding else 0
    relative_strength_score = 5 if latest_close >= close.tail(60).quantile(0.70) else 2
    sector_strength_score = 3
    institutional_score = 5 if (delivery is not None and delivery > 50 and obv_30d_high) else 2
    total_score = sum(
        [
            near_200_ema_score,
            near_200_sma_score,
            delivery_score,
            obv_score,
            darvas_score,
            vcp_score,
            volume_score,
            relative_strength_score,
            sector_strength_score,
            institutional_score,
        ]
    )

    signal_types: list[str] = []
    if near_195_ema:
        signal_types.append("Type A: 195-200 EMA zone")
    if near_195_sma:
        signal_types.append("Type B: 195-200 SMA zone")
    if near_ema and near_sma:
        signal_types.append("Type C: below both 200 EMA and 200 SMA")
    if distance_ema is not None and 0 <= distance_ema <= 2 and delivery is not None and delivery > 60 and obv_30d_high and darvas_detected and vcp_detected:
        signal_types.append("Type D: highest conviction")

    probability = bounded_score(total_score, 100)
    trend_change_probability = bounded_score(total_score * 0.75 + (10 if ema_improving else 0) + (5 if higher_lows else 0), 100)
    window = "1-5 sessions" if total_score >= 85 else "5-15 sessions" if total_score >= 70 else "Watchlist"
    reason = []
    if near_ema:
        reason.append("price is within 0-5% below 200 EMA")
    if near_sma:
        reason.append("price is within 0-5% below 200 SMA")
    if ema_improving:
        reason.append("20/50/100 EMA trend improving")
    if vcp_detected:
        reason.append("VCP compression detected")
    if obv_30d_high:
        reason.append("OBV near 30-day high")
    if delivery is not None:
        reason.append(f"delivery {delivery:.2f}%")

    return {
        "name": row.get("name", symbol),
        "nsecode": symbol,
        "current_price": round(latest_close, 2),
        "200_ema": round(latest_ema200, 2),
        "200_sma": round(latest_sma200, 2),
        "distance_from_200_ema_pct": round(distance_ema, 2) if distance_ema is not None else None,
        "distance_from_200_sma_pct": round(distance_sma, 2) if distance_sma is not None else None,
        "delivery_pct": round(delivery, 2) if delivery is not None and pd.notna(delivery) else None,
        "obv_trend": "30D high / rising" if obv_30d_high else "Not confirmed",
        "institutional_score": institutional_score,
        "breakout_probability": probability,
        "expected_trend_change_probability": trend_change_probability,
        "expected_breakout_window": window,
        "total_score": total_score,
        "signal_type": ", ".join(signal_types) if signal_types else "Base launch pad",
        "vcp_detected": vcp_detected,
        "darvas_box_detected": darvas_detected,
        "higher_lows": higher_lows,
        "volume_ratio": round(volume_ratio, 2),
        "near_200_ema_score": near_200_ema_score,
        "near_200_sma_score": near_200_sma_score,
        "delivery_score": delivery_score,
        "obv_score": obv_score,
        "darvas_score": darvas_score,
        "vcp_score": vcp_score,
        "volume_score": volume_score,
        "relative_strength_score": relative_strength_score,
        "sector_strength_score": sector_strength_score,
        "reason_for_selection": "; ".join(reason) if reason else "Launch pad conditions partially forming",
    }


def build_launch_pad_200_model(df: pd.DataFrame, history_limit: int = 120) -> pd.DataFrame:
    if df.empty:
        return df

    rows: list[dict[str, Any]] = []
    for _, row in df.head(history_limit).iterrows():
        scored = score_launch_pad_candidate(row)
        if scored.get("total_score", 0) > 0:
            rows.append(scored)
    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return model.sort_values(["total_score", "breakout_probability", "expected_trend_change_probability"], ascending=[False, False, False], kind="mergesort")


def apply_launch_pad_filters(
    model: pd.DataFrame,
    min_total_score: int,
    min_delivery: int,
    max_ema_distance: float,
    max_sma_distance: float,
    require_obv: bool,
    require_vcp: bool,
    require_darvas: bool,
) -> pd.DataFrame:
    if model.empty:
        return model
    filtered = model[
        (pd.to_numeric(model["total_score"], errors="coerce") >= min_total_score)
        & (pd.to_numeric(model["delivery_pct"], errors="coerce").fillna(0) >= min_delivery)
        & (pd.to_numeric(model["distance_from_200_ema_pct"], errors="coerce").between(0, max_ema_distance))
        & (pd.to_numeric(model["distance_from_200_sma_pct"], errors="coerce").between(0, max_sma_distance))
    ].copy()
    if require_obv:
        filtered = filtered[filtered["obv_trend"].astype(str).str.contains("30D high", na=False)]
    if require_vcp:
        filtered = filtered[filtered["vcp_detected"] == True]
    if require_darvas:
        filtered = filtered[filtered["darvas_box_detected"] == True]
    return filtered.sort_values(["total_score", "breakout_probability"], ascending=[False, False], kind="mergesort")


def render_launch_pad_200_page() -> None:
    st.subheader("200 EMA / 200 SMA Launch Pad Scanner")
    st.caption("Finds stocks approaching the 200-day EMA/SMA from below before potential trend reversal or Stage-2 breakout.")

    with st.sidebar:
        st.header("Launch Pad Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="launch_rows")
        history_limit = st.slider("Candidates to score", 20, 200, 120, 20, key="launch_history_limit")
        st.divider()
        min_total_score = st.slider("Minimum total score", 0, 100, 80, 1, key="launch_min_score")
        min_delivery = st.slider("Minimum delivery %", 0, 100, 50, 1, key="launch_min_delivery")
        max_ema_distance = st.slider("Max distance below 200 EMA %", 0.0, 10.0, 5.0, 0.5)
        max_sma_distance = st.slider("Max distance below 200 SMA %", 0.0, 10.0, 5.0, 0.5)
        require_obv = st.toggle("Require OBV 30D high", value=True)
        require_vcp = st.toggle("Require VCP detected", value=True)
        require_darvas = st.toggle("Require Darvas box detected", value=True)
        if st.button("Refresh launch pad scanner", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            st.rerun()

    with st.spinner("Fetching 200 EMA/SMA launch pad candidates..."):
        df, error = run_scan(LAUNCH_PAD_200_CLAUSE)

    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust LAUNCH_PAD_200_CLAUSE.")
        return

    model = build_launch_pad_200_model(df, history_limit=history_limit)
    if model.empty:
        st.info("No candidates returned by the launch pad pre-filter or historical scoring.")
        return

    filtered = apply_launch_pad_filters(
        model,
        min_total_score=min_total_score,
        min_delivery=min_delivery,
        max_ema_distance=max_ema_distance,
        max_sma_distance=max_sma_distance,
        require_obv=require_obv,
        require_vcp=require_vcp,
        require_darvas=require_darvas,
    )

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Scored candidates", len(model))
    metric_b.metric("Filtered candidates", len(filtered))
    metric_c.metric("Top score", int((filtered if not filtered.empty else model).iloc[0]["total_score"]))

    if filtered.empty:
        st.warning("No stocks pass the current final filter. Loosen the sidebar filters or review the scored universe below.")
    else:
        st.subheader("Launch Pad Candidates")
        display_dataframe(filtered.head(rows_shown), height=560)
        st.download_button(
            "Download launch pad candidates CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            file_name="launch_pad_200_candidates.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored universe before final filters", expanded=filtered.empty):
        display_dataframe(model.head(rows_shown), height=520)


def score_ai_early_breakout_candidate(row: pd.Series) -> dict[str, Any]:
    symbol = str(row.get("nsecode") or "").strip().upper()
    history = fetch_ohlcv_history(symbol)
    if history.empty or len(history) < 220 or not {"close", "high", "low", "volume"}.issubset(history.columns):
        return {"ai_early_breakout_score": 0, "reason_for_selection": "Historical OHLCV unavailable or insufficient."}

    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    high = pd.to_numeric(history["high"], errors="coerce").dropna()
    low = pd.to_numeric(history["low"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    if len(close) < 220 or len(volume) < 60:
        return {"ai_early_breakout_score": 0, "reason_for_selection": "Not enough clean historical rows."}

    current_price = float(close.iloc[-1])
    previous_close = close.shift(1)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema190 = close.ewm(span=190, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    sma190 = close.rolling(190).mean()
    sma200 = close.rolling(200).mean()
    latest_ema200 = float(ema200.iloc[-1])
    latest_sma200 = float(sma200.iloc[-1])
    distance_ema200 = (latest_ema200 - current_price) / latest_ema200 * 100 if latest_ema200 else None
    distance_sma200 = (latest_sma200 - current_price) / latest_sma200 * 100 if latest_sma200 else None

    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    range_pct = (high - low) / close
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_width = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid
    rsi_delta = close.diff()
    rsi_gain = rsi_delta.clip(lower=0).rolling(14).mean()
    rsi_loss = (-rsi_delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + (rsi_gain / rsi_loss)))
    latest_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None

    direction = close.diff().fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    obv = (direction * volume.fillna(0)).cumsum()
    obv_30d_high = bool(obv.iloc[-1] >= obv.tail(30).max())
    obv_slope_up = bool(obv.iloc[-1] > obv.shift(10).iloc[-1])
    down_volume = volume.where(close < previous_close, 0)
    pocket_pivot = bool(volume.iloc[-1] > down_volume.shift(1).rolling(10).max().iloc[-1] and close.iloc[-1] > previous_close.iloc[-1])

    breakout_level = float(max(high.tail(55).max(), high.tail(20).max()))
    high_52w = float(high.tail(252).max())
    distance_breakout = (breakout_level - current_price) / breakout_level * 100 if breakout_level else None
    distance_52w = (high_52w - current_price) / high_52w * 100 if high_52w else None
    higher_lows = bool(low.tail(20).min() > low.shift(20).tail(20).min())
    darvas_detected = bool(distance_breakout is not None and 0 <= distance_breakout <= 3)
    vcp_detected = bool(
        pd.notna(atr14.shift(5).iloc[-1])
        and atr14.iloc[-1] < atr14.shift(5).iloc[-1]
        and bb_width.iloc[-1] <= bb_width.tail(120).quantile(0.20)
        and range_pct.tail(5).mean() < range_pct.shift(5).tail(5).mean()
    )
    nr7 = bool((high.iloc[-1] - low.iloc[-1]) <= (high - low).tail(7).min())
    inside_cluster = bool((high.tail(3).max() <= high.shift(3).tail(3).max()) and (low.tail(3).min() >= low.shift(3).tail(3).min()))

    delivery_snapshot = fetch_nse_delivery_snapshot(symbol)
    delivery_pct = delivery_snapshot.get("delivery_percentage")
    if (delivery_pct is None or pd.isna(delivery_pct)) and delivery_snapshot.get("delivery_quantity") and delivery_snapshot.get("traded_quantity"):
        delivery_pct = delivery_snapshot["delivery_quantity"] / delivery_snapshot["traded_quantity"] * 100

    latest_volume = float(volume.iloc[-1])
    avg_volume_20 = float(volume.tail(20).mean())
    volume_ratio = latest_volume / avg_volume_20 if avg_volume_20 else 0
    turnover_cr = current_price * latest_volume / 10_000_000
    gap_up = (current_price - float(previous_close.iloc[-1])) / float(previous_close.iloc[-1]) * 100 if previous_close.iloc[-1] else 0

    stock_return_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 else 0
    nifty = fetch_ohlcv_history("^NSEI")
    sector_underperforming = False
    rs_vs_nifty = None
    if not nifty.empty and "close" in nifty.columns:
        nifty_close = pd.to_numeric(nifty["close"], errors="coerce").dropna()
        if len(nifty_close) > 21:
            nifty_return_20 = nifty_close.iloc[-1] / nifty_close.iloc[-21] - 1
            rs_vs_nifty = (stock_return_20 - nifty_return_20) * 100
            sector_underperforming = rs_vs_nifty < 0

    trend_position = 0
    trend_position += 2 if current_price > ema50.iloc[-1] else 0
    trend_position += 2 if current_price > ema100.iloc[-1] else 0
    trend_position += 2 if current_price >= ema190.iloc[-1] or (distance_ema200 is not None and 0 <= distance_ema200 <= 3) else 0
    trend_position += 2 if current_price >= sma190.iloc[-1] or (distance_sma200 is not None and 0 <= distance_sma200 <= 3) else 0
    trend_position += 2 if ema20.iloc[-1] > ema50.iloc[-1] else 0
    trend_position += 2 if ema50.iloc[-1] > ema50.shift(5).iloc[-1] else 0
    trend_position += 2 if ema100.iloc[-1] > ema100.shift(5).iloc[-1] else 0
    trend_position += 1 if ema200.iloc[-1] >= ema200.shift(10).iloc[-1] * 0.995 else 0
    trend_position = bounded_score(trend_position, 15)

    breakout_readiness = 0
    breakout_readiness += 5 if darvas_detected else 0
    breakout_readiness += 3 if distance_52w is not None and 0 <= distance_52w <= 3 else 0
    breakout_readiness += 3 if higher_lows else 0
    breakout_readiness += 3 if distance_breakout is not None and 0 <= distance_breakout <= 3 else 0
    breakout_readiness += 3 if close.tail(20).max() <= high.tail(55).max() * 1.01 else 0
    breakout_readiness += 3 if distance_breakout is not None and distance_breakout >= 0 else 0
    breakout_readiness = bounded_score(breakout_readiness, 20)

    compression = 0
    compression += 5 if vcp_detected else 0
    compression += 3 if pd.notna(atr14.shift(5).iloc[-1]) and atr14.iloc[-1] < atr14.shift(5).iloc[-1] else 0
    compression += 3 if bb_width.iloc[-1] <= bb_width.tail(120).quantile(0.20) else 0
    compression += 2 if nr7 else 0
    compression += 1 if inside_cluster else 0
    compression += 1 if range_pct.tail(5).mean() < range_pct.shift(5).tail(5).mean() else 0
    compression = bounded_score(compression, 15)

    smart_money_raw = 0
    smart_money_raw += 20 if delivery_pct is not None and delivery_pct >= 60 else 12 if delivery_pct is not None and delivery_pct >= 55 else 5
    smart_money_raw += 20 if obv_30d_high else 10 if obv_slope_up else 0
    smart_money_raw += 10 if volume_ratio >= 1.2 else 5 if volume_ratio >= 0.8 else 0
    smart_money = bounded_score(smart_money_raw / 50 * 20, 20)
    smart_money_percent = bounded_score(smart_money_raw * 2, 100)

    relative_strength = bounded_score((5 if rs_vs_nifty is not None and rs_vs_nifty > 0 else 0) + (3 if stock_return_20 > 0 else 0) + (2 if distance_52w is not None and 0 <= distance_52w <= 3 else 0), 10)
    fundamental = 5
    risk = 10
    penalties = 0
    if latest_rsi is not None and latest_rsi > 80:
        penalties += 5
        risk -= 2
    if distance_breakout is not None and distance_breakout < -8:
        penalties += 5
        risk -= 3
    if delivery_pct is not None and delivery_pct < 40:
        penalties += 5
        risk -= 2
    if sector_underperforming:
        penalties += 5
        risk -= 2
    if turnover_cr < 50:
        risk -= 3
    if gap_up > 5:
        penalties += 5
        risk -= 2
    risk = bounded_score(risk, 10)

    bonus = min(10, (2 if vcp_detected else 0) + (2 if darvas_detected else 0) + (2 if pocket_pivot else 0) + (2 if delivery_pct is not None and delivery_pct > 60 else 0) + (2 if obv_30d_high else 0))
    ai_score = bounded_score(trend_position + breakout_readiness + compression + smart_money + relative_strength + fundamental + risk + bonus - penalties, 100)
    swot_advantage = bounded_score((trend_position + breakout_readiness + compression + smart_money + relative_strength) - max(0, 10 - risk) - penalties, 100)
    risk_reward = 3.5 if distance_breakout is not None and 0 <= distance_breakout <= 3 and risk >= 7 else 2.5 if risk >= 5 else 1.5

    if ai_score >= 96:
        classification, window, confidence = "Rare Institutional Setup", "1-3 trading sessions", 96
    elif ai_score >= 91:
        classification, window, confidence = "Elite Early Breakout", "2-5 trading sessions", 92
    elif ai_score >= 86:
        classification, window, confidence = "High Probability Watchlist", "3-5 trading sessions", 88
    elif ai_score >= 80:
        classification, window, confidence = "Monitor Closely", "5+ trading sessions", 82
    else:
        classification, window, confidence = "Reject", "No near-term setup", ai_score

    reasons = []
    if darvas_detected:
        reasons.append("near Darvas/resistance breakout level")
    if vcp_detected:
        reasons.append("volatility compression detected")
    if obv_30d_high:
        reasons.append("OBV at 30-day high")
    if delivery_pct is not None:
        reasons.append(f"delivery {delivery_pct:.2f}%")
    if rs_vs_nifty is not None:
        reasons.append(f"20D RS vs Nifty {rs_vs_nifty:.2f}%")

    candidate = {
        "stock_name": row.get("name", symbol),
        "nsecode": symbol,
        "sector": row.get("sector", ""),
        "current_price": round(current_price, 2),
        "ai_early_breakout_score": ai_score,
        "classification": classification,
        "expected_breakout_window": window,
        "breakout_level": round(float(breakout_level), 2),
        "distance_from_breakout_pct": round(distance_breakout, 2) if distance_breakout is not None else None,
        "distance_from_ema200_pct": round(distance_ema200, 2) if distance_ema200 is not None else None,
        "distance_from_sma200_pct": round(distance_sma200, 2) if distance_sma200 is not None else None,
        "delivery_pct": round(delivery_pct, 2) if delivery_pct is not None and pd.notna(delivery_pct) else None,
        "delivery_trend": "Strong" if delivery_pct is not None and delivery_pct >= 60 else "Positive" if delivery_pct is not None and delivery_pct >= 55 else "Unavailable/weak",
        "obv_trend": "30D high" if obv_30d_high else "Rising" if obv_slope_up else "Not confirmed",
        "vcp_status": "Detected" if vcp_detected else "Not detected",
        "darvas_box_status": "Detected" if darvas_detected else "Not detected",
        "pocket_pivot_status": "Detected" if pocket_pivot else "Not detected",
        "risk_reward_ratio": round(risk_reward, 2),
        "confidence_pct": confidence,
        "trend_position_score": trend_position,
        "breakout_readiness_score": breakout_readiness,
        "compression_score": compression,
        "smart_money_score": smart_money_percent,
        "relative_strength_score": relative_strength,
        "fundamental_momentum_score": fundamental,
        "risk_score": risk,
        "bonus_points": bonus,
        "penalties": penalties,
        "swot_advantage": swot_advantage,
        "turnover_cr": round(turnover_cr, 2),
        "reason_for_selection": "; ".join(reasons) if reasons else "Setup not mature yet",
    }
    return candidate


def build_ai_early_breakout_model(df: pd.DataFrame, history_limit: int = 120) -> pd.DataFrame:
    if df.empty:
        return df
    rows = []
    for _, row in df.head(history_limit).iterrows():
        try:
            scored = score_ai_early_breakout_candidate(row)
        except Exception as exc:
            scored = {
                "ai_early_breakout_score": 0,
                "nsecode": row.get("nsecode", ""),
                "reason_for_selection": f"Scoring skipped: {exc}",
            }
        if isinstance(scored, dict) and coerce_float(scored.get("ai_early_breakout_score"), 0) and coerce_float(scored.get("ai_early_breakout_score"), 0) > 0:
            rows.append(scored)
    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return safe_sort_dataframe(model, ["ai_early_breakout_score", "confidence_pct", "risk_reward_ratio"], [False, False, False])


def render_ai_early_breakout_page() -> None:
    st.subheader("AI Early Breakout Score")
    st.caption("Ranks NSE stocks preparing for a potential breakout in the next 1-5 sessions without chasing extended breakouts.")

    with st.sidebar:
        st.header("AI Early Breakout Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="ai_early_rows")
        history_limit = st.slider("Candidates to score", 20, 200, 120, 20, key="ai_early_history")
        st.divider()
        min_score = st.slider("Minimum AI score", 0, 100, 90, 1, key="ai_early_min_score")
        min_delivery = st.slider("Minimum delivery %", 0, 100, 55, 1, key="ai_early_min_delivery")
        min_smart_money = st.slider("Minimum smart money score", 0, 100, 75, 1, key="ai_early_min_smart")
        min_swot_advantage = st.slider("Minimum SWOT advantage", 0, 100, 25, 1, key="ai_early_min_swot")
        min_rr = st.slider("Minimum risk/reward", 1.0, 5.0, 3.0, 0.25, key="ai_early_min_rr")
        min_turnover = st.slider("Minimum turnover crore", 0, 200, 50, 5, key="ai_early_min_turnover")
        if st.button("Refresh AI early breakout", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            st.rerun()

    with st.spinner("Fetching AI early breakout candidates..."):
        df, error = run_scan(AI_EARLY_BREAKOUT_CLAUSE)
    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust AI_EARLY_BREAKOUT_CLAUSE.")
        return

    model = build_ai_early_breakout_model(df, history_limit=history_limit)
    if model.empty:
        st.info("No candidates returned by the AI early breakout pre-filter or scoring engine.")
        return

    filtered = model[
        (pd.to_numeric(model["ai_early_breakout_score"], errors="coerce") >= min_score)
        & (pd.to_numeric(model["delivery_pct"], errors="coerce").fillna(0) >= min_delivery)
        & (pd.to_numeric(model["smart_money_score"], errors="coerce") >= min_smart_money)
        & (pd.to_numeric(model["swot_advantage"], errors="coerce") >= min_swot_advantage)
        & (pd.to_numeric(model["risk_reward_ratio"], errors="coerce") >= min_rr)
        & (pd.to_numeric(model["turnover_cr"], errors="coerce") >= min_turnover)
        & (model["expected_breakout_window"].astype(str).str.contains("1-3|2-5|3-5", regex=True))
    ].copy()
    filtered = filtered.sort_values(["ai_early_breakout_score", "confidence_pct"], ascending=[False, False], kind="mergesort")

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Scored candidates", len(model))
    metric_b.metric("Filtered candidates", len(filtered))
    metric_c.metric("Top AI score", int((filtered if not filtered.empty else model).iloc[0]["ai_early_breakout_score"]))

    if filtered.empty:
        st.warning("No stocks pass the current strict final filter. Loosen sidebar filters or review the scored universe below.")
    else:
        st.subheader("AI Early Breakout Candidates")
        display_dataframe(filtered.head(rows_shown), height=560)
        st.download_button(
            "Download AI early breakout candidates CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            file_name="ai_early_breakout_candidates.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored universe before final filters", expanded=filtered.empty):
        display_dataframe(model.head(rows_shown), height=560)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def compute_iq5000_market_regime() -> dict[str, Any]:
    index_specs = [
        ("^NSEI", "NIFTY trend", 40, False),
        ("^NSEBANK", "BANKNIFTY trend", 20, False),
        ("^CNXMDCP", "Midcap trend", 15, False),
        ("^CNXSC", "Smallcap trend", 15, False),
        ("^INDIAVIX", "India VIX", 10, True),
    ]
    weighted_score = 0.0
    available_weight = 0.0
    details: list[dict[str, Any]] = []

    for ticker, label, weight, inverse in index_specs:
        history = fetch_ohlcv_history(ticker, lookback_days=300)
        if history.empty or "close" not in history.columns:
            details.append({"Component": label, "Score": "Unavailable", "Status": "Data unavailable"})
            continue

        close = pd.to_numeric(history["close"], errors="coerce").dropna()
        if len(close) < 80:
            details.append({"Component": label, "Score": "Unavailable", "Status": "Insufficient history"})
            continue

        latest = float(close.iloc[-1])
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema100 = close.ewm(span=100, adjust=False).mean()
        ret20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 21 and close.iloc[-21] else 0

        if inverse:
            component_score = 100
            component_score -= 35 if latest > ema20.iloc[-1] else 0
            component_score -= 25 if latest > ema50.iloc[-1] else 0
            component_score -= 20 if ret20 > 5 else 0
            component_score = bounded_score(component_score, 100)
            status = "Risk-on volatility" if component_score >= 70 else "Volatility headwind"
        else:
            component_score = 0
            component_score += 25 if latest > ema20.iloc[-1] else 0
            component_score += 25 if latest > ema50.iloc[-1] else 0
            component_score += 20 if ema20.iloc[-1] > ema50.iloc[-1] else 0
            component_score += 15 if ema50.iloc[-1] > ema100.iloc[-1] else 0
            component_score += 15 if ret20 > 0 else 0
            component_score = bounded_score(component_score, 100)
            status = "Improving" if component_score >= 70 else "Weak/neutral"

        weighted_score += component_score / 100 * weight
        available_weight += weight
        details.append({"Component": label, "Score": component_score, "Status": status, "20D Return %": round(ret20, 2)})

    if available_weight == 0:
        score = 60
        details.append({"Component": "Fallback", "Score": score, "Status": "Neutral regime used because index data was unavailable"})
    else:
        score = bounded_score(weighted_score / available_weight * 100, 100)

    if score >= 85:
        label = "Strong Bullish"
    elif score >= 70:
        label = "Bullish"
    elif score >= 55:
        label = "Neutral"
    elif score >= 40:
        label = "Bearish"
    else:
        label = "Strong Bearish"

    return {
        "market_regime_score": score,
        "market_regime": label,
        "details": details,
    }


def iq5000_pattern_label(candidate: dict[str, Any]) -> str:
    patterns: list[str] = []
    if candidate.get("darvas_box_status") == "Detected":
        patterns.append("Darvas")
    if candidate.get("vcp_status") == "Detected":
        patterns.append("VCP")
    if candidate.get("pocket_pivot_status") == "Detected":
        patterns.append("Pocket Pivot")
    if not patterns:
        patterns.append("Early Breakout Watch")
    return " + ".join(patterns)


def initialize_iq5000_memory_state() -> None:
    if "iq5000_trade_log" not in st.session_state:
        st.session_state["iq5000_trade_log"] = pd.DataFrame(columns=IQ5000_TRADE_LOG_COLUMNS)
    if "iq5000_market_memory" not in st.session_state:
        st.session_state["iq5000_market_memory"] = pd.DataFrame(columns=IQ5000_MARKET_MEMORY_COLUMNS)


def get_iq5000_memory_estimate(pattern: str, sector: str, market_regime: str, fallback_similarity: int) -> dict[str, Any]:
    trade_log = st.session_state.get("iq5000_trade_log", pd.DataFrame())
    if not isinstance(trade_log, pd.DataFrame) or trade_log.empty:
        estimated_win_rate = bounded_score(48 + fallback_similarity * 0.35, 100)
        return {
            "number_of_similar_setups": 0,
            "historical_win_rate": estimated_win_rate,
            "historical_average_return": round((estimated_win_rate - 50) / 8, 2),
            "historical_average_holding_days": "Unavailable",
            "best_historical_exit": "ATR trailing stop",
            "best_historical_stop_loss": "Structure or 1.5 ATR",
            "most_similar_historical_stock": "Unavailable",
            "most_similar_historical_date": "Unavailable",
        }

    working = trade_log.copy()
    for column in ["Pattern Detected", "Sector", "Market Regime"]:
        if column not in working.columns:
            working[column] = ""

    pattern_mask = working["Pattern Detected"].astype(str).str.contains(pattern.split(" + ")[0], case=False, na=False)
    sector_mask = working["Sector"].astype(str).str.lower().eq(str(sector).lower()) if sector else pd.Series(False, index=working.index)
    regime_mask = working["Market Regime"].astype(str).str.lower().eq(str(market_regime).lower())
    matches = working[pattern_mask | sector_mask | regime_mask].copy()
    if matches.empty:
        matches = working.copy()

    pnl = pd.to_numeric(matches.get("Actual Profit/Loss", pd.Series(dtype="float64")), errors="coerce").dropna()
    if pnl.empty:
        win_rate = bounded_score(48 + fallback_similarity * 0.35, 100)
        avg_return = round((win_rate - 50) / 8, 2)
    else:
        win_rate = round((pnl > 0).mean() * 100, 2)
        avg_return = round(float(pnl.mean()), 2)

    holding = pd.to_numeric(matches.get("Holding Time", pd.Series(dtype="float64")), errors="coerce").dropna()
    holding_days = round(float(holding.mean()), 2) if not holding.empty else "Unavailable"
    stock_name = matches.get("Stock Name", pd.Series(["Unavailable"])).dropna()
    trade_date = matches.get("Date", pd.Series(["Unavailable"])).dropna()

    return {
        "number_of_similar_setups": int(len(matches)),
        "historical_win_rate": win_rate,
        "historical_average_return": avg_return,
        "historical_average_holding_days": holding_days,
        "best_historical_exit": "Highest expectancy from saved trades" if not pnl.empty else "ATR trailing stop",
        "best_historical_stop_loss": "Use saved winning-trade stop profile" if not pnl.empty else "Structure or 1.5 ATR",
        "most_similar_historical_stock": str(stock_name.iloc[-1]) if not stock_name.empty else "Unavailable",
        "most_similar_historical_date": str(trade_date.iloc[-1]) if not trade_date.empty else "Unavailable",
    }


def score_iq5000_candidate(
    row: pd.Series,
    market_regime: dict[str, Any],
    capital: float,
    max_risk_pct: float,
    max_capital_pct: float,
) -> dict[str, Any]:
    try:
        early = score_ai_early_breakout_candidate(row)
    except Exception as exc:
        early = {
            "ai_early_breakout_score": 0,
            "reason_for_selection": f"Early breakout scoring failed: {exc}",
        }
    if not isinstance(early, dict):
        early = {
            "ai_early_breakout_score": 0,
            "reason_for_selection": "Early breakout scorer returned no usable data.",
        }
    if (coerce_float(early.get("ai_early_breakout_score"), 0) or 0) <= 0:
        return {
            "ai_iq_score": 0,
            "nsecode": str(row.get("nsecode") or "").upper(),
            "reason_for_selection": early.get("reason_for_selection", "Historical data unavailable."),
        }

    early_score = coerce_float(early.get("ai_early_breakout_score"), 0) or 0
    smart_money_score = coerce_float(early.get("smart_money_score"), 0) or 0
    swot_advantage = coerce_float(early.get("swot_advantage"), 0) or 0
    delivery_pct = coerce_float(early.get("delivery_pct"), 0) or 0
    turnover_cr = coerce_float(early.get("turnover_cr"), 0) or 0
    risk_reward = coerce_float(early.get("risk_reward_ratio"), 0) or 0
    trend_score = coerce_float(early.get("trend_position_score"), 0) or 0
    breakout_score = coerce_float(early.get("breakout_readiness_score"), 0) or 0
    compression_score = coerce_float(early.get("compression_score"), 0) or 0
    relative_strength = coerce_float(early.get("relative_strength_score"), 0) or 0
    penalties = coerce_float(early.get("penalties"), 0) or 0
    risk_score_raw = coerce_float(early.get("risk_score"), 0) or 0

    market_score = coerce_float(market_regime.get("market_regime_score"), 60) or 60
    trend_pct = trend_score / 15 * 100 if trend_score else 0
    breakout_pct = breakout_score / 20 * 100 if breakout_score else 0
    compression_pct = compression_score / 15 * 100 if compression_score else 0
    relative_pct = relative_strength * 10
    obv_positive = str(early.get("obv_trend", "")).lower() in {"30d high", "rising"}
    vcp_detected = early.get("vcp_status") == "Detected"
    darvas_detected = early.get("darvas_box_status") == "Detected"
    pocket_pivot = early.get("pocket_pivot_status") == "Detected"

    ai_swing_score = bounded_score(
        trend_pct * 0.35
        + breakout_pct * 0.25
        + compression_pct * 0.15
        + smart_money_score * 0.15
        + relative_pct * 0.10,
        100,
    )
    ai_intraday_score = bounded_score(
        35
        + (20 if turnover_cr >= 50 else 8 if turnover_cr >= 20 else 0)
        + (15 if pocket_pivot else 0)
        + (10 if obv_positive else 0)
        + (10 if market_score >= 70 else 0)
        + (10 if risk_reward >= 3 else 0),
        100,
    )
    ai_institutional_score = bounded_score(
        smart_money_score * 0.55
        + (20 if delivery_pct >= 60 else 14 if delivery_pct >= 55 else 6 if delivery_pct >= 40 else 0)
        + (10 if obv_positive else 0)
        + (10 if turnover_cr >= 50 else 0)
        + (5 if pocket_pivot else 0),
        100,
    )
    fundamental_score = bounded_score(
        (coerce_float(early.get("fundamental_momentum_score"), 5) or 5) * 10
        + (15 if swot_advantage >= 25 else 0)
        + (10 if turnover_cr >= 50 else 0),
        100,
    )
    risk_management_score = bounded_score(
        risk_score_raw * 10
        + (15 if risk_reward >= 3 else 0)
        + (10 if turnover_cr >= 50 else 0)
        + (10 if delivery_pct >= 55 else 0)
        - penalties * 2,
        100,
    )
    trade_probability = bounded_score(
        market_score * 0.10
        + early_score * 0.25
        + ai_swing_score * 0.20
        + ai_institutional_score * 0.20
        + smart_money_score * 0.10
        + swot_advantage * 0.10
        + risk_management_score * 0.05,
        100,
    )

    pattern_count = sum([darvas_detected, vcp_detected, pocket_pivot, obv_positive, delivery_pct >= 55])
    pattern = iq5000_pattern_label(early)
    similarity_score = bounded_score(40 + pattern_count * 10 + (10 if market_score >= 70 else 0), 100)
    memory = get_iq5000_memory_estimate(pattern, str(early.get("sector") or ""), str(market_regime.get("market_regime")), similarity_score)
    historical_win_rate = coerce_float(memory.get("historical_win_rate"), 50) or 50
    pattern_reliability = bounded_score(45 + pattern_count * 8 + (historical_win_rate - 50) * 0.35, 100)
    market_memory_score = bounded_score((pattern_reliability + historical_win_rate + market_score + smart_money_score) / 4, 100)
    market_dna_score = bounded_score(similarity_score * 0.35 + historical_win_rate * 0.25 + market_memory_score * 0.20 + trade_probability * 0.20, 100)
    ai_confidence = bounded_score(trade_probability * 0.55 + market_dna_score * 0.20 + historical_win_rate * 0.15 + risk_management_score * 0.10, 100)

    weighted_total = (
        market_score / 100 * IQ5000_MASTER_WEIGHTS["market_regime_score"]
        + ai_intraday_score / 100 * IQ5000_MASTER_WEIGHTS["ai_intraday_score"]
        + ai_swing_score / 100 * IQ5000_MASTER_WEIGHTS["ai_swing_score"]
        + ai_institutional_score / 100 * IQ5000_MASTER_WEIGHTS["ai_institutional_score"]
        + early_score / 100 * IQ5000_MASTER_WEIGHTS["ai_early_breakout_score"]
        + smart_money_score / 100 * IQ5000_MASTER_WEIGHTS["smart_money_score"]
        + swot_advantage / 100 * IQ5000_MASTER_WEIGHTS["swot_advantage_score"]
        + fundamental_score / 100 * IQ5000_MASTER_WEIGHTS["fundamental_score"]
        + trade_probability / 100 * IQ5000_MASTER_WEIGHTS["trade_probability"]
        + risk_management_score / 100 * IQ5000_MASTER_WEIGHTS["risk_management_score"]
    )
    ai_iq_score = bounded_score(weighted_total, 1000)

    current_price = coerce_float(early.get("current_price"), 0) or 0
    breakout_level = coerce_float(early.get("breakout_level"), current_price) or current_price
    entry_price = breakout_level * 1.001 if breakout_level > current_price else current_price
    stop_loss = min(entry_price * 0.94, current_price * 0.96) if entry_price else 0
    per_share_risk = max(entry_price - stop_loss, 0.01)
    max_rupee_risk = capital * max_risk_pct / 100
    max_capital_allowed = capital * max_capital_pct / 100
    risk_size = int(max_rupee_risk / per_share_risk) if per_share_risk else 0
    capital_size = int(max_capital_allowed / entry_price) if entry_price else 0
    position_size = max(0, min(risk_size, capital_size))
    target_1 = entry_price + per_share_risk * 3
    target_2 = entry_price + per_share_risk * 4
    target_3 = entry_price + per_share_risk * 5
    holding_period = "Same day" if ai_intraday_score >= ai_swing_score and ai_intraday_score >= 90 else str(early.get("expected_breakout_window", "1-20 trading sessions"))

    if ai_iq_score >= 950:
        confidence_rating = "Elite institutional setup"
    elif ai_iq_score >= 900:
        confidence_rating = "High conviction"
    elif ai_iq_score >= 850:
        confidence_rating = "Strong watchlist"
    elif ai_iq_score >= 800:
        confidence_rating = "Monitor closely"
    else:
        confidence_rating = "Reject / research only"

    reason_parts = [
        str(early.get("reason_for_selection", "Setup scored by IQ-5000 model")),
        f"market regime {market_regime.get('market_regime')} ({market_score}/100)",
        f"pattern reliability {pattern_reliability}/100",
        f"market DNA {market_dna_score}/100",
    ]

    return {
        "stock_name": early.get("stock_name", row.get("name", "")),
        "nsecode": early.get("nsecode", row.get("nsecode", "")),
        "sector": early.get("sector", row.get("sector", "")),
        "current_price": early.get("current_price"),
        "ai_iq_score": ai_iq_score,
        "ai_intraday_score": ai_intraday_score,
        "ai_swing_score": ai_swing_score,
        "ai_institutional_score": ai_institutional_score,
        "ai_early_breakout_score": early_score,
        "smart_money_score": bounded_score(smart_money_score, 100),
        "swot_advantage_score": bounded_score(swot_advantage, 100),
        "fundamental_score": fundamental_score,
        "trade_probability": trade_probability,
        "market_regime_score": bounded_score(market_score, 100),
        "market_regime": market_regime.get("market_regime"),
        "delivery_pct": round(delivery_pct, 2) if delivery_pct else None,
        "delivery_trend": early.get("delivery_trend"),
        "obv_trend": early.get("obv_trend"),
        "vcp_status": early.get("vcp_status"),
        "darvas_box_status": early.get("darvas_box_status"),
        "pocket_pivot_status": early.get("pocket_pivot_status"),
        "breakout_level": round(breakout_level, 2) if breakout_level else None,
        "distance_from_breakout_pct": early.get("distance_from_breakout_pct"),
        "distance_from_ema200_pct": early.get("distance_from_ema200_pct"),
        "distance_from_sma200_pct": early.get("distance_from_sma200_pct"),
        "entry_price": round(entry_price, 2) if entry_price else None,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "target_1": round(target_1, 2) if entry_price else None,
        "target_2": round(target_2, 2) if entry_price else None,
        "target_3": round(target_3, 2) if entry_price else None,
        "position_size": position_size,
        "maximum_rupee_risk": round(max_rupee_risk, 2),
        "capital_required": round(position_size * entry_price, 2) if entry_price else 0,
        "expected_holding_period": holding_period,
        "confidence_rating": confidence_rating,
        "ai_confidence_pct": ai_confidence,
        "risk_reward_ratio": round(risk_reward, 2),
        "risk_management_score": risk_management_score,
        "turnover_cr": round(turnover_cr, 2),
        "pattern_detected": pattern,
        "pattern_reliability_score": pattern_reliability,
        "market_memory_score": market_memory_score,
        "market_dna_score": market_dna_score,
        "similarity_score": similarity_score,
        "number_of_similar_historical_setups": memory.get("number_of_similar_setups"),
        "historical_win_rate": memory.get("historical_win_rate"),
        "historical_average_return": memory.get("historical_average_return"),
        "historical_average_holding_days": memory.get("historical_average_holding_days"),
        "best_historical_exit": memory.get("best_historical_exit"),
        "best_historical_stop_loss": memory.get("best_historical_stop_loss"),
        "most_similar_historical_stock": memory.get("most_similar_historical_stock"),
        "most_similar_historical_date": memory.get("most_similar_historical_date"),
        "reason_for_selection": "; ".join(reason_parts),
    }


def build_iq5000_model(
    df: pd.DataFrame,
    market_regime: dict[str, Any],
    capital: float,
    max_risk_pct: float,
    max_capital_pct: float,
    history_limit: int = 100,
) -> pd.DataFrame:
    if df.empty:
        return df

    rows: list[dict[str, Any]] = []
    for _, row in df.head(history_limit).iterrows():
        try:
            scored = score_iq5000_candidate(
                row,
                market_regime=market_regime,
                capital=capital,
                max_risk_pct=max_risk_pct,
                max_capital_pct=max_capital_pct,
            )
        except Exception as exc:
            scored = {
                "ai_iq_score": 0,
                "nsecode": row.get("nsecode", ""),
                "reason_for_selection": f"IQ-5000 scoring skipped: {exc}",
            }
        if isinstance(scored, dict) and (coerce_float(scored.get("ai_iq_score"), 0) or 0) > 0:
            rows.append(scored)

    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return safe_sort_dataframe(model, ["ai_iq_score", "trade_probability", "market_dna_score"], [False, False, False])


def apply_iq5000_filters(
    model: pd.DataFrame,
    min_iq_score: int,
    min_market_regime: int,
    min_module_score: int,
    min_institutional: int,
    min_swot: int,
    min_delivery: int,
    min_smart_money: int,
    min_trade_probability: int,
    min_rr: float,
    min_turnover: int,
) -> pd.DataFrame:
    if model.empty:
        return model

    filtered = model[
        (pd.to_numeric(model["ai_iq_score"], errors="coerce") >= min_iq_score)
        & (pd.to_numeric(model["market_regime_score"], errors="coerce") >= min_market_regime)
        & (
            (pd.to_numeric(model["ai_intraday_score"], errors="coerce") >= min_module_score)
            | (pd.to_numeric(model["ai_swing_score"], errors="coerce") >= min_module_score)
            | (pd.to_numeric(model["ai_early_breakout_score"], errors="coerce") >= min_module_score)
        )
        & (pd.to_numeric(model["ai_institutional_score"], errors="coerce") >= min_institutional)
        & (pd.to_numeric(model["swot_advantage_score"], errors="coerce") >= min_swot)
        & (pd.to_numeric(model["delivery_pct"], errors="coerce").fillna(0) >= min_delivery)
        & (pd.to_numeric(model["smart_money_score"], errors="coerce") >= min_smart_money)
        & (pd.to_numeric(model["trade_probability"], errors="coerce") >= min_trade_probability)
        & (pd.to_numeric(model["risk_reward_ratio"], errors="coerce") >= min_rr)
        & (pd.to_numeric(model["turnover_cr"], errors="coerce").fillna(0) >= min_turnover)
    ].copy()
    return filtered.sort_values(["ai_iq_score", "trade_probability", "ai_confidence_pct"], ascending=[False, False, False], kind="mergesort")


def iq5000_display_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "stock_name",
        "nsecode",
        "sector",
        "current_price",
        "ai_iq_score",
        "ai_intraday_score",
        "ai_swing_score",
        "ai_institutional_score",
        "ai_early_breakout_score",
        "smart_money_score",
        "swot_advantage_score",
        "trade_probability",
        "market_regime_score",
        "delivery_pct",
        "breakout_level",
        "entry_price",
        "stop_loss",
        "target_1",
        "target_2",
        "target_3",
        "position_size",
        "maximum_rupee_risk",
        "expected_holding_period",
        "confidence_rating",
        "market_memory_score",
        "market_dna_score",
        "similarity_score",
        "historical_win_rate",
        "risk_reward_ratio",
        "turnover_cr",
        "reason_for_selection",
    ]
    return [column for column in columns if column in df.columns]


def safe_max_value(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.max())


def format_score_check(label: str, actual: float | None, required: float, suffix: str = "") -> dict[str, Any]:
    if actual is None:
        value = "Unavailable"
        passed = False
    else:
        value = f"{actual:.2f}{suffix}"
        passed = actual >= required
    return {
        "Condition": label,
        "Best Available": value,
        "Minimum Required": f"{required:.2f}{suffix}",
        "Status": "Pass" if passed else "Fail",
    }


def market_status_label(market_score: float, filtered_count: int, near_count: int = 0) -> str:
    if market_score >= 85 and filtered_count > 0:
        return "GREEN - AGGRESSIVE BUYING ENVIRONMENT"
    if market_score >= 70 and filtered_count > 0:
        return "GREEN - SELECTIVE BUYING ENVIRONMENT"
    if market_score >= 60 and near_count > 0:
        return "YELLOW - WATCHLIST ONLY"
    if market_score >= 50:
        return "ORANGE - DEFENSIVE MODE"
    return "RED - CAPITAL PRESERVATION MODE"


def render_no_trade_decision_engine(
    *,
    model: pd.DataFrame,
    market_regime: dict[str, Any],
    failed_conditions: list[dict[str, Any]],
    watchlist: pd.DataFrame,
    watchlist_columns: list[str],
    context: str,
) -> None:
    market_score = coerce_float(market_regime.get("market_regime_score"), 0) or 0
    near_count = len(watchlist) if isinstance(watchlist, pd.DataFrame) else 0

    st.error("STATUS: NO TRADE TODAY")
    st.caption("Reason: Capital preservation has the highest expected value under current market conditions.")

    st.subheader("Why No Trade?")
    if failed_conditions:
        display_dataframe(pd.DataFrame(failed_conditions), height=360)
    else:
        st.info("No complete qualifying setup is available from the current scored universe.")

    status = market_status_label(market_score, filtered_count=0, near_count=near_count)
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Market Status", status)
    metric_b.metric("Recommended Cash Allocation", "100%")
    metric_c.metric("Maximum Risk", "0%")

    st.subheader("Trading Decision")
    st.markdown(
        """
        **Decision:** No Capital Deployment

        **Recommended Cash Allocation:** 100%

        **Maximum Risk:** 0%
        """
    )

    st.subheader("What Would Change The Decision?")
    waiting_for = []
    for row in failed_conditions:
        if row.get("Status") == "Fail":
            waiting_for.append(f"{row.get('Condition')} to reach {row.get('Minimum Required')}")
    if not waiting_for:
        waiting_for = [
            "Stronger market breadth",
            "Better sector rotation",
            "Higher intraday/early breakout score",
            "Smart money score above threshold",
            "Delivery percentage above threshold",
            "Relative volume above 2",
            "Better risk-to-reward",
        ]
    for item in waiting_for[:10]:
        st.markdown(f"- {item}")

    st.subheader("Watchlist For Tomorrow")
    if isinstance(watchlist, pd.DataFrame) and not watchlist.empty:
        display_dataframe(watchlist[watchlist_columns].head(10), height=420)
        st.download_button(
            f"Download {context} no-trade watchlist CSV",
            watchlist.head(10).to_csv(index=False).encode("utf-8"),
            file_name=f"{slugify(context)}_no_trade_watchlist.csv",
            mime="text/csv",
            width="stretch",
        )
    else:
        st.info("No watchlist candidates are available from the current scan.")

    st.subheader("Trader Psychology Message")
    st.info(
        "There is no obligation to trade every day. Professional traders are paid for making high-quality decisions, not for being constantly invested. "
        "Protecting capital today increases your ability to exploit higher-probability opportunities tomorrow."
    )
    st.markdown(
        """
        **Final Message:** NO TRADE TODAY. Continue monitoring the watchlist. Wait for confirmation.
        Capital preservation takes priority over activity. The next high-probability opportunity is more valuable than forcing a low-quality trade.
        """
    )


def build_iq5000_failed_conditions(
    model: pd.DataFrame,
    market_regime: dict[str, Any],
    *,
    min_iq_score: int,
    min_market_regime: int,
    min_module_score: int,
    min_institutional: int,
    min_swot: int,
    min_delivery: int,
    min_smart_money: int,
    min_trade_probability: int,
    min_rr: float,
    min_turnover: int,
) -> list[dict[str, Any]]:
    highest_module = max(
        [
            safe_max_value(model, "ai_intraday_score") or 0,
            safe_max_value(model, "ai_swing_score") or 0,
            safe_max_value(model, "ai_early_breakout_score") or 0,
        ]
    )
    checks = [
        format_score_check("Market Regime Score", coerce_float(market_regime.get("market_regime_score"), 0), min_market_regime, "/100"),
        format_score_check("AI IQ Score", safe_max_value(model, "ai_iq_score"), min_iq_score, "/1000"),
        format_score_check("AI Intraday/Swing/Early Score", highest_module, min_module_score, "/100"),
        format_score_check("AI Institutional Score", safe_max_value(model, "ai_institutional_score"), min_institutional, "/100"),
        format_score_check("SWOT Advantage", safe_max_value(model, "swot_advantage_score"), min_swot, "/100"),
        format_score_check("Delivery Percentage", safe_max_value(model, "delivery_pct"), min_delivery, "%"),
        format_score_check("Smart Money Score", safe_max_value(model, "smart_money_score"), min_smart_money, "/100"),
        format_score_check("Trade Probability", safe_max_value(model, "trade_probability"), min_trade_probability, "%"),
        format_score_check("Risk/Reward", safe_max_value(model, "risk_reward_ratio"), min_rr),
        format_score_check("Turnover", safe_max_value(model, "turnover_cr"), min_turnover, " Cr"),
    ]
    return checks


def build_iq5000_no_trade_watchlist(model: pd.DataFrame) -> pd.DataFrame:
    if model.empty:
        return model
    watchlist = model.copy()
    watchlist["reason_for_monitoring"] = watchlist.get("reason_for_selection", "Near setup but final filters not met.")
    watchlist["required_trigger_for_entry"] = (
        "Live confirmation: VWAP hold, ORB, RVOL > 2, smart money above threshold, and risk/reward >= 1:3."
    )
    return safe_sort_dataframe(watchlist, ["ai_iq_score", "trade_probability", "ai_early_breakout_score"], [False, False, False])


def iq5000_no_trade_watchlist_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "stock_name",
        "nsecode",
        "ai_early_breakout_score",
        "ai_intraday_score",
        "ai_institutional_score",
        "expected_holding_period",
        "reason_for_monitoring",
        "required_trigger_for_entry",
    ]
    return [column for column in columns if column in df.columns]


def build_overnight_failed_conditions(
    model: pd.DataFrame,
    market_regime: dict[str, Any],
    *,
    min_probability: int,
    min_delivery: int,
    min_liquidity: int,
    min_volume_score: int,
    min_closing_strength: int,
    min_rr: float,
    min_turnover: int,
    min_memory_probability: int,
    min_consensus_score: int,
) -> list[dict[str, Any]]:
    model = ensure_ai_overnight_columns(model)
    return [
        format_score_check("Market Regime Score", coerce_float(market_regime.get("market_regime_score"), 0), 70, "/100"),
        format_score_check("Tomorrow Intraday Probability", safe_max_value(model, "tomorrow_intraday_probability"), min_probability, "%"),
        format_score_check("Memory Probability", safe_max_value(model, "similarity_based_probability"), min_memory_probability, "%"),
        format_score_check("Consensus Agreement", safe_max_value(model, "module16_consensus_score"), min_consensus_score, "%"),
        format_score_check("Risk/Reward", safe_max_value(model, "risk_to_reward_estimate"), min_rr),
        format_score_check("Delivery Trend", safe_max_value(model, "delivery_pct"), min_delivery, "%"),
        format_score_check("Volume Profile", safe_max_value(model, "volume_profile_score"), min_volume_score, "/100"),
        format_score_check("Closing Strength", safe_max_value(model, "closing_strength_score"), min_closing_strength, "/100"),
        format_score_check("Liquidity", safe_max_value(model, "liquidity_score"), min_liquidity, "/100"),
        format_score_check("Turnover", safe_max_value(model, "turnover_cr"), min_turnover, " Cr"),
    ]


def build_overnight_no_trade_watchlist(model: pd.DataFrame) -> pd.DataFrame:
    if model.empty:
        return model
    watchlist = ensure_ai_overnight_columns(model)
    watchlist["reason_for_monitoring"] = watchlist.get("reason_for_selection", "Overnight setup requires live confirmation.")
    watchlist["required_trigger_for_entry"] = (
        "Next-day trigger: price above VWAP, opening range breakout, RVOL > 2, no selling pressure, and consensus improves."
    )
    return safe_sort_dataframe(watchlist, ["similarity_based_probability", "tomorrow_intraday_probability"], [False, False])


def overnight_no_trade_watchlist_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "stock_name",
        "nsecode",
        "tomorrow_intraday_probability",
        "similarity_based_probability",
        "module16_consensus_score",
        "best_entry_time_window",
        "reason_for_monitoring",
        "required_trigger_for_entry",
    ]
    return [column for column in columns if column in df.columns]


def build_iq5000_performance_summary(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty or "Actual Profit/Loss" not in trade_log.columns:
        return pd.DataFrame()

    pnl = pd.to_numeric(trade_log["Actual Profit/Loss"], errors="coerce").dropna()
    if pnl.empty:
        return pd.DataFrame()

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    profit_factor = wins.sum() / abs(losses.sum()) if not losses.empty and losses.sum() != 0 else None
    summary = [
        {"Metric": "Completed Trades", "Value": int(len(pnl))},
        {"Metric": "Win Rate", "Value": f"{(wins.count() / len(pnl) * 100):.2f}%"},
        {"Metric": "Loss Rate", "Value": f"{(losses.count() / len(pnl) * 100):.2f}%"},
        {"Metric": "Average Profit", "Value": round(float(wins.mean()), 2) if not wins.empty else 0},
        {"Metric": "Average Loss", "Value": round(float(losses.mean()), 2) if not losses.empty else 0},
        {"Metric": "Profit Factor", "Value": round(float(profit_factor), 2) if profit_factor is not None else "Unavailable"},
        {"Metric": "Expectancy", "Value": round(float(pnl.mean()), 2)},
        {"Metric": "Largest Winner", "Value": round(float(pnl.max()), 2)},
        {"Metric": "Largest Loser", "Value": round(float(pnl.min()), 2)},
    ]
    return pd.DataFrame(summary)


def build_iq5000_pattern_reliability(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty or "Pattern Detected" not in trade_log.columns or "Actual Profit/Loss" not in trade_log.columns:
        return pd.DataFrame()

    working = trade_log.copy()
    working["pnl"] = pd.to_numeric(working["Actual Profit/Loss"], errors="coerce")
    working = working.dropna(subset=["pnl"])
    if working.empty:
        return pd.DataFrame()

    grouped = (
        working.groupby("Pattern Detected", dropna=False)
        .agg(
            trades=("pnl", "count"),
            win_rate=("pnl", lambda values: round((values > 0).mean() * 100, 2)),
            average_pnl=("pnl", "mean"),
            total_pnl=("pnl", "sum"),
        )
        .reset_index()
    )
    grouped["average_pnl"] = grouped["average_pnl"].round(2)
    grouped["total_pnl"] = grouped["total_pnl"].round(2)
    return grouped.sort_values(["win_rate", "total_pnl"], ascending=[False, False], kind="mergesort")


def render_iq5000_learning_console() -> None:
    initialize_iq5000_memory_state()
    st.subheader("Self-Learning and Market Memory Console")
    st.caption("Session-based prototype. Export CSV to preserve data between Streamlit restarts; no SQLite database is added.")

    tab_log, tab_summary, tab_memory = st.tabs(["Trade Database", "Learning Summary", "Market Memory"])

    with tab_log:
        edited_log = st.data_editor(
            st.session_state["iq5000_trade_log"],
            num_rows="dynamic",
            width="stretch",
            key="iq5000_trade_log_editor",
        )
        if isinstance(edited_log, pd.DataFrame):
            st.session_state["iq5000_trade_log"] = edited_log
        st.download_button(
            "Download trade database CSV",
            st.session_state["iq5000_trade_log"].to_csv(index=False).encode("utf-8"),
            file_name="iq5000_trade_database.csv",
            mime="text/csv",
            width="stretch",
        )

    with tab_summary:
        summary_df = build_iq5000_performance_summary(st.session_state["iq5000_trade_log"])
        pattern_df = build_iq5000_pattern_reliability(st.session_state["iq5000_trade_log"])
        if summary_df.empty:
            st.info("Add completed trades in the Trade Database tab to activate win rate, expectancy, profit factor, and drawdown-style analytics.")
        else:
            display_dataframe(summary_df)
        st.markdown("**Pattern Reliability Engine**")
        if pattern_df.empty:
            st.info("Pattern reliability will appear after trades include Pattern Detected and Actual Profit/Loss.")
        else:
            display_dataframe(pattern_df)

    with tab_memory:
        edited_memory = st.data_editor(
            st.session_state["iq5000_market_memory"],
            num_rows="dynamic",
            width="stretch",
            key="iq5000_market_memory_editor",
        )
        if isinstance(edited_memory, pd.DataFrame):
            st.session_state["iq5000_market_memory"] = edited_memory
        st.download_button(
            "Download market memory CSV",
            st.session_state["iq5000_market_memory"].to_csv(index=False).encode("utf-8"),
            file_name="iq5000_market_memory.csv",
            mime="text/csv",
            width="stretch",
        )


def render_iq5000_platform_page() -> None:
    initialize_iq5000_memory_state()
    st.subheader("IQ-5000 AI Trading Platform")
    st.caption("Institutional-style decision engine for NSE research: market regime, intraday, swing, smart money, SWOT, probability, risk, and memory scores.")

    with st.sidebar:
        st.header("IQ-5000 Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="iq5000_rows")
        history_limit = st.slider("Candidates to score", 20, 200, 100, 20, key="iq5000_history_limit")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key="iq5000_capital")
        max_risk_pct = st.slider("Max risk per trade %", 0.25, 5.0, 1.0, 0.25, key="iq5000_risk_pct")
        max_capital_pct = st.slider("Max capital per trade %", 5.0, 100.0, 25.0, 5.0, key="iq5000_capital_pct")
        st.divider()
        min_iq_score = st.slider("Minimum AI IQ score", 0, 1000, 900, 10, key="iq5000_min_iq")
        min_market_regime = st.slider("Minimum market regime score", 0, 100, 70, 1, key="iq5000_min_market")
        min_module_score = st.slider("Minimum intraday/swing/early score", 0, 100, 90, 1, key="iq5000_min_module")
        min_institutional = st.slider("Minimum institutional score", 0, 100, 85, 1, key="iq5000_min_inst")
        min_swot = st.slider("Minimum SWOT advantage", 0, 100, 25, 1, key="iq5000_min_swot")
        min_delivery = st.slider("Minimum delivery %", 0, 100, 55, 1, key="iq5000_min_delivery")
        min_smart_money = st.slider("Minimum smart money score", 0, 100, 75, 1, key="iq5000_min_smart")
        min_trade_probability = st.slider("Minimum trade probability", 0, 100, 90, 1, key="iq5000_min_probability")
        min_rr = st.slider("Minimum risk/reward", 1.0, 5.0, 3.0, 0.25, key="iq5000_min_rr")
        min_turnover = st.slider("Minimum turnover crore", 0, 250, 50, 5, key="iq5000_min_turnover")
        if st.button("Refresh IQ-5000", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            compute_iq5000_market_regime.clear()
            st.rerun()

    market_regime = compute_iq5000_market_regime()
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Market Regime", str(market_regime.get("market_regime")))
    metric_b.metric("Regime Score", int(market_regime.get("market_regime_score", 0)))
    metric_c.metric("Master Weight", "1000 pts")

    with st.expander("Market Regime AI details"):
        display_dataframe(pd.DataFrame(market_regime.get("details", [])))

    with st.spinner("Fetching and scoring IQ-5000 candidates..."):
        df, error = run_scan(AI_EARLY_BREAKOUT_CLAUSE)
    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust AI_EARLY_BREAKOUT_CLAUSE.")
        render_iq5000_learning_console()
        return

    model = build_iq5000_model(
        df,
        market_regime=market_regime,
        capital=capital,
        max_risk_pct=max_risk_pct,
        max_capital_pct=max_capital_pct,
        history_limit=history_limit,
    )
    if model.empty:
        st.info("No candidates returned by the IQ-5000 pre-filter or historical scoring engine.")
        render_iq5000_learning_console()
        return

    filtered = apply_iq5000_filters(
        model,
        min_iq_score=min_iq_score,
        min_market_regime=min_market_regime,
        min_module_score=min_module_score,
        min_institutional=min_institutional,
        min_swot=min_swot,
        min_delivery=min_delivery,
        min_smart_money=min_smart_money,
        min_trade_probability=min_trade_probability,
        min_rr=min_rr,
        min_turnover=min_turnover,
    )

    metric_d, metric_e, metric_f = st.columns(3)
    metric_d.metric("Scored Candidates", len(model))
    metric_e.metric("Final Qualified", len(filtered))
    metric_f.metric("Top AI IQ", int((filtered if not filtered.empty else model).iloc[0]["ai_iq_score"]))

    if filtered.empty:
        failed_conditions = build_iq5000_failed_conditions(
            model,
            market_regime,
            min_iq_score=min_iq_score,
            min_market_regime=min_market_regime,
            min_module_score=min_module_score,
            min_institutional=min_institutional,
            min_swot=min_swot,
            min_delivery=min_delivery,
            min_smart_money=min_smart_money,
            min_trade_probability=min_trade_probability,
            min_rr=min_rr,
            min_turnover=min_turnover,
        )
        watchlist = build_iq5000_no_trade_watchlist(model)
        render_no_trade_decision_engine(
            model=model,
            market_regime=market_regime,
            failed_conditions=failed_conditions,
            watchlist=watchlist,
            watchlist_columns=iq5000_no_trade_watchlist_columns(watchlist),
            context="iq5000",
        )
    else:
        st.subheader("Top 10 IQ-5000 Opportunities")
        top10 = filtered.head(10)
        display_dataframe(top10[iq5000_display_columns(top10)], height=560)
        st.download_button(
            "Download IQ-5000 final candidates CSV",
            top10.to_csv(index=False).encode("utf-8"),
            file_name="iq5000_final_candidates.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored universe before final IQ-5000 filters", expanded=filtered.empty):
        display_dataframe(model[iq5000_display_columns(model)].head(rows_shown), height=560)

    with st.expander("Master score weights"):
        weights_df = pd.DataFrame(
            [{"Module": key.replace("_", " ").title(), "Weight": value} for key, value in IQ5000_MASTER_WEIGHTS.items()]
        )
        display_dataframe(weights_df)

    with st.expander("Integrated workflow: Module 18 -> Module 15 -> Module 16", expanded=False):
        st.markdown(
            """
            **After market close:** Module 18 builds the overnight watchlist.

            **Before market open:** Module 15 compares each stock with saved historical analogs and assigns memory-adjusted probability.

            **After first 15-30 minutes:** Module 16 consensus requires technical, quant, smart-money, memory, catalyst, risk, regime, and live price-action votes before a trade recommendation is allowed.
            """
        )
        run_integrated_workflow = st.toggle("Run integrated overnight-memory-consensus workflow", value=False, key="iq5000_run_integrated_workflow")
        if run_integrated_workflow:
            with st.spinner("Running Module 18, Module 15, and Module 16 workflow..."):
                overnight_df, overnight_error = run_scan(AI_OVERNIGHT_OPPORTUNITY_CLAUSE)
            if overnight_error:
                st.error(overnight_error)
            else:
                overnight_model = build_ai_overnight_model(
                    overnight_df,
                    market_regime=market_regime,
                    history_limit=min(history_limit, 80),
                )
                if overnight_model.empty:
                    st.info("No overnight-memory-consensus candidates were available.")
                else:
                    workflow_columns = ai_overnight_display_columns(overnight_model)
                    display_dataframe(overnight_model[workflow_columns].head(rows_shown), height=560)
                    st.download_button(
                        "Download integrated workflow CSV",
                        overnight_model.to_csv(index=False).encode("utf-8"),
                        file_name="iq5000_integrated_overnight_memory_consensus.csv",
                        mime="text/csv",
                        width="stretch",
                    )

    render_iq5000_learning_console()


def classify_overnight_watchlist(probability: float) -> tuple[str, str]:
    if probability >= 96:
        return "Elite Tomorrow Candidate", "Expected probability > 80%"
    if probability >= 91:
        return "Very High Probability", "Confirm at open"
    if probability >= 86:
        return "High Probability", "Strong watchlist"
    if probability >= 80:
        return "Watchlist", "Needs live confirmation"
    return "Reject", "Below overnight threshold"


def overnight_best_entry_window(
    closing_strength_score: int,
    volume_profile_score: int,
    compression_score: int,
    gap_up_probability: int,
) -> str:
    if gap_up_probability >= 75 and volume_profile_score >= 75:
        return "09:20-09:35"
    if closing_strength_score >= 80 and compression_score >= 70:
        return "09:35-10:00"
    if volume_profile_score >= 85:
        return "09:15-09:20 only after VWAP hold"
    if compression_score >= 80:
        return "10:00-10:30"
    return "After opening range confirmation"


def overnight_pattern_label(candidate: dict[str, Any]) -> str:
    patterns: list[str] = []
    if candidate.get("vcp_status") == "Detected":
        patterns.append("VCP")
    if candidate.get("darvas_box_status") == "Detected":
        patterns.append("Darvas")
    if candidate.get("pocket_pivot_status") == "Detected":
        patterns.append("Pocket Pivot")
    if coerce_float(candidate.get("closing_strength_score"), 0) and coerce_float(candidate.get("closing_strength_score"), 0) >= 80:
        patterns.append("Strong Close")
    if coerce_float(candidate.get("delivery_pct"), 0) and coerce_float(candidate.get("delivery_pct"), 0) >= 60:
        patterns.append("High Delivery")
    if not patterns:
        patterns.append("Overnight Watch")
    return " + ".join(patterns)


def score_module16_consensus(candidate: dict[str, Any]) -> dict[str, Any]:
    closing_strength = coerce_float(candidate.get("closing_strength_score"), 0) or 0
    compression = coerce_float(candidate.get("compression_score"), 0) or 0
    relative_strength = coerce_float(candidate.get("relative_strength_score"), 0) or 0
    tomorrow_probability = coerce_float(candidate.get("tomorrow_intraday_probability"), 0) or 0
    orb_probability = coerce_float(candidate.get("opening_range_breakout_probability"), 0) or 0
    vwap_probability = coerce_float(candidate.get("vwap_hold_probability"), 0) or 0
    volume_score = coerce_float(candidate.get("volume_profile_score"), 0) or 0
    delivery_score = coerce_float(candidate.get("delivery_score"), 0) or 0
    auction_score = coerce_float(candidate.get("closing_auction_score"), 0) or 0
    memory_score = coerce_float(candidate.get("market_memory_score"), 0) or 0
    dna_score = coerce_float(candidate.get("market_dna_score"), 0) or 0
    similarity_probability = coerce_float(candidate.get("similarity_based_probability"), tomorrow_probability) or tomorrow_probability
    news_score = coerce_float(candidate.get("news_catalyst_score"), 0) or 0
    liquidity_score = coerce_float(candidate.get("liquidity_score"), 0) or 0
    risk_reward = coerce_float(candidate.get("risk_to_reward_estimate"), 0) or 0
    gap_down = coerce_float(candidate.get("gap_down_probability"), 50) or 50
    market_score = coerce_float(candidate.get("market_regime_score"), 60) or 60

    experts = [
        {
            "Expert": "Technical",
            "Score": bounded_score(closing_strength * 0.35 + compression * 0.25 + relative_strength * 0.25 + tomorrow_probability * 0.15, 100),
            "Reason": "Closing strength, compression, and relative strength.",
        },
        {
            "Expert": "Quant",
            "Score": bounded_score(tomorrow_probability * 0.35 + orb_probability * 0.25 + vwap_probability * 0.20 + volume_score * 0.20, 100),
            "Reason": "Probability, ORB, VWAP hold, and volume expansion.",
        },
        {
            "Expert": "Smart Money",
            "Score": bounded_score(delivery_score * 0.35 + volume_score * 0.30 + auction_score * 0.20 + relative_strength * 0.15, 100),
            "Reason": "Delivery, closing volume, auction proxy, and RS.",
        },
        {
            "Expert": "Market Memory",
            "Score": bounded_score(memory_score * 0.35 + dna_score * 0.25 + similarity_probability * 0.25 + market_score * 0.15, 100),
            "Reason": "Historical analogs, market DNA, and regime context.",
        },
        {
            "Expert": "Fundamental/Catalyst",
            "Score": bounded_score(news_score * 0.55 + relative_strength * 0.25 + market_score * 0.20, 100),
            "Reason": "Catalyst proxy, RS, and market support.",
        },
        {
            "Expert": "Risk",
            "Score": bounded_score(liquidity_score * 0.35 + min(risk_reward * 25, 100) * 0.35 + (100 - gap_down) * 0.30, 100),
            "Reason": "Liquidity, risk/reward, and gap-down risk.",
        },
        {
            "Expert": "Market Regime",
            "Score": bounded_score(market_score, 100),
            "Reason": "Index trend, breadth proxy, and volatility regime.",
        },
        {
            "Expert": "Live Price Action Gate",
            "Score": bounded_score(orb_probability * 0.35 + vwap_probability * 0.35 + volume_score * 0.30, 100),
            "Reason": "Pre-open proxy; must be confirmed after first 15-30 minutes.",
        },
    ]

    for expert in experts:
        expert["Vote"] = "Approve" if expert["Score"] >= 70 else "Reject/Wait"

    votes_for = sum(1 for expert in experts if expert["Vote"] == "Approve")
    consensus_score = bounded_score(sum(expert["Score"] for expert in experts) / len(experts), 100)
    vote_text = f"{votes_for}/{len(experts)}"

    if consensus_score >= 85 and votes_for >= 7:
        decision = "Strong consensus - eligible after live confirmation"
    elif consensus_score >= 75 and votes_for >= 6:
        decision = "Conditional consensus - wait for live confirmation"
    elif consensus_score >= 65 and votes_for >= 5:
        decision = "Watchlist only - needs stronger live evidence"
    else:
        decision = "No trade - consensus not strong enough"

    live_checks = [
        "Price above VWAP",
        "Opening range breakout confirmed",
        "Relative volume above 2",
        "No major selling pressure",
        "AI intraday score above 90",
        "Market regime still supportive",
        "Smart money score above threshold",
    ]
    if decision.startswith("Strong") or decision.startswith("Conditional"):
        live_gate = "Trade recommendation only after all live checks pass"
    elif decision.startswith("Watchlist"):
        live_gate = "Watchlist only until live checks improve"
    else:
        live_gate = "Do not generate trade recommendation"

    return {
        "module16_consensus_score": consensus_score,
        "module16_votes": vote_text,
        "module16_decision": decision,
        "final_trade_gate": live_gate,
        "live_confirmation_checklist": "; ".join(live_checks),
        "consensus_expert_votes": "; ".join(f"{expert['Expert']}: {expert['Vote']} ({expert['Score']})" for expert in experts),
    }


def apply_module15_memory_to_overnight(candidate: dict[str, Any]) -> dict[str, Any]:
    initialize_iq5000_memory_state()
    pattern = overnight_pattern_label(candidate)
    pattern_count = sum(
        [
            candidate.get("vcp_status") == "Detected",
            candidate.get("darvas_box_status") == "Detected",
            candidate.get("pocket_pivot_status") == "Detected",
            (coerce_float(candidate.get("delivery_pct"), 0) or 0) >= 50,
            (coerce_float(candidate.get("closing_strength_score"), 0) or 0) >= 75,
            (coerce_float(candidate.get("volume_profile_score"), 0) or 0) >= 70,
        ]
    )
    fallback_similarity = bounded_score(35 + pattern_count * 8 + ((coerce_float(candidate.get("market_regime_score"), 60) or 60) - 50) * 0.25, 100)
    memory = get_iq5000_memory_estimate(
        pattern,
        str(candidate.get("sector") or ""),
        str(candidate.get("market_regime") or ""),
        fallback_similarity,
    )
    historical_win_rate = coerce_float(memory.get("historical_win_rate"), 50) or 50
    historical_behaviour = coerce_float(candidate.get("historical_behaviour_score"), 0) or 0
    tomorrow_probability = coerce_float(candidate.get("tomorrow_intraday_probability"), 0) or 0
    market_score = coerce_float(candidate.get("market_regime_score"), 60) or 60
    delivery_score = coerce_float(candidate.get("delivery_score"), 0) or 0
    relative_strength = coerce_float(candidate.get("relative_strength_score"), 0) or 0
    memory_score = bounded_score(
        historical_win_rate * 0.30
        + historical_behaviour * 0.25
        + fallback_similarity * 0.20
        + market_score * 0.15
        + relative_strength * 0.10,
        100,
    )
    market_dna_score = bounded_score(
        fallback_similarity * 0.30
        + historical_win_rate * 0.25
        + delivery_score * 0.15
        + relative_strength * 0.15
        + tomorrow_probability * 0.15,
        100,
    )
    similarity_based_probability = bounded_score(
        tomorrow_probability * 0.45
        + historical_win_rate * 0.25
        + memory_score * 0.20
        + fallback_similarity * 0.10,
        100,
    )
    return {
        "module15_pattern": pattern,
        "similarity_score": fallback_similarity,
        "market_memory_score": memory_score,
        "market_dna_score": market_dna_score,
        "similarity_based_probability": similarity_based_probability,
        "number_of_similar_historical_setups": memory.get("number_of_similar_setups"),
        "historical_win_rate": memory.get("historical_win_rate"),
        "historical_average_return": memory.get("historical_average_return"),
        "historical_average_holding_days": memory.get("historical_average_holding_days"),
        "best_historical_exit": memory.get("best_historical_exit"),
        "best_historical_stop_loss": memory.get("best_historical_stop_loss"),
        "most_similar_historical_stock": memory.get("most_similar_historical_stock"),
        "most_similar_historical_date": memory.get("most_similar_historical_date"),
    }


def integrate_overnight_memory_consensus(candidate: dict[str, Any]) -> dict[str, Any]:
    enhanced = dict(candidate)
    enhanced.update(apply_module15_memory_to_overnight(enhanced))
    enhanced.update(score_module16_consensus(enhanced))
    return enhanced


def score_ai_overnight_candidate(row: pd.Series, market_regime: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("nsecode") or "").strip().upper()
    history = fetch_ohlcv_history(symbol)
    if history.empty or len(history) < 120 or not {"close", "high", "low", "open", "volume"}.issubset(history.columns):
        return {"tomorrow_intraday_probability": 0, "nsecode": symbol, "reason_for_selection": "Historical EOD OHLCV unavailable or insufficient."}

    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    high = pd.to_numeric(history["high"], errors="coerce").dropna()
    low = pd.to_numeric(history["low"], errors="coerce").dropna()
    open_price = pd.to_numeric(history["open"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    if min(len(close), len(high), len(low), len(open_price), len(volume)) < 120:
        return {"tomorrow_intraday_probability": 0, "nsecode": symbol, "reason_for_selection": "Not enough clean EOD rows."}

    current_price = float(close.iloc[-1])
    latest_open = float(open_price.iloc[-1])
    latest_high = float(high.iloc[-1])
    latest_low = float(low.iloc[-1])
    day_range = max(latest_high - latest_low, 0.01)
    closing_position = (current_price - latest_low) / day_range * 100
    body_pct = abs(current_price - latest_open) / day_range * 100
    bullish_close = current_price > latest_open
    bullish_engulfing = bool(current_price > open_price.shift(1).iloc[-1] and latest_open < close.shift(1).iloc[-1] and bullish_close)
    marubozu_proxy = bool(closing_position >= 85 and body_pct >= 65)
    nr7 = bool((high.iloc[-1] - low.iloc[-1]) <= (high - low).tail(7).min())
    inside_day = bool(latest_high <= high.shift(1).iloc[-1] and latest_low >= low.shift(1).iloc[-1])
    higher_high = bool(latest_high > high.shift(1).iloc[-1])
    higher_low = bool(latest_low > low.shift(1).iloc[-1])

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    previous_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    atr_pct = float(atr14.iloc[-1] / current_price * 100) if pd.notna(atr14.iloc[-1]) and current_price else 0
    daily_range_pct = float((high.iloc[-1] - low.iloc[-1]) / current_price * 100) if current_price else 0
    vwap_proxy = float(((high + low + close) / 3).iloc[-1])

    closing_strength_score = 0
    closing_strength_score += min(35, closing_position * 0.35)
    closing_strength_score += 10 if current_price > vwap_proxy else 0
    closing_strength_score += 10 if current_price > ema20.iloc[-1] else 0
    closing_strength_score += 10 if current_price > ema50.iloc[-1] else 0
    closing_strength_score += 8 if current_price > ema100.iloc[-1] else 0
    closing_strength_score += 8 if bullish_close else 0
    closing_strength_score += 6 if bullish_engulfing else 0
    closing_strength_score += 5 if marubozu_proxy else 0
    closing_strength_score += 4 if nr7 or inside_day else 0
    closing_strength_score += 4 if higher_high and higher_low else 0
    closing_strength_score = bounded_score(closing_strength_score, 100)

    latest_volume = float(volume.iloc[-1])
    avg_volume_20 = float(volume.tail(20).mean())
    avg_volume_50 = float(volume.tail(50).mean())
    volume_ratio = latest_volume / avg_volume_20 if avg_volume_20 else 0
    turnover_cr = current_price * latest_volume / 10_000_000 if current_price else 0
    volume_dryup = bool(volume.shift(1).tail(5).mean() < volume.shift(6).tail(20).mean() * 0.8) if len(volume) > 30 else False
    down_volume = volume.where(close < previous_close, 0)
    pocket_pivot = bool(volume.iloc[-1] > down_volume.shift(1).rolling(10).max().iloc[-1] and current_price > previous_close.iloc[-1])

    closing_auction_score = bounded_score(
        (25 if closing_position >= 80 else 15 if closing_position >= 65 else 5)
        + (25 if volume_ratio >= 1.5 else 15 if volume_ratio >= 1.0 else 5)
        + (20 if current_price > vwap_proxy else 0)
        + (15 if turnover_cr >= 50 else 8 if turnover_cr >= 20 else 0)
        + (15 if bullish_close and latest_volume > avg_volume_50 else 0),
        100,
    )

    delivery_snapshot = fetch_nse_delivery_snapshot(symbol)
    delivery_pct = delivery_snapshot.get("delivery_percentage")
    delivery_qty = delivery_snapshot.get("delivery_quantity")
    traded_qty = delivery_snapshot.get("traded_quantity")
    if (delivery_pct is None or pd.isna(delivery_pct)) and delivery_qty and traded_qty:
        delivery_pct = delivery_qty / traded_qty * 100
    delivery_pct_float = coerce_float(delivery_pct, 0) or 0
    delivery_score = 100 if delivery_pct_float >= 60 else 82 if delivery_pct_float >= 50 else 55 if delivery_pct_float >= 40 else 25 if delivery_pct_float else 35
    delivery_classification = "Excellent" if delivery_pct_float >= 60 else "Strong" if delivery_pct_float >= 50 else "Neutral" if delivery_pct_float >= 40 else "Weak/Unavailable"

    volume_profile_score = bounded_score(
        (35 if volume_ratio >= 2 else 28 if volume_ratio >= 1.5 else 18 if volume_ratio >= 1 else 8)
        + (20 if pocket_pivot else 0)
        + (15 if volume_dryup and volume_ratio >= 1.1 else 0)
        + (15 if turnover_cr >= 50 else 8 if turnover_cr >= 20 else 0)
        + (15 if latest_volume > avg_volume_50 else 0),
        100,
    )

    stock_return_5 = close.iloc[-1] / close.iloc[-6] - 1 if len(close) > 6 and close.iloc[-6] else 0
    stock_return_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 and close.iloc[-21] else 0
    nifty = fetch_ohlcv_history("^NSEI")
    rs_vs_nifty = None
    if not nifty.empty and "close" in nifty.columns:
        nifty_close = pd.to_numeric(nifty["close"], errors="coerce").dropna()
        if len(nifty_close) > 21 and nifty_close.iloc[-21]:
            nifty_return_20 = nifty_close.iloc[-1] / nifty_close.iloc[-21] - 1
            rs_vs_nifty = (stock_return_20 - nifty_return_20) * 100
    relative_strength_score = bounded_score(
        (35 if rs_vs_nifty is not None and rs_vs_nifty > 5 else 25 if rs_vs_nifty is not None and rs_vs_nifty > 0 else 10)
        + (25 if stock_return_5 > 0 else 0)
        + (20 if stock_return_20 > 0 else 0)
        + (20 if current_price >= close.tail(60).quantile(0.75) else 8),
        100,
    )

    # Options OI data is not available from the current free data stack, so this is a neutral proxy.
    options_score = bounded_score(
        50
        + (15 if volume_ratio >= 1.5 and bullish_close else 0)
        + (10 if delivery_pct_float >= 50 else 0)
        - (15 if not bullish_close else 0),
        100,
    )
    options_status = "Proxy only - OI feed not connected"

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_width = ((sma20 + 2 * std20) - (sma20 - 2 * std20)) / sma20
    bb_squeeze = bool(bb_width.iloc[-1] <= bb_width.tail(120).quantile(0.20))
    atr_contracting = bool(atr14.iloc[-1] < atr14.shift(5).iloc[-1]) if pd.notna(atr14.shift(5).iloc[-1]) else False
    range_contracting = bool(((high - low) / close).tail(5).mean() < ((high - low) / close).shift(5).tail(5).mean())
    breakout_level = float(high.tail(55).max())
    darvas_box = bool(0 <= (breakout_level - current_price) / breakout_level * 100 <= 4) if breakout_level else False
    flat_base = bool(close.tail(20).max() / max(close.tail(20).min(), 0.01) <= 1.08)
    compression_score = bounded_score(
        (25 if bb_squeeze else 0)
        + (20 if atr_contracting else 0)
        + (20 if range_contracting else 0)
        + (15 if darvas_box else 0)
        + (10 if flat_base else 0)
        + (10 if nr7 or inside_day else 0),
        100,
    )

    info = fetch_ticker_info(symbol)
    earnings_growth = coerce_float(info.get("earningsGrowth"), None)
    revenue_growth = coerce_float(info.get("revenueGrowth"), None)
    ex_dividend_date = info.get("exDividendDate")
    news_catalyst_score = bounded_score(
        40
        + (20 if earnings_growth is not None and earnings_growth > 0 else 0)
        + (15 if revenue_growth is not None and revenue_growth > 0 else 0)
        + (10 if ex_dividend_date else 0)
        + (15 if stock_return_20 > 0 and volume_ratio >= 1.2 else 0),
        100,
    )

    market_score = coerce_float(market_regime.get("market_regime_score"), 60) or 60
    pattern_count = sum([pocket_pivot, darvas_box, bb_squeeze, atr_contracting, delivery_pct_float >= 50, closing_position >= 75])
    historical_behaviour_score = bounded_score(
        35
        + pattern_count * 8
        + (10 if market_score >= 70 else 0)
        + (10 if rs_vs_nifty is not None and rs_vs_nifty > 0 else 0),
        100,
    )

    liquidity_score = bounded_score(
        (45 if turnover_cr >= 100 else 35 if turnover_cr >= 50 else 20 if turnover_cr >= 20 else 5)
        + (25 if avg_volume_20 >= 1_000_000 else 18 if avg_volume_20 >= 300_000 else 8)
        + (15 if current_price >= 100 else 5)
        + (15 if daily_range_pct <= 8 else 5),
        100,
    )

    weighted_probability = sum(
        [
            closing_strength_score / 100 * OVERNIGHT_SCORE_WEIGHTS["closing_strength_score"],
            closing_auction_score / 100 * OVERNIGHT_SCORE_WEIGHTS["closing_auction_score"],
            delivery_score / 100 * OVERNIGHT_SCORE_WEIGHTS["delivery_score"],
            volume_profile_score / 100 * OVERNIGHT_SCORE_WEIGHTS["volume_profile_score"],
            relative_strength_score / 100 * OVERNIGHT_SCORE_WEIGHTS["relative_strength_score"],
            options_score / 100 * OVERNIGHT_SCORE_WEIGHTS["options_score"],
            compression_score / 100 * OVERNIGHT_SCORE_WEIGHTS["compression_score"],
            news_catalyst_score / 100 * OVERNIGHT_SCORE_WEIGHTS["news_catalyst_score"],
            historical_behaviour_score / 100 * OVERNIGHT_SCORE_WEIGHTS["historical_behaviour_score"],
            liquidity_score / 100 * OVERNIGHT_SCORE_WEIGHTS["liquidity_score"],
        ]
    )
    tomorrow_probability = bounded_score(weighted_probability, 100)
    if market_score < 60:
        tomorrow_probability = bounded_score(tomorrow_probability - 8, 100)

    gap_up_probability = bounded_score(
        tomorrow_probability * 0.45
        + closing_strength_score * 0.25
        + volume_profile_score * 0.15
        + max(stock_return_5 * 100, 0) * 2,
        100,
    )
    gap_down_probability = bounded_score(100 - gap_up_probability + (12 if closing_position < 45 else 0), 100)
    orb_probability = bounded_score(tomorrow_probability * 0.45 + volume_profile_score * 0.30 + liquidity_score * 0.25, 100)
    vwap_hold_probability = bounded_score(tomorrow_probability * 0.40 + closing_strength_score * 0.35 + relative_strength_score * 0.25, 100)
    intraday_trend_probability = bounded_score(tomorrow_probability * 0.45 + relative_strength_score * 0.25 + market_score * 0.15 + compression_score * 0.15, 100)
    intraday_reversal_probability = bounded_score(100 - intraday_trend_probability + (10 if gap_up_probability > 80 and atr_pct > 4 else 0), 100)
    expected_volume_expansion = round(max(volume_ratio, 0), 2)
    expected_momentum_strength = bounded_score((closing_strength_score + relative_strength_score + volume_profile_score) / 3, 100)
    best_window = overnight_best_entry_window(closing_strength_score, volume_profile_score, compression_score, gap_up_probability)
    classification, classification_note = classify_overnight_watchlist(tomorrow_probability)

    risk_to_reward = 3.2 if compression_score >= 70 and closing_strength_score >= 70 else 2.5 if liquidity_score >= 70 else 1.8
    reason = []
    if closing_position >= 75:
        reason.append(f"closed in top zone of day range ({closing_position:.1f}%)")
    if current_price > ema20.iloc[-1] and current_price > ema50.iloc[-1]:
        reason.append("close above EMA20 and EMA50")
    if delivery_pct_float:
        reason.append(f"delivery {delivery_pct_float:.2f}% ({delivery_classification})")
    if volume_ratio:
        reason.append(f"relative volume {volume_ratio:.2f}x")
    if pocket_pivot:
        reason.append("pocket pivot volume proxy")
    if compression_score >= 70:
        reason.append("volatility compression active")
    if rs_vs_nifty is not None:
        reason.append(f"20D RS vs Nifty {rs_vs_nifty:.2f}%")

    return {
        "stock_name": row.get("name", symbol),
        "nsecode": symbol,
        "sector": row.get("sector", ""),
        "current_price": round(current_price, 2),
        "tomorrow_intraday_probability": tomorrow_probability,
        "gap_up_probability": gap_up_probability,
        "gap_down_probability": gap_down_probability,
        "opening_range_breakout_probability": orb_probability,
        "vwap_hold_probability": vwap_hold_probability,
        "intraday_trend_probability": intraday_trend_probability,
        "intraday_reversal_probability": intraday_reversal_probability,
        "expected_intraday_volatility_pct": round(max(atr_pct, daily_range_pct), 2),
        "expected_momentum_strength": expected_momentum_strength,
        "expected_volume_expansion": expected_volume_expansion,
        "best_entry_time_window": best_window,
        "classification": classification,
        "classification_note": classification_note,
        "closing_strength_score": closing_strength_score,
        "closing_auction_score": closing_auction_score,
        "delivery_score": delivery_score,
        "delivery_pct": round(delivery_pct_float, 2) if delivery_pct_float else None,
        "delivery_classification": delivery_classification,
        "volume_profile_score": volume_profile_score,
        "relative_strength_score": relative_strength_score,
        "options_score": options_score,
        "options_status": options_status,
        "compression_score": compression_score,
        "news_catalyst_score": news_catalyst_score,
        "historical_behaviour_score": historical_behaviour_score,
        "liquidity_score": liquidity_score,
        "risk_to_reward_estimate": round(risk_to_reward, 2),
        "turnover_cr": round(turnover_cr, 2),
        "closing_position_pct": round(closing_position, 2),
        "volume_ratio": round(volume_ratio, 2),
        "vcp_status": "Detected" if bb_squeeze and atr_contracting and range_contracting else "Partial" if compression_score >= 50 else "Not detected",
        "darvas_box_status": "Detected" if darvas_box else "Not detected",
        "pocket_pivot_status": "Detected" if pocket_pivot else "Not detected",
        "market_regime": market_regime.get("market_regime"),
        "market_regime_score": market_score,
        "reason_for_selection": "; ".join(reason) if reason else "Overnight setup is not mature yet",
    }
    return integrate_overnight_memory_consensus(candidate)


def build_ai_overnight_model(df: pd.DataFrame, market_regime: dict[str, Any], history_limit: int = 100) -> pd.DataFrame:
    if df.empty:
        return df
    rows: list[dict[str, Any]] = []
    for _, row in df.head(history_limit).iterrows():
        try:
            scored = score_ai_overnight_candidate(row, market_regime)
        except Exception as exc:
            scored = {
                "tomorrow_intraday_probability": 0,
                "nsecode": row.get("nsecode", ""),
                "reason_for_selection": f"Overnight scoring skipped: {exc}",
            }
        if isinstance(scored, dict) and (coerce_float(scored.get("tomorrow_intraday_probability"), 0) or 0) > 0:
            rows.append(scored)
    model = pd.DataFrame(rows)
    if model.empty:
        return model
    model = ensure_ai_overnight_columns(model)
    return safe_sort_dataframe(
        model,
        ["similarity_based_probability", "module16_consensus_score", "tomorrow_intraday_probability"],
        [False, False, False],
    )


def apply_ai_overnight_filters(
    model: pd.DataFrame,
    min_probability: int,
    min_delivery: int,
    min_liquidity: int,
    min_volume_score: int,
    min_closing_strength: int,
    min_rr: float,
    min_turnover: int,
    min_memory_probability: int = 0,
    min_consensus_score: int = 0,
) -> pd.DataFrame:
    if model.empty:
        return model
    model = ensure_ai_overnight_columns(model)
    filtered = model[
        (pd.to_numeric(model["tomorrow_intraday_probability"], errors="coerce") >= min_probability)
        & (pd.to_numeric(model["delivery_pct"], errors="coerce").fillna(0) >= min_delivery)
        & (pd.to_numeric(model["liquidity_score"], errors="coerce") >= min_liquidity)
        & (pd.to_numeric(model["volume_profile_score"], errors="coerce") >= min_volume_score)
        & (pd.to_numeric(model["closing_strength_score"], errors="coerce") >= min_closing_strength)
        & (pd.to_numeric(model["risk_to_reward_estimate"], errors="coerce") >= min_rr)
        & (pd.to_numeric(model["turnover_cr"], errors="coerce").fillna(0) >= min_turnover)
        & (pd.to_numeric(model["similarity_based_probability"], errors="coerce").fillna(0) >= min_memory_probability)
        & (pd.to_numeric(model["module16_consensus_score"], errors="coerce").fillna(0) >= min_consensus_score)
    ].copy()
    return safe_sort_dataframe(filtered, ["similarity_based_probability", "module16_consensus_score"], [False, False])


def ai_overnight_display_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "stock_name",
        "nsecode",
        "sector",
        "current_price",
        "tomorrow_intraday_probability",
        "similarity_based_probability",
        "module16_consensus_score",
        "module16_votes",
        "module16_decision",
        "final_trade_gate",
        "classification",
        "gap_up_probability",
        "opening_range_breakout_probability",
        "vwap_hold_probability",
        "intraday_trend_probability",
        "expected_intraday_volatility_pct",
        "best_entry_time_window",
        "closing_strength_score",
        "delivery_score",
        "delivery_pct",
        "volume_profile_score",
        "relative_strength_score",
        "options_score",
        "compression_score",
        "news_catalyst_score",
        "historical_behaviour_score",
        "market_memory_score",
        "market_dna_score",
        "historical_win_rate",
        "number_of_similar_historical_setups",
        "liquidity_score",
        "risk_to_reward_estimate",
        "turnover_cr",
        "live_confirmation_checklist",
        "reason_for_selection",
    ]
    return [column for column in columns if column in df.columns]


def render_ai_overnight_opportunity_page() -> None:
    st.subheader("AI Overnight Opportunity")
    st.caption("EOD watchlist engine for stocks most likely to become tomorrow's intraday leaders. Use it after market close, then confirm live with VWAP, ORB, RVOL, and market regime.")

    with st.sidebar:
        st.header("Overnight Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="overnight_rows")
        history_limit = st.slider("Candidates to score", 20, 200, 100, 20, key="overnight_history")
        st.divider()
        min_probability = st.slider("Minimum tomorrow probability", 0, 100, 80, 1, key="overnight_min_prob")
        min_delivery = st.slider("Minimum delivery %", 0, 100, 40, 1, key="overnight_min_delivery")
        min_liquidity = st.slider("Minimum liquidity score", 0, 100, 60, 1, key="overnight_min_liq")
        min_volume_score = st.slider("Minimum volume profile score", 0, 100, 60, 1, key="overnight_min_volume")
        min_closing_strength = st.slider("Minimum closing strength", 0, 100, 60, 1, key="overnight_min_close")
        min_rr = st.slider("Minimum risk/reward estimate", 1.0, 5.0, 2.0, 0.25, key="overnight_min_rr")
        min_turnover = st.slider("Minimum turnover crore", 0, 250, 20, 5, key="overnight_min_turnover")
        min_memory_probability = st.slider("Minimum memory probability", 0, 100, 60, 1, key="overnight_min_memory")
        min_consensus_score = st.slider("Minimum consensus score", 0, 100, 65, 1, key="overnight_min_consensus")
        if st.button("Refresh overnight opportunity", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            fetch_ticker_info.clear()
            compute_iq5000_market_regime.clear()
            st.rerun()

    market_regime = compute_iq5000_market_regime()
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Market Regime", str(market_regime.get("market_regime")))
    metric_b.metric("Regime Score", int(market_regime.get("market_regime_score", 0)))
    metric_c.metric("Engine", "Tomorrow EOD")

    with st.expander("M18 + M15 + M16 workflow", expanded=True):
        st.markdown(
            """
            1. **After market close:** Module 18 ranks overnight candidates from EOD price, volume, delivery, compression, RS, catalyst, and liquidity evidence.
            2. **Before market open:** Module 15 adds market-memory context using similar historical setups, historical win rate, market DNA, and similarity-based probability.
            3. **After first 15-30 minutes:** Module 16 asks the expert committee to vote. The app should only move from watchlist to trade idea after live VWAP, ORB, RVOL, and selling-pressure checks confirm.
            """
        )

    with st.expander("Confirmation rule before next-day entry"):
        st.markdown(
            """
            - Price above VWAP
            - Opening Range Breakout confirmed
            - Relative Volume above 2
            - No major selling pressure
            - AI Intraday Score above 90
            - Market regime remains supportive
            - Smart money score remains above threshold
            """
        )

    with st.spinner("Fetching and scoring AI overnight opportunities..."):
        df, error = run_scan(AI_OVERNIGHT_OPPORTUNITY_CLAUSE)
    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust AI_OVERNIGHT_OPPORTUNITY_CLAUSE.")
        return

    model = build_ai_overnight_model(df, market_regime=market_regime, history_limit=history_limit)
    if model.empty:
        st.info("No candidates returned by the overnight pre-filter or scoring engine.")
        return

    filtered = apply_ai_overnight_filters(
        model,
        min_probability=min_probability,
        min_delivery=min_delivery,
        min_liquidity=min_liquidity,
        min_volume_score=min_volume_score,
        min_closing_strength=min_closing_strength,
        min_rr=min_rr,
        min_turnover=min_turnover,
        min_memory_probability=min_memory_probability,
        min_consensus_score=min_consensus_score,
    )

    metric_d, metric_e, metric_f = st.columns(3)
    metric_d.metric("Scored candidates", len(model))
    metric_e.metric("Final watchlist", len(filtered))
    metric_f.metric("Top memory probability", int((filtered if not filtered.empty else model).iloc[0]["similarity_based_probability"]))

    if filtered.empty:
        failed_conditions = build_overnight_failed_conditions(
            model,
            market_regime,
            min_probability=min_probability,
            min_delivery=min_delivery,
            min_liquidity=min_liquidity,
            min_volume_score=min_volume_score,
            min_closing_strength=min_closing_strength,
            min_rr=min_rr,
            min_turnover=min_turnover,
            min_memory_probability=min_memory_probability,
            min_consensus_score=min_consensus_score,
        )
        watchlist = build_overnight_no_trade_watchlist(model)
        render_no_trade_decision_engine(
            model=model,
            market_regime=market_regime,
            failed_conditions=failed_conditions,
            watchlist=watchlist,
            watchlist_columns=overnight_no_trade_watchlist_columns(watchlist),
            context="overnight_opportunity",
        )
    else:
        st.subheader("Tomorrow Watchlist")
        table = filtered[ai_overnight_display_columns(filtered)].head(rows_shown)
        display_dataframe(table, height=620)
        st.download_button(
            "Download overnight opportunity CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            file_name="ai_overnight_opportunity_watchlist.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored universe before overnight filters", expanded=filtered.empty):
        display_dataframe(model[ai_overnight_display_columns(model)].head(rows_shown), height=560)

    with st.expander("Overnight scoring weights"):
        weights_df = pd.DataFrame(
            [{"Module": key.replace("_", " ").title(), "Weight": value} for key, value in OVERNIGHT_SCORE_WEIGHTS.items()]
        )
        display_dataframe(weights_df)


def resample_chart_timeframe(history: pd.DataFrame, rule: str) -> pd.DataFrame:
    if history.empty or "date" not in history.columns:
        return pd.DataFrame()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(history.columns):
        return pd.DataFrame()

    working = history.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working = working.dropna(subset=["date"]).sort_values("date")
    if working.empty:
        return pd.DataFrame()

    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"])
    if working.empty:
        return pd.DataFrame()

    aggregation = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    indexed = working.set_index("date")
    for candidate_rule in [rule, "ME" if str(rule).upper() == "M" else None, "M" if str(rule).upper() == "ME" else None]:
        if not candidate_rule:
            continue
        try:
            return indexed.resample(candidate_rule).agg(aggregation).dropna(subset=["open", "high", "low", "close"])
        except ValueError:
            continue

    rule_text = str(rule).upper()
    fallback = working.copy()
    if rule_text.startswith("W"):
        fallback["_period"] = fallback["date"].dt.to_period("W-FRI")
    elif rule_text in {"M", "ME", "MS"}:
        fallback["_period"] = fallback["date"].dt.to_period("M")
    else:
        fallback["_period"] = fallback["date"].dt.to_period("M")
    return fallback.groupby("_period").agg(aggregation).dropna(subset=["open", "high", "low", "close"])


def chart_verdict(score: float) -> str:
    if score >= 95:
        return "Legendary Chart Setup"
    if score >= 90:
        return "Elite Chart Setup"
    if score >= 85:
        return "High Quality Setup"
    if score >= 80:
        return "Watchlist"
    return "Reject"


def classify_chart_stage(current: float, ema50: float, ema200: float, ema200_prior: float, base_tightness: float) -> str:
    ema200_rising = ema200 >= ema200_prior
    if current > ema200 and ema50 > ema200 and ema200_rising:
        return "Stage 2 - Uptrend"
    if abs(current - ema200) / ema200 <= 0.08 and base_tightness <= 0.18:
        return "Stage 1 to Stage 2 Transition"
    if current > ema200 and not ema200_rising:
        return "Stage 3 - Distribution Risk"
    if current < ema200 and not ema200_rising:
        return "Stage 4 - Downtrend"
    return "Stage 1 - Accumulation"


def score_ai_chart_reading_candidate(row: pd.Series, history_override: pd.DataFrame | None = None) -> dict[str, Any]:
    symbol = str(row.get("nsecode") or "").strip().upper()
    history = history_override.copy() if isinstance(history_override, pd.DataFrame) and not history_override.empty else fetch_ohlcv_history(symbol, lookback_days=900)
    required = {"open", "high", "low", "close", "volume"}
    if history.empty or len(history) < 220 or not required.issubset(history.columns):
        return {"chart_quality_score": 0, "nsecode": symbol, "reason": "Historical OHLCV unavailable or insufficient."}

    df = history.copy()
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    if len(df) < 220:
        return {"chart_quality_score": 0, "nsecode": symbol, "reason": "Not enough clean OHLCV rows."}

    open_price = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    current = float(close.iloc[-1])
    latest_open = float(open_price.iloc[-1])
    latest_high = float(high.iloc[-1])
    latest_low = float(low.iloc[-1])
    previous_close = close.shift(1)
    previous_high = high.shift(1)
    previous_low = low.shift(1)
    day_range = max(latest_high - latest_low, 0.01)
    body = abs(current - latest_open)
    upper_wick = latest_high - max(current, latest_open)
    lower_wick = min(current, latest_open) - latest_low
    closing_position = (current - latest_low) / day_range * 100

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    latest_atr = float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else current * 0.03
    range_pct = (high - low) / close
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_width = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid
    rsi_delta = close.diff()
    rsi_gain = rsi_delta.clip(lower=0).rolling(14).mean()
    rsi_loss = (-rsi_delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + (rsi_gain / rsi_loss)))
    latest_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50

    weekly = resample_chart_timeframe(df, "W-FRI")
    monthly = resample_chart_timeframe(df, "M")
    weekly_bullish = False
    monthly_bullish = False
    if not weekly.empty and len(weekly) >= 30:
        weekly_close = weekly["close"]
        weekly_bullish = bool(weekly_close.iloc[-1] > weekly_close.ewm(span=10, adjust=False).mean().iloc[-1] > weekly_close.ewm(span=30, adjust=False).mean().iloc[-1])
    if not monthly.empty and len(monthly) >= 12:
        monthly_close = monthly["close"]
        monthly_bullish = bool(monthly_close.iloc[-1] > monthly_close.rolling(6).mean().iloc[-1])

    bullish_close = current > latest_open
    bearish_close = current < latest_open
    bullish_engulfing = bool(current > open_price.shift(1).iloc[-1] and latest_open < close.shift(1).iloc[-1] and bullish_close)
    bearish_engulfing = bool(current < open_price.shift(1).iloc[-1] and latest_open > close.shift(1).iloc[-1] and bearish_close)
    bullish_marubozu = bool(bullish_close and closing_position >= 85 and body / day_range >= 0.65)
    bearish_marubozu = bool(bearish_close and closing_position <= 20 and body / day_range >= 0.65)
    hammer = bool(lower_wick >= body * 2 and upper_wick <= body * 0.8 and closing_position >= 55)
    shooting_star = bool(upper_wick >= body * 2 and lower_wick <= body * 0.8 and closing_position <= 55)
    doji = bool(body / day_range <= 0.10)
    inside_bar = bool(latest_high <= previous_high.iloc[-1] and latest_low >= previous_low.iloc[-1])
    nr7 = bool((high.iloc[-1] - low.iloc[-1]) <= (high - low).tail(7).min())
    wide_range = bool((high.iloc[-1] - low.iloc[-1]) > (high - low).tail(20).mean() * 1.5)
    gap_candle = bool(latest_open > previous_high.iloc[-1] or latest_open < previous_low.iloc[-1])

    latest_volume = float(volume.iloc[-1])
    avg_volume_20 = float(volume.tail(20).mean())
    avg_volume_50 = float(volume.tail(50).mean())
    rvol = latest_volume / avg_volume_20 if avg_volume_20 else 0
    up_volume_expansion = bool(bullish_close and latest_volume > avg_volume_20 * 1.2)
    down_volume_expansion = bool(bearish_close and latest_volume > avg_volume_20 * 1.2)
    volume_dryup = bool(volume.shift(1).tail(5).mean() < volume.shift(6).tail(20).mean() * 0.8) if len(volume) > 30 else False
    down_volume = volume.where(close < previous_close, 0)
    pocket_pivot = bool(latest_volume > down_volume.shift(1).rolling(10).max().iloc[-1] and current > previous_close.iloc[-1])
    direction = close.diff().fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    obv = (direction * volume.fillna(0)).cumsum()
    obv_rising = bool(obv.iloc[-1] > obv.shift(10).iloc[-1])
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, pd.NA)
    ad_line = (money_flow_multiplier.fillna(0) * volume.fillna(0)).cumsum()
    ad_rising = bool(ad_line.iloc[-1] > ad_line.shift(10).iloc[-1])

    resistance = float(high.tail(55).max())
    support = float(low.tail(55).min())
    demand_low = float(low.tail(20).min())
    demand_high = float(close.tail(20).quantile(0.25))
    supply_low = float(close.tail(20).quantile(0.75))
    supply_high = float(high.tail(20).max())
    breakout_gap = (resistance - current) / resistance * 100 if resistance else None
    darvas_box = bool(breakout_gap is not None and 0 <= breakout_gap <= 4)
    atr_contracting = bool(atr14.iloc[-1] < atr14.shift(5).iloc[-1]) if pd.notna(atr14.shift(5).iloc[-1]) else False
    bb_squeeze = bool(bb_width.iloc[-1] <= bb_width.tail(120).quantile(0.20)) if pd.notna(bb_width.iloc[-1]) else False
    range_contracting = bool(range_pct.tail(5).mean() < range_pct.shift(5).tail(5).mean())
    vcp = bool(atr_contracting and bb_squeeze and range_contracting)
    base_tightness = float((close.tail(40).max() - close.tail(40).min()) / max(close.tail(40).min(), 0.01))
    flat_base = bool(base_tightness <= 0.12)
    higher_lows = bool(low.tail(20).min() > low.shift(20).tail(20).min())
    repeated_tests = int((high.tail(30) >= resistance * 0.985).sum())
    ascending_triangle = bool(higher_lows and repeated_tests >= 2)
    wyckoff_accumulation = bool(base_tightness <= 0.18 and obv_rising and higher_lows and not down_volume_expansion)
    wyckoff_distribution = bool(base_tightness <= 0.18 and not obv_rising and down_volume_expansion)
    launch_pad_200 = bool(abs(current - ema200.iloc[-1]) / ema200.iloc[-1] <= 0.05 and current >= ema200.iloc[-1] * 0.95)
    stage2_breakout = bool(current >= resistance * 0.995 and current > ema50.iloc[-1] > ema200.iloc[-1] and up_volume_expansion)
    double_bottom = bool(low.tail(80).nsmallest(2).max() <= low.tail(80).min() * 1.05 and current > close.tail(80).median())
    double_top = bool(high.tail(80).nlargest(2).min() >= high.tail(80).max() * 0.95 and current < close.tail(80).median())
    bull_flag = bool(current > ema20.iloc[-1] and range_contracting and close.tail(20).max() > close.shift(20).tail(20).max())
    bear_flag = bool(current < ema20.iloc[-1] and range_contracting and close.tail(20).min() < close.shift(20).tail(20).min())

    chart_stage = classify_chart_stage(current, float(ema50.iloc[-1]), float(ema200.iloc[-1]), float(ema200.shift(20).iloc[-1]), base_tightness)
    daily_bullish = bool(current > ema20.iloc[-1] > ema50.iloc[-1] and current > ema100.iloc[-1])
    vwap_proxy = float(((high + low + close) / 3).iloc[-1])
    intraday_15m_proxy = bool(current > vwap_proxy and closing_position >= 60)
    intraday_5m_proxy = bool(closing_position >= 70 and not shooting_star)
    timeframe_alignment_score = bounded_score(
        (3 if monthly_bullish else 0)
        + (4 if weekly_bullish else 0)
        + (4 if daily_bullish else 0)
        + (2 if intraday_15m_proxy else 0)
        + (2 if intraday_5m_proxy else 0),
        15,
    )
    timeframe_alignment = "; ".join(
        [
            "Monthly bullish" if monthly_bullish else "Monthly not confirmed",
            "Weekly bullish" if weekly_bullish else "Weekly not confirmed",
            "Daily bullish" if daily_bullish else "Daily weak",
            "15m proxy bullish" if intraday_15m_proxy else "15m live confirmation needed",
            "5m proxy clean" if intraday_5m_proxy else "5m live entry pending",
        ]
    )

    trend_clarity_score = bounded_score(
        (4 if current > ema20.iloc[-1] else 0)
        + (4 if ema20.iloc[-1] > ema50.iloc[-1] else 0)
        + (3 if ema50.iloc[-1] > ema100.iloc[-1] else 0)
        + (2 if ema100.iloc[-1] > ema200.iloc[-1] else 0)
        + (2 if ema200.iloc[-1] > ema200.shift(20).iloc[-1] else 0),
        15,
    )
    structure_quality_score = bounded_score(
        (4 if darvas_box else 0)
        + (3 if higher_lows else 0)
        + (3 if ascending_triangle else 0)
        + (2 if flat_base else 0)
        + (2 if current >= resistance * 0.97 else 0)
        + (1 if support < current < resistance * 1.05 else 0),
        15,
    )
    volume_confirmation_score = bounded_score(
        (4 if up_volume_expansion else 0)
        + (3 if pocket_pivot else 0)
        + (3 if rvol >= 1.5 else 2 if rvol >= 1.2 else 0)
        + (2 if volume_dryup and up_volume_expansion else 0)
        + (2 if obv_rising else 0)
        + (1 if latest_volume > avg_volume_50 else 0),
        15,
    )
    pattern_count = sum([darvas_box, vcp, wyckoff_accumulation, ascending_triangle, flat_base, bull_flag, double_bottom, stage2_breakout, launch_pad_200])
    pattern_reliability_score = bounded_score(min(pattern_count * 2, 10) + (3 if stage2_breakout else 0) + (2 if vcp and darvas_box else 0), 15)
    institutional_footprints_score = bounded_score(
        (2 if higher_lows else 0)
        + (2 if repeated_tests >= 2 else 0)
        + (2 if obv_rising else 0)
        + (2 if ad_rising else 0)
        + (1 if up_volume_expansion else 0)
        + (1 if current > vwap_proxy else 0),
        10,
    )

    entry_price = resistance * 1.001 if current <= resistance else current
    stop_loss = min(demand_low, current - latest_atr * 1.5)
    if stop_loss <= 0 or stop_loss >= entry_price:
        stop_loss = entry_price * 0.94
    risk = max(entry_price - stop_loss, 0.01)
    target_1 = entry_price + risk * 3
    target_2 = entry_price + risk * 5
    risk_reward = (target_1 - entry_price) / risk if risk else 0
    risk_reward_quality_score = bounded_score(10 if risk_reward >= 3 else 7 if risk_reward >= 2.5 else 4 if risk_reward >= 2 else 1, 10)

    false_breakout_risk = 20
    false_breakout_risk += 25 if latest_rsi > 75 else 0
    false_breakout_risk += 20 if down_volume_expansion else 0
    false_breakout_risk += 15 if not up_volume_expansion and current >= resistance * 0.98 else 0
    false_breakout_risk += 15 if not weekly_bullish else 0
    false_breakout_risk += 10 if supply_high <= current * 1.03 else 0
    false_breakout_risk = bounded_score(false_breakout_risk, 100)
    false_breakout_risk_score = bounded_score((100 - false_breakout_risk) / 20, 5)

    chart_quality_score = bounded_score(
        trend_clarity_score
        + structure_quality_score
        + volume_confirmation_score
        + pattern_reliability_score
        + timeframe_alignment_score
        + institutional_footprints_score
        + risk_reward_quality_score
        + false_breakout_risk_score,
        100,
    )

    patterns = []
    if darvas_box:
        patterns.append("Darvas Box")
    if vcp:
        patterns.append("VCP")
    if wyckoff_accumulation:
        patterns.append("Wyckoff Accumulation")
    if wyckoff_distribution:
        patterns.append("Wyckoff Distribution")
    if ascending_triangle:
        patterns.append("Ascending Triangle")
    if flat_base:
        patterns.append("Flat Base")
    if bull_flag:
        patterns.append("Bull Flag")
    if bear_flag:
        patterns.append("Bear Flag")
    if double_bottom:
        patterns.append("Double Bottom")
    if double_top:
        patterns.append("Double Top")
    if stage2_breakout:
        patterns.append("Stage-2 Breakout")
    if launch_pad_200:
        patterns.append("200 EMA Launch Pad")

    candles = []
    if bullish_marubozu:
        candles.append("Bullish Marubozu")
    if bearish_marubozu:
        candles.append("Bearish Marubozu")
    if bullish_engulfing:
        candles.append("Bullish Engulfing")
    if bearish_engulfing:
        candles.append("Bearish Engulfing")
    if hammer:
        candles.append("Hammer")
    if shooting_star:
        candles.append("Shooting Star")
    if doji:
        candles.append("Doji")
    if inside_bar:
        candles.append("Inside Bar")
    if nr7:
        candles.append("NR7")
    if wide_range:
        candles.append("Wide Range Candle")
    if gap_candle:
        candles.append("Gap Candle")

    volume_confirmation = "Confirmed" if volume_confirmation_score >= 10 else "Partial" if volume_confirmation_score >= 6 else "Weak"
    institutional_footprints = "Strong" if institutional_footprints_score >= 8 else "Present" if institutional_footprints_score >= 5 else "Weak"
    entry_trigger = (
        "Breakout above resistance with volume confirmation and VWAP hold"
        if chart_quality_score >= 90
        else "Watch for breakout/retest confirmation before entry"
    )
    retest_low = max(resistance - latest_atr * 0.50, 0)
    retest_high = resistance + latest_atr * 0.25
    reason = []
    if chart_stage.startswith("Stage 2"):
        reason.append("Stage 2 trend structure")
    if darvas_box or vcp:
        reason.append("base/compression near resistance")
    if volume_confirmation_score >= 10:
        reason.append("volume supports the setup")
    if timeframe_alignment_score >= 10:
        reason.append("multi-timeframe alignment is supportive")
    if false_breakout_risk >= 60:
        reason.append("false breakout risk remains elevated")

    return {
        "stock_name": row.get("name", symbol),
        "nsecode": symbol,
        "timeframe_alignment": timeframe_alignment,
        "chart_stage": chart_stage,
        "chart_quality_score": chart_quality_score,
        "trend_clarity_score": trend_clarity_score,
        "structure_quality_score": structure_quality_score,
        "volume_confirmation_score": volume_confirmation_score,
        "pattern_reliability_score": pattern_reliability_score,
        "multi_timeframe_alignment_score": timeframe_alignment_score,
        "institutional_footprints_score": institutional_footprints_score,
        "risk_reward_quality_score": risk_reward_quality_score,
        "false_breakout_risk_score": false_breakout_risk_score,
        "pattern_detected": ", ".join(patterns) if patterns else "No major pattern confirmed",
        "candlestick_signal": ", ".join(candles) if candles else "No major candle signal",
        "support_zone": f"{support:.2f} - {demand_high:.2f}",
        "resistance_zone": f"{supply_low:.2f} - {resistance:.2f}",
        "demand_zone": f"{demand_low:.2f} - {demand_high:.2f}",
        "supply_zone": f"{supply_low:.2f} - {supply_high:.2f}",
        "breakout_level": round(resistance, 2),
        "retest_zone": f"{retest_low:.2f} - {retest_high:.2f}",
        "entry_trigger": entry_trigger,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "risk_reward": round(risk_reward, 2),
        "false_breakout_risk": false_breakout_risk,
        "volume_confirmation": volume_confirmation,
        "institutional_footprints": institutional_footprints,
        "final_chart_verdict": chart_verdict(chart_quality_score),
        "current_price": round(current, 2),
        "rvol": round(rvol, 2),
        "rsi": round(latest_rsi, 2),
        "reason": "; ".join(reason) if reason else "Chart does not yet show enough high-quality confirmation.",
    }


def build_ai_chart_reading_model(df: pd.DataFrame, history_limit: int = 80) -> pd.DataFrame:
    if df.empty:
        return df
    rows: list[dict[str, Any]] = []
    for _, row in df.head(history_limit).iterrows():
        try:
            scored = score_ai_chart_reading_candidate(row)
        except Exception as exc:
            scored = {
                "chart_quality_score": 0,
                "nsecode": row.get("nsecode", ""),
                "reason": f"Chart scoring skipped: {exc}",
            }
        if isinstance(scored, dict) and (coerce_float(scored.get("chart_quality_score"), 0) or 0) > 0:
            rows.append(scored)
    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return safe_sort_dataframe(model, ["chart_quality_score", "risk_reward", "false_breakout_risk"], [False, False, True])


def apply_ai_chart_reading_filters(
    model: pd.DataFrame,
    min_chart_quality: int,
    min_risk_reward: float,
    max_false_breakout_risk: int,
    require_higher_timeframe: bool,
    require_volume_confirmation: bool,
) -> pd.DataFrame:
    if model.empty:
        return model
    filtered = model[
        (pd.to_numeric(model["chart_quality_score"], errors="coerce") >= min_chart_quality)
        & (pd.to_numeric(model["risk_reward"], errors="coerce") >= min_risk_reward)
        & (pd.to_numeric(model["false_breakout_risk"], errors="coerce") <= max_false_breakout_risk)
    ].copy()
    if require_higher_timeframe:
        filtered = filtered[
            filtered["timeframe_alignment"].astype(str).str.contains("Monthly bullish", na=False)
            & filtered["timeframe_alignment"].astype(str).str.contains("Weekly bullish", na=False)
        ]
    if require_volume_confirmation:
        filtered = filtered[filtered["volume_confirmation"].astype(str).isin(["Confirmed"])]
    return safe_sort_dataframe(filtered, ["chart_quality_score", "risk_reward"], [False, False])


def ai_chart_reading_display_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "stock_name",
        "nsecode",
        "timeframe_alignment",
        "chart_stage",
        "chart_quality_score",
        "pattern_detected",
        "candlestick_signal",
        "support_zone",
        "resistance_zone",
        "breakout_level",
        "retest_zone",
        "entry_trigger",
        "entry_price",
        "stop_loss",
        "target_1",
        "target_2",
        "risk_reward",
        "false_breakout_risk",
        "volume_confirmation",
        "institutional_footprints",
        "final_chart_verdict",
        "reason",
    ]
    return [column for column in columns if column in df.columns]


def render_ai_chart_reading_page() -> None:
    st.subheader("AI Chart Reading Engine")
    st.caption("Reads price action, volume, structure, trend, support-resistance, compression, expansion, institutional footprints, and multi-timeframe alignment.")

    with st.sidebar:
        st.header("Chart Reading Controls")
        rows_shown = st.slider("Rows shown", 5, 100, 25, 5, key="chart_reading_rows")
        history_limit = st.slider("Candidates to score", 20, 180, 80, 20, key="chart_reading_history")
        st.divider()
        min_chart_quality = st.slider("Minimum chart quality score", 0, 100, 80, 1, key="chart_min_quality")
        min_risk_reward = st.slider("Minimum risk/reward", 1.0, 5.0, 3.0, 0.25, key="chart_min_rr")
        max_false_breakout_risk = st.slider("Maximum false breakout risk", 0, 100, 55, 5, key="chart_max_false")
        require_higher_timeframe = st.toggle("Require monthly + weekly bullish", value=False, key="chart_require_htf")
        require_volume_confirmation = st.toggle("Require volume confirmation", value=False, key="chart_require_volume")
        if st.button("Refresh chart reading engine", type="primary", width="stretch"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            st.rerun()

    with st.expander("Chart Quality Model", expanded=True):
        weights_df = pd.DataFrame(
            [{"Component": key.replace("_", " ").title(), "Weight": value} for key, value in CHART_QUALITY_WEIGHTS.items()]
        )
        display_dataframe(weights_df)

    with st.spinner("Fetching and reading charts..."):
        df, error = run_scan(AI_CHART_READING_CLAUSE)
    if error:
        st.error(error)
        st.caption("If Chartink rejects the pre-filter, adjust AI_CHART_READING_CLAUSE.")
        return

    model = build_ai_chart_reading_model(df, history_limit=history_limit)
    if model.empty:
        st.info("No charts could be scored from the current pre-filter.")
        return

    filtered = apply_ai_chart_reading_filters(
        model,
        min_chart_quality=min_chart_quality,
        min_risk_reward=min_risk_reward,
        max_false_breakout_risk=max_false_breakout_risk,
        require_higher_timeframe=require_higher_timeframe,
        require_volume_confirmation=require_volume_confirmation,
    )

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Charts scored", len(model))
    metric_b.metric("Qualified charts", len(filtered))
    metric_c.metric("Top chart score", int((filtered if not filtered.empty else model).iloc[0]["chart_quality_score"]))

    if filtered.empty:
        st.warning("No chart passes the current Module 19 quality filter. Review the scored universe below or loosen controls.")
    else:
        st.subheader("Qualified Chart Setups")
        table = filtered[ai_chart_reading_display_columns(filtered)].head(rows_shown)
        display_dataframe(table, height=640)
        st.download_button(
            "Download AI chart reading candidates CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            file_name="ai_chart_reading_candidates.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Scored chart universe before filters", expanded=filtered.empty):
        display_dataframe(model[ai_chart_reading_display_columns(model)].head(rows_shown), height=620)


def timeframe_interpretation(history: pd.DataFrame, label: str) -> dict[str, Any]:
    if history.empty or "close" not in history.columns:
        return {
            "Timeframe": label,
            "Bias": "Unavailable",
            "Trend Evidence": "Data unavailable",
            "Conflict": "Cannot confirm",
        }

    working = history.copy()
    for column in ["close", "high", "low", "volume"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["close"])
    if len(working) < 20:
        return {
            "Timeframe": label,
            "Bias": "Unavailable",
            "Trend Evidence": "Insufficient rows",
            "Conflict": "Cannot confirm",
        }

    close = working["close"]
    high = working["high"] if "high" in working.columns else close
    low = working["low"] if "low" in working.columns else close
    volume = working["volume"] if "volume" in working.columns else pd.Series(0, index=working.index)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean() if len(close) >= 50 else ema20
    latest = float(close.iloc[-1])
    ret = (close.iloc[-1] / close.iloc[max(0, len(close) - 11)] - 1) * 100 if close.iloc[max(0, len(close) - 11)] else 0
    higher_lows = bool(low.tail(8).min() >= low.shift(8).tail(8).min()) if len(low) >= 16 else False
    higher_highs = bool(high.tail(8).max() >= high.shift(8).tail(8).max()) if len(high) >= 16 else False
    rvol = float(volume.iloc[-1] / volume.tail(20).mean()) if "volume" in working.columns and volume.tail(20).mean() else 0

    if latest > ema20.iloc[-1] and ema20.iloc[-1] >= ema50.iloc[-1] and ret > 0:
        bias = "Bullish"
    elif latest < ema20.iloc[-1] and ret < 0:
        bias = "Bearish"
    else:
        bias = "Neutral"

    evidence = []
    evidence.append("price above EMA20" if latest > ema20.iloc[-1] else "price below EMA20")
    evidence.append("EMA20 above EMA50" if ema20.iloc[-1] >= ema50.iloc[-1] else "EMA20 below EMA50")
    if higher_highs:
        evidence.append("higher highs")
    if higher_lows:
        evidence.append("higher lows")
    if rvol >= 1.2:
        evidence.append(f"volume {rvol:.2f}x average")

    return {
        "Timeframe": label,
        "Bias": bias,
        "Trend Evidence": ", ".join(evidence),
        "Recent Return %": round(float(ret), 2),
        "Conflict": "Aligned" if bias == "Bullish" else "Needs confirmation" if bias == "Neutral" else "Conflicting/weak",
    }


def build_professional_chart_report(
    symbol: str,
    capital: float,
    risk_pct: float,
    daily_history_override: pd.DataFrame | None = None,
    replay_mode: bool = False,
) -> dict[str, Any]:
    cleaned_symbol = symbol.strip().upper().replace(".NS", "")
    if not cleaned_symbol:
        return {}

    row = pd.Series({"nsecode": cleaned_symbol, "name": cleaned_symbol})
    daily_history = daily_history_override.copy() if isinstance(daily_history_override, pd.DataFrame) and not daily_history_override.empty else fetch_ohlcv_history(cleaned_symbol, lookback_days=900)
    weekly_history = resample_chart_timeframe(daily_history, "W-FRI")
    monthly_history = resample_chart_timeframe(daily_history, "M")
    one_hour = pd.DataFrame() if replay_mode else fetch_interval_ohlcv_history(cleaned_symbol, period="60d", interval="60m")
    fifteen_min = pd.DataFrame() if replay_mode else fetch_interval_ohlcv_history(cleaned_symbol, period="30d", interval="15m")
    five_min = pd.DataFrame() if replay_mode else fetch_interval_ohlcv_history(cleaned_symbol, period="5d", interval="5m")

    chart = score_ai_chart_reading_candidate(row, history_override=daily_history)
    if not isinstance(chart, dict):
        chart = {"chart_quality_score": 0, "reason": "Chart data unavailable."}

    if replay_mode:
        early = {}
        iq = {}
    else:
        try:
            early = score_ai_early_breakout_candidate(row)
        except Exception:
            early = {}
        if not isinstance(early, dict):
            early = {}

        market_regime = compute_iq5000_market_regime()
        try:
            iq = score_iq5000_candidate(row, market_regime=market_regime, capital=capital, max_risk_pct=risk_pct, max_capital_pct=25.0)
        except Exception:
            iq = {}
    if not isinstance(iq, dict):
        iq = {}

    timeframes = pd.DataFrame(
        [
            timeframe_interpretation(monthly_history.reset_index() if not monthly_history.empty else pd.DataFrame(), "Monthly"),
            timeframe_interpretation(weekly_history.reset_index() if not weekly_history.empty else pd.DataFrame(), "Weekly"),
            timeframe_interpretation(daily_history, "Daily"),
            timeframe_interpretation(one_hour, "1 Hour"),
            timeframe_interpretation(fifteen_min, "15 Minute"),
            timeframe_interpretation(five_min, "5 Minute"),
        ]
    )

    chart_score = coerce_float(chart.get("chart_quality_score"), 0) or 0
    early_score = coerce_float(early.get("ai_early_breakout_score"), 0) or 0
    institutional_score = coerce_float(iq.get("ai_institutional_score"), 0) or coerce_float(chart.get("institutional_footprints_score"), 0) * 10 or 0
    smart_money_score = coerce_float(iq.get("smart_money_score"), 0) or institutional_score
    intraday_score = coerce_float(iq.get("ai_intraday_score"), 0) or max(0, chart_score - 10)
    swing_score = coerce_float(iq.get("ai_swing_score"), 0) or chart_score
    iq_score = coerce_float(iq.get("ai_iq_score"), 0) or chart_score * 10
    consensus = bounded_score((chart_score + early_score + institutional_score + smart_money_score + swing_score) / 5, 100)
    trade_probability = bounded_score((chart_score * 0.35) + (early_score * 0.20) + (institutional_score * 0.20) + (consensus * 0.25), 100)

    scores = pd.DataFrame(
        [
            {"Score": "Chart Quality Score", "Value": round(chart_score, 2)},
            {"Score": "Trend Score", "Value": chart.get("trend_clarity_score", 0)},
            {"Score": "Pattern Score", "Value": chart.get("pattern_reliability_score", 0)},
            {"Score": "Volume Score", "Value": chart.get("volume_confirmation_score", 0)},
            {"Score": "Institutional Score", "Value": round(institutional_score, 2)},
            {"Score": "Smart Money Score", "Value": round(smart_money_score, 2)},
            {"Score": "AI Intraday Score", "Value": round(intraday_score, 2)},
            {"Score": "AI Swing Score", "Value": round(swing_score, 2)},
            {"Score": "AI Institutional Score", "Value": round(institutional_score, 2)},
            {"Score": "AI Early Breakout Score", "Value": round(early_score, 2)},
            {"Score": "AI IQ Score", "Value": round(iq_score, 2)},
            {"Score": "Consensus Score", "Value": consensus},
            {"Score": "Trade Probability", "Value": trade_probability},
        ]
    )

    bullish_timeframes = int((timeframes["Bias"] == "Bullish").sum()) if "Bias" in timeframes.columns else 0
    bearish_timeframes = int((timeframes["Bias"] == "Bearish").sum()) if "Bias" in timeframes.columns else 0
    if chart_score >= 92 and consensus >= 80 and trade_probability >= 80:
        verdict = "5/5 Elite Institutional Buy"
    elif chart_score >= 85 and consensus >= 72:
        verdict = "4/5 Strong Buy"
    elif chart_score >= 78:
        verdict = "4/5 Buy on Dips"
    elif chart_score >= 65:
        verdict = "3/5 Watchlist"
    elif chart_score >= 45:
        verdict = "2/5 Avoid for Now"
    else:
        verdict = "1/5 Strong Avoid"

    entry_price = coerce_float(chart.get("entry_price"), None)
    stop_loss = coerce_float(chart.get("stop_loss"), None)
    target_1 = coerce_float(chart.get("target_1"), None)
    target_2 = coerce_float(chart.get("target_2"), None)
    risk_amount = capital * risk_pct / 100
    per_share_risk = max((entry_price or 0) - (stop_loss or 0), 0.01)
    position_size = int(risk_amount / per_share_risk) if entry_price and stop_loss and entry_price > stop_loss else 0
    target_3 = entry_price + per_share_risk * 7 if entry_price else None

    strengths = []
    weaknesses = []
    opportunities = []
    threats = []
    if chart_score >= 80:
        strengths.append("Chart quality is high enough to justify active monitoring.")
    else:
        weaknesses.append("Chart quality is not yet in the high-conviction zone.")
    if bullish_timeframes >= 4:
        strengths.append("Most monitored timeframes are aligned bullish.")
    elif bearish_timeframes >= 2:
        threats.append("Multiple timeframes remain bearish or conflicting.")
    if "Darvas" in str(chart.get("pattern_detected")) or "VCP" in str(chart.get("pattern_detected")):
        opportunities.append("Base/compression pattern may support a breakout attempt.")
    if coerce_float(chart.get("false_breakout_risk"), 100) and coerce_float(chart.get("false_breakout_risk"), 100) > 60:
        threats.append("False breakout risk is elevated and needs live confirmation.")
    if str(chart.get("volume_confirmation", "")).lower() == "confirmed":
        strengths.append("Volume is supporting the current structure.")
    else:
        weaknesses.append("Volume confirmation is incomplete.")
    if str(chart.get("institutional_footprints", "")).lower() in {"strong", "present"}:
        strengths.append("Institutional footprints are visible in the chart behavior.")
    else:
        weaknesses.append("Institutional footprints are not strong yet.")
    if not opportunities:
        opportunities.append("Wait for a clean breakout, retest, or VWAP-supported entry.")
    if not threats:
        threats.append("Main risk is a failed breakout if volume or market breadth weakens.")

    swot = pd.DataFrame(
        [
            {"Type": "Strengths", "Details": "; ".join(strengths)},
            {"Type": "Weaknesses", "Details": "; ".join(weaknesses)},
            {"Type": "Opportunities", "Details": "; ".join(opportunities)},
            {"Type": "Threats", "Details": "; ".join(threats)},
        ]
    )

    plan = pd.DataFrame(
        [
            {"Plan Item": "Ideal Entry", "Value": chart.get("entry_trigger", "Wait for confirmation")},
            {"Plan Item": "Aggressive Entry", "Value": f"Above {entry_price:.2f}" if entry_price else "Unavailable"},
            {"Plan Item": "Conservative Entry", "Value": f"Retest zone {chart.get('retest_zone', 'Unavailable')}"},
            {"Plan Item": "Breakout Entry", "Value": f"Breakout level {chart.get('breakout_level', 'Unavailable')}"},
            {"Plan Item": "Retest Entry", "Value": chart.get("retest_zone", "Unavailable")},
            {"Plan Item": "Stop Loss", "Value": f"{stop_loss:.2f}" if stop_loss else "Unavailable"},
            {"Plan Item": "Target 1", "Value": f"{target_1:.2f}" if target_1 else "Unavailable"},
            {"Plan Item": "Target 2", "Value": f"{target_2:.2f}" if target_2 else "Unavailable"},
            {"Plan Item": "Target 3", "Value": f"{target_3:.2f}" if target_3 else "Unavailable"},
            {"Plan Item": "Trailing Stop", "Value": "Trail below EMA20 or 2 ATR after target 1."},
            {"Plan Item": "Expected Holding Period", "Value": "Intraday to swing; use live structure for final timing."},
            {"Plan Item": "Position Size", "Value": position_size},
            {"Plan Item": "Rupee Risk", "Value": round(risk_amount, 2)},
        ]
    )

    buyers_comment = "Buyers are in control when price holds above key moving averages and closes near the upper part of the range."
    if chart_score >= 80:
        buyers_comment = "Buyers appear to be defending higher levels, with structure and volume supporting continued monitoring."
    sellers_comment = "Sellers are not fully defeated until price accepts above resistance and holds the retest zone."
    if coerce_float(chart.get("false_breakout_risk"), 100) and coerce_float(chart.get("false_breakout_risk"), 100) >= 60:
        sellers_comment = "Sellers still have influence because false-breakout risk is elevated near resistance."

    professional_summary = {
        "Executive Summary": f"{cleaned_symbol} is classified as {chart.get('chart_stage', 'Unavailable')} with a chart quality score of {chart_score:.0f}/100 and final verdict: {verdict}.",
        "Current Market Structure": f"The chart is showing {chart.get('pattern_detected', 'no major pattern confirmed')}. Support is around {chart.get('support_zone', 'Unavailable')} and resistance is around {chart.get('resistance_zone', 'Unavailable')}.",
        "Trend Analysis": f"{bullish_timeframes} of 6 monitored timeframes are bullish. Higher-timeframe conflicts should be respected before capital deployment.",
        "Volume Analysis": f"Volume confirmation is {chart.get('volume_confirmation', 'Unavailable')} with RVOL near {chart.get('rvol', 'Unavailable')}.",
        "Institutional Activity": f"Institutional footprint reading: {chart.get('institutional_footprints', 'Unavailable')}. Smart money score estimate: {smart_money_score:.0f}/100.",
        "Strengths": "; ".join(strengths),
        "Weaknesses": "; ".join(weaknesses),
        "Risks": f"False breakout risk is {chart.get('false_breakout_risk', 'Unavailable')}/100. Gap, trend failure, and liquidity risks must be controlled with position sizing.",
        "Trading Strategy": f"Use {chart.get('entry_trigger', 'confirmation-based entry')} with stop near {stop_loss:.2f}" if stop_loss else "Wait for a valid entry and stop before trading.",
        "Swing Outlook": "Constructive" if swing_score >= 75 else "Neutral/unclear",
        "Intraday Outlook": "Constructive after VWAP/ORB confirmation" if intraday_score >= 70 else "Needs live confirmation",
        "Long-Term Outlook": "Constructive if monthly and weekly remain bullish" if bullish_timeframes >= 3 else "Mixed until higher timeframes improve",
        "Capital Allocation Recommendation": "Deploy only after confirmation; use reduced size if verdict is below Strong Buy.",
        "Expected Probability": f"{trade_probability}/100",
        "Confidence Level": f"{consensus}/100 consensus",
        "Historical Similarity": iq.get("historical_win_rate", "Unavailable"),
        "Market Memory Reference": iq.get("market_memory_score", "Unavailable"),
        "Legendary Analyst Explanation": f"{buyers_comment} {sellers_comment} Momentum should be interpreted through price acceptance, not indicators alone.",
    }

    return {
        "symbol": cleaned_symbol,
        "chart": chart,
        "early": early,
        "iq": iq,
        "timeframes": timeframes,
        "scores": scores,
        "swot": swot,
        "plan": plan,
        "summary": professional_summary,
        "verdict": verdict,
    }


def render_professional_chart_interpretation_page() -> None:
    st.subheader("AI Professional Chart Interpretation Engine")
    st.caption("Enter any NSE symbol to generate an institutional-grade chart interpretation, trading plan, SWOT, scores, and professional analyst summary.")

    with st.sidebar:
        st.header("Professional Chart Controls")
        symbol = st.text_input("Stock symbol or company name", value="RELIANCE", key="professional_chart_symbol")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key="professional_chart_capital")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key="professional_chart_risk")
        if st.button("Refresh professional interpretation", type="primary", width="stretch"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            st.rerun()

    cleaned_symbol = symbol.strip().upper().replace(".NS", "")
    if not cleaned_symbol:
        st.info("Enter an NSE symbol such as RELIANCE, SBIN, BEL, CDSL, or TRENT.")
        return
    if " " in cleaned_symbol:
        st.warning("For reliable data lookup, use the NSE trading symbol. Company-name lookup is limited by the current data provider.")

    with st.spinner(f"Reading {cleaned_symbol} like a professional chart analyst..."):
        report = build_professional_chart_report(cleaned_symbol, capital=capital, risk_pct=risk_pct)

    if not report:
        st.info("No report could be generated for this symbol.")
        return

    chart = report.get("chart", {})
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Final Verdict", report.get("verdict", "Unavailable"))
    metric_b.metric("Chart Quality", int(coerce_float(chart.get("chart_quality_score"), 0) or 0))
    metric_c.metric("Risk/Reward", chart.get("risk_reward", "Unavailable"))
    metric_d.metric("False Breakout Risk", chart.get("false_breakout_risk", "Unavailable"))

    tab_report, tab_structure, tab_volume, tab_swot, tab_plan, tab_scores = st.tabs(
        ["Analyst Report", "Structure", "Volume & Footprints", "Chart SWOT", "Trading Plan", "Scores"]
    )

    with tab_report:
        for title, body in report["summary"].items():
            st.markdown(f"**{title}**")
            st.write(body)

    with tab_structure:
        structure_rows = [
            {"Metric": "Chart Stage", "Value": chart.get("chart_stage", "Unavailable")},
            {"Metric": "Pattern Detected", "Value": chart.get("pattern_detected", "Unavailable")},
            {"Metric": "Candlestick Signal", "Value": chart.get("candlestick_signal", "Unavailable")},
            {"Metric": "Support Zone", "Value": chart.get("support_zone", "Unavailable")},
            {"Metric": "Resistance Zone", "Value": chart.get("resistance_zone", "Unavailable")},
            {"Metric": "Demand Zone", "Value": chart.get("demand_zone", "Unavailable")},
            {"Metric": "Supply Zone", "Value": chart.get("supply_zone", "Unavailable")},
            {"Metric": "Breakout Level", "Value": chart.get("breakout_level", "Unavailable")},
            {"Metric": "Retest Zone", "Value": chart.get("retest_zone", "Unavailable")},
            {"Metric": "Final Chart Verdict", "Value": chart.get("final_chart_verdict", "Unavailable")},
            {"Metric": "Reason", "Value": chart.get("reason", "Unavailable")},
        ]
        display_dataframe(pd.DataFrame(structure_rows), height=360)
        st.markdown("**Multi-Timeframe Analysis**")
        display_dataframe(report["timeframes"], height=300)

    with tab_volume:
        volume_rows = [
            {"Metric": "Volume Confirmation", "Value": chart.get("volume_confirmation", "Unavailable")},
            {"Metric": "Institutional Footprints", "Value": chart.get("institutional_footprints", "Unavailable")},
            {"Metric": "Relative Volume", "Value": chart.get("rvol", "Unavailable")},
            {"Metric": "RSI Context", "Value": chart.get("rsi", "Unavailable")},
            {"Metric": "Smart Money Interpretation", "Value": report["summary"].get("Institutional Activity", "Unavailable")},
        ]
        display_dataframe(pd.DataFrame(volume_rows), height=260)
        st.info(report["summary"].get("Legendary Analyst Explanation", "Volume and price must confirm each other before action."))

    with tab_swot:
        display_dataframe(report["swot"], height=260)

    with tab_plan:
        display_dataframe(report["plan"], height=420)
        st.caption("This is a research plan. Actual entry requires live confirmation, liquidity, and disciplined risk control.")

    with tab_scores:
        display_dataframe(report["scores"], height=520)


def escape_svg_text(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def parse_price_zone(value: Any) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", str(value))
    if not numbers:
        return None, None
    first = coerce_float(numbers[0], None)
    second = coerce_float(numbers[1], first) if len(numbers) > 1 else first
    if first is None or second is None:
        return None, None
    return min(first, second), max(first, second)


def normalize_chart_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    working = history.copy()
    if "date" not in working.columns:
        working = working.reset_index()
        first_column = working.columns[0]
        working = working.rename(columns={first_column: "date"})
    required = ["open", "high", "low", "close", "volume"]
    if not set(required).issubset(working.columns):
        return pd.DataFrame()
    working["date"] = pd.to_datetime(working["date"].astype(str), errors="coerce")
    for column in required:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    if "volume" in working.columns:
        working["volume"] = working["volume"].fillna(0)
    return working.reset_index(drop=True)


def fetch_chart_teacher_history(symbol: str, timeframe: str) -> pd.DataFrame:
    timeframe = timeframe.strip()
    if timeframe == "Monthly":
        daily = fetch_ohlcv_history(symbol, lookback_days=2400)
        return normalize_chart_history(resample_chart_timeframe(daily, "M"))
    if timeframe == "Weekly":
        daily = fetch_ohlcv_history(symbol, lookback_days=1800)
        return normalize_chart_history(resample_chart_timeframe(daily, "W-FRI"))
    if timeframe == "Daily":
        return normalize_chart_history(fetch_ohlcv_history(symbol, lookback_days=1200))
    if timeframe == "4 Hour":
        hourly = fetch_interval_ohlcv_history(symbol, period="180d", interval="60m")
        return normalize_chart_history(resample_chart_timeframe(hourly, "4h"))

    interval_map = {
        "1 Hour": ("730d", "60m"),
        "30 Minute": ("60d", "30m"),
        "15 Minute": ("30d", "15m"),
        "5 Minute": ("5d", "5m"),
        "1 Minute": ("5d", "1m"),
    }
    period, interval = interval_map.get(timeframe, ("60d", "60m"))
    return normalize_chart_history(fetch_interval_ohlcv_history(symbol, period=period, interval=interval))


def add_chart_teacher_indicators(history: pd.DataFrame) -> pd.DataFrame:
    working = normalize_chart_history(history)
    if working.empty:
        return working
    high = working["high"]
    low = working["low"]
    close = working["close"]
    volume = working["volume"].fillna(0)
    previous_close = close.shift(1)

    working["ema20"] = close.ewm(span=20, adjust=False).mean()
    working["ema50"] = close.ewm(span=50, adjust=False).mean()
    working["ema100"] = close.ewm(span=100, adjust=False).mean()
    working["ema190"] = close.ewm(span=190, adjust=False).mean()
    working["ema200"] = close.ewm(span=200, adjust=False).mean()
    working["sma200"] = close.rolling(200, min_periods=20).mean()
    typical = (high + low + close) / 3
    cumulative_volume = volume.cumsum().replace(0, pd.NA)
    working["vwap"] = (typical * volume).cumsum() / cumulative_volume
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    working["atr14"] = true_range.rolling(14, min_periods=3).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=3).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=3).mean()
    working["rsi14"] = 100 - (100 / (1 + (gain / loss.replace(0, pd.NA))))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    working["macd"] = ema12 - ema26
    working["macd_signal"] = working["macd"].ewm(span=9, adjust=False).mean()
    direction = close.diff().fillna(0).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    working["obv"] = (direction * volume).cumsum()
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, pd.NA)
    working["ad_line"] = (money_flow_multiplier.fillna(0) * volume).cumsum()
    positive_flow = (typical * volume).where(typical > typical.shift(1), 0).rolling(14, min_periods=3).sum()
    negative_flow = (typical * volume).where(typical < typical.shift(1), 0).rolling(14, min_periods=3).sum()
    working["mfi14"] = 100 - (100 / (1 + positive_flow / negative_flow.replace(0, pd.NA)))
    sma20 = close.rolling(20, min_periods=5).mean()
    std20 = close.rolling(20, min_periods=5).std()
    working["bb_upper"] = sma20 + 2 * std20
    working["bb_lower"] = sma20 - 2 * std20

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)
    atr = true_range.rolling(14, min_periods=3).mean().replace(0, pd.NA)
    plus_di = 100 * plus_dm.rolling(14, min_periods=3).sum() / atr
    minus_di = 100 * minus_dm.rolling(14, min_periods=3).sum() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
    working["adx14"] = dx.rolling(14, min_periods=3).mean()
    return working


def build_chart_teacher_annotations(chart: dict[str, Any], visible_history: pd.DataFrame) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    current = coerce_float(chart.get("current_price"), None)

    demand_low, demand_high = parse_price_zone(chart.get("demand_zone"))
    if demand_low is not None and demand_high is not None:
        annotations.append(
            {
                "Type": "Demand Zone",
                "Price": f"{demand_low:.2f} - {demand_high:.2f}",
                "Color": "#10b981",
                "Kind": "zone",
                "Low": demand_low,
                "High": demand_high,
                "Explanation": "Buyers have repeatedly accepted price in this lower zone. A professional watches whether pullbacks dry up here instead of assuming every dip is safe.",
            }
        )

    supply_low, supply_high = parse_price_zone(chart.get("supply_zone"))
    if supply_low is not None and supply_high is not None:
        annotations.append(
            {
                "Type": "Supply Zone",
                "Price": f"{supply_low:.2f} - {supply_high:.2f}",
                "Color": "#ef4444",
                "Kind": "zone",
                "Low": supply_low,
                "High": supply_high,
                "Explanation": "Sellers have defended this upper zone. A breakout needs acceptance above it, ideally with stronger volume.",
            }
        )

    breakout = coerce_float(chart.get("breakout_level"), None)
    if breakout is not None:
        annotations.append(
            {
                "Type": "Breakout Level",
                "Price": f"{breakout:.2f}",
                "Color": "#2563eb",
                "Kind": "line",
                "Low": breakout,
                "High": breakout,
                "Explanation": "This is the resistance level the chart must absorb. Price near this line without volume can still fail.",
            }
        )

    retest_low, retest_high = parse_price_zone(chart.get("retest_zone"))
    if retest_low is not None and retest_high is not None:
        annotations.append(
            {
                "Type": "Retest Zone",
                "Price": f"{retest_low:.2f} - {retest_high:.2f}",
                "Color": "#f59e0b",
                "Kind": "zone",
                "Low": retest_low,
                "High": retest_high,
                "Explanation": "If price breaks out, this zone is where professionals look for acceptance or rejection on the retest.",
            }
        )

    stop_loss = coerce_float(chart.get("stop_loss"), None)
    if stop_loss is not None:
        annotations.append(
            {
                "Type": "Risk Line / Stop Loss",
                "Price": f"{stop_loss:.2f}",
                "Color": "#dc2626",
                "Kind": "line",
                "Low": stop_loss,
                "High": stop_loss,
                "Explanation": "The trade thesis weakens below this level. It defines risk before reward is considered.",
            }
        )

    for target_name in ["target_1", "target_2"]:
        target = coerce_float(chart.get(target_name), None)
        if target is not None:
            annotations.append(
                {
                    "Type": target_name.replace("_", " ").title(),
                    "Price": f"{target:.2f}",
                    "Color": "#16a34a",
                    "Kind": "line",
                    "Low": target,
                    "High": target,
                    "Explanation": "Reward reference derived from the current risk structure. Targets are planning levels, not guarantees.",
                }
            )

    pattern = str(chart.get("pattern_detected", ""))
    if pattern and pattern != "No major pattern confirmed":
        annotations.append(
            {
                "Type": "Pattern Teacher",
                "Price": chart.get("current_price", "Current"),
                "Color": "#7c3aed",
                "Kind": "label",
                "Low": current,
                "High": current,
                "Explanation": f"{pattern} detected. The key evidence is structure near resistance, compression, higher lows, or volume behavior depending on the pattern.",
            }
        )

    if str(chart.get("volume_confirmation", "")).lower() in {"confirmed", "partial"}:
        annotations.append(
            {
                "Type": "Volume Evidence",
                "Price": chart.get("current_price", "Current"),
                "Color": "#0891b2",
                "Kind": "label",
                "Low": current,
                "High": current,
                "Explanation": f"Volume confirmation is {chart.get('volume_confirmation')}. Professionals want price progress to be supported by participation, not just thin moves.",
            }
        )

    if visible_history.empty:
        return annotations
    last_close = float(pd.to_numeric(visible_history["close"], errors="coerce").dropna().iloc[-1])
    if current is None:
        current = last_close
    return annotations


def chart_teacher_indicator_snapshot(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else latest
    rows = [
        {"Indicator": "OHLC", "Value": f"O {latest['open']:.2f} / H {latest['high']:.2f} / L {latest['low']:.2f} / C {latest['close']:.2f}", "Interpretation": "Latest visible candle context."},
        {"Indicator": "EMA20", "Value": round(coerce_float(latest.get("ema20"), 0) or 0, 2), "Interpretation": "Short-term trend guide."},
        {"Indicator": "EMA50", "Value": round(coerce_float(latest.get("ema50"), 0) or 0, 2), "Interpretation": "Intermediate trend guide."},
        {"Indicator": "EMA200", "Value": round(coerce_float(latest.get("ema200"), 0) or 0, 2), "Interpretation": "Institutional long-term trend reference."},
        {"Indicator": "SMA200", "Value": round(coerce_float(latest.get("sma200"), 0) or 0, 2), "Interpretation": "Widely watched long-term average."},
        {"Indicator": "VWAP", "Value": round(coerce_float(latest.get("vwap"), 0) or 0, 2), "Interpretation": "Price acceptance benchmark for the visible chart."},
        {"Indicator": "ATR14", "Value": round(coerce_float(latest.get("atr14"), 0) or 0, 2), "Interpretation": "Current volatility and stop-distance context."},
        {"Indicator": "ADX14", "Value": round(coerce_float(latest.get("adx14"), 0) or 0, 2), "Interpretation": "Trend-strength proxy. Above 25 suggests stronger directional behavior."},
        {"Indicator": "RSI14", "Value": round(coerce_float(latest.get("rsi14"), 0) or 0, 2), "Interpretation": "Momentum context; overbought alone is not a sell signal."},
        {"Indicator": "MACD", "Value": round(coerce_float(latest.get("macd"), 0) or 0, 2), "Interpretation": "Momentum is improving" if coerce_float(latest.get("macd"), 0) >= coerce_float(previous.get("macd"), 0) else "Momentum is cooling."},
        {"Indicator": "MFI14", "Value": round(coerce_float(latest.get("mfi14"), 0) or 0, 2), "Interpretation": "Money-flow context using price and volume."},
        {"Indicator": "OBV", "Value": round(coerce_float(latest.get("obv"), 0) or 0, 0), "Interpretation": "On-balance volume accumulation/distribution proxy."},
        {"Indicator": "A/D Line", "Value": round(coerce_float(latest.get("ad_line"), 0) or 0, 0), "Interpretation": "Accumulation/distribution pressure proxy."},
    ]
    return pd.DataFrame(rows)


def render_tradingview_widget(symbol: str, timeframe: str, theme: str) -> None:
    interval_map = {
        "Monthly": "M",
        "Weekly": "W",
        "Daily": "D",
        "4 Hour": "240",
        "1 Hour": "60",
        "30 Minute": "30",
        "15 Minute": "15",
        "5 Minute": "5",
        "1 Minute": "1",
    }
    widget_id = f"tv_chart_{hashlib.md5((symbol + timeframe + theme).encode()).hexdigest()[:10]}"
    tv_theme = "dark" if theme == "Dark" else "light"
    interval = interval_map.get(timeframe, "D")
    html = f"""
    <div class="tradingview-widget-container" style="height:640px;width:100%;">
      <div id="{widget_id}" style="height:640px;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "NSE:{escape_svg_text(symbol)}",
        "interval": "{interval}",
        "timezone": "Asia/Kolkata",
        "theme": "{tv_theme}",
        "style": "1",
        "locale": "in",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "hide_side_toolbar": false,
        "withdateranges": true,
        "studies": ["Volume@tv-basicstudies", "RSI@tv-basicstudies", "MACD@tv-basicstudies"],
        "container_id": "{widget_id}"
      }});
      </script>
    </div>
    """
    components.html(html, height=660)


def render_chart_teacher_svg(
    history: pd.DataFrame,
    chart: dict[str, Any],
    annotations: list[dict[str, Any]],
    overlays: list[str],
    theme: str,
    symbol: str,
    timeframe: str,
) -> None:
    if history.empty:
        st.info("No chart candles available for visual rendering.")
        return

    visible = history.tail(180).copy().reset_index(drop=True)
    width = 1180
    height = 660
    pad_left = 64
    pad_right = 128
    pad_top = 42
    price_height = 430
    volume_top = pad_top + price_height + 42
    volume_height = 110
    chart_width = width - pad_left - pad_right
    candle_gap = chart_width / max(len(visible), 1)
    candle_width = max(3, min(12, candle_gap * 0.58))

    price_columns = ["high", "low"]
    for column in ["ema20", "ema50", "ema100", "ema190", "ema200", "sma200", "vwap", "bb_upper", "bb_lower"]:
        if column in visible.columns:
            price_columns.append(column)
    extra_prices: list[float] = []
    for annotation in annotations:
        for key in ["Low", "High"]:
            value = coerce_float(annotation.get(key), None)
            if value is not None:
                extra_prices.append(value)
    valid_price_lows: list[float] = []
    valid_price_highs: list[float] = []
    for column in price_columns:
        if column not in visible.columns:
            continue
        series = pd.to_numeric(visible[column], errors="coerce").dropna()
        if series.empty:
            continue
        valid_price_lows.append(float(series.min()))
        valid_price_highs.append(float(series.max()))
    if not valid_price_lows or not valid_price_highs:
        st.info("No valid price values are available for chart rendering.")
        return
    price_min = min(valid_price_lows)
    price_max = max(valid_price_highs)
    if extra_prices:
        price_min = min(price_min, min(extra_prices))
        price_max = max(price_max, max(extra_prices))
    price_span = max(price_max - price_min, 0.01)
    price_min -= price_span * 0.06
    price_max += price_span * 0.08
    price_span = max(price_max - price_min, 0.01)
    max_volume = max(float(visible["volume"].max()), 1)

    def x_pos(index: int) -> float:
        return pad_left + index * candle_gap + candle_gap / 2

    def y_pos(price: float) -> float:
        return pad_top + (price_max - price) / price_span * price_height

    bg = "#0f172a" if theme == "Dark" else "#ffffff"
    panel = "#111827" if theme == "Dark" else "#f8fafc"
    grid = "#334155" if theme == "Dark" else "#e2e8f0"
    text = "#e5e7eb" if theme == "Dark" else "#0f172a"
    muted = "#94a3b8" if theme == "Dark" else "#64748b"
    up_color = "#10b981"
    down_color = "#f43f5e"

    svg_parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="16" fill="{bg}"/>',
        f'<rect x="18" y="18" width="{width-36}" height="{height-36}" rx="14" fill="{panel}" stroke="{grid}"/>',
        f'<text x="{pad_left}" y="32" fill="{text}" font-size="18" font-family="Arial" font-weight="700">{escape_svg_text(symbol)} - {escape_svg_text(timeframe)} AI Visual Chart Teacher</text>',
    ]

    for step in range(6):
        price = price_min + (price_span / 5) * step
        y = y_pos(price)
        svg_parts.append(f'<line x1="{pad_left}" y1="{y:.2f}" x2="{width-pad_right}" y2="{y:.2f}" stroke="{grid}" stroke-width="1" opacity="0.55"/>')
        svg_parts.append(f'<text x="{width-pad_right+10}" y="{y+4:.2f}" fill="{muted}" font-size="11" font-family="Arial">{price:.2f}</text>')

    if "Supply/Demand" in overlays:
        for annotation in annotations:
            if annotation.get("Kind") != "zone":
                continue
            low = coerce_float(annotation.get("Low"), None)
            high = coerce_float(annotation.get("High"), None)
            if low is None or high is None:
                continue
            y_high = y_pos(high)
            y_low = y_pos(low)
            color = annotation.get("Color", "#64748b")
            svg_parts.append(
                f'<rect x="{pad_left}" y="{y_high:.2f}" width="{chart_width}" height="{max(y_low-y_high, 2):.2f}" fill="{color}" opacity="0.12" stroke="{color}" stroke-width="1" stroke-dasharray="6 5"/>'
            )
            svg_parts.append(f'<text x="{pad_left+8}" y="{y_high-5:.2f}" fill="{color}" font-size="11" font-family="Arial" font-weight="700">{escape_svg_text(annotation.get("Type"))}</text>')

    for index, candle in visible.iterrows():
        open_price = float(candle["open"])
        high_price = float(candle["high"])
        low_price = float(candle["low"])
        close_price = float(candle["close"])
        x = x_pos(index)
        color = up_color if close_price >= open_price else down_color
        y_open = y_pos(open_price)
        y_close = y_pos(close_price)
        y_high = y_pos(high_price)
        y_low = y_pos(low_price)
        body_y = min(y_open, y_close)
        body_height = max(abs(y_close - y_open), 2)
        volume_height_px = (float(candle.get("volume", 0)) / max_volume) * volume_height
        date_label = pd.to_datetime(candle["date"]).strftime("%Y-%m-%d %H:%M")
        svg_parts.append(f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" stroke="{color}" stroke-width="1.2"><title>{date_label} H {high_price:.2f} L {low_price:.2f}</title></line>')
        svg_parts.append(f'<rect x="{x-candle_width/2:.2f}" y="{body_y:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" rx="1.2" fill="{color}"><title>{date_label} O {open_price:.2f} C {close_price:.2f}</title></rect>')
        svg_parts.append(f'<rect x="{x-candle_width/2:.2f}" y="{volume_top + volume_height - volume_height_px:.2f}" width="{candle_width:.2f}" height="{volume_height_px:.2f}" fill="{color}" opacity="0.45"/>')

    def draw_line(column: str, color: str, label: str, dashed: bool = False) -> None:
        if column not in visible.columns:
            return
        points = []
        for index, value in enumerate(pd.to_numeric(visible[column], errors="coerce")):
            if pd.isna(value):
                continue
            points.append(f"{x_pos(index):.2f},{y_pos(float(value)):.2f}")
        if len(points) < 2:
            return
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        svg_parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.8"{dash}/>')
        last_value = coerce_float(visible[column].dropna().iloc[-1] if not visible[column].dropna().empty else None, None)
        if last_value is not None:
            svg_parts.append(f'<text x="{width-pad_right+10}" y="{y_pos(last_value)+4:.2f}" fill="{color}" font-size="11" font-family="Arial">{escape_svg_text(label)}</text>')

    overlay_lines = {
        "VWAP": ("vwap", "#0ea5e9", "VWAP", False),
        "EMA20": ("ema20", "#22c55e", "EMA20", False),
        "EMA50": ("ema50", "#f59e0b", "EMA50", False),
        "EMA100": ("ema100", "#a855f7", "EMA100", False),
        "EMA190": ("ema190", "#14b8a6", "EMA190", True),
        "EMA200": ("ema200", "#ef4444", "EMA200", False),
        "SMA200": ("sma200", "#64748b", "SMA200", True),
    }
    for overlay, args in overlay_lines.items():
        if overlay in overlays:
            draw_line(*args)
    if "Bollinger Bands" in overlays:
        draw_line("bb_upper", "#60a5fa", "BB+", True)
        draw_line("bb_lower", "#60a5fa", "BB-", True)

    if "Support/Resistance" in overlays or "Trading Plan" in overlays:
        for annotation in annotations:
            if annotation.get("Kind") == "zone":
                continue
            low = coerce_float(annotation.get("Low"), None)
            if low is None:
                continue
            color = annotation.get("Color", "#64748b")
            y = y_pos(low)
            svg_parts.append(f'<line x1="{pad_left}" y1="{y:.2f}" x2="{width-pad_right}" y2="{y:.2f}" stroke="{color}" stroke-width="1.5" stroke-dasharray="8 5"/>')
            svg_parts.append(f'<text x="{pad_left+8}" y="{y-6:.2f}" fill="{color}" font-size="11" font-family="Arial" font-weight="700">{escape_svg_text(annotation.get("Type"))}</text>')

    if "Annotations" in overlays:
        label_y = 72
        for number, annotation in enumerate(annotations[:7], start=1):
            color = annotation.get("Color", "#64748b")
            price = coerce_float(annotation.get("High"), coerce_float(annotation.get("Low"), None))
            y = y_pos(price) if price is not None else label_y
            x = width - pad_right + 18
            svg_parts.append(f'<circle cx="{x}" cy="{y:.2f}" r="10" fill="{color}"/>')
            svg_parts.append(f'<text x="{x-3}" y="{y+4:.2f}" fill="#ffffff" font-size="10" font-family="Arial" font-weight="700">{number}</text>')

    svg_parts.append(f'<text x="{pad_left}" y="{volume_top-12}" fill="{muted}" font-size="12" font-family="Arial">Volume</text>')
    svg_parts.append("</svg>")

    legend_items = []
    for number, annotation in enumerate(annotations[:7], start=1):
        legend_items.append(
            f'<div class="legend-row"><span style="background:{annotation.get("Color", "#64748b")}">{number}</span><b>{escape_svg_text(annotation.get("Type"))}</b><small>{escape_svg_text(annotation.get("Explanation"))}</small></div>'
        )

    html = f"""
    <div style="font-family:Arial, sans-serif;">
      <div style="border-radius:16px; overflow:hidden; border:1px solid {grid}; background:{bg};">
        {''.join(svg_parts)}
      </div>
      <style>
        .legend-grid {{
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
          gap:10px;
          margin-top:12px;
        }}
        .legend-row {{
          border:1px solid {grid};
          border-radius:10px;
          padding:10px;
          background:{panel};
          color:{text};
        }}
        .legend-row span {{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          width:22px;
          height:22px;
          border-radius:999px;
          color:white;
          font-size:12px;
          font-weight:700;
          margin-right:8px;
        }}
        .legend-row small {{
          display:block;
          color:{muted};
          line-height:1.4;
          margin-top:5px;
        }}
      </style>
      <div class="legend-grid">{''.join(legend_items)}</div>
    </div>
    """
    components.html(html, height=880)


def chart_teacher_live_panel(report: dict[str, Any], visible_history: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    chart = report.get("chart", {})
    visible = visible_history.copy()
    latest = visible.iloc[-1] if not visible.empty else pd.Series(dtype=object)
    latest_close = coerce_float(latest.get("close"), coerce_float(chart.get("current_price"), 0)) or 0
    ema20 = coerce_float(latest.get("ema20"), 0) or 0
    ema50 = coerce_float(latest.get("ema50"), 0) or 0
    rsi = coerce_float(latest.get("rsi14"), chart.get("rsi")) or 0
    adx = coerce_float(latest.get("adx14"), 0) or 0
    trend = "Bullish" if latest_close > ema20 > ema50 else "Neutral" if latest_close >= ema50 else "Bearish"
    control = "Buyers" if latest_close >= ema20 and rsi >= 50 else "Sellers" if latest_close < ema50 else "Balanced"
    risk = "Elevated" if (coerce_float(chart.get("false_breakout_risk"), 100) or 100) >= 60 else "Controlled"
    action = (
        "Wait for breakout plus volume and VWAP confirmation"
        if report.get("verdict", "").lower().find("watch") >= 0 or (coerce_float(chart.get("chart_quality_score"), 0) or 0) < 85
        else "Eligible for active watchlist; execute only after live confirmation"
    )
    rows = [
        {"Panel": "Visible Timeframe", "Reading": timeframe, "Professional Interpretation": "The analysis is regenerated whenever this timeframe or symbol changes."},
        {"Panel": "Current Trend", "Reading": trend, "Professional Interpretation": f"Close is {latest_close:.2f}; EMA20 is {ema20:.2f}; EMA50 is {ema50:.2f}."},
        {"Panel": "Buyer vs Seller Control", "Reading": control, "Professional Interpretation": "Control is inferred from price acceptance around moving averages, RSI, candle position, and volume context."},
        {"Panel": "Market Structure", "Reading": chart.get("chart_stage", "Unavailable"), "Professional Interpretation": chart.get("reason", "Structure evidence is still developing.")},
        {"Panel": "Pattern Quality", "Reading": chart.get("pattern_detected", "Unavailable"), "Professional Interpretation": "A pattern matters only when price, volume, and risk location agree."},
        {"Panel": "Institutional Activity", "Reading": chart.get("institutional_footprints", "Unavailable"), "Professional Interpretation": "Institutional footprints are inferred from higher lows, OBV/A-D behavior, repeated tests, and volume expansion."},
        {"Panel": "Volume Confirmation", "Reading": chart.get("volume_confirmation", "Unavailable"), "Professional Interpretation": f"ADX is {adx:.2f}; professionals prefer expansion on up moves and contraction on pullbacks."},
        {"Panel": "Current Risk", "Reading": risk, "Professional Interpretation": f"False breakout risk is {chart.get('false_breakout_risk', 'Unavailable')}/100."},
        {"Panel": "Recommended Action", "Reading": action, "Professional Interpretation": "This is a research workflow. Live execution still requires VWAP, ORB, liquidity, and market-regime confirmation."},
        {"Panel": "Confidence Level", "Reading": report.get("summary", {}).get("Confidence Level", "Unavailable"), "Professional Interpretation": "Confidence is probabilistic, never guaranteed."},
    ]
    return pd.DataFrame(rows)


def render_interactive_chart_teacher_page() -> None:
    st.subheader("AI Interactive Chart Reading & Visual Chart Teacher")
    st.caption("Module 20 workstation: interactive chart, visual annotations, institutional-style explanation, smart-money context, and a complete trading plan.")

    with st.sidebar:
        st.header("Visual Chart Teacher")
        symbol = st.text_input("Stock symbol or company name", value="RELIANCE", key="interactive_teacher_symbol")
        timeframe = st.selectbox(
            "Chart timeframe",
            ["Daily", "Weekly", "Monthly", "4 Hour", "1 Hour", "30 Minute", "15 Minute", "5 Minute", "1 Minute"],
            index=0,
            key="interactive_teacher_timeframe",
        )
        chart_mode = st.radio("Chart engine", ["AI Annotated Chart", "TradingView Widget", "Both"], index=0, key="interactive_teacher_mode")
        theme = st.radio("Theme", ["Dark", "Light"], index=0, horizontal=True, key="interactive_teacher_theme")
        lookback = st.slider("Visible candles", 60, 300, 160, 10, key="interactive_teacher_lookback")
        overlays = st.multiselect(
            "Overlay toggles",
            ["VWAP", "EMA20", "EMA50", "EMA100", "EMA190", "EMA200", "SMA200", "Bollinger Bands", "Support/Resistance", "Supply/Demand", "Trading Plan", "Annotations"],
            default=["VWAP", "EMA20", "EMA50", "EMA200", "Bollinger Bands", "Support/Resistance", "Supply/Demand", "Trading Plan", "Annotations"],
            key="interactive_teacher_overlays",
        )
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key="interactive_teacher_capital")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key="interactive_teacher_risk")
        if st.button("Refresh interactive chart teacher", type="primary", width="stretch"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            st.rerun()

    cleaned_symbol = symbol.strip().upper().replace(".NS", "")
    if not cleaned_symbol:
        st.info("Enter an NSE symbol such as RELIANCE, SBIN, BEL, TRENT, or CDSL.")
        return
    if " " in cleaned_symbol:
        st.warning("Use the NSE trading symbol for the most reliable chart data. Company-name lookup is limited by the current providers.")

    with st.spinner(f"Building interactive chart workstation for {cleaned_symbol}..."):
        visual_history = add_chart_teacher_indicators(fetch_chart_teacher_history(cleaned_symbol, timeframe))
        daily_history = fetch_ohlcv_history(cleaned_symbol, lookback_days=1200)
        report = build_professional_chart_report(cleaned_symbol, capital=capital, risk_pct=risk_pct, daily_history_override=daily_history)

    if visual_history.empty:
        st.info("No chart data is available for this timeframe. Try Daily or Weekly if intraday data is blocked by the provider.")
        return
    if not report:
        st.info("No professional report could be generated for this symbol.")
        return

    visible_history = visual_history.tail(lookback)
    chart = report.get("chart", {})
    annotations = build_chart_teacher_annotations(chart, visible_history)

    metric_a, metric_b, metric_c, metric_d, metric_e = st.columns(5)
    metric_a.metric("Current Price", chart.get("current_price", "Unavailable"))
    metric_b.metric("Final Rating", report.get("verdict", "Unavailable"))
    metric_c.metric("Chart Quality", int(coerce_float(chart.get("chart_quality_score"), 0) or 0))
    metric_d.metric("Trade Probability", report.get("summary", {}).get("Expected Probability", "Unavailable"))
    metric_e.metric("False Breakout Risk", chart.get("false_breakout_risk", "Unavailable"))

    chart_tab, panel_tab, report_tab, plan_tab, scores_tab = st.tabs(
        ["Visual Chart Teacher", "Live Analysis Panel", "Professional Report", "Trading Plan", "Indicators & Scores"]
    )

    with chart_tab:
        if chart_mode in {"AI Annotated Chart", "Both"}:
            render_chart_teacher_svg(visible_history, chart, annotations, overlays, theme, cleaned_symbol, timeframe)
        if chart_mode in {"TradingView Widget", "Both"}:
            st.markdown("**TradingView Interactive Chart**")
            st.caption("Use this for zoom, pan, crosshair, drawing tools, and native TradingView indicators. The AI explanation below remains based on the app's data and scoring engine.")
            render_tradingview_widget(cleaned_symbol, timeframe, theme)
        st.markdown("**Educational Annotation Evidence**")
        display_dataframe(pd.DataFrame([{key: value for key, value in item.items() if key not in {"Low", "High", "Kind", "Color"}} for item in annotations]), height=300)

    with panel_tab:
        display_dataframe(chart_teacher_live_panel(report, visible_history, timeframe), height=430)
        st.info(report.get("summary", {}).get("Legendary Analyst Explanation", "Professional chart reading requires price, volume, structure, and risk to agree."))

    with report_tab:
        render_professional_report_tabs(report, height=360)

    with plan_tab:
        display_dataframe(report.get("plan", pd.DataFrame()), height=430)
        st.markdown("**Execution Confirmation Checklist**")
        checklist = pd.DataFrame(
            [
                {"Check": "VWAP / price acceptance", "Required Evidence": "Price holds above VWAP or key retest zone after breakout."},
                {"Check": "Opening range / intraday trigger", "Required Evidence": "Break above ORB or pullback holds with reduced selling pressure."},
                {"Check": "Relative volume", "Required Evidence": "Volume expands on the move, preferably RVOL above 1.5 to 2."},
                {"Check": "Risk control", "Required Evidence": "Entry, stop, and target produce acceptable reward-to-risk before trade."},
                {"Check": "Invalidation", "Required Evidence": "Close below stop/retest zone invalidates the setup."},
            ]
        )
        display_dataframe(checklist, height=260)

    with scores_tab:
        left, right = st.columns(2)
        with left:
            st.markdown("**Indicator Snapshot**")
            display_dataframe(chart_teacher_indicator_snapshot(visible_history), height=520)
        with right:
            st.markdown("**AI Scores**")
            display_dataframe(report.get("scores", pd.DataFrame()), height=520)
        st.download_button(
            "Download visual chart teacher annotations CSV",
            pd.DataFrame([{key: value for key, value in item.items() if key not in {"Low", "High", "Kind", "Color"}} for item in annotations]).to_csv(index=False).encode("utf-8"),
            file_name=f"{cleaned_symbol}_visual_chart_teacher_annotations.csv",
            mime="text/csv",
            width="stretch",
        )


CUSTOM_CHART_TIMEFRAMES = ["Monthly", "Weekly", "Daily", "4 Hour", "1 Hour", "30 Minute", "15 Minute", "5 Minute", "1 Minute"]
CUSTOM_CHART_PROVIDER_PRIORITY = [
    ("Zerodha Kite Connect API", "Future connector - not configured in this package"),
    ("NSE Bhavcopy", "Future EOD connector - not enabled after SQL rollback"),
    ("Yahoo Finance", "Active fallback for OHLCV"),
    ("Uploaded CSV", "Active manual fallback"),
    ("Polygon API", "Future connector"),
    ("Alpha Vantage", "Future connector"),
]
CUSTOM_CHART_SYMBOL_ALIASES = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "INDIAVIX": "^INDIAVIX",
}


def normalize_custom_chart_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace(".NS", "")
    return CUSTOM_CHART_SYMBOL_ALIASES.get(cleaned, cleaned)


def load_uploaded_ohlcv_csv(uploaded_file: Any) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    try:
        raw = pd.read_csv(uploaded_file)
    except Exception:
        return pd.DataFrame()
    raw.columns = [re.sub(r"[^a-z0-9]+", "_", str(column).lower()).strip("_") for column in raw.columns]
    rename_map: dict[str, str] = {}
    for target, candidates in {
        "date": ["date", "datetime", "timestamp", "time"],
        "open": ["open", "o"],
        "high": ["high", "h"],
        "low": ["low", "l"],
        "close": ["close", "adj_close", "c"],
        "volume": ["volume", "vol", "v"],
    }.items():
        for candidate in candidates:
            if candidate in raw.columns:
                rename_map[candidate] = target
                break
    return normalize_chart_history(raw.rename(columns=rename_map))


def load_custom_chart_engine_history(symbol: str, timeframe: str, provider: str, uploaded_file: Any) -> tuple[pd.DataFrame, str]:
    if provider == "Uploaded CSV":
        uploaded = load_uploaded_ohlcv_csv(uploaded_file)
        return uploaded, "Uploaded CSV" if not uploaded.empty else "Uploaded CSV unavailable or invalid"

    if provider == "Auto Provider Fallback" and uploaded_file is not None:
        uploaded = load_uploaded_ohlcv_csv(uploaded_file)
        if not uploaded.empty:
            return uploaded, "Uploaded CSV"

    # Zerodha/NSE bhavcopy placeholders intentionally fall through to Yahoo until credentials/connectors exist.
    history = fetch_chart_teacher_history(symbol, timeframe)
    if not history.empty:
        return history, "Yahoo Finance"
    uploaded = load_uploaded_ohlcv_csv(uploaded_file)
    if not uploaded.empty:
        return uploaded, "Uploaded CSV fallback"
    return pd.DataFrame(), "No provider returned usable OHLCV"


def add_custom_chart_engine_indicators(history: pd.DataFrame) -> pd.DataFrame:
    working = add_chart_teacher_indicators(history)
    if working.empty:
        return working

    high = pd.to_numeric(working["high"], errors="coerce")
    low = pd.to_numeric(working["low"], errors="coerce")
    close = pd.to_numeric(working["close"], errors="coerce")
    volume = pd.to_numeric(working["volume"], errors="coerce").fillna(0)
    previous_close = close.shift(1)
    typical = (high + low + close) / 3
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14, min_periods=3).mean()

    for period in [20, 50, 100, 190, 200]:
        working[f"sma{period}"] = close.rolling(period, min_periods=min(20, period)).mean()
        working[f"avg_volume_{period}"] = volume.rolling(period, min_periods=min(20, period)).mean()

    working["rvol"] = volume / working["avg_volume_20"].replace(0, pd.NA)
    working["macd_histogram"] = working["macd"] - working["macd_signal"]
    working["keltner_mid"] = close.ewm(span=20, adjust=False).mean()
    working["keltner_upper"] = working["keltner_mid"] + atr14 * 1.5
    working["keltner_lower"] = working["keltner_mid"] - atr14 * 1.5
    working["pivot_point"] = (high.shift(1) + low.shift(1) + close.shift(1)) / 3
    working["pivot_r1"] = 2 * working["pivot_point"] - low.shift(1)
    working["pivot_s1"] = 2 * working["pivot_point"] - high.shift(1)
    working["pivot_r2"] = working["pivot_point"] + (high.shift(1) - low.shift(1))
    working["pivot_s2"] = working["pivot_point"] - (high.shift(1) - low.shift(1))

    multiplier = 3.0
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr14
    lower_band = hl2 - multiplier * atr14
    direction = pd.Series(1, index=working.index, dtype="int64")
    supertrend = pd.Series(index=working.index, dtype="float64")
    for index in range(len(working)):
        if index == 0 or pd.isna(upper_band.iloc[index - 1]) or pd.isna(lower_band.iloc[index - 1]):
            direction.iloc[index] = 1
        elif close.iloc[index] > upper_band.iloc[index - 1]:
            direction.iloc[index] = 1
        elif close.iloc[index] < lower_band.iloc[index - 1]:
            direction.iloc[index] = -1
        else:
            direction.iloc[index] = direction.iloc[index - 1]
        supertrend.iloc[index] = lower_band.iloc[index] if direction.iloc[index] == 1 else upper_band.iloc[index]
    working["supertrend"] = supertrend
    working["supertrend_direction"] = direction
    return working


def custom_volume_profile(history: pd.DataFrame, bins: int = 16) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    close = pd.to_numeric(history["close"], errors="coerce")
    volume = pd.to_numeric(history["volume"], errors="coerce").fillna(0)
    valid = pd.DataFrame({"close": close, "volume": volume}).dropna()
    if valid.empty or valid["close"].nunique() < 2:
        return pd.DataFrame()
    try:
        valid["price_bin"] = pd.cut(valid["close"], bins=bins)
    except Exception:
        return pd.DataFrame()
    profile = valid.groupby("price_bin", observed=False)["volume"].sum().reset_index()
    if profile.empty:
        return pd.DataFrame()
    total_volume = float(profile["volume"].sum()) or 1.0
    profile["Low"] = profile["price_bin"].apply(lambda interval: round(float(interval.left), 2))
    profile["High"] = profile["price_bin"].apply(lambda interval: round(float(interval.right), 2))
    profile["Volume"] = profile["volume"].round(0)
    profile["Volume Share %"] = (profile["volume"] / total_volume * 100).round(2)
    return profile[["Low", "High", "Volume", "Volume Share %"]].sort_values("Volume", ascending=False)


def custom_chart_feature_events(history: pd.DataFrame, chart: dict[str, Any]) -> pd.DataFrame:
    if history.empty or len(history) < 12:
        return pd.DataFrame()
    working = history.copy()
    latest = working.iloc[-1]
    previous = working.iloc[-2]
    close = pd.to_numeric(working["close"], errors="coerce")
    high = pd.to_numeric(working["high"], errors="coerce")
    low = pd.to_numeric(working["low"], errors="coerce")
    open_price = pd.to_numeric(working["open"], errors="coerce")
    volume = pd.to_numeric(working["volume"], errors="coerce").fillna(0)
    down_volume = volume.where(close < close.shift(1), 0)
    latest_volume = coerce_float(latest.get("volume"), 0) or 0
    highest_down_volume = coerce_float(down_volume.shift(1).rolling(10).max().iloc[-1], 0) or 0
    pocket_pivot = bool(latest_volume > highest_down_volume and close.iloc[-1] > close.shift(1).iloc[-1])
    inside_day = bool(high.iloc[-1] <= high.iloc[-2] and low.iloc[-1] >= low.iloc[-2])
    nr7 = bool((high.iloc[-1] - low.iloc[-1]) <= (high - low).tail(7).min())
    gap_up = bool(open_price.iloc[-1] > high.iloc[-2])
    gap_down = bool(open_price.iloc[-1] < low.iloc[-2])
    high_volume = bool((coerce_float(latest.get("rvol"), 0) or 0) >= 1.8)
    close_position = (close.iloc[-1] - low.iloc[-1]) / max(high.iloc[-1] - low.iloc[-1], 0.01) * 100
    bullish_candle = bool(close.iloc[-1] > open_price.iloc[-1] and close_position >= 65)
    distribution_candle = bool(close.iloc[-1] < open_price.iloc[-1] and high_volume and close_position <= 40)
    false_breakout_zone = bool((coerce_float(chart.get("false_breakout_risk"), 0) or 0) >= 65)
    event_date = latest.get("date")
    price = coerce_float(latest.get("high"), coerce_float(chart.get("current_price"), None))
    rows: list[dict[str, Any]] = []

    def add_event(name: str, active: bool, color: str, confidence: int, interpretation: str, implication: str) -> None:
        if not active:
            return
        rows.append(
            {
                "Event": name,
                "Date": event_date,
                "Price": price,
                "Color": color,
                "Evidence": chart.get("reason", "Visible price/volume structure"),
                "Professional Interpretation": interpretation,
                "Potential Implication": implication,
                "Confidence Level": confidence,
            }
        )

    add_event(
        "Pocket Pivot Candle",
        pocket_pivot,
        "#10b981",
        78,
        "Volume exceeded the highest down-volume of the previous 10 sessions while price closed up.",
        "Potential institutional accumulation near a constructive price location.",
    )
    add_event(
        "High Volume Candle",
        high_volume,
        "#2563eb",
        70,
        "Relative volume expanded versus the 20-period average.",
        "Participation is rising; confirm whether it supports breakout or distribution.",
    )
    add_event(
        "Bullish Control Candle",
        bullish_candle,
        "#16a34a",
        72,
        "Price closed in the upper part of the candle body/range.",
        "Buyers controlled the latest visible candle.",
    )
    add_event(
        "Distribution Candle",
        distribution_candle,
        "#ef4444",
        74,
        "High volume with weak close suggests selling pressure.",
        "Avoid aggressive entries until supply is absorbed.",
    )
    add_event("Inside Day", inside_day, "#f59e0b", 66, "Range compressed inside the prior candle.", "Compression can precede expansion; wait for direction.")
    add_event("NR7", nr7, "#a855f7", 65, "Latest candle has the narrowest range in seven periods.", "Volatility is compressed; prepare for range expansion.")
    add_event("Gap Up", gap_up, "#22c55e", 62, "Opening price was above the prior high.", "Gap strength needs acceptance, not immediate chasing.")
    add_event("Gap Down", gap_down, "#f43f5e", 62, "Opening price was below the prior low.", "Risk is elevated unless price reclaims the gap zone.")
    add_event(
        "False Breakout Risk Zone",
        false_breakout_zone,
        "#dc2626",
        int(coerce_float(chart.get("false_breakout_risk"), 65) or 65),
        "False breakout risk is elevated from the chart model.",
        "Demand confirmation is required before treating resistance as conquered.",
    )
    return pd.DataFrame(rows)


def build_custom_ai_plotly_chart(
    history: pd.DataFrame,
    chart: dict[str, Any],
    annotations: list[dict[str, Any]],
    feature_events: pd.DataFrame,
    overlays: list[str],
    theme: str,
    symbol: str,
    timeframe: str,
) -> Any:
    if go is None or make_subplots is None:
        return None
    visible = history.copy().dropna(subset=["date", "open", "high", "low", "close"])
    if visible.empty:
        return None

    dark = theme == "Dark"
    template = "plotly_dark" if dark else "plotly_white"
    grid_color = "#334155" if dark else "#e2e8f0"
    up_color = "#10b981"
    down_color = "#f43f5e"
    volume_colors = [up_color if close >= open_ else down_color for open_, close in zip(visible["open"], visible["close"])]

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.58, 0.16, 0.13, 0.13],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
    )
    fig.add_trace(
        go.Candlestick(
            x=visible["date"],
            open=visible["open"],
            high=visible["high"],
            low=visible["low"],
            close=visible["close"],
            name="OHLC",
            increasing_line_color=up_color,
            decreasing_line_color=down_color,
            increasing_fillcolor=up_color,
            decreasing_fillcolor=down_color,
            hoverlabel={"namelength": -1},
        ),
        row=1,
        col=1,
    )

    def add_line(column: str, name: str, color: str, width: float = 1.5, dash: str | None = None, row: int = 1) -> None:
        if column not in visible.columns:
            return
        series = pd.to_numeric(visible[column], errors="coerce")
        if series.dropna().empty:
            return
        fig.add_trace(
            go.Scatter(
                x=visible["date"],
                y=series,
                mode="lines",
                line={"color": color, "width": width, "dash": dash or "solid"},
                name=name,
            ),
            row=row,
            col=1,
        )

    line_specs = {
        "VWAP": ("vwap", "VWAP", "#0ea5e9", 1.6, "solid"),
        "EMA20": ("ema20", "EMA20", "#22c55e", 1.5, "solid"),
        "EMA50": ("ema50", "EMA50", "#f59e0b", 1.5, "solid"),
        "EMA100": ("ema100", "EMA100", "#a855f7", 1.4, "solid"),
        "EMA190": ("ema190", "EMA190", "#14b8a6", 1.3, "dash"),
        "EMA200": ("ema200", "EMA200", "#ef4444", 1.7, "solid"),
        "SMA20": ("sma20", "SMA20", "#84cc16", 1.2, "dot"),
        "SMA50": ("sma50", "SMA50", "#f97316", 1.2, "dot"),
        "SMA100": ("sma100", "SMA100", "#8b5cf6", 1.2, "dot"),
        "SMA190": ("sma190", "SMA190", "#06b6d4", 1.2, "dash"),
        "SMA200": ("sma200", "SMA200", "#64748b", 1.5, "dash"),
        "SuperTrend": ("supertrend", "SuperTrend", "#22c55e", 1.5, "dash"),
    }
    for overlay, args in line_specs.items():
        if overlay in overlays:
            add_line(*args)

    if "Bollinger Bands" in overlays:
        add_line("bb_upper", "BB Upper", "#60a5fa", 1.1, "dot")
        add_line("bb_lower", "BB Lower", "#60a5fa", 1.1, "dot")
    if "Keltner Channel" in overlays:
        add_line("keltner_upper", "Keltner Upper", "#facc15", 1.1, "dot")
        add_line("keltner_lower", "Keltner Lower", "#facc15", 1.1, "dot")

    if "Pivot Points" in overlays:
        latest = visible.iloc[-1]
        for column, label, color in [
            ("pivot_point", "Pivot", "#64748b"),
            ("pivot_r1", "R1", "#ef4444"),
            ("pivot_r2", "R2", "#b91c1c"),
            ("pivot_s1", "S1", "#10b981"),
            ("pivot_s2", "S2", "#047857"),
        ]:
            value = coerce_float(latest.get(column), None)
            if value is not None:
                fig.add_hline(y=value, line_color=color, line_dash="dot", annotation_text=label, annotation_position="right", row=1, col=1)

    if "AI Overlays" in overlays:
        for annotation in annotations:
            low = coerce_float(annotation.get("Low"), None)
            high = coerce_float(annotation.get("High"), None)
            color = annotation.get("Color", "#64748b")
            kind = annotation.get("Kind")
            label = str(annotation.get("Type", "AI Overlay"))
            if low is None or high is None:
                continue
            if kind == "zone" and low != high:
                fig.add_hrect(y0=low, y1=high, fillcolor=color, opacity=0.12, line_width=1, line_dash="dash", row=1, col=1)
                fig.add_annotation(x=visible["date"].iloc[-1], y=high, text=label, showarrow=False, font={"color": color, "size": 11}, row=1, col=1)
            else:
                fig.add_hline(y=low, line_color=color, line_dash="dash", annotation_text=label, annotation_position="right", row=1, col=1)

    if "Volume Profile" in overlays:
        profile = custom_volume_profile(visible)
        if not profile.empty:
            top_profile = profile.head(3)
            for _, row_profile in top_profile.iterrows():
                fig.add_hrect(
                    y0=row_profile["Low"],
                    y1=row_profile["High"],
                    fillcolor="#94a3b8",
                    opacity=min(0.18, max(0.05, float(row_profile["Volume Share %"]) / 100)),
                    line_width=0,
                    row=1,
                    col=1,
                )

    if "AI Annotations" in overlays and not feature_events.empty:
        fig.add_trace(
            go.Scatter(
                x=feature_events["Date"],
                y=feature_events["Price"],
                mode="markers+text",
                marker={
                    "size": 12,
                    "color": feature_events["Color"],
                    "symbol": "triangle-up",
                    "line": {"color": "#ffffff", "width": 1},
                },
                text=feature_events["Event"],
                textposition="top center",
                customdata=feature_events[["Professional Interpretation", "Potential Implication", "Confidence Level"]],
                hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>%{customdata[1]}<br>Confidence: %{customdata[2]}<extra></extra>",
                name="AI Teaching Events",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Bar(x=visible["date"], y=visible["volume"], marker_color=volume_colors, name="Volume", opacity=0.72),
        row=2,
        col=1,
    )
    if "Average Volume" in overlays:
        add_line("avg_volume_20", "Average Volume 20", "#eab308", 1.3, "dash", row=2)
    add_line("rsi14", "RSI14", "#a855f7", 1.4, "solid", row=3)
    fig.add_hline(y=70, line_color="#ef4444", line_dash="dot", row=3, col=1)
    fig.add_hline(y=30, line_color="#22c55e", line_dash="dot", row=3, col=1)
    add_line("macd", "MACD", "#0ea5e9", 1.4, "solid", row=4)
    add_line("macd_signal", "Signal", "#f59e0b", 1.2, "solid", row=4)
    fig.add_trace(
        go.Bar(x=visible["date"], y=visible.get("macd_histogram", pd.Series(0, index=visible.index)), marker_color="#64748b", name="MACD Histogram", opacity=0.45),
        row=4,
        col=1,
    )

    fig.update_layout(
        title=f"{symbol} Custom AI Chart Engine - {timeframe}",
        template=template,
        height=920,
        hovermode="x unified",
        dragmode="pan",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        margin={"l": 20, "r": 20, "t": 72, "b": 30},
        xaxis_rangeslider_visible=False,
    )
    for axis in ["xaxis", "xaxis2", "xaxis3", "xaxis4", "yaxis", "yaxis2", "yaxis3", "yaxis4"]:
        fig.update_layout({axis: {"gridcolor": grid_color}})
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    return fig


def custom_chart_engine_score_panel(report: dict[str, Any], history: pd.DataFrame, feature_events: pd.DataFrame, data_source: str) -> pd.DataFrame:
    chart = report.get("chart", {})
    latest = history.iloc[-1] if not history.empty else pd.Series(dtype="object")
    rows = [
        {"Panel": "Data Source", "Reading": data_source, "Professional Interpretation": "The engine falls back through configured providers and never depends on TradingView."},
        {"Panel": "Current Trend", "Reading": latest.get("trend_status", "Derived from EMAs"), "Professional Interpretation": "Trend is judged from price acceptance relative to EMA20/EMA50/EMA200 and structure."},
        {"Panel": "Trend Stage", "Reading": chart.get("chart_stage", "Unavailable"), "Professional Interpretation": "Stage reading connects the current chart to accumulation, markup, distribution, or markdown behavior."},
        {"Panel": "Market Structure", "Reading": chart.get("pattern_detected", "Unavailable"), "Professional Interpretation": "Patterns are useful only when price, volume, and risk location agree."},
        {"Panel": "Buyer vs Seller Control", "Reading": "Buyers" if (coerce_float(latest.get("rsi14"), 50) or 50) >= 55 and (coerce_float(latest.get("rvol"), 0) or 0) >= 1 else "Balanced/unclear", "Professional Interpretation": "Control is inferred from close location, RSI, RVOL, OBV, and A/D line behavior."},
        {"Panel": "Volume Analysis", "Reading": chart.get("volume_confirmation", "Unavailable"), "Professional Interpretation": f"Latest RVOL: {coerce_float(latest.get('rvol'), 0) or 0:.2f}. Volume must confirm price movement."},
        {"Panel": "Institutional Activity", "Reading": chart.get("institutional_footprints", "Unavailable"), "Professional Interpretation": "Proxy uses delivery, OBV, A/D line, repeated tests, and volume expansion. True order flow requires a live feed."},
        {"Panel": "Pattern Quality", "Reading": chart.get("pattern_reliability_score", "Unavailable"), "Professional Interpretation": "Higher pattern score means the visible setup has more supporting evidence."},
        {"Panel": "False Breakout Risk", "Reading": chart.get("false_breakout_risk", "Unavailable"), "Professional Interpretation": "High false-breakout risk means wait for acceptance above resistance or a clean retest."},
        {"Panel": "Teaching Events", "Reading": len(feature_events), "Professional Interpretation": "Highlighted candles teach what professionals are noticing on the chart."},
    ]
    return pd.DataFrame(rows)


def render_custom_ai_chart_engine_page() -> None:
    st.subheader("Custom AI Chart Engine")
    st.caption("No TradingView dependency. The app loads OHLCV, calculates indicators internally, renders Plotly candlesticks, draws AI overlays, and syncs the chart with IQ-5000 analysis.")

    if go is None or make_subplots is None:
        st.error("Plotly is not installed. Install package requirements or redeploy with the updated requirements.txt.")
        return

    with st.sidebar:
        st.header("Custom Chart Engine")
        raw_symbol = st.text_input("Symbol / index", value="RELIANCE", key="custom_chart_symbol")
        timeframe = st.selectbox("Timeframe", CUSTOM_CHART_TIMEFRAMES, index=2, key="custom_chart_timeframe")
        provider = st.selectbox("Data provider", ["Auto Provider Fallback", "Yahoo Finance", "Uploaded CSV", "Zerodha Kite Placeholder", "NSE Bhavcopy Placeholder"], key="custom_chart_provider")
        uploaded_file = st.file_uploader("Optional OHLCV CSV", type=["csv"], key="custom_chart_csv")
        theme = st.radio("Theme", ["Dark", "Light"], index=0, horizontal=True, key="custom_chart_theme")
        visible_candles = st.slider("Visible candles", 60, 500, 220, 20, key="custom_chart_visible")
        overlays = st.multiselect(
            "Chart overlays",
            [
                "VWAP",
                "EMA20",
                "EMA50",
                "EMA100",
                "EMA190",
                "EMA200",
                "SMA20",
                "SMA50",
                "SMA100",
                "SMA190",
                "SMA200",
                "Bollinger Bands",
                "Keltner Channel",
                "SuperTrend",
                "Pivot Points",
                "Average Volume",
                "Volume Profile",
                "AI Overlays",
                "AI Annotations",
            ],
            default=["VWAP", "EMA20", "EMA50", "EMA200", "Bollinger Bands", "SuperTrend", "Volume Profile", "AI Overlays", "AI Annotations", "Average Volume"],
            key="custom_chart_overlays",
        )
        replay_mode = st.toggle("Replay mode: hide future candles", value=False, key="custom_chart_replay_mode")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key="custom_chart_capital")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key="custom_chart_risk")
        if st.button("Refresh custom chart engine", type="primary", width="stretch"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            fetch_ticker_info.clear()
            st.rerun()

    symbol = normalize_custom_chart_symbol(raw_symbol)
    if not symbol:
        st.info("Enter an NSE symbol or index alias such as RELIANCE, SBIN, NIFTY, BANKNIFTY, or upload a CSV.")
        return

    with st.expander("Data Provider Priority", expanded=False):
        display_dataframe(pd.DataFrame(CUSTOM_CHART_PROVIDER_PRIORITY, columns=["Priority Source", "Status"]))

    raw_history, data_source = load_custom_chart_engine_history(symbol, timeframe, provider, uploaded_file)
    history = add_custom_chart_engine_indicators(raw_history)
    if history.empty:
        st.info(f"No usable OHLCV data found. Provider status: {data_source}. Try Daily timeframe or upload a CSV with date, open, high, low, close, volume columns.")
        return

    replay_future = pd.DataFrame()
    replay_selected_date = None
    if replay_mode:
        dates = pd.to_datetime(history["date"], errors="coerce").dropna().sort_values()
        if len(dates) < 80:
            st.warning("Replay needs more historical candles. Disable replay or use a longer timeframe/history source.")
        else:
            min_date = dates.iloc[min(40, len(dates) - 1)].date()
            max_date = dates.iloc[max(0, len(dates) - 21)].date()
            default_date = dates.iloc[max(0, len(dates) - 60)].date()
            replay_selected_date = st.date_input("Replay cutoff date", value=default_date, min_value=min_date, max_value=max_date, key="custom_chart_replay_date")
            past, future, selected_ts = prepare_replay_history(history, replay_selected_date)
            if not past.empty:
                history = add_custom_chart_engine_indicators(past)
                replay_future = future
                st.caption(f"Replay locked to data available up to {selected_ts.date() if selected_ts is not None else replay_selected_date}. Future candles are hidden from the chart and analysis.")

    analysis_history = history.tail(max(visible_candles, 220)).copy()
    visible_history = history.tail(visible_candles).copy()
    with st.spinner("Calculating custom indicators, AI overlays, and institutional analysis..."):
        report = build_professional_chart_report(symbol, capital=capital, risk_pct=risk_pct, daily_history_override=analysis_history, replay_mode=replay_mode)
    if not report:
        st.info("The chart rendered, but the professional report could not be generated.")
        report = {
            "chart": score_ai_chart_reading_candidate(pd.Series({"nsecode": symbol, "name": symbol}), history_override=analysis_history),
            "summary": {},
            "plan": pd.DataFrame(),
            "scores": pd.DataFrame(),
            "timeframes": pd.DataFrame(),
            "verdict": "Research only",
        }

    chart = report.get("chart", {})
    annotations = build_chart_teacher_annotations(chart, visible_history)
    feature_events = custom_chart_feature_events(visible_history, chart)
    fig = build_custom_ai_plotly_chart(visible_history, chart, annotations, feature_events, overlays, theme, symbol, timeframe)

    metric_a, metric_b, metric_c, metric_d, metric_e = st.columns(5)
    metric_a.metric("Data Source", data_source)
    metric_b.metric("Current Price", chart.get("current_price", "Unavailable"))
    metric_c.metric("Chart Quality", int(coerce_float(chart.get("chart_quality_score"), 0) or 0))
    metric_d.metric("Trade Probability", report.get("summary", {}).get("Expected Probability", "Unavailable"))
    metric_e.metric("False Breakout Risk", chart.get("false_breakout_risk", "Unavailable"))

    chart_tab, analysis_tab, plan_tab, replay_tab, data_tab = st.tabs(
        ["AI Chart", "Live AI Analysis", "Trading Plan", "Replay / Teacher", "Data & Indicators"]
    )

    with chart_tab:
        if fig is None:
            st.info("Plotly chart could not be created from the current data.")
        else:
            config = {
                "displaylogo": False,
                "scrollZoom": True,
                "responsive": True,
                "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
                "toImageButtonOptions": {
                    "format": "png",
                    "filename": f"{symbol}_{timeframe}_custom_ai_chart",
                    "height": 1200,
                    "width": 1800,
                    "scale": 2,
                },
            }
            st.plotly_chart(fig, width="stretch", config=config)
            html_bytes = fig.to_html(include_plotlyjs="cdn", full_html=True).encode("utf-8")
            col_a, col_b = st.columns(2)
            col_a.download_button("Export interactive chart HTML", html_bytes, file_name=f"{symbol}_custom_ai_chart.html", mime="text/html", width="stretch")
            try:
                pdf_bytes = fig.to_image(format="pdf")
                col_b.download_button("Export chart PDF", pdf_bytes, file_name=f"{symbol}_custom_ai_chart.pdf", mime="application/pdf", width="stretch")
            except Exception:
                col_b.caption("PDF export requires Kaleido. PNG export is available from the Plotly toolbar.")

    with analysis_tab:
        display_dataframe(custom_chart_engine_score_panel(report, visible_history, feature_events, data_source), height=430)
        st.markdown("**Professional Report**")
        render_professional_report_tabs(report, height=330)

    with plan_tab:
        display_dataframe(report.get("plan", pd.DataFrame()), height=420)
        st.caption("This is research and planning output. Final execution still requires live confirmation, liquidity, and risk discipline.")

    with replay_tab:
        st.markdown("**AI Visual Teacher Events**")
        if feature_events.empty:
            st.info("No special teaching candle was detected on the latest visible candle.")
        else:
            display_dataframe(feature_events.drop(columns=["Color"], errors="ignore"), height=360)
        if replay_mode and not replay_future.empty:
            st.markdown("**Future Outcome Check**")
            outcome = evaluate_chart_replay_outcome(replay_future, chart)
            display_dataframe(outcome.get("outcomes", pd.DataFrame()), height=260)
            display_dataframe(outcome.get("summary", pd.DataFrame()), height=300)
        elif replay_mode:
            st.info("No future candles are available after the selected replay date.")

    with data_tab:
        left, right = st.columns(2)
        with left:
            st.markdown("**Indicator Snapshot**")
            display_dataframe(chart_teacher_indicator_snapshot(visible_history), height=520)
        with right:
            st.markdown("**Volume Profile**")
            display_dataframe(custom_volume_profile(visible_history), height=520)
        with st.expander("Raw visible OHLCV + indicators"):
            display_dataframe(visible_history.tail(250), height=520)


ADVANCED_IQ_MODULES: dict[int, str] = {
    23: "M23 - AI Order Flow Engine",
    24: "M24 - AI Institutional Portfolio Tracker",
    25: "M25 - AI Global Correlation Engine",
    26: "M26 - AI Sector Rotation Engine",
    27: "M27 - AI Capital Rotation Detector",
    28: "M28 - AI Relative Performance Matrix",
    29: "M29 - AI Market DNA Engine",
    30: "M30 - AI Trade Coach",
    31: "M31 - AI Learning Academy",
    32: "M32 - AI Portfolio Manager",
    33: "M33 - AI Trade Journal",
    34: "M34 - AI Psychology Engine",
    35: "M35 - AI Scenario Simulator",
    36: "M36 - AI Replay Simulator",
    37: "M37 - AI Research Report Generator",
    38: "M38 - AI Live Market Radar",
    39: "M39 - AI Opportunity Ranking",
    40: "M40 - AI Master Brain",
}
ADVANCED_IQ_MODULE_LOOKUP = {label: module for module, label in ADVANCED_IQ_MODULES.items()}
ADVANCED_DEFAULT_WATCHLIST = "RELIANCE, SBIN, HDFCBANK, ICICIBANK, BEL, HAL, LT, TRENT, CDSL, TCS, INFY, WABAG"
ADVANCED_AUTO_SCAN_SOURCES: dict[str, str] = {
    "AI Early Breakout Universe": AI_EARLY_BREAKOUT_CLAUSE,
    "AI Chart Reading Universe": AI_CHART_READING_CLAUSE,
    "AI Overnight Opportunity Universe": AI_OVERNIGHT_OPPORTUNITY_CLAUSE,
    "Institutional Setup Universe": INSTITUTIONAL_SETUP_CLAUSE,
    "Breakout Probability Universe": BREAKOUT_PROBABILITY_CLAUSE,
    "200 EMA/SMA Launch Pad Universe": LAUNCH_PAD_200_CLAUSE,
}
ADVANCED_SECTOR_BASKETS: dict[str, list[str]] = {
    "Auto": ["M&M", "TATAMOTORS", "MARUTI"],
    "Banks": ["HDFCBANK", "ICICIBANK", "SBIN"],
    "IT": ["TCS", "INFY", "HCLTECH"],
    "PSU": ["SBIN", "BHEL", "NTPC"],
    "Capital Goods": ["LT", "ABB", "SIEMENS"],
    "Power": ["NTPC", "POWERGRID", "TATAPOWER"],
    "Pharma": ["SUNPHARMA", "CIPLA", "DIVISLAB"],
    "Realty": ["DLF", "LODHA", "OBEROIRLTY"],
    "Defence": ["HAL", "BEL", "BDL"],
    "Railways": ["IRFC", "RVNL", "RAILTEL"],
    "Chemicals": ["PIDILITIND", "SRF", "AARTIIND"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "Energy": ["RELIANCE", "ONGC", "COALINDIA"],
}
GLOBAL_CORRELATION_ASSETS: dict[str, str] = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "Dow Jones": "^DJI",
    "NASDAQ": "^IXIC",
    "S&P 500": "^GSPC",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Dollar Index": "DX-Y.NYB",
    "USD/INR": "USDINR=X",
    "Crude Oil": "CL=F",
    "US 10Y Yield": "^TNX",
    "India VIX": "^INDIAVIX",
}


def parse_advanced_symbols(raw_symbols: str, limit: int = 25) -> list[str]:
    symbols: list[str] = []
    for token in re.split(r"[\s,;]+", raw_symbols.upper()):
        cleaned = token.strip().replace(".NS", "")
        if cleaned and cleaned not in symbols:
            symbols.append(cleaned)
    return symbols[:limit]


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_raw_yfinance_history(ticker: str, lookback_days: int = 365) -> pd.DataFrame:
    if yf is None or not ticker:
        return pd.DataFrame()
    start = date.today() - timedelta(days=lookback_days)
    try:
        history = yf.download(ticker, start=start.isoformat(), progress=False, auto_adjust=False, threads=False)
    except Exception:
        return pd.DataFrame()
    if history.empty:
        return pd.DataFrame()
    return normalize_ohlcv_columns(history)


def advanced_pct_return(close: pd.Series, days: int) -> float | None:
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if len(clean) <= days or clean.iloc[-days - 1] == 0:
        return None
    return float((clean.iloc[-1] / clean.iloc[-days - 1] - 1) * 100)


def advanced_stock_metrics(symbol: str, lookback_days: int = 500) -> dict[str, Any]:
    history = add_chart_teacher_indicators(fetch_ohlcv_history(symbol, lookback_days=lookback_days))
    if history.empty or len(history) < 40:
        return {"symbol": symbol, "status": "Historical data unavailable", "history": pd.DataFrame()}

    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    high = pd.to_numeric(history["high"], errors="coerce").dropna()
    low = pd.to_numeric(history["low"], errors="coerce").dropna()
    open_price = pd.to_numeric(history["open"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    if min(len(close), len(high), len(low), len(open_price), len(volume)) < 40:
        return {"symbol": symbol, "status": "Insufficient clean history", "history": history}

    latest_close = float(close.iloc[-1])
    latest_open = float(open_price.iloc[-1])
    latest_high = float(high.iloc[-1])
    latest_low = float(low.iloc[-1])
    day_range = max(latest_high - latest_low, 0.01)
    closing_position = (latest_close - latest_low) / day_range * 100
    body_pct = abs(latest_close - latest_open) / day_range * 100
    avg_volume_20 = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
    volume_ratio = float(volume.iloc[-1] / avg_volume_20) if avg_volume_20 else 0
    turnover_cr = latest_close * float(volume.iloc[-1]) / 10_000_000 if latest_close else 0
    ret_5 = advanced_pct_return(close, 5)
    ret_20 = advanced_pct_return(close, 20)
    ret_60 = advanced_pct_return(close, 60)
    ret_120 = advanced_pct_return(close, 120)
    high_52w = float(high.tail(252).max()) if len(high) >= 60 else float(high.max())
    drawdown_from_high = (latest_close / high_52w - 1) * 100 if high_52w else None
    latest = history.iloc[-1]
    previous = history.iloc[-11] if len(history) > 11 else history.iloc[0]
    obv_slope = coerce_float(latest.get("obv"), 0) - coerce_float(previous.get("obv"), 0)
    ad_slope = coerce_float(latest.get("ad_line"), 0) - coerce_float(previous.get("ad_line"), 0)
    ema20 = coerce_float(latest.get("ema20"), None)
    ema50 = coerce_float(latest.get("ema50"), None)
    ema200 = coerce_float(latest.get("ema200"), None)
    trend_status = "Bullish" if ema20 and ema50 and ema200 and latest_close > ema20 > ema50 > ema200 else "Neutral" if ema50 and latest_close >= ema50 else "Weak"

    return {
        "symbol": symbol,
        "status": "OK",
        "history": history,
        "current_price": round(latest_close, 2),
        "closing_position_pct": round(closing_position, 2),
        "body_pct": round(body_pct, 2),
        "volume_ratio": round(volume_ratio, 2),
        "turnover_cr": round(turnover_cr, 2),
        "return_5d": round(ret_5, 2) if ret_5 is not None else None,
        "return_20d": round(ret_20, 2) if ret_20 is not None else None,
        "return_60d": round(ret_60, 2) if ret_60 is not None else None,
        "return_120d": round(ret_120, 2) if ret_120 is not None else None,
        "drawdown_from_52w_high_pct": round(drawdown_from_high, 2) if drawdown_from_high is not None else None,
        "rsi": round(coerce_float(latest.get("rsi14"), 50) or 50, 2),
        "adx": round(coerce_float(latest.get("adx14"), 0) or 0, 2),
        "mfi": round(coerce_float(latest.get("mfi14"), 50) or 50, 2),
        "atr_pct": round((coerce_float(latest.get("atr14"), 0) or 0) / latest_close * 100, 2) if latest_close else None,
        "obv_rising": bool(obv_slope > 0),
        "ad_rising": bool(ad_slope > 0),
        "trend_status": trend_status,
    }


def advanced_stock_context(symbol: str, capital: float = 500_000.0, risk_pct: float = 1.0) -> dict[str, Any]:
    cleaned = symbol.strip().upper().replace(".NS", "")
    metrics = advanced_stock_metrics(cleaned)
    history = metrics.get("history", pd.DataFrame())
    row = pd.Series({"nsecode": cleaned, "name": cleaned, "sector": ""})
    market = compute_iq5000_market_regime()

    try:
        chart = score_ai_chart_reading_candidate(row, history_override=history if isinstance(history, pd.DataFrame) else None)
    except Exception as exc:
        chart = {"chart_quality_score": 0, "reason": f"Chart score unavailable: {exc}"}
    try:
        early = score_ai_early_breakout_candidate(row)
    except Exception as exc:
        early = {"ai_early_breakout_score": 0, "reason_for_selection": f"Early breakout score unavailable: {exc}"}
    try:
        iq = score_iq5000_candidate(row, market_regime=market, capital=capital, max_risk_pct=risk_pct, max_capital_pct=25.0)
    except Exception as exc:
        iq = {"ai_iq_score": 0, "reason_for_selection": f"IQ score unavailable: {exc}"}
    try:
        overnight = score_ai_overnight_candidate(row, market_regime=market)
    except Exception as exc:
        overnight = {"tomorrow_intraday_probability": 0, "reason_for_selection": f"Overnight score unavailable: {exc}"}
    delivery = fetch_nse_delivery_snapshot(cleaned)
    info = fetch_ticker_info(cleaned)

    return {
        "symbol": cleaned,
        "metrics": metrics,
        "history": history if isinstance(history, pd.DataFrame) else pd.DataFrame(),
        "chart": chart if isinstance(chart, dict) else {},
        "early": early if isinstance(early, dict) else {},
        "iq": iq if isinstance(iq, dict) else {},
        "overnight": overnight if isinstance(overnight, dict) else {},
        "market": market,
        "delivery": delivery if isinstance(delivery, dict) else {},
        "info": info if isinstance(info, dict) else {},
    }


def advanced_scorecard_rows(context: dict[str, Any]) -> pd.DataFrame:
    metrics = context.get("metrics", {})
    chart = context.get("chart", {})
    iq = context.get("iq", {})
    early = context.get("early", {})
    overnight = context.get("overnight", {})
    rows = [
        {"Metric": "Current Price", "Value": metrics.get("current_price", chart.get("current_price"))},
        {"Metric": "Trend Status", "Value": metrics.get("trend_status")},
        {"Metric": "Chart Quality Score", "Value": chart.get("chart_quality_score")},
        {"Metric": "AI Early Breakout Score", "Value": early.get("ai_early_breakout_score")},
        {"Metric": "AI IQ Score", "Value": iq.get("ai_iq_score")},
        {"Metric": "Tomorrow Intraday Probability", "Value": overnight.get("tomorrow_intraday_probability")},
        {"Metric": "Smart Money Score", "Value": iq.get("smart_money_score", early.get("smart_money_score"))},
        {"Metric": "Delivery %", "Value": context.get("delivery", {}).get("delivery_percentage", early.get("delivery_pct"))},
        {"Metric": "Turnover Cr", "Value": metrics.get("turnover_cr", early.get("turnover_cr"))},
        {"Metric": "False Breakout Risk", "Value": chart.get("false_breakout_risk")},
    ]
    return pd.DataFrame(rows)


def advanced_order_flow_table(context: dict[str, Any]) -> pd.DataFrame:
    metrics = context.get("metrics", {})
    chart = context.get("chart", {})
    closing = coerce_float(metrics.get("closing_position_pct"), 50) or 50
    rvol = coerce_float(metrics.get("volume_ratio"), 0) or 0
    body = coerce_float(metrics.get("body_pct"), 0) or 0
    obv = bool(metrics.get("obv_rising"))
    ad = bool(metrics.get("ad_rising"))
    false_risk = coerce_float(chart.get("false_breakout_risk"), 50) or 50
    buyer = bounded_score(closing * 0.45 + min(rvol * 20, 35) + (12 if obv else 0) + (8 if ad else 0), 100)
    seller = bounded_score((100 - closing) * 0.45 + (18 if rvol >= 1.5 and closing < 45 else 0) + false_risk * 0.20, 100)
    absorption = bounded_score((30 if rvol >= 1.5 and body <= 45 else 10) + (20 if obv and ad else 0) + (20 if closing >= 60 else 0), 100)
    liquidity_grab = bounded_score(false_risk * 0.35 + (25 if rvol >= 1.8 else 0) + (20 if closing <= 25 or closing >= 80 else 0), 100)
    smart_money = bounded_score((buyer + absorption + (coerce_float(context.get("iq", {}).get("smart_money_score"), 0) or 0)) / 3, 100)
    rows = [
        {"Output": "Buyer Dominance", "Score": buyer, "Reading": "Strong" if buyer >= 70 else "Moderate" if buyer >= 50 else "Weak", "Evidence": f"Close position {closing:.1f}%, RVOL {rvol:.2f}, OBV rising {obv}."},
        {"Output": "Seller Dominance", "Score": seller, "Reading": "High" if seller >= 70 else "Moderate" if seller >= 50 else "Low", "Evidence": f"False-breakout risk {false_risk:.0f}/100 and close position {closing:.1f}%."},
        {"Output": "Absorption", "Score": absorption, "Reading": "Visible proxy" if absorption >= 65 else "Not clear", "Evidence": "High-volume narrow-body or strong close behavior can imply absorption, but true tape data is unavailable."},
        {"Output": "Liquidity Grab", "Score": liquidity_grab, "Reading": "Watch closely" if liquidity_grab >= 65 else "Normal", "Evidence": "Proxy uses wick/close location, RVOL, and failed-breakout risk."},
        {"Output": "Smart Money Activity", "Score": smart_money, "Reading": "Active" if smart_money >= 70 else "Developing" if smart_money >= 50 else "Weak", "Evidence": "Proxy blends buyer dominance, absorption, OBV/A-D behavior, and IQ smart-money score."},
    ]
    return pd.DataFrame(rows)


def advanced_institutional_tracker_table(context: dict[str, Any]) -> pd.DataFrame:
    delivery = context.get("delivery", {})
    early = context.get("early", {})
    iq = context.get("iq", {})
    info = context.get("info", {})
    delivery_pct = coerce_float(delivery.get("delivery_percentage"), coerce_float(early.get("delivery_pct"), 0)) or 0
    conviction = bounded_score(
        (40 if delivery_pct >= 60 else 30 if delivery_pct >= 50 else 18 if delivery_pct >= 40 else 8)
        + (coerce_float(iq.get("ai_institutional_score"), 0) or 0) * 0.35
        + (coerce_float(iq.get("smart_money_score"), 0) or 0) * 0.25,
        100,
    )
    rows = [
        {"Institution Type": "FII", "Available Evidence": "Not connected in current free data stack", "Proxy Reading": "Use exchange filings / quarterly shareholding when integrated"},
        {"Institution Type": "DII", "Available Evidence": "Not connected in current free data stack", "Proxy Reading": "Use exchange filings / quarterly shareholding when integrated"},
        {"Institution Type": "Mutual Funds", "Available Evidence": "Not connected in current free data stack", "Proxy Reading": "Track MF holding change when feed is available"},
        {"Institution Type": "Promoters", "Available Evidence": info.get("heldPercentInsiders", "Unavailable"), "Proxy Reading": "Promoter/insider proxy from yfinance if returned"},
        {"Institution Type": "Foreign Institutions", "Available Evidence": info.get("heldPercentInstitutions", "Unavailable"), "Proxy Reading": "Institutional ownership proxy from yfinance if returned"},
        {"Institution Type": "Delivery Trend", "Available Evidence": f"{delivery_pct:.2f}%" if delivery_pct else "Unavailable", "Proxy Reading": "High delivery supports accumulation only when price structure also confirms"},
        {"Institution Type": "Institutional Conviction Score", "Available Evidence": conviction, "Proxy Reading": "Accumulation" if conviction >= 70 else "Neutral" if conviction >= 45 else "Weak"},
    ]
    return pd.DataFrame(rows)


def global_correlation_table() -> pd.DataFrame:
    nifty = fetch_raw_yfinance_history("^NSEI", lookback_days=420)
    nifty_close = pd.to_numeric(nifty.get("close", pd.Series(dtype="float64")), errors="coerce").dropna()
    rows: list[dict[str, Any]] = []
    for name, ticker in GLOBAL_CORRELATION_ASSETS.items():
        history = fetch_raw_yfinance_history(ticker, lookback_days=420)
        close = pd.to_numeric(history.get("close", pd.Series(dtype="float64")), errors="coerce").dropna()
        if len(close) < 80:
            rows.append({"Asset": name, "Ticker": ticker, "20D Return %": "Unavailable", "Correlation vs NIFTY": "Unavailable", "Risk Read": "Data unavailable"})
            continue
        ret20 = advanced_pct_return(close, 20)
        ret60 = advanced_pct_return(close, 60)
        correlation = "Unavailable"
        if len(nifty_close) >= 80:
            joined = pd.concat([close.pct_change().tail(120).reset_index(drop=True), nifty_close.pct_change().tail(120).reset_index(drop=True)], axis=1).dropna()
            if len(joined) > 30:
                correlation = round(float(joined.iloc[:, 0].corr(joined.iloc[:, 1])), 2)
        risk_read = "Risk-on" if name in {"NIFTY", "BANKNIFTY", "NASDAQ", "S&P 500"} and (ret20 or 0) > 0 else "Risk-off hedge rising" if name in {"Gold", "Dollar Index", "US 10Y Yield", "India VIX"} and (ret20 or 0) > 0 else "Neutral"
        rows.append({"Asset": name, "Ticker": ticker, "20D Return %": round(ret20, 2) if ret20 is not None else None, "60D Return %": round(ret60, 2) if ret60 is not None else None, "Correlation vs NIFTY": correlation, "Risk Read": risk_read})
    return pd.DataFrame(rows)


def sector_rotation_table() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sector, basket in ADVANCED_SECTOR_BASKETS.items():
        returns_5: list[float] = []
        returns_20: list[float] = []
        returns_60: list[float] = []
        bullish_count = 0
        available = 0
        for symbol in basket:
            metrics = advanced_stock_metrics(symbol, lookback_days=260)
            if metrics.get("status") != "OK":
                continue
            available += 1
            for source, target in [(metrics.get("return_5d"), returns_5), (metrics.get("return_20d"), returns_20), (metrics.get("return_60d"), returns_60)]:
                value = coerce_float(source, None)
                if value is not None:
                    target.append(value)
            if metrics.get("trend_status") == "Bullish":
                bullish_count += 1
        if available == 0:
            rows.append({"Sector": sector, "Sector Strength": "Unavailable", "Sector Momentum": "Unavailable", "Capital Rotation": "Data unavailable", "Leading/Weak": "Unavailable", "Basket": ", ".join(basket)})
            continue
        avg20 = sum(returns_20) / len(returns_20) if returns_20 else 0
        avg60 = sum(returns_60) / len(returns_60) if returns_60 else 0
        breadth = bullish_count / available * 100
        score = bounded_score(50 + avg20 * 2.5 + avg60 * 0.8 + (breadth - 50) * 0.4, 100)
        rows.append(
            {
                "Sector": sector,
                "Sector Strength": score,
                "Sector Momentum": round(sum(returns_5) / len(returns_5), 2) if returns_5 else None,
                "20D Return %": round(avg20, 2),
                "60D Return %": round(avg60, 2),
                "Bullish Breadth %": round(breadth, 2),
                "Capital Rotation": "Inflows improving" if score >= 70 else "Neutral" if score >= 45 else "Outflow/lagging",
                "Leading/Weak": "Leading Sector" if score >= 75 else "Weak Sector" if score < 40 else "Middle of pack",
                "Basket": ", ".join(basket),
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["Sector Strength", "20D Return %"], [False, False])


def relative_performance_matrix(symbols: list[str]) -> pd.DataFrame:
    nifty = fetch_raw_yfinance_history("^NSEI", lookback_days=260)
    nifty_close = pd.to_numeric(nifty.get("close", pd.Series(dtype="float64")), errors="coerce").dropna()
    nifty_20 = advanced_pct_return(nifty_close, 20) or 0
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        metrics = advanced_stock_metrics(symbol, lookback_days=260)
        if metrics.get("status") != "OK":
            rows.append({"Stock": symbol, "Status": metrics.get("status"), "RS Score": 0})
            continue
        ret20 = coerce_float(metrics.get("return_20d"), 0) or 0
        ret60 = coerce_float(metrics.get("return_60d"), 0) or 0
        rs_nifty = ret20 - nifty_20
        score = bounded_score(50 + rs_nifty * 4 + ret60 * 0.8 + (10 if metrics.get("trend_status") == "Bullish" else -8), 100)
        rows.append(
            {
                "Stock": symbol,
                "Current Price": metrics.get("current_price"),
                "20D Return %": ret20,
                "60D Return %": ret60,
                "RS vs NIFTY 20D": round(rs_nifty, 2),
                "RS Score": score,
                "Trend": metrics.get("trend_status"),
                "Matrix Read": "Outperforming" if score >= 70 else "Neutral" if score >= 45 else "Underperforming",
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["RS Score", "20D Return %"], [False, False])


def market_dna_table(context: dict[str, Any]) -> pd.DataFrame:
    chart = context.get("chart", {})
    early = context.get("early", {})
    iq = context.get("iq", {})
    pattern = iq.get("pattern_detected") or chart.get("pattern_detected") or iq5000_pattern_label(early)
    memory = get_iq5000_memory_estimate(str(pattern), str(iq.get("sector", "")), str(context.get("market", {}).get("market_regime", "")), coerce_float(iq.get("similarity_score"), 60) or 60)
    rows = [
        {"DNA Field": "Detected Pattern", "Value": pattern, "Interpretation": "The pattern label becomes the historical analogy key."},
        {"DNA Field": "Most Similar Historical Stock", "Value": memory.get("most_similar_historical_stock"), "Interpretation": "Based on saved IQ-5000 memory when available; otherwise estimated."},
        {"DNA Field": "Most Similar Historical Date", "Value": memory.get("most_similar_historical_date"), "Interpretation": "Unavailable until the journal/memory has enough stored trades."},
        {"DNA Field": "Similarity Score", "Value": iq.get("similarity_score", "Unavailable"), "Interpretation": "Higher means current setup resembles known high-quality patterns."},
        {"DNA Field": "Historical Win Rate", "Value": memory.get("historical_win_rate"), "Interpretation": "Estimated from saved memory or fallback pattern similarity."},
        {"DNA Field": "Historical Average Return", "Value": memory.get("historical_average_return"), "Interpretation": "Research estimate, not a promised outcome."},
        {"DNA Field": "Average Breakout Time", "Value": memory.get("historical_average_holding_days"), "Interpretation": "Used for patience and holding-period planning."},
    ]
    return pd.DataFrame(rows)


def opportunity_ranking_table(symbols: list[str], capital: float, risk_pct: float) -> pd.DataFrame:
    market = compute_iq5000_market_regime()
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        row = pd.Series({"nsecode": symbol, "name": symbol, "sector": ""})
        try:
            iq = score_iq5000_candidate(row, market_regime=market, capital=capital, max_risk_pct=risk_pct, max_capital_pct=25.0)
        except Exception as exc:
            iq = {"nsecode": symbol, "ai_iq_score": 0, "reason_for_selection": f"Skipped: {exc}"}
        if isinstance(iq, dict):
            rows.append(
                {
                    "Stock": symbol,
                    "AI IQ Score": iq.get("ai_iq_score", 0),
                    "Intraday": iq.get("ai_intraday_score", 0),
                    "Swing": iq.get("ai_swing_score", 0),
                    "Institutional": iq.get("ai_institutional_score", 0),
                    "Early Breakout": iq.get("ai_early_breakout_score", 0),
                    "Smart Money": iq.get("smart_money_score", 0),
                    "Low Risk": iq.get("risk_management_score", 0),
                    "High Conviction": iq.get("trade_probability", 0),
                    "Classification": iq.get("confidence_rating", "Research only"),
                    "Reason": iq.get("reason_for_selection", ""),
                }
            )
    return safe_sort_dataframe(pd.DataFrame(rows), ["AI IQ Score", "High Conviction"], [False, False])


def advanced_symbols_from_scan_results(df: pd.DataFrame, limit: int) -> list[str]:
    if df.empty:
        return []
    symbol_column = find_column(df, ["nsecode", "symbol", "stock", "stock_name", "name"])
    if symbol_column is None:
        return []
    symbols: list[str] = []
    for value in df[symbol_column].dropna().astype(str):
        cleaned = value.strip().upper().replace(".NS", "")
        cleaned = re.sub(r"[^A-Z0-9&_-]+", "", cleaned)
        if cleaned and cleaned not in symbols:
            symbols.append(cleaned)
        if len(symbols) >= limit:
            break
    return symbols


def render_auto_universe_controls(module_key: int, default_limit: int = 10) -> tuple[list[str], float, float, str, pd.DataFrame]:
    with st.sidebar:
        st.header("Auto Stock Universe")
        scan_source = st.selectbox(
            "Auto-fetch source",
            list(ADVANCED_AUTO_SCAN_SOURCES),
            index=0,
            key=f"advanced_auto_source_{module_key}",
        )
        candidate_limit = st.slider("Stocks to analyze", 3, 30, default_limit, 1, key=f"advanced_auto_limit_{module_key}")
        include_manual = st.toggle("Add manual symbols", value=False, key=f"advanced_auto_include_manual_{module_key}")
        manual_symbols = ""
        if include_manual:
            manual_symbols = st.text_area(
                "Manual symbols",
                value=ADVANCED_DEFAULT_WATCHLIST,
                height=90,
                key=f"advanced_auto_manual_{module_key}",
            )
        capital = st.number_input(
            "Trading capital",
            min_value=10_000.0,
            value=500_000.0,
            step=50_000.0,
            key=f"advanced_auto_capital_{module_key}",
        )
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key=f"advanced_auto_risk_{module_key}")
        if st.button("Refresh auto universe", type="primary", width="stretch", key=f"advanced_auto_refresh_{module_key}"):
            run_scan.clear()
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            fetch_ticker_info.clear()
            fetch_raw_yfinance_history.clear()
            st.rerun()

    scan_df, scan_error = run_scan(ADVANCED_AUTO_SCAN_SOURCES[scan_source])
    if scan_error:
        st.warning(f"Auto-fetch source returned an error: {scan_error}")
    symbols = advanced_symbols_from_scan_results(scan_df, candidate_limit)
    if include_manual:
        for symbol in parse_advanced_symbols(manual_symbols, limit=candidate_limit):
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= candidate_limit:
                break
    if not symbols:
        st.info("Auto-fetch returned no symbols, so the module is using the default liquid watchlist.")
        symbols = parse_advanced_symbols(ADVANCED_DEFAULT_WATCHLIST, limit=candidate_limit)
    return symbols[:candidate_limit], capital, risk_pct, scan_source, scan_df


def render_auto_universe_metrics(symbols: list[str], scan_source: str, scan_df: pd.DataFrame) -> None:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Auto Source", scan_source)
    col_b.metric("Fetched Rows", len(scan_df))
    col_c.metric("Stocks Analyzed", len(symbols))
    with st.expander("Auto-fetched symbols", expanded=False):
        display_dataframe(pd.DataFrame({"Symbol": symbols}), height=220)


def build_advanced_contexts(symbols: list[str], capital: float, risk_pct: float) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            contexts.append(advanced_stock_context(symbol, capital=capital, risk_pct=risk_pct))
        except Exception as exc:
            contexts.append(
                {
                    "symbol": symbol,
                    "metrics": {"status": f"Skipped: {exc}"},
                    "chart": {},
                    "early": {},
                    "iq": {},
                    "overnight": {},
                    "market": compute_iq5000_market_regime(),
                    "delivery": {},
                    "info": {},
                }
            )
    return contexts


def context_common_fields(context: dict[str, Any]) -> dict[str, Any]:
    metrics = context.get("metrics", {})
    chart = context.get("chart", {})
    iq = context.get("iq", {})
    early = context.get("early", {})
    overnight = context.get("overnight", {})
    return {
        "Stock": context.get("symbol"),
        "Price": metrics.get("current_price", chart.get("current_price")),
        "Trend": metrics.get("trend_status"),
        "Chart Score": chart.get("chart_quality_score"),
        "AI IQ Score": iq.get("ai_iq_score"),
        "Early Breakout": early.get("ai_early_breakout_score"),
        "Smart Money": iq.get("smart_money_score", early.get("smart_money_score")),
        "Tomorrow Probability": overnight.get("tomorrow_intraday_probability"),
        "Turnover Cr": metrics.get("turnover_cr", early.get("turnover_cr")),
        "Reason": chart.get("reason", iq.get("reason_for_selection", early.get("reason_for_selection", ""))),
    }


def module23_order_flow_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        table = advanced_order_flow_table(context)
        score_map = dict(zip(table["Output"], table["Score"])) if not table.empty else {}
        reading_map = dict(zip(table["Output"], table["Reading"])) if not table.empty else {}
        rows.append(
            {
                **common,
                "Buyer Dominance": score_map.get("Buyer Dominance"),
                "Seller Dominance": score_map.get("Seller Dominance"),
                "Absorption": score_map.get("Absorption"),
                "Liquidity Grab": score_map.get("Liquidity Grab"),
                "Smart Money Activity": score_map.get("Smart Money Activity"),
                "Order Flow Read": reading_map.get("Smart Money Activity", "Unavailable"),
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["Smart Money Activity", "Buyer Dominance", "Chart Score"], [False, False, False])


def module24_institutional_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        delivery_pct = coerce_float(context.get("delivery", {}).get("delivery_percentage"), coerce_float(context.get("early", {}).get("delivery_pct"), 0)) or 0
        institutional_score = coerce_float(context.get("iq", {}).get("ai_institutional_score"), 0) or 0
        conviction = bounded_score(
            (40 if delivery_pct >= 60 else 30 if delivery_pct >= 50 else 18 if delivery_pct >= 40 else 8)
            + institutional_score * 0.40
            + (coerce_float(context.get("iq", {}).get("smart_money_score"), 0) or 0) * 0.25,
            100,
        )
        rows.append(
            {
                **common,
                "Delivery %": round(delivery_pct, 2) if delivery_pct else None,
                "Institutional Score": institutional_score,
                "Institutional Conviction": conviction,
                "Accumulation Trend": "Accumulation" if conviction >= 70 else "Neutral" if conviction >= 45 else "Weak",
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["Institutional Conviction", "Institutional Score"], [False, False])


def module29_market_dna_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        iq = context.get("iq", {})
        dna = market_dna_table(context)
        dna_map = dict(zip(dna["DNA Field"], dna["Value"])) if not dna.empty else {}
        rows.append(
            {
                **common,
                "Detected Pattern": dna_map.get("Detected Pattern"),
                "Similarity Score": iq.get("similarity_score"),
                "Historical Win Rate": dna_map.get("Historical Win Rate"),
                "Historical Average Return": dna_map.get("Historical Average Return"),
                "Average Breakout Time": dna_map.get("Average Breakout Time"),
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["Similarity Score", "Historical Win Rate", "Chart Score"], [False, False, False])


def module30_trade_coach_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        chart = context.get("chart", {})
        iq = context.get("iq", {})
        action = (
            "Eligible for watchlist confirmation"
            if (coerce_float(common.get("AI IQ Score"), 0) or 0) >= 800 or (coerce_float(common.get("Chart Score"), 0) or 0) >= 80
            else "Research only / wait"
        )
        rows.append(
            {
                **common,
                "Coach Action": action,
                "What Confirms": "VWAP hold, breakout/retest acceptance, RVOL expansion, and market regime support.",
                "What Invalidates": f"Failure below stop/retest zone. Stop: {iq.get('stop_loss', chart.get('stop_loss', 'Unavailable'))}",
                "Professional Lesson": "Define invalidation before entry; no clean risk level means no trade.",
            }
        )
    return safe_sort_dataframe(pd.DataFrame(rows), ["AI IQ Score", "Chart Score"], [False, False])


def module35_scenario_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        base_prob = coerce_float(context.get("iq", {}).get("trade_probability"), coerce_float(context.get("chart", {}).get("chart_quality_score"), 50)) or 50
        bull = bounded_score(base_prob * 0.70 + 20, 100)
        sideways = bounded_score(35 - abs(base_prob - 60) * 0.25, 100)
        bear = max(0, 100 - bull - sideways)
        rows.append({**common, "Bull Scenario %": bull, "Sideways %": sideways, "Bear Scenario %": bear, "Preferred Mode": "Bullish continuation" if bull >= 65 else "Wait / range" if sideways >= bear else "Defensive"})
    return safe_sort_dataframe(pd.DataFrame(rows), ["Bull Scenario %", "AI IQ Score"], [False, False])


def module40_master_brain_universe(contexts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for context in contexts:
        common = context_common_fields(context)
        final_score = bounded_score(
            (coerce_float(context.get("iq", {}).get("ai_iq_score"), 0) or 0) / 10 * 0.35
            + (coerce_float(context.get("chart", {}).get("chart_quality_score"), 0) or 0) * 0.20
            + (coerce_float(context.get("early", {}).get("ai_early_breakout_score"), 0) or 0) * 0.20
            + (coerce_float(context.get("overnight", {}).get("tomorrow_intraday_probability"), 0) or 0) * 0.15
            + (coerce_float(context.get("market", {}).get("market_regime_score"), 60) or 60) * 0.10,
            100,
        )
        rows.append({**common, "Master Brain Score": final_score, "Decision": "High-quality watchlist" if final_score >= 80 else "Monitor" if final_score >= 60 else "No trade / research only"})
    return safe_sort_dataframe(pd.DataFrame(rows), ["Master Brain Score", "AI IQ Score", "Chart Score"], [False, False, False])


def render_module_symbol_controls(default_symbol: str = "RELIANCE") -> tuple[str, float, float]:
    with st.sidebar:
        st.header("Module Controls")
        symbol = st.text_input("NSE symbol", value=default_symbol, key=f"advanced_symbol_{st.session_state.get('_advanced_module_key', 'x')}")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key=f"advanced_capital_{st.session_state.get('_advanced_module_key', 'x')}")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key=f"advanced_risk_{st.session_state.get('_advanced_module_key', 'x')}")
        if st.button("Refresh module data", type="primary", width="stretch", key=f"advanced_refresh_{st.session_state.get('_advanced_module_key', 'x')}"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            fetch_ticker_info.clear()
            fetch_raw_yfinance_history.clear()
            st.rerun()
    return symbol.strip().upper().replace(".NS", ""), capital, risk_pct


def render_watchlist_controls(module_key: int) -> tuple[list[str], float, float]:
    with st.sidebar:
        st.header("Module Controls")
        raw_symbols = st.text_area("NSE symbols", value=ADVANCED_DEFAULT_WATCHLIST, height=110, key=f"advanced_watchlist_{module_key}")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key=f"advanced_watch_capital_{module_key}")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key=f"advanced_watch_risk_{module_key}")
        if st.button("Refresh module data", type="primary", width="stretch", key=f"advanced_watch_refresh_{module_key}"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            fetch_raw_yfinance_history.clear()
            st.rerun()
    return parse_advanced_symbols(raw_symbols, limit=25), capital, risk_pct


def render_advanced_module_summary(context: dict[str, Any]) -> None:
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Symbol", context.get("symbol", "Unavailable"))
    metric_b.metric("Price", context.get("metrics", {}).get("current_price", "Unavailable"))
    metric_c.metric("AI IQ Score", context.get("iq", {}).get("ai_iq_score", "Unavailable"))
    metric_d.metric("Market Regime", context.get("market", {}).get("market_regime", "Unavailable"))


def render_advanced_iq_module_page(module_key: int) -> None:
    st.session_state["_advanced_module_key"] = module_key
    title = ADVANCED_IQ_MODULES.get(module_key, "Advanced IQ Module")
    st.subheader(title)

    if module_key in {25, 26, 27}:
        st.caption("Auto-fetches macro and sector evidence. Uses available yfinance/price proxies and labels unavailable institutional feeds clearly.")
        if module_key == 25:
            table = global_correlation_table()
            risk_score = bounded_score(
                50
                + sum(8 for value in table.get("Risk Read", pd.Series(dtype="object")).astype(str) if "Risk-on" in value)
                - sum(6 for value in table.get("Risk Read", pd.Series(dtype="object")).astype(str) if "Risk-off" in value),
                100,
            )
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Global Market Risk", "Low/Moderate" if risk_score >= 60 else "Elevated")
            col_b.metric("Correlation Score", risk_score)
            col_c.metric("Mode", "Risk-On" if risk_score >= 60 else "Risk-Off")
            display_dataframe(table, height=560)
            return
        sector_table = sector_rotation_table()
        if module_key == 26:
            col_a, col_b, col_c = st.columns(3)
            leader = sector_table.iloc[0]["Sector"] if not sector_table.empty else "Unavailable"
            laggard = sector_table.iloc[-1]["Sector"] if not sector_table.empty else "Unavailable"
            col_a.metric("Leading Sector", leader)
            col_b.metric("Weak Sector", laggard)
            col_c.metric("Sectors Scanned", len(sector_table))
            display_dataframe(sector_table, height=620)
            return
        rotation_rows = []
        if not sector_table.empty:
            leaders = sector_table.head(3)["Sector"].tolist()
            laggards = sector_table.tail(3)["Sector"].tolist()
            rotation_rows = [
                {"Rotation Pair": f"{laggard} -> {leader}", "Signal": "Potential capital rotation", "Evidence": "Leader strength outranks laggard strength in the current proxy table."}
                for leader, laggard in zip(leaders, laggards)
            ]
        display_dataframe(pd.DataFrame(rotation_rows), height=260)
        st.markdown("**Underlying Sector Evidence**")
        display_dataframe(sector_table, height=560)
        return

    default_limit = 8 if module_key in {23, 24, 29, 30, 31, 35, 37, 40} else 12
    symbols, capital, risk_pct, scan_source, scan_df = render_auto_universe_controls(module_key, default_limit=default_limit)
    render_auto_universe_metrics(symbols, scan_source, scan_df)
    if not symbols:
        st.info("No stocks are available for this module after auto-fetch.")
        return

    if module_key in {28, 38, 39, 32, 33, 34, 36, 37}:
        if module_key == 28:
            table = relative_performance_matrix(symbols)
            st.caption("Auto-ranks fetched stocks against NIFTY using 20D/60D relative performance and trend quality.")
            display_dataframe(table, height=620)
            return

        table = opportunity_ranking_table(symbols, capital, risk_pct)

        if module_key == 38:
            radar = table.copy()
            if not radar.empty:
                radar["Radar Signal"] = radar.apply(
                    lambda row: "Elite setup entering radar" if coerce_float(row.get("AI IQ Score"), 0) >= 850 else "Monitor" if coerce_float(row.get("High Conviction"), 0) >= 65 else "Research only",
                    axis=1,
                )
            display_dataframe(radar, height=640)
            return

        display_dataframe(table.head(25), height=640)

        if module_key == 39:
            st.download_button(
                "Download opportunity ranking CSV",
                table.to_csv(index=False).encode("utf-8"),
                file_name="ai_opportunity_ranking.csv",
                mime="text/csv",
                width="stretch",
            )
            return

        if module_key == 32:
            total_risk_budget = capital * risk_pct / 100
            active = table[pd.to_numeric(table.get("AI IQ Score", pd.Series(dtype="float64")), errors="coerce") >= 800] if not table.empty else pd.DataFrame()
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("Portfolio Capital", f"{capital:,.0f}")
            col_b.metric("Risk Budget", f"{total_risk_budget:,.0f}")
            col_c.metric("Qualified Ideas", len(active))
            col_d.metric("Cash Mode", "High" if active.empty else "Selective")
            allocation_rows = []
            per_idea = total_risk_budget / max(len(active), 1)
            for _, row in active.head(8).iterrows():
                allocation_rows.append({"Stock": row.get("Stock"), "AI IQ Score": row.get("AI IQ Score"), "Max Rupee Risk": round(per_idea, 2), "Allocation Note": "Risk sized equally across qualified ideas"})
            st.markdown("**Auto Portfolio Allocation Draft**")
            display_dataframe(pd.DataFrame(allocation_rows), height=300)
            return

        if module_key == 33:
            st.markdown("**Auto Journal Prompts From Fetched Stocks**")
            journal_prompts = []
            for _, row in table.head(10).iterrows():
                journal_prompts.append(
                    {
                        "Stock": row.get("Stock"),
                        "Prompt": "Write why this setup deserves attention before entering. Record confirmation, invalidation, emotion, and planned risk.",
                        "Required Trigger": "VWAP/ORB/RVOL confirmation and clean stop level.",
                        "Risk Note": row.get("Classification", "Research only"),
                    }
                )
            display_dataframe(pd.DataFrame(journal_prompts), height=320)
            if "advanced_trade_journal" not in st.session_state:
                st.session_state["advanced_trade_journal"] = pd.DataFrame(columns=["Date", "Stock", "Reason", "Emotion", "Mistake", "Lesson", "Result"])
            default_stock = str(table.iloc[0]["Stock"]) if not table.empty and "Stock" in table.columns else symbols[0]
            with st.form("advanced_trade_journal_form"):
                col_a, col_b, col_c = st.columns(3)
                trade_date = col_a.date_input("Trade date", value=date.today())
                stock = col_b.text_input("Stock", value=default_stock)
                result = col_c.text_input("Result", value="Open / P&L")
                reason = st.text_area("Chart reason")
                emotion = st.text_area("Emotion / behavior")
                mistake = st.text_area("Mistakes")
                lesson = st.text_area("Lesson")
                submitted = st.form_submit_button("Save journal entry")
            if submitted:
                row = pd.DataFrame([{"Date": trade_date.isoformat(), "Stock": stock.upper(), "Reason": reason, "Emotion": emotion, "Mistake": mistake, "Lesson": lesson, "Result": result}])
                st.session_state["advanced_trade_journal"] = pd.concat([st.session_state["advanced_trade_journal"], row], ignore_index=True)
                st.success("Trade journal entry saved in session memory.")
            journal = st.session_state["advanced_trade_journal"]
            display_dataframe(journal, height=320)
            if not journal.empty:
                st.download_button("Download trade journal CSV", journal.to_csv(index=False).encode("utf-8"), "ai_trade_journal.csv", "text/csv", width="stretch")
            return

        if module_key == 34:
            with st.sidebar:
                trades_today = st.number_input("Trades taken today", min_value=0, value=0, step=1, key="psych_trades_today")
                loss_streak = st.number_input("Current loss streak", min_value=0, value=0, step=1, key="psych_loss_streak")
                daily_risk_used = st.slider("Daily risk used %", 0.0, 10.0, 0.0, 0.25, key="psych_risk_used")
                urge = st.slider("Urge to trade / FOMO", 0, 10, 3, 1, key="psych_urge")
            best_iq = pd.to_numeric(table.get("AI IQ Score", pd.Series(dtype="float64")), errors="coerce").max() if not table.empty else 0
            market_quality_penalty = 20 if pd.isna(best_iq) or best_iq < 750 else 0
            risk = bounded_score(trades_today * 10 + loss_streak * 15 + daily_risk_used * 8 + urge * 5 + market_quality_penalty, 100)
            status = "Take a break" if risk >= 75 else "Defensive mode" if risk >= 55 else "Stable"
            rows = [
                {"Psychology Check": "Auto Market Quality", "Status": "Low quality" if market_quality_penalty else "Acceptable", "Coach Note": "If fetched opportunities are weak, forcing trades is a behavior error."},
                {"Psychology Check": "Revenge Trading", "Status": "High risk" if loss_streak >= 3 or urge >= 8 else "Controlled", "Coach Note": "Do not trade to recover losses. Trade only valid setups."},
                {"Psychology Check": "Overtrading", "Status": "High risk" if trades_today >= 5 else "Controlled", "Coach Note": "Professionals are paid for quality decisions, not activity."},
                {"Psychology Check": "Daily Risk", "Status": "Exceeded" if daily_risk_used >= 3 else "Within limit", "Coach Note": "Stop trading when daily risk is consumed."},
                {"Psychology Check": "FOMO", "Status": "High" if urge >= 7 else "Normal", "Coach Note": "If the setup is missed, wait for the next clean structure."},
                {"Psychology Check": "Final Psychology Status", "Status": status, "Coach Note": "Capital protection is part of edge."},
            ]
            st.metric("Psychology Risk Score", risk)
            display_dataframe(pd.DataFrame(rows), height=390)
            return

        if module_key == 36:
            scenario = st.selectbox("Historical scenario", ["Auto Candidate Replay", "2008 Global Crisis", "2020 COVID Crash", "2020-2021 Rally", "2022 Bear Market", "2024 Bull Run"], key="replay_scenario")
            selected_symbol = st.selectbox("Replay candidate from auto universe", symbols, key="auto_replay_candidate")
            rows = [
                {"Replay Scenario": scenario, "Stock": selected_symbol, "Training Focus": "Practice entries without hindsight", "Rule": "Hide future candles, write thesis first, reveal outcome after."},
                {"Replay Scenario": scenario, "Stock": selected_symbol, "Training Focus": "Mark support, resistance, trend, volume", "Rule": "Write invalidation before entry."},
                {"Replay Scenario": scenario, "Stock": selected_symbol, "Training Focus": "Reveal 5/10/20 sessions", "Rule": "Score whether your thesis, not only P&L, was correct."},
            ]
            display_dataframe(pd.DataFrame(rows), height=260)
            st.info("For full candle-by-candle no-lookahead replay, open Chart Workstation > AI Chart Reading & Replay. This module now auto-selects candidates for replay practice.")
            return

        if module_key == 37:
            selected_symbol = st.selectbox("Research report candidate", table["Stock"].tolist() if not table.empty and "Stock" in table.columns else symbols, key="auto_report_candidate")
            report = build_professional_chart_report(selected_symbol, capital=capital, risk_pct=risk_pct)
            if not report:
                st.info("Report could not be generated.")
                return
            summary = report.get("summary", {})
            report_text = "\n\n".join([f"{title}\n{body}" for title, body in summary.items()])
            st.text_area("Institutional Research Report Draft", report_text, height=520)
            st.download_button("Download research report draft", report_text.encode("utf-8"), file_name=f"{selected_symbol}_institutional_research_report.txt", mime="text/plain", width="stretch")
            return

    with st.spinner(f"Analyzing {len(symbols)} auto-fetched stocks for {title}..."):
        contexts = build_advanced_contexts(symbols, capital=capital, risk_pct=risk_pct)

    if module_key == 23:
        st.caption("Auto-ranked order-flow proxy. True bid/ask depth, hidden liquidity, iceberg, spoofing, and delta volume require live Level-2 feeds.")
        display_dataframe(module23_order_flow_universe(contexts), height=640)
        return

    if module_key == 24:
        st.caption("Auto-ranked institutional tracker. Quarterly holdings require a shareholding feed; current results combine ownership proxies, delivery, and smart-money scores.")
        display_dataframe(module24_institutional_universe(contexts), height=640)
        return

    if module_key == 29:
        display_dataframe(module29_market_dna_universe(contexts), height=640)
        return

    if module_key == 30:
        display_dataframe(module30_trade_coach_universe(contexts), height=660)
        return

    if module_key == 31:
        rows = []
        for context in contexts:
            rows.append(
                {
                    **context_common_fields(context),
                    "Lesson": context.get("chart", {}).get("pattern_detected", "Unavailable"),
                    "Teaching Point": "A pattern is only useful when risk, volume, and trend confirm.",
                    "Quiz": "What confirms this setup, and what invalidates it?",
                    "Replay Task": "Replay the symbol before taking the next live setup.",
                }
            )
        display_dataframe(pd.DataFrame(rows), height=340)
        return

    if module_key == 35:
        display_dataframe(module35_scenario_universe(contexts), height=640)
        return

    if module_key == 40:
        st.markdown("**Master Brain Consensus**")
        table = module40_master_brain_universe(contexts)
        display_dataframe(table, height=660)
        if not table.empty:
            st.metric("Top Master Brain Score", table.iloc[0].get("Master Brain Score", "Unavailable"))
        st.info("Final decision remains evidence-based: no trade is better than forcing a low-quality setup.")
        return

    table = module40_master_brain_universe(contexts)
    display_dataframe(table, height=620)


def initialize_chart_replay_state() -> None:
    if "chart_replay_memory" not in st.session_state:
        st.session_state["chart_replay_memory"] = pd.DataFrame(
            columns=[
                "Date",
                "Symbol",
                "Replay Date",
                "Chart Quality Score",
                "Verdict",
                "Prediction Accuracy",
                "MFE %",
                "MAE %",
                "Time To Target",
                "Time To Stop",
                "Plan Valid",
            ]
        )


def prepare_replay_history(full_history: pd.DataFrame, replay_date: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp | None]:
    if full_history.empty or "date" not in full_history.columns:
        return pd.DataFrame(), pd.DataFrame(), None
    working = full_history.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working = working.dropna(subset=["date"]).sort_values("date")
    replay_ts = pd.Timestamp(replay_date)
    past = working[working["date"] <= replay_ts].copy()
    if past.empty:
        return pd.DataFrame(), working, None
    selected_ts = pd.Timestamp(past["date"].iloc[-1])
    future = working[working["date"] > selected_ts].copy()
    return past, future, selected_ts


def evaluate_chart_replay_outcome(future: pd.DataFrame, chart: dict[str, Any]) -> dict[str, Any]:
    if future.empty:
        return {
            "outcomes": pd.DataFrame(),
            "summary": pd.DataFrame([{"Metric": "Outcome", "Value": "No future candles available after replay date."}]),
        }

    working = future.copy().head(20)
    for column in ["open", "high", "low", "close", "volume"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["close", "high", "low"])
    if working.empty:
        return {
            "outcomes": pd.DataFrame(),
            "summary": pd.DataFrame([{"Metric": "Outcome", "Value": "Future candles are incomplete."}]),
        }

    entry = coerce_float(chart.get("entry_price"), None) or float(working["open"].iloc[0])
    stop = coerce_float(chart.get("stop_loss"), None) or entry * 0.94
    target = coerce_float(chart.get("target_1"), None) or entry * 1.12
    replay_close = entry

    outcomes = []
    for horizon in [1, 3, 5, 10, 20]:
        horizon_df = working.head(horizon)
        if horizon_df.empty:
            continue
        last_close = float(horizon_df["close"].iloc[-1])
        max_high = float(horizon_df["high"].max())
        min_low = float(horizon_df["low"].min())
        outcomes.append(
            {
                "Horizon": f"{horizon}D",
                "Close": round(last_close, 2),
                "Return %": round((last_close - replay_close) / replay_close * 100, 2) if replay_close else 0,
                "MFE %": round((max_high - entry) / entry * 100, 2) if entry else 0,
                "MAE %": round((min_low - entry) / entry * 100, 2) if entry else 0,
                "Target Hit": bool(max_high >= target),
                "Stop Hit": bool(min_low <= stop),
            }
        )

    target_hit_day = None
    stop_hit_day = None
    best_exit_day = None
    best_exit_return = None
    worst_drawdown = None
    for day_index, (_, candle) in enumerate(working.iterrows(), start=1):
        if target_hit_day is None and float(candle["high"]) >= target:
            target_hit_day = day_index
        if stop_hit_day is None and float(candle["low"]) <= stop:
            stop_hit_day = day_index
        day_return = (float(candle["close"]) - entry) / entry * 100 if entry else 0
        if best_exit_return is None or day_return > best_exit_return:
            best_exit_return = day_return
            best_exit_day = day_index
    worst_drawdown = (float(working["low"].min()) - entry) / entry * 100 if entry else 0
    mfe = (float(working["high"].max()) - entry) / entry * 100 if entry else 0
    mae = (float(working["low"].min()) - entry) / entry * 100 if entry else 0
    chart_score = coerce_float(chart.get("chart_quality_score"), 0) or 0
    bullish_prediction = chart_score >= 80
    final_return = (float(working["close"].iloc[-1]) - entry) / entry * 100 if entry else 0
    target_before_stop = target_hit_day is not None and (stop_hit_day is None or target_hit_day <= stop_hit_day)
    if bullish_prediction:
        prediction_accuracy = 100 if target_before_stop else 70 if final_return > 0 and mae > -8 else 35
    else:
        prediction_accuracy = 80 if final_return <= 0 or stop_hit_day is not None else 45
    plan_valid = "Yes" if target_before_stop or (bullish_prediction and final_return > 0 and mae > -8) else "No"

    summary = pd.DataFrame(
        [
            {"Metric": "Prediction Accuracy", "Value": f"{prediction_accuracy:.0f}%"},
            {"Metric": "Maximum Favorable Excursion", "Value": f"{mfe:.2f}%"},
            {"Metric": "Maximum Adverse Excursion", "Value": f"{mae:.2f}%"},
            {"Metric": "Time To Target", "Value": f"{target_hit_day} trading days" if target_hit_day else "Not hit in 20 sessions"},
            {"Metric": "Time To Stop Loss", "Value": f"{stop_hit_day} trading days" if stop_hit_day else "Not hit in 20 sessions"},
            {"Metric": "Best Exit Point", "Value": f"Day {best_exit_day}, {best_exit_return:.2f}%" if best_exit_day else "Unavailable"},
            {"Metric": "Worst Drawdown", "Value": f"{worst_drawdown:.2f}%"},
            {"Metric": "Trade Plan Valid", "Value": plan_valid},
        ]
    )
    return {
        "outcomes": pd.DataFrame(outcomes),
        "summary": summary,
        "accuracy": prediction_accuracy,
        "mfe": mfe,
        "mae": mae,
        "target_hit_day": target_hit_day,
        "stop_hit_day": stop_hit_day,
        "plan_valid": plan_valid,
    }


def render_professional_report_tabs(report: dict[str, Any], height: int = 360) -> None:
    chart = report.get("chart", {})
    tab_report, tab_structure, tab_volume, tab_swot, tab_plan, tab_scores = st.tabs(
        ["Analyst Report", "Structure", "Volume & Footprints", "Chart SWOT", "Trading Plan", "Scores"]
    )
    with tab_report:
        for title, body in report.get("summary", {}).items():
            st.markdown(f"**{title}**")
            st.write(body)
    with tab_structure:
        structure_rows = [
            {"Metric": "Chart Stage", "Value": chart.get("chart_stage", "Unavailable")},
            {"Metric": "Pattern Detected", "Value": chart.get("pattern_detected", "Unavailable")},
            {"Metric": "Candlestick Signal", "Value": chart.get("candlestick_signal", "Unavailable")},
            {"Metric": "Support Zone", "Value": chart.get("support_zone", "Unavailable")},
            {"Metric": "Resistance Zone", "Value": chart.get("resistance_zone", "Unavailable")},
            {"Metric": "Breakout Level", "Value": chart.get("breakout_level", "Unavailable")},
            {"Metric": "Retest Zone", "Value": chart.get("retest_zone", "Unavailable")},
            {"Metric": "Reason", "Value": chart.get("reason", "Unavailable")},
        ]
        display_dataframe(pd.DataFrame(structure_rows), height=height)
        st.markdown("**Multi-Timeframe Analysis**")
        display_dataframe(report.get("timeframes", pd.DataFrame()), height=300)
    with tab_volume:
        volume_rows = [
            {"Metric": "Volume Confirmation", "Value": chart.get("volume_confirmation", "Unavailable")},
            {"Metric": "Institutional Footprints", "Value": chart.get("institutional_footprints", "Unavailable")},
            {"Metric": "Relative Volume", "Value": chart.get("rvol", "Unavailable")},
            {"Metric": "RSI Context", "Value": chart.get("rsi", "Unavailable")},
            {"Metric": "Smart Money Interpretation", "Value": report.get("summary", {}).get("Institutional Activity", "Unavailable")},
        ]
        display_dataframe(pd.DataFrame(volume_rows), height=260)
        st.info(report.get("summary", {}).get("Legendary Analyst Explanation", "Volume and price must confirm each other before action."))
    with tab_swot:
        display_dataframe(report.get("swot", pd.DataFrame()), height=260)
    with tab_plan:
        display_dataframe(report.get("plan", pd.DataFrame()), height=420)
        st.caption("This is a research plan. Actual entry requires live confirmation, liquidity, and disciplined risk control.")
    with tab_scores:
        display_dataframe(report.get("scores", pd.DataFrame()), height=520)


def render_chart_reading_replay_page() -> None:
    initialize_chart_replay_state()
    st.subheader("AI Chart Reading & Replay Engine")
    st.caption("Module 20 + 21: professional chart interpretation plus no-lookahead historical replay and prediction validation.")

    with st.sidebar:
        st.header("Chart Replay Controls")
        symbol = st.text_input("Stock symbol or company name", value="RELIANCE", key="chart_replay_symbol")
        capital = st.number_input("Trading capital", min_value=10_000.0, value=500_000.0, step=50_000.0, key="chart_replay_capital")
        risk_pct = st.slider("Max risk per idea %", 0.25, 5.0, 1.0, 0.25, key="chart_replay_risk")
        if st.button("Refresh chart replay engine", type="primary", width="stretch"):
            fetch_ohlcv_history.clear()
            fetch_interval_ohlcv_history.clear()
            fetch_nse_delivery_snapshot.clear()
            st.rerun()

    cleaned_symbol = symbol.strip().upper().replace(".NS", "")
    if not cleaned_symbol:
        st.info("Enter an NSE symbol such as RELIANCE, SBIN, BEL, CDSL, or TRENT.")
        return

    live_tab, replay_tab, memory_tab = st.tabs(["Professional Reading", "Chart Replay", "Replay Memory"])

    with live_tab:
        with st.spinner(f"Reading {cleaned_symbol} with current chart data..."):
            live_report = build_professional_chart_report(cleaned_symbol, capital=capital, risk_pct=risk_pct)
        if not live_report:
            st.info("No live chart report could be generated.")
        else:
            chart = live_report.get("chart", {})
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("Final Verdict", live_report.get("verdict", "Unavailable"))
            col_b.metric("Chart Quality", int(coerce_float(chart.get("chart_quality_score"), 0) or 0))
            col_c.metric("Risk/Reward", chart.get("risk_reward", "Unavailable"))
            col_d.metric("False Breakout Risk", chart.get("false_breakout_risk", "Unavailable"))
            render_professional_report_tabs(live_report)

    with replay_tab:
        full_history = fetch_ohlcv_history(cleaned_symbol, lookback_days=1200)
        if full_history.empty or "date" not in full_history.columns:
            st.info("Historical data unavailable for replay.")
        else:
            history_dates = pd.to_datetime(full_history["date"], errors="coerce").dropna().sort_values()
            if history_dates.empty:
                st.info("Historical dates unavailable for replay.")
            else:
                min_date = history_dates.iloc[min(220, len(history_dates) - 1)].date()
                max_date = history_dates.iloc[max(0, len(history_dates) - 21)].date()
                default_date = history_dates.iloc[max(0, len(history_dates) - 60)].date()
                replay_date = st.date_input(
                    "Replay date",
                    value=default_date,
                    min_value=min_date,
                    max_value=max_date,
                    key="chart_replay_date",
                )
                past, future, selected_ts = prepare_replay_history(full_history, replay_date)
                if past.empty or selected_ts is None or len(past) < 220:
                    st.warning("Select a later replay date with at least 220 prior trading sessions.")
                else:
                    st.caption(f"Replay is locked to data available up to {selected_ts.date()}. Candles after this date are hidden from the interpretation.")
                    with st.spinner("Running no-lookahead chart interpretation..."):
                        replay_report = build_professional_chart_report(
                            cleaned_symbol,
                            capital=capital,
                            risk_pct=risk_pct,
                            daily_history_override=past,
                            replay_mode=True,
                        )
                    if not replay_report:
                        st.info("No replay report could be generated.")
                    else:
                        replay_chart = replay_report.get("chart", {})
                        outcome = evaluate_chart_replay_outcome(future, replay_chart)
                        col_a, col_b, col_c, col_d = st.columns(4)
                        col_a.metric("Replay Verdict", replay_report.get("verdict", "Unavailable"))
                        col_b.metric("Replay Chart Score", int(coerce_float(replay_chart.get("chart_quality_score"), 0) or 0))
                        col_c.metric("Prediction Accuracy", f"{coerce_float(outcome.get('accuracy'), 0):.0f}%")
                        col_d.metric("Plan Valid", outcome.get("plan_valid", "Unavailable"))

                        st.subheader("No-Lookahead Interpretation")
                        render_professional_report_tabs(replay_report, height=320)

                        st.subheader("What Actually Happened Next")
                        if isinstance(outcome.get("outcomes"), pd.DataFrame) and not outcome["outcomes"].empty:
                            display_dataframe(outcome["outcomes"], height=260)
                        display_dataframe(outcome.get("summary", pd.DataFrame()), height=300)

                        replay_row = {
                            "Date": date.today().isoformat(),
                            "Symbol": cleaned_symbol,
                            "Replay Date": str(selected_ts.date()),
                            "Chart Quality Score": replay_chart.get("chart_quality_score"),
                            "Verdict": replay_report.get("verdict"),
                            "Prediction Accuracy": outcome.get("accuracy"),
                            "MFE %": round(coerce_float(outcome.get("mfe"), 0) or 0, 2),
                            "MAE %": round(coerce_float(outcome.get("mae"), 0) or 0, 2),
                            "Time To Target": outcome.get("target_hit_day") or "Not hit",
                            "Time To Stop": outcome.get("stop_hit_day") or "Not hit",
                            "Plan Valid": outcome.get("plan_valid"),
                        }
                        if st.button("Store replay result in self-learning memory", width="stretch"):
                            st.session_state["chart_replay_memory"] = pd.concat(
                                [st.session_state["chart_replay_memory"], pd.DataFrame([replay_row])],
                                ignore_index=True,
                            )
                            st.success("Replay result stored in session memory.")

    with memory_tab:
        st.subheader("Chart Replay Self-Learning Memory")
        memory_df = st.session_state.get("chart_replay_memory", pd.DataFrame())
        if memory_df.empty:
            st.info("No replay results stored yet.")
        else:
            display_dataframe(memory_df, height=420)
            st.download_button(
                "Download chart replay memory CSV",
                memory_df.to_csv(index=False).encode("utf-8"),
                file_name="chart_replay_memory.csv",
                mime="text/csv",
                width="stretch",
            )


def render_high_accuracy_table(high_accuracy_df: pd.DataFrame) -> None:
    with st.container(border=True):
        st.subheader("High Accuracy Candidates")
        st.caption(
            "Requires at least 6 unique scanner confirmations across 3 or more categories, then ranks by setup breadth and any strict indicator filters available in Chartink output."
        )

        if high_accuracy_df.empty:
            st.info("No stocks currently pass the high-accuracy confirmation layer.")
            st.caption(
                "This is intentionally strict: duplicate scanner clauses do not inflate the count, and direct filters such as ADX, RVOL, delivery, turnover, Darvas level, and ATR are applied when available."
            )
            return

        display_dataframe(high_accuracy_df, height=420)
        st.download_button(
            "Download high accuracy candidates CSV",
            high_accuracy_df.to_csv(index=False).encode("utf-8"),
            file_name="high_accuracy_candidates.csv",
            mime="text/csv",
            width="stretch",
        )


def main() -> None:
    inject_css()
    render_header()

    selected_page = sidebar_page_choice()
    if selected_page == "Institutional Breakout Setup":
        render_institutional_setup_page()
        return
    if selected_page == "Breakout Probability Model":
        render_breakout_probability_page()
        return
    if selected_page == "Hedge Fund Stock Picker":
        render_hedge_fund_model_page()
        return
    if selected_page == "IQ-5000 AI Trading Platform":
        render_iq5000_platform_page()
        return
    if selected_page == "AI Overnight Opportunity":
        render_ai_overnight_opportunity_page()
        return
    if selected_page == "AI Chart Reading Engine":
        render_ai_chart_reading_page()
        return
    if selected_page == "AI Custom Chart Engine":
        render_custom_ai_chart_engine_page()
        return
    if selected_page == "AI Professional Chart Interpretation":
        render_professional_chart_interpretation_page()
        return
    if selected_page == "AI Interactive Chart Teacher":
        render_interactive_chart_teacher_page()
        return
    if selected_page == "AI Chart Reading & Replay":
        render_chart_reading_replay_page()
        return
    if selected_page in ADVANCED_IQ_MODULE_LOOKUP:
        render_advanced_iq_module_page(ADVANCED_IQ_MODULE_LOOKUP[selected_page])
        return
    if selected_page == "AI Early Breakout Score":
        render_ai_early_breakout_page()
        return
    if selected_page == "200 EMA/SMA Launch Pad":
        render_launch_pad_200_page()
        return
    if selected_page == "Stock Technicals & SWOT Card":
        render_stock_analysis_card_page()
        return

    selected_scans, sort_column, descending, auto_refresh, refresh_seconds, rows_per_scan = sidebar_controls()
    maybe_autorefresh(auto_refresh, refresh_seconds)

    if not selected_scans:
        st.info("Select at least one scan from the sidebar.")
        return

    progress = st.progress(0, text="Fetching Chartink scan results...")
    results: dict[str, tuple[pd.DataFrame, str | None]] = {}
    clause_cache: dict[str, tuple[pd.DataFrame, str | None]] = {}

    for index, scan in enumerate(selected_scans, start=1):
        if scan.clause not in clause_cache:
            clause_cache[scan.clause] = run_scan(scan.clause)

        df, error = clause_cache[scan.clause]
        results[scan.key] = (sort_results(df, sort_column, descending), error)
        progress.progress(index / len(selected_scans), text=f"Fetched {index} of {len(selected_scans)} scanner modules")

    progress.empty()

    total_rows = sum(len(df) for df, _ in results.values())
    failed_scans = sum(1 for _, error in results.values() if error)
    non_empty_scans = sum(1 for df, error in results.values() if not error and not df.empty)
    overlap_df = build_overlap_table(selected_scans, results)
    high_accuracy_df = build_high_accuracy_table(overlap_df)
    best_setup_df = build_best_setup_watchlist(high_accuracy_df)

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Selected scanners", len(selected_scans))
    metric_b.metric("Scanners with results", non_empty_scans)
    metric_c.metric("Total rows", f"{total_rows:,}")
    metric_d.metric("Best setups", len(best_setup_df), delta=f"{failed_scans} failed")

    st.divider()
    render_best_setup_watchlist(best_setup_df)
    st.divider()
    render_high_accuracy_table(high_accuracy_df)
    st.divider()
    render_overlap_table(overlap_df)
    st.divider()

    for start in range(0, len(selected_scans), 2):
        columns = st.columns(2)
        for offset, column in enumerate(columns):
            scan_index = start + offset
            if scan_index >= len(selected_scans):
                continue

            scan = selected_scans[scan_index]
            df, error = results[scan.key]
            with column:
                render_scan_card(scan, df, error, rows_per_scan)

    st.markdown(
        '<div class="footer-note">Data sources: Chartink, NSE, Yahoo Finance, and user-uploaded OHLCV where available. This platform is for screening and research workflows, not financial advice.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

