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
    import yfinance as yf
except ImportError:  # Optional dependency for local OHLCV enrichment.
    yf = None


APP_TITLE = "Chartink Multi-Screener Signal Dashboard"
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
            --muted: #64748b;
            --border: #e2e8f0;
            --accent: #2563eb;
            --accent-dark: #1d4ed8;
            --bg: #f8fafc;
        }

        .stApp {
            background: var(--bg);
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }

        [data-testid="stMetricValue"] {
            font-size: 1.35rem;
        }

        .dashboard-title {
            font-size: 2rem;
            font-weight: 760;
            line-height: 1.1;
            color: #0f172a;
            margin-bottom: .2rem;
        }

        .dashboard-subtitle {
            color: var(--muted);
            font-size: .98rem;
            margin-bottom: 1.1rem;
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
            margin-top: 1rem;
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
    st.markdown(f'<div class="dashboard-title">{APP_TITLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dashboard-subtitle">A structured Chartink dashboard for comparing breakout, volume, trend, risk, and fundamental screens.</div>',
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
        return st.radio(
            "Workspace",
            [
                "Multi-Screener Dashboard",
                "Institutional Breakout Setup",
                "Breakout Probability Model",
                "Hedge Fund Stock Picker",
                "IQ-5000 AI Platform",
                "AI Early Breakout Score",
                "200 EMA/SMA Launch Pad",
                "Stock Technicals & SWOT Card",
            ],
            index=0,
        )


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

    return {
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


def build_ai_early_breakout_model(df: pd.DataFrame, history_limit: int = 120) -> pd.DataFrame:
    if df.empty:
        return df
    rows = []
    for _, row in df.head(history_limit).iterrows():
        scored = score_ai_early_breakout_candidate(row)
        if scored.get("ai_early_breakout_score", 0) > 0:
            rows.append(scored)
    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return model.sort_values(["ai_early_breakout_score", "confidence_pct", "risk_reward_ratio"], ascending=[False, False, False], kind="mergesort")


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
    early = score_ai_early_breakout_candidate(row)
    if early.get("ai_early_breakout_score", 0) <= 0:
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
        scored = score_iq5000_candidate(
            row,
            market_regime=market_regime,
            capital=capital,
            max_risk_pct=max_risk_pct,
            max_capital_pct=max_capital_pct,
        )
        if scored.get("ai_iq_score", 0) > 0:
            rows.append(scored)

    model = pd.DataFrame(rows)
    if model.empty:
        return model
    return model.sort_values(["ai_iq_score", "trade_probability", "market_dna_score"], ascending=[False, False, False], kind="mergesort")


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
        st.error("NO TRADE TODAY - CAPITAL PRESERVATION HAS THE HIGHEST EXPECTED VALUE.")
        st.caption("Loosen the sidebar controls to inspect near-miss setups, or review the full scored universe below.")
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

    render_iq5000_learning_console()


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
    if selected_page == "IQ-5000 AI Platform":
        render_iq5000_platform_page()
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
        '<div class="footer-note">Data source: Chartink. This dashboard is for screening and research workflows, not financial advice.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

