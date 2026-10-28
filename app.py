"""
AI Stock Analysis Assistant — web UI (Streamlit)

Run locally:   streamlit run app.py
Deploy:        see DEPLOY.md

This file only *wraps* the existing project (agents/, tools/, utils/).
Nothing in the backend needs to change.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid

from pathlib import Path
...
APP_DIR = Path(__file__).resolve().parent
os.chdir(APP_DIR)

import pandas as pd
import sys
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

# The backend uses paths relative to the project root (memory/, data/).
APP_DIR = Path(__file__).resolve().parent
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))

st.set_page_config(
    page_title="AI Stock Analyst · NSE",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Secrets / config  (Streamlit Cloud secrets -> env vars, before backend import)
# ---------------------------------------------------------------------------
for _key in ("GEMINI_API_KEY", "NEWS_API_KEY"):
    if not os.getenv(_key):
        try:
            if _key in st.secrets:
                os.environ[_key] = str(st.secrets[_key])
        except Exception:
            pass

MAX_QUERIES = int(os.getenv("MAX_QUERIES_PER_SESSION", "15"))
COOLDOWN_SECONDS = float(os.getenv("QUERY_COOLDOWN_SECONDS", "3"))
# 1 = every visitor gets private memory + portfolio (use for public hosting)
# 0 = use the real memory/*.json files (use for local personal use)
ISOLATE_SESSIONS = os.getenv("ISOLATE_SESSIONS", "1") != "0"

# ---------------------------------------------------------------------------
# Backend imports
# ---------------------------------------------------------------------------
BACKEND_ERROR = None
try:
    from agents import manager_agent
    from tools import portfolio_tool
    from utils import memory_manager
    from utils.helpers import get_multiple_tickers, get_ticker
except Exception as exc:  # most commonly: GEMINI_API_KEY missing
    BACKEND_ERROR = exc
    manager_agent = portfolio_tool = memory_manager = None  # type: ignore

    # Charts / portfolio search still work without the AI backend
    try:
        from utils.helpers import get_multiple_tickers, get_ticker
    except Exception:  # pragma: no cover
        get_ticker = get_multiple_tickers = None  # type: ignore


# ---------------------------------------------------------------------------
# Per-visitor storage (so a public demo never mixes users' data)
# ---------------------------------------------------------------------------
SESSION_ROOT = Path(tempfile.gettempdir()) / "stock_assistant_sessions"


@st.cache_resource
def _install_session_paths():
    """
    The backend stores memory/portfolio in module-level path constants.
    We swap them for path-like objects that resolve to a per-thread folder.
    Streamlit runs each visitor in its own thread, so no locking is needed.
    """
    ctx = threading.local()

    class SessionPath(os.PathLike):
        def __init__(self, filename: str, fallback: str):
            self.filename, self.fallback = filename, fallback

        def __fspath__(self) -> str:
            folder = getattr(ctx, "dir", None)
            return str(folder / self.filename) if folder else self.fallback

        def __str__(self) -> str:
            return self.__fspath__()

    if memory_manager is not None and portfolio_tool is not None:
        memory_manager.MEMORY_FILE = SessionPath("history.json", "memory/history.json")
        portfolio_tool.PORTFOLIO_FILE = SessionPath("portfolio.json", "memory/portfolio.json")

    # Tidy up folders from visitors who left long ago
    try:
        cutoff = time.time() - 6 * 3600
        for child in SESSION_ROOT.glob("*"):
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
    except Exception:
        pass
    return ctx


_ctx = _install_session_paths()

if "sid" not in st.session_state:
    st.session_state.sid = uuid.uuid4().hex[:12]
    st.session_state.messages = []
    st.session_state.pending = None
    st.session_state.n_queries = 0
    st.session_state.last_query_at = 0.0
    st.session_state.last_ticker = None

if ISOLATE_SESSIONS:
    _folder = SESSION_ROOT / st.session_state.sid
    _folder.mkdir(parents=True, exist_ok=True)
    _ctx.dir = _folder
else:
    _ctx.dir = None

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
UP, DOWN, ACCENT = "#3DDC97", "#FF5C7A", "#3DDC97"

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');

html, body, [class*="css"], .stApp { font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.block-container { padding-top: 1.6rem; max-width: 1180px; }
footer, [data-testid="stAppDeployButton"], .stDeployButton { display: none !important; }

.hero h1 { font-family: 'Fraunces', serif; font-weight: 600; font-size: 2.3rem;
           letter-spacing: -0.01em; margin: 0; line-height: 1.1; }
.hero h1 { color: #E6EAF0 !important; }
.hero h1 .accent { color: #3DDC97; }
.hero p { margin: .35rem 0 0 0; opacity: .65; font-size: .95rem; }

[data-testid="stMetric"] {
  background: #121821; border: 1px solid #1E2733; border-radius: 12px;
  padding: .7rem .9rem;
}
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase;
  letter-spacing: .06em; opacity: .6; }
[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; font-size: 1.15rem; }
[data-testid="stMetricValue"] > div { overflow: visible !important; text-overflow: clip !important;
  white-space: normal !important; }

.signal { background:#121821; border:1px solid #1E2733; border-radius:12px; padding:.7rem .9rem; }
.signal .k { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; opacity:.6; }
.signal .v { font-family:'IBM Plex Mono',monospace; font-size:1.05rem; margin-top:.15rem; }
.signal .d { font-size:.8rem; opacity:.7; margin-top:.1rem; }
.pos { color:#3DDC97; } .neg { color:#FF5C7A; } .neu { color:#F6C177; }

.tickerline { font-size:.85rem; opacity:.7; margin:.2rem 0 .4rem 0; }
.tickerline b { opacity:1; }
.disclaimer { font-size:.75rem !important; opacity:.55; line-height:1.4; }

[data-testid="stChatMessage"] { background: transparent; }
div[data-testid="stChatMessageContent"] h2 { font-family:'Fraunces',serif; font-size:1.5rem;
  border-bottom:1px solid #1E2733; padding-bottom:.4rem; }
div[data-testid="stChatMessageContent"] h3 { font-size:1.05rem; margin-top:1.1rem; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
HEADINGS = [
    "Company Overview", "Market Performance", "Financial Analysis",
    "Technical Analysis", "Recent News", "Overall Summary",
    "Market Performance Comparison", "Financial Ratio Comparison",
    "Technical Indicator Comparison", "News Comparison",
    "Strengths of Company 1", "Strengths of Company 2", "Risks", "Final Verdict",
]


def format_report(text: str) -> str:
    """Turn the agent's '=====' banner text into clean Markdown."""
    text = str(text).replace("$", r"\$")
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"[=\-_─━]{3,}", stripped):
            continue
        plain = stripped.strip("#* :").strip()
        upper = plain.upper()
        if "STOCK ANALYSIS REPORT" in upper or "STOCK COMPARISON REPORT" in upper:
            out.append(f"## {plain}")
            continue
        if any(h.lower() in plain.lower() and len(plain) < len(h) + 8 for h in HEADINGS):
            out.append(f"### {plain}")
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def inr(x, digits=2):
    return "—" if x is None or pd.isna(x) else f"₹{x:,.{digits}f}"


def inr_cap(x):
    if x is None or pd.isna(x):
        return "—"
    if x >= 1e12:
        return f"₹{x / 1e12:.2f} L Cr"
    if x >= 1e7:
        return f"₹{x / 1e7:,.0f} Cr"
    return f"₹{x:,.0f}"


def compact(x):
    if x is None or pd.isna(x):
        return "—"
    for div, suffix in ((1e7, " Cr"), (1e5, " L"), (1e3, "K")):
        if x >= div:
            return f"{x / div:.2f}{suffix}"
    return f"{x:,.0f}"


# ---------------------------------------------------------------------------
# Market data (cached so reruns are instant)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_snapshot(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose")
        rate = info.get("dividendRate")
        return {
            "ticker": ticker,
            "name": info.get("longName") or ticker,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "price": price,
            "prev": prev,
            "change_pct": ((price - prev) / prev * 100) if price and prev else None,
            "day_low": info.get("dayLow"),
            "day_high": info.get("dayHigh"),
            "wk_low": info.get("fiftyTwoWeekLow"),
            "wk_high": info.get("fiftyTwoWeekHigh"),
            "volume": info.get("volume"),
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "pb": info.get("priceToBook"),
            "beta": info.get("beta"),
            "div_yield": (rate / price * 100) if rate and price else None,
        }
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc)}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_chart_frame(ticker: str):
    """5y of daily candles + every indicator the AI report talks about."""
    try:
        hist = yf.Ticker(ticker).history(period="5y")
    except Exception as exc:
        return f"Could not download price history: {exc}"
    if hist is None or hist.empty:
        return "No price history found for this ticker."

    df = hist.copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    close = df["Close"]
    for window in (20, 50, 200):
        df[f"SMA{window}"] = SMAIndicator(close, window).sma_indicator()
    bands = BollingerBands(close, 20, 2)
    df["BBU"], df["BBL"] = bands.bollinger_hband(), bands.bollinger_lband()
    df["RSI"] = RSIIndicator(close, 14).rsi()
    macd = MACD(close)
    df["MACD"], df["SIG"], df["HIST"] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    return df


PERIODS = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 5000}


def build_chart(df: pd.DataFrame, overlays: list[str], height: int = 760) -> go.Figure:
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.025,
        row_heights=[0.55, 0.12, 0.165, 0.165],
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=UP, decreasing_line_color=DOWN,
        increasing_fillcolor=UP, decreasing_fillcolor=DOWN,
        name="Price", showlegend=False,
    ), row=1, col=1)

    if "Bollinger Bands" in overlays:
        fig.add_trace(go.Scatter(x=df.index, y=df["BBU"], name="Bollinger",
                                 line=dict(color="rgba(150,160,180,.45)", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["BBL"], name="Bollinger low", showlegend=False,
                                 line=dict(color="rgba(150,160,180,.45)", width=1),
                                 fill="tonexty", fillcolor="rgba(150,160,180,.08)"), row=1, col=1)
    for window, color in ((20, "#F6C177"), (50, "#8EC5FF"), (200, "#C4A7FF")):
        if f"SMA {window}" in overlays:
            fig.add_trace(go.Scatter(x=df.index, y=df[f"SMA{window}"], name=f"SMA {window}",
                                     line=dict(color=color, width=1.4)), row=1, col=1)

    vol_colors = [UP if c >= o else DOWN for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors, opacity=.55,
                         name="Volume", showlegend=False), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI (14)", showlegend=False,
                             line=dict(color="#8EC5FF", width=1.4)), row=3, col=1)
    for level in (30, 70):
        fig.add_hline(y=level, line=dict(color="rgba(150,160,180,.4)", width=1, dash="dot"),
                      row=3, col=1)

    hist_colors = [UP if v >= 0 else DOWN for v in df["HIST"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=df["HIST"], marker_color=hist_colors, opacity=.5,
                         name="Histogram", showlegend=False), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD", showlegend=False,
                             line=dict(color="#F6C177", width=1.3)), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SIG"], name="Signal", showlegend=False,
                             line=dict(color="#C4A7FF", width=1.3)), row=4, col=1)

    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified", xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.03, x=0, bgcolor="rgba(0,0,0,0)"),
        font=dict(family="IBM Plex Sans"),
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor="rgba(255,255,255,.04)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,.05)")
    fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    return fig


def signal_cards(df: pd.DataFrame):
    last = df.iloc[-1]
    price = last["Close"]

    rsi = last["RSI"]
    if pd.isna(rsi):
        rsi_txt, rsi_cls, rsi_note = "—", "neu", "not enough data"
    elif rsi > 70:
        rsi_txt, rsi_cls, rsi_note = f"{rsi:.1f}", "neg", "Overbought (>70)"
    elif rsi < 30:
        rsi_txt, rsi_cls, rsi_note = f"{rsi:.1f}", "pos", "Oversold (<30)"
    else:
        rsi_txt, rsi_cls, rsi_note = f"{rsi:.1f}", "neu", "Neutral (30–70)"

    if pd.isna(last["MACD"]) or pd.isna(last["SIG"]):
        macd_txt, macd_cls, macd_note = "—", "neu", "not enough data"
    elif last["MACD"] > last["SIG"]:
        macd_txt, macd_cls, macd_note = "Bullish", "pos", "MACD above signal line"
    else:
        macd_txt, macd_cls, macd_note = "Bearish", "neg", "MACD below signal line"

    s50, s200 = last["SMA50"], last["SMA200"]
    if pd.isna(s50) or pd.isna(s200):
        trend_txt, trend_cls, trend_note = "—", "neu", "needs 200 days of data"
    elif price > s50 > s200:
        trend_txt, trend_cls, trend_note = "Uptrend", "pos", "Price > SMA50 > SMA200"
    elif price < s50 < s200:
        trend_txt, trend_cls, trend_note = "Downtrend", "neg", "Price < SMA50 < SMA200"
    else:
        trend_txt, trend_cls, trend_note = "Mixed", "neu", "Moving averages disagree"

    if pd.isna(last["BBU"]):
        bb_txt, bb_cls, bb_note = "—", "neu", "not enough data"
    elif price >= last["BBU"]:
        bb_txt, bb_cls, bb_note = "Upper band", "neg", "Price stretched high"
    elif price <= last["BBL"]:
        bb_txt, bb_cls, bb_note = "Lower band", "pos", "Price stretched low"
    else:
        bb_txt, bb_cls, bb_note = "Within bands", "neu", "Normal volatility range"

    cards = [("RSI (14)", rsi_txt, rsi_cls, rsi_note), ("MACD", macd_txt, macd_cls, macd_note),
             ("Trend", trend_txt, trend_cls, trend_note), ("Bollinger", bb_txt, bb_cls, bb_note)]
    for col, (k, v, cls, note) in zip(st.columns(4), cards):
        col.markdown(
            f'<div class="signal"><div class="k">{k}</div>'
            f'<div class="v {cls}">{v}</div><div class="d">{note}</div></div>',
            unsafe_allow_html=True,
        )


def render_snapshot(ticker: str, compact_view: bool = False):
    snap = fetch_snapshot(ticker)
    if "error" in snap or not snap.get("price"):
        st.caption(f"Live quote for {ticker} is unavailable right now.")
        return
    meta = " · ".join(x for x in (snap.get("sector"), snap.get("industry")) if x)
    st.markdown(
        f'<div class="tickerline"><b>{snap["name"]}</b> · {ticker}'
        f'{" · " + meta if meta else ""}</div>',
        unsafe_allow_html=True,
    )
    delta = f'{snap["change_pct"]:+.2f}%' if snap.get("change_pct") is not None else None
    if compact_view:
        cols = st.columns(3)
        cols[0].metric("Price", inr(snap["price"]), delta)
        cols[1].metric("Market cap", inr_cap(snap["market_cap"]))
        cols[2].metric("P/E", "—" if not snap["pe"] else f'{snap["pe"]:.1f}')
    else:
        cols = st.columns(5)
        cols[0].metric("Price", inr(snap["price"]), delta)
        cols[1].metric("Day range", f'{inr(snap["day_low"], 0)} – {inr(snap["day_high"], 0)}')
        cols[2].metric("52-week range", f'{inr(snap["wk_low"], 0)} – {inr(snap["wk_high"], 0)}')
        cols[3].metric("Market cap", inr_cap(snap["market_cap"]))
        cols[4].metric("P/E", "—" if not snap["pe"] else f'{snap["pe"]:.1f}')


# ---------------------------------------------------------------------------
# Agent plumbing
# ---------------------------------------------------------------------------
def resolve_symbol(text: str):
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[A-Za-z0-9&\-]+\.(NS|BO)", text):
        return text.upper()
    return get_ticker(text) if get_ticker else None


def detect_tickers(query: str) -> list[str]:
    """Mirror the agent's own routing so the UI can show matching live data."""
    if get_ticker is None or "portfolio" in query.lower():
        return []
    try:
        pair = get_multiple_tickers(query)
        if len(pair) == 2:
            return pair
        ticker = get_ticker(query)
        if ticker:
            return [ticker]
        if manager_agent and manager_agent.is_follow_up_query(query):
            prev = memory_manager.get_last_company()
            if prev:
                return [prev["ticker"]]
    except Exception:
        pass
    return []


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "quota" in low or "rate" in low:
        return "⏳ The AI service is busy or its free quota is used up. Please try again in a minute."
    if "api key" in low or "permission" in low or "401" in msg or "403" in msg:
        return "🔑 The AI service rejected the API key. Check `GEMINI_API_KEY`."
    return f"❌ Something went wrong while generating the analysis.\n\n`{msg[:300]}`"


def run_query(query: str):
    now = time.time()
    if st.session_state.n_queries >= MAX_QUERIES:
        st.warning(f"Demo limit reached ({MAX_QUERIES} questions per session). Refresh to start over.")
        return
    if now - st.session_state.last_query_at < COOLDOWN_SECONDS:
        st.info("Easy there — give it a couple of seconds between questions.")
        return

    st.session_state.last_query_at = now
    st.session_state.n_queries += 1
    st.session_state.messages.append({"role": "user", "content": query})

    tickers: list[str] = []
    try:
        with st.spinner("Pulling live data, indicators and news…"):
            reply = manager_agent.chat_with_agent(query)
            tickers = detect_tickers(query)
    except Exception as exc:
        reply = friendly_error(exc)

    if tickers:
        st.session_state.last_ticker = tickers[0]
    st.session_state.messages.append(
        {"role": "assistant", "content": str(reply), "tickers": tickers}
    )
    st.rerun()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
QUICK = [
    ("Analyze Infosys", "Analyze Infosys"),
    ("Compare Infosys vs TCS", "Compare Infosys and TCS"),
    ("Reliance P/E ratio", "What is the PE ratio of Reliance?"),
    ("HDFC Bank news", "Show latest news for HDFC Bank"),
    ("Add TCS to portfolio", "Add TCS to my portfolio"),
    ("Analyze portfolio", "Analyze portfolio"),
]


def render_message(msg: dict, is_last: bool):
    with st.chat_message(msg["role"], avatar="🧑‍💼" if msg["role"] == "user" else "📈"):
        if msg["role"] == "user":
            st.markdown(msg["content"])
            return
        tickers = msg.get("tickers") or []
        if len(tickers) == 2:
            for col, t in zip(st.columns(2), tickers):
                with col:
                    render_snapshot(t, compact_view=True)
        elif len(tickers) == 1:
            render_snapshot(tickers[0])
            if is_last:
                frame = fetch_chart_frame(tickers[0])
                if isinstance(frame, pd.DataFrame):
                    with st.expander("📉 Price chart & technical indicators (6M)"):
                        view = frame.tail(PERIODS["6M"])
                        st.plotly_chart(
                            build_chart(view, ["SMA 20", "SMA 50", "Bollinger Bands"], 620),
                            use_container_width=True,
                        )
        text = msg["content"]
        if "PORTFOLIO" in text[:150].upper() and "====" in text[:150]:
            st.code(text.strip("= \n"), language=None)  # tool output is column-aligned text
        else:
            st.markdown(format_report(text))


def view_assistant():
    if BACKEND_ERROR is not None:
        st.error(
            "The AI backend couldn't start — most likely **GEMINI_API_KEY** isn't set.\n\n"
            "Locally: put it in `.env`. On Streamlit Cloud: add it under *App settings → Secrets*.\n\n"
            f"Details: `{BACKEND_ERROR}`"
        )
        return

    msgs = st.session_state.messages
    if not msgs:
        st.markdown("##### Ask about any NSE-listed company")
        st.caption("Reports combine live Yahoo Finance data, technical indicators and the latest news.")
        for row in (QUICK[:3], QUICK[3:]):
            for col, (label, q) in zip(st.columns(3), row):
                if col.button(label, use_container_width=True, key=f"quick-{label}"):
                    st.session_state.pending = q
                    st.rerun()
    for i, m in enumerate(msgs):
        render_message(m, is_last=(i == len(msgs) - 1))

    typed = st.chat_input("Ask about a stock… e.g. “Analyze Wipro”, then “Should I buy it?”")
    query = st.session_state.pending or typed
    st.session_state.pending = None
    if query:
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(query)
        run_query(query)


def view_charts():
    c1, c2 = st.columns([2, 1])
    default = (st.session_state.last_ticker or "INFY.NS").replace(".NS", "")
    company = c1.text_input("Company name or NSE symbol", value=default, key="chart_company")
    period = c2.segmented_control("Range", list(PERIODS), default="6M", key="chart_period") or "6M"
    overlays = st.multiselect(
        "Overlays", ["SMA 20", "SMA 50", "SMA 200", "Bollinger Bands"],
        default=["SMA 20", "SMA 50", "Bollinger Bands"], key="chart_overlays",
    )

    ticker = resolve_symbol(company)
    if not ticker:
        st.warning("I couldn't match that to an NSE company. Try “Infosys”, “TCS” or a symbol like `RELIANCE`.")
        return
    st.session_state.last_ticker = ticker

    with st.spinner("Loading price history…"):
        frame = fetch_chart_frame(ticker)
    if isinstance(frame, str):
        st.error(frame)
        return

    render_snapshot(ticker)
    view = frame.tail(PERIODS[period])
    st.plotly_chart(build_chart(view, overlays), use_container_width=True)
    st.markdown("##### Indicator read-out")
    signal_cards(frame)
    st.caption("Signals are computed from the same indicators the AI report uses (SMA, RSI-14, MACD 12/26/9, Bollinger 20/2).")


def view_portfolio():
    if BACKEND_ERROR is not None:
        st.error("Portfolio tools need the backend to start (see the Assistant tab).")
        return

    holdings = portfolio_tool.load_portfolio()
    left, right = st.columns([3, 2])

    with right:
        st.markdown("##### Manage")
        new = st.text_input("Add a company", placeholder="e.g. Wipro", key="pf_add")
        if st.button("➕ Add to portfolio", use_container_width=True) and new:
            ticker = resolve_symbol(new)
            if ticker:
                st.success(portfolio_tool.add_stock(ticker))
                st.rerun()
            else:
                st.warning("Couldn't find that company.")
        if holdings:
            labels = {f'{h["company"]} ({h["ticker"]})': h["ticker"] for h in holdings}
            pick = st.selectbox("Remove", list(labels), index=None, placeholder="Choose a holding", key="pf_rm")
            if st.button("🗑️ Remove selected", use_container_width=True) and pick:
                portfolio_tool.remove_stock(labels[pick])
                st.rerun()
        else:
            if st.button("✨ Load sample portfolio", use_container_width=True):
                portfolio_tool.save_portfolio([
                    {"ticker": "INFY.NS", "company": "Infosys Limited"},
                    {"ticker": "TCS.NS", "company": "Tata Consultancy Services Limited"},
                    {"ticker": "RELIANCE.NS", "company": "Reliance Industries Limited"},
                ])
                st.rerun()

    with left:
        st.markdown("##### Holdings")
        if not holdings:
            st.info("Your portfolio is empty. Add a company, or load the sample portfolio.")
            return
        rows = []
        for h in holdings:
            snap = fetch_snapshot(h["ticker"])
            rows.append({
                "Company": h["company"],
                "Ticker": h["ticker"],
                "Price (₹)": snap.get("price"),
                "Day %": snap.get("change_pct"),
                "P/E": snap.get("pe"),
                "Market cap": inr_cap(snap.get("market_cap")),
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            column_config={
                "Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
                "P/E": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption("Ask the assistant to “Analyze portfolio” for a written breakdown.")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### About")
    st.caption(
        "An agentic research assistant for **NSE-listed** stocks. It fetches live market data, "
        "computes SMA / RSI / MACD / Bollinger indicators, reads recent news and asks "
        "Gemini to write the report."
    )
    st.divider()
    left = max(MAX_QUERIES - st.session_state.n_queries, 0)
    st.progress(left / MAX_QUERIES, text=f"AI questions left this session: {left}/{MAX_QUERIES}")
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        if memory_manager is not None:
            memory_manager.clear_history()
        st.rerun()
    st.divider()
    st.markdown(
        '<p class="disclaimer">Educational project. Not financial or investment advice. '
        "Market data may be delayed or inaccurate. Do your own research.</p>",
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="hero"><h1>AI Stock <span class="accent">Analyst</span></h1>'
    "<p>NSE equities · live data · technical indicators · news · Gemini-written research</p></div>",
    unsafe_allow_html=True,
)
st.write("")

page = st.segmented_control(
    "View", ["💬 Assistant", "📉 Charts", "💼 Portfolio"],
    default="💬 Assistant", key="page", label_visibility="collapsed",
) or "💬 Assistant"

if page == "💬 Assistant":
    view_assistant()
elif page == "📉 Charts":
    view_charts()
else:
    view_portfolio()
