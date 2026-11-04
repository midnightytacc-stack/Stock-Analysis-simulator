"""
AI Stock Analysis Assistant — web UI (Streamlit)

Run locally:   streamlit run app.py
Deploy:        see DEPLOY.md

This file only *wraps* the existing project (agents/, tools/, utils/).
Nothing in the backend needs to change.
"""
from __future__ import annotations

import html
import inspect
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
import streamlit as st
import yfinance as yf

# The backend uses paths relative to the project root (memory/, data/).
APP_DIR = Path(__file__).resolve().parent
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))

from utils.charting import (  # noqa: E402  (needs APP_DIR on sys.path)
    DEFAULT_OVERLAYS, OVERLAY_OPTIONS, build_chart, chart_notes, compute_indicator_frame,
)
from utils.portfolio_actions import add_selected, holding_tickers  # noqa: E402
from utils.stock_search import load_universe, normalise, search  # noqa: E402

st.set_page_config(
    page_title="AI Stock Analyst · NSE",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
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

# `.env` must be loaded before the knobs below are read; config.py (which also calls load_dotenv)
# is only imported further down, so without this `.env` values for these settings were ignored.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is in requirements.txt; deployed secrets still work without it
    pass

# Optional per-session cap on AI questions for public showcases. 0 (the default) = the app imposes
# no cap. Gemini's own rate/quota limits still apply and are reported when they are hit.
MAX_QUERIES = max(int(os.getenv("MAX_QUERIES_PER_SESSION", "0") or 0), 0)
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


DATA_DIR_KEY = "data_dir"   # st.session_state key holding this visitor's private storage folder


@st.cache_resource
def _install_session_paths():
    """
    The backend stores memory/portfolio in module-level path constants. We swap them for
    path-like objects that resolve to the current visitor's private folder.

    The folder is looked up in st.session_state, which belongs to the *session*. (It used to live
    in a threading.local set at the top of the script, but `@st.fragment` reruns - used by the
    portfolio search/Add button - run on a different thread without re-executing the top of the
    script, so they silently read and wrote the shared fallback files instead of the visitor's.)
    """

    class SessionPath(os.PathLike):
        def __init__(self, filename: str, fallback: str):
            self.filename, self.fallback = filename, fallback

        def __fspath__(self) -> str:
            folder = st.session_state.get(DATA_DIR_KEY)
            return str(Path(folder) / self.filename) if folder else self.fallback

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


_install_session_paths()

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
    st.session_state[DATA_DIR_KEY] = str(_folder)
else:
    st.session_state.pop(DATA_DIR_KEY, None)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
# Theme tokens: (light, dark). Single source for every custom (non-native) surface.
# Native widgets read the same values from .streamlit/config.toml - keep both in
# sync (tests/test_theme_tokens.py checks this).
THEME = {
    "bg":      ("#F5F7FA", "#0B1118"),
    "card":    ("#FFFFFF", "#121B26"),
    "surface": ("#EDF2F7", "#182433"),
    "text":    ("#172B4D", "#E8EEF5"),
    "text-2":  ("#526277", "#A7B4C5"),
    "border":  ("#D8E1EB", "#293747"),
    "accent":  ("#0F766E", "#45C4B0"),
    "pos":     ("#0B7A4B", "#3DDC97"),
    "neg":     ("#C0213D", "#FF6B87"),
    "neu":     ("#8A5A00", "#F6C177"),
}

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,500;9..144,600"
    "&display=swap');\n"
)


def theme_variables_css() -> str:
    """
    Emit --sa-* variables on .stApp.

    Streamlit sets CSS `color-scheme` on .stApp from the *active* theme (OS
    preference or the Settings switch), so `light-dark()` follows theme changes
    instantly - no Python-side detection, which can be stale after a switch.
    Browsers without light-dark() fall back to light values, or to the OS
    preference via prefers-color-scheme.
    """
    light = "".join(f"--sa-{k}:{lt};" for k, (lt, _) in THEME.items())
    dark = "".join(f"--sa-{k}:{dk};" for k, (_, dk) in THEME.items())
    both = "".join(f"--sa-{k}:light-dark({lt},{dk});" for k, (lt, dk) in THEME.items())
    return (
        f".stApp{{{light}}}\n"
        f"@media (prefers-color-scheme: dark){{.stApp{{{dark}}}}}\n"
        f"@supports (color: light-dark(#000,#fff)){{.stApp{{{both}}}}}\n"
    )


COMPONENT_CSS = """
.stApp { font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.stApp .block-container { padding-top: 1.6rem; max-width: 1180px; }
footer, [data-testid="stAppDeployButton"], .stDeployButton { display: none !important; }

/* ---- Header / branding ---- */
.stApp .hero h1 { font-family: 'Fraunces', serif; font-weight: 600;
  font-size: clamp(1.8rem, 4vw, 2.3rem); letter-spacing: -0.01em; margin: 0;
  line-height: 1.1; color: var(--sa-text); }
.stApp .hero h1 .accent { color: var(--sa-accent); }
.stApp .hero p { margin: .4rem 0 0 0; color: var(--sa-text-2); font-size: .95rem; }

/* ---- Page navigation (st.segmented_control, key="page") ----
   Sticky, so Assistant / Charts / Portfolio stay reachable while a long conversation scrolls.
   top = Streamlit's fixed header height (3.75rem); the opaque page-coloured background stops
   scrolled content showing through; z-index sits above Plotly's modebar (1001). */
.stApp .st-key-page { position: sticky; top: 3.75rem; z-index: 1002; width: 100% !important;
  background: var(--sa-bg); padding: .45rem 0 .9rem 0; }
.stApp .st-key-page > div { width: fit-content; max-width: 100%;
  border-bottom: 1px solid var(--sa-border); padding-bottom: .65rem; }
.stApp .st-key-page button { font-weight: 600; }

/* ---- KPI cards: native st.metric + custom .signal share one card style ---- */
.stApp [data-testid="stMetric"], .stApp .signal {
  background: var(--sa-card); border: 1px solid var(--sa-border); border-radius: 12px;
  padding: .7rem .9rem; box-sizing: border-box; min-width: 0; }
@media (min-width: 641px) {
  .stApp [data-testid="stMetric"], .stApp .signal { min-height: 5.2rem; }
}
.stApp [data-testid="stMetricLabel"],
.stApp [data-testid="stMetricLabel"] p { color: var(--sa-text-2); font-size: .72rem;
  font-weight: 500; text-transform: uppercase; letter-spacing: .06em; }
.stApp [data-testid="stMetricValue"] { color: var(--sa-text);
  font-family: 'IBM Plex Mono', monospace; font-weight: 500; line-height: 1.25;
  font-size: clamp(.95rem, .55vw + .8rem, 1.15rem); }
.stApp [data-testid="stMetricValue"] > div { overflow: visible; text-overflow: clip;
  white-space: normal; overflow-wrap: anywhere; }
.stApp [data-testid="stMetricValue"] p { white-space: normal; overflow: visible;
  text-overflow: clip; overflow-wrap: break-word; }
.stApp [data-testid="stMetricDelta"] { font-size: .8rem; font-weight: 600; }

.stApp .signal .k { color: var(--sa-text-2); font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em; }
.stApp .signal .v { color: var(--sa-text); font-family: 'IBM Plex Mono', monospace;
  font-size: 1.05rem; font-weight: 600; margin-top: .15rem; line-height: 1.25;
  overflow-wrap: anywhere; }
.stApp .signal .d { color: var(--sa-text-2); font-size: .8rem; margin-top: .1rem; }
.stApp .signal .v.pos { color: var(--sa-pos); }
.stApp .signal .v.neg { color: var(--sa-neg); }
.stApp .signal .v.neu { color: var(--sa-neu); }

/* ---- Supporting text ---- */
.stApp .tickerline { font-size: .85rem; color: var(--sa-text-2); margin: .2rem 0 .4rem 0; }
.stApp .tickerline b { color: var(--sa-text); }
.stApp .disclaimer { font-size: .75rem !important; color: var(--sa-text-2); line-height: 1.4; }

/* ---- Chat, expanders ---- */
.stApp [data-testid="stChatMessage"] { background: transparent; }
.stApp [data-testid="stChatMessageContent"] h2 { font-family: 'Fraunces', serif;
  font-size: 1.5rem; border-bottom: 1px solid var(--sa-border); padding-bottom: .4rem; }
.stApp [data-testid="stChatMessageContent"] h3 { font-size: 1.05rem; margin-top: 1.1rem; }
.stApp [data-testid="stExpander"] details { background: var(--sa-card);
  border-color: var(--sa-border); border-radius: 12px; }

/* ---- Sidebar: contextual About ---- */
.stApp [data-testid="stSidebar"] .sa-about h3 { font-size: 1.05rem; margin: 0 0 .4rem 0; padding: 0; }
.stApp [data-testid="stSidebar"] .sa-about p { color: var(--sa-text-2); font-size: .82rem; line-height: 1.45; margin: 0; }
.stApp [data-testid="stSidebar"] .sa-about p.sa-note { color: var(--sa-text); font-size: .78rem; }
.stApp [data-testid="stSidebar"] ul { margin: .3rem 0 .5rem 0; padding-left: 1.1rem; }
.stApp [data-testid="stSidebar"] li { color: var(--sa-text-2); font-size: .82rem; line-height: 1.45; margin-bottom: .2rem; }
.stApp [data-testid="stSidebar"] li strong { color: var(--sa-text); }

/* ---- Portfolio: the Holdings table needs ~36rem; below that Manage wraps underneath ---- */
.stApp .st-key-pf_layout [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
.stApp .st-key-pf_layout [data-testid="stColumn"]:first-child { min-width: min(100%, 36rem); }
.stApp .st-key-pf_layout [data-testid="stColumn"]:last-child { min-width: min(100%, 16rem); }

/* ---- Portfolio: selected company ---- */
.stApp .sa-selected { background: var(--sa-card); border: 1px solid var(--sa-border);
  border-left: 3px solid var(--sa-accent); border-radius: 12px; padding: .6rem .9rem;
  margin: .5rem 0 .6rem 0; }
.stApp .sa-selected .k { color: var(--sa-text-2); font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em; }
.stApp .sa-selected .v { color: var(--sa-text); font-size: 1rem; font-weight: 600;
  line-height: 1.3; overflow-wrap: anywhere; }
.stApp .sa-selected .d { color: var(--sa-text-2); font-size: .8rem; margin-top: .1rem; }

/* ---- Narrow screens ---- */
@media (max-width: 640px) {
  .stApp .modebar-container { display: none; }  /* the chart toolbar would sit on top of a wrapped legend */
  .stApp .block-container { padding-left: 1rem; padding-right: 1rem; }
  .stApp .hero p { font-size: .88rem; }
}
"""

st.markdown(
    "<style>\n" + FONT_IMPORT + theme_variables_css() + COMPONENT_CSS + "</style>",
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


class ChartDataError(Exception):
    """Raised inside the cached download so a failure is never cached (a retry really retries)."""


@st.cache_data(ttl=900, show_spinner=False)
def _download_chart_frame(ticker: str, history_period: str):
    try:
        hist = yf.Ticker(ticker).history(period=history_period)
    except Exception as exc:
        raise ChartDataError(f"Could not download price history ({type(exc).__name__}): {exc}") from exc
    if hist is None or hist.empty:
        raise ChartDataError("No price history found for this ticker.")
    try:
        df = compute_indicator_frame(hist)
    except Exception as exc:
        raise ChartDataError(f"Could not compute indicators ({type(exc).__name__}): {exc}") from exc
    if len(df) < 2:
        raise ChartDataError("Not enough complete price history to draw a chart for this ticker.")
    return df


def fetch_chart_frame(ticker: str, history_period: str = "5y"):
    """
    Daily candles + every indicator the AI report talks about, as a DataFrame - or an error
    message (str) the caller shows. `history_period` is what Yahoo Finance is asked for.
    """
    try:
        return _download_chart_frame(ticker, history_period)
    except ChartDataError as exc:
        return str(exc)


# Trading days shown per range (None = everything that was fetched).
PERIODS = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 5000, "All Time": None}
# What Yahoo is asked for. "All Time" asks for the provider's full history ("max"); every other
# range is a slice of 5 years, which also gives SMA 200 / MACD enough warm-up bars and lets the
# user switch between those ranges without another download.
HISTORY_PERIOD = {"All Time": "max"}


def history_period_for(range_label: str) -> str:
    return HISTORY_PERIOD.get(range_label, "5y")


def history_note(frame: pd.DataFrame, view: pd.DataFrame, range_label: str) -> str | None:
    """One line saying what is actually on screen when it differs from what was asked for."""
    if view is None or len(view) < 2:
        return None
    first, last = view.index[0], view.index[-1]
    span_years = (last - first).days / 365.25
    if range_label == "All Time":
        return (f"All Time shows the full history Yahoo Finance has for this stock: {len(view):,} trading days "
                f"({span_years:.1f} years), from {first:%d %b %Y}.")
    wanted = PERIODS.get(range_label)
    if wanted and len(frame) < wanted:
        return (f"Only {len(frame):,} trading days of history are available for this stock "
                f"(since {first:%d %b %Y}), so the {range_label} range shows all of it.")
    return None


def render_price_chart(view: pd.DataFrame, overlays: list[str], height: int):
    """One renderer for the Charts page and the Assistant expander."""
    if view is None or len(view) < 2:
        st.info("Not enough price history to draw a chart for this period.")
        return
    st.plotly_chart(build_chart(view, overlays, height), use_container_width=True)
    for note in chart_notes(view, overlays):
        st.caption(f"ℹ️ {note}")


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


def _retry_seconds(msg: str) -> int | None:
    m = (re.search(r"retry in ([\d.]+)\s*s", msg, re.I)
         or re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", msg))
    return int(float(m.group(1))) + 1 if m else None


def classify_error(exc: Exception) -> tuple[str, bool]:
    """(message for the UI, whether trying again can help). Says what actually went wrong."""
    msg = str(exc)
    low = msg.lower()
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()

    if code == 429 or status == "RESOURCE_EXHAUSTED" or "resource_exhausted" in low or re.search(r"\b429\b", msg):
        wait = _retry_seconds(msg)
        compact_low = low.replace(" ", "").replace("_", "")
        if "perday" in compact_low:
            kind = "the Gemini API's **daily** quota for this API key is used up"
            retry = "It resets on Google's schedule, so retrying now will not help - try again later, or use a key or plan with a higher quota."
        elif "perminute" in compact_low or wait:
            kind = "the Gemini API's **per-minute** rate limit was reached"
            retry = f"Wait about {wait or 60} seconds, then press **Try again**."
        else:
            kind = "the Gemini API reported that a rate limit or quota was reached"
            retry = "It may be a per-minute or a daily limit; wait a minute and press **Try again**."
        return (f"⏳ This is a limit on the Gemini API key, not a limit set by this app: {kind} (HTTP 429). {retry}", True)

    if (code in (401, 403) or status in ("PERMISSION_DENIED", "UNAUTHENTICATED")
            or "api key not valid" in low or "api_key_invalid" in low or "permission denied" in low):
        return ("🔑 The Gemini API rejected the API key (invalid, expired or without access). Check `GEMINI_API_KEY`.", False)

    if code in (500, 502, 503, 504) or status in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED") or "overloaded" in low:
        return ("🌐 The Gemini model is temporarily unavailable or overloaded (HTTP "
                f"{code or 503}). This usually clears within a minute - press **Try again**.", True)

    name = type(exc).__name__.lower()
    if "timeout" in name or "connect" in name or "timed out" in low:
        return ("🌐 Couldn't reach the Gemini API (network problem or timeout). Check the connection and press **Try again**.", True)

    return (f"❌ Something went wrong while generating the analysis.\n\n`{type(exc).__name__}: {msg[:300]}`", True)


def friendly_error(exc: Exception) -> str:
    return classify_error(exc)[0]


def run_query(query: str):
    now = time.time()
    # MAX_QUERIES is an optional cap for public showcases; 0 (default) means the app sets no cap.
    if MAX_QUERIES and st.session_state.n_queries >= MAX_QUERIES:
        st.warning(f"This deployment limits each session to {MAX_QUERIES} AI questions. "
                   "Refresh the page to start a new session.")
        return
    if now - st.session_state.last_query_at < COOLDOWN_SECONDS:
        st.info("Easy there — give it a couple of seconds between questions.")
        return

    st.session_state.last_query_at = now
    st.session_state.n_queries += 1
    st.session_state.messages.append({"role": "user", "content": query})

    tickers: list[str] = []
    retry_query = None
    try:
        with st.spinner("Pulling live data, indicators and news…"):
            reply = manager_agent.chat_with_agent(query)
            tickers = detect_tickers(query)
    except Exception as exc:
        reply, retryable = classify_error(exc)
        retry_query = query if retryable else None
        st.session_state.n_queries -= 1      # a failed request is not a used question

    if tickers:
        st.session_state.last_ticker = tickers[0]
    st.session_state.messages.append(
        {"role": "assistant", "content": str(reply), "tickers": tickers, "retry_query": retry_query}
    )
    st.rerun()


def _retry_last():
    """'Try again' button: drop the failed exchange and ask the same question again."""
    msgs = st.session_state.messages
    if msgs and msgs[-1].get("retry_query"):
        st.session_state.pending = msgs[-1]["retry_query"]
        del msgs[-2:]
        st.session_state.last_query_at = 0.0     # a deliberate retry is not "too fast"


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
                        overlays = st.multiselect(
                            "Overlays", OVERLAY_OPTIONS, default=DEFAULT_OVERLAYS,
                            key="assistant_chart_overlays",
                        )
                        render_price_chart(frame.tail(PERIODS["6M"]), overlays, 780)
        text = msg["content"]
        if "PORTFOLIO" in text[:150].upper() and "====" in text[:150]:
            st.code(text.strip("= \n"), language=None)  # tool output is column-aligned text
        else:
            st.markdown(format_report(text))
        if is_last and msg.get("retry_query"):
            st.button("↻ Try again", key="retry-last", on_click=_retry_last)


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
    universe = load_universe()
    if not universe.ok:
        st.error(f"{universe.error} Company search is unavailable, so charts can't be loaded.")
        return

    # Streamlit drops the state of widgets that aren't rendered (e.g. while on another page), so the
    # choices are mirrored into plain session keys and restored before the widgets are created.
    for key, saved, fallback in (("chart_period", "saved_chart_period", "6M"),
                                 ("chart_overlays", "saved_chart_overlays", list(DEFAULT_OVERLAYS))):
        if key not in st.session_state:
            st.session_state[key] = st.session_state.get(saved, fallback)

    c1, c2 = st.columns([2, 1])
    with c1:
        chart_company_picker()
    period = c2.segmented_control("Range", list(PERIODS), key="chart_period") or "6M"
    overlays = st.multiselect("Overlays", OVERLAY_OPTIONS, key="chart_overlays")
    st.session_state.saved_chart_period, st.session_state.saved_chart_overlays = period, list(overlays)

    company = universe.get(st.session_state.get(CHART_SELECTED) or CHART_DEFAULT)
    if company is None:
        st.warning(f"“{st.session_state.get(CHART_SELECTED)}” isn't in the NSE company list. "
                   "Search for a company above and pick one of the suggestions.")
        return
    ticker = company.ticker
    st.session_state.last_ticker = ticker

    with st.spinner("Loading price history…"):
        frame = fetch_chart_frame(ticker, history_period_for(period))
    if isinstance(frame, str):
        st.error(f"{company.name} ({ticker}): {frame}")
        st.button("Try again", key="chart_retry")      # any click reruns the page; failures aren't cached
        return

    render_snapshot(ticker)
    view = frame if PERIODS[period] is None else frame.tail(PERIODS[period])
    render_price_chart(view, overlays, 920)
    note = history_note(frame, view, period)
    if note:
        st.caption(f"ℹ️ {note}")
    st.markdown("##### Indicator read-out")
    signal_cards(frame)
    st.caption(
        "Signals are computed from the same indicators the AI report uses (SMA, RSI-14, MACD 12/26/9, "
        "Bollinger 20/2). They are analytical indicators, not predictions or guarantees of future returns."
    )


# Newer Streamlit can commit a text input while the user types (after a short pause); older
# versions commit on Enter / when the field loses focus. Detect it rather than assume.
_LIVE_SEARCH = {"live": True} if "live" in inspect.signature(st.text_input).parameters else {}
PF_QUERY, PF_SELECTED, PF_FLASH, PF_RESET, PF_LABELS = (
    "pf_query", "pf_selected", "pf_flash", "pf_reset", "pf_labels")
PF_RM, PF_RM_LABELS = "pf_rm", "pf_rm_labels"
CHART_SELECTED = "last_ticker"      # the Charts page shows the last company the Assistant/Charts used
CHART_DEFAULT = "INFY.NS"


def _remember_pick(radio_key: str, labels_key: str, selected_key: str, clear_query_key: str | None,
                   picked_key: str):
    """Radio on_change: store the explicitly chosen company so it survives every rerun."""
    ticker = st.session_state.get(labels_key, {}).get(st.session_state.get(radio_key))
    if ticker:
        st.session_state[selected_key] = ticker
        st.session_state[picked_key] = True
        if clear_query_key:
            st.session_state[clear_query_key] = ""      # allowed here: callbacks run before the widgets


def company_picker(prefix: str, universe, *, selected_key: str, default: str | None = None,
                   label: str = "Search NSE companies", card_label: str = "Selected",
                   rerun_on_pick: bool = False, clear_query_on_pick: bool = False, card_note=None):
    """
    Search box + ranked suggestions (utils.stock_search over data/nse_symbols.csv), shared by the
    Portfolio and Charts pages. The explicit pick is kept in st.session_state[selected_key] as an
    NSE ticker ("INFY.NS"); it is never auto-picked from the typed text. Returns the chosen
    `Company` (or None). Call it from an @st.fragment so typing re-runs only this widget group;
    `rerun_on_pick` then triggers one full rerun for pages that depend on the choice.
    """
    query_key, labels_key, picked_key = f"{prefix}_query", f"{prefix}_labels", f"{prefix}_picked"
    if st.session_state.pop(picked_key, False) and rerun_on_pick:
        st.rerun()

    query = st.text_input(label, placeholder="Company name or ticker, e.g. Infosys or INFY",
                          key=query_key, **_LIVE_SEARCH)
    result = search(query, universe)
    if result.matches:
        labels = {c.label: c.ticker for c in result.companies}
        st.session_state[labels_key] = labels
        radio_key = f"{prefix}_pick::{normalise(query)}"   # new query -> fresh radio, never a stale index
        st.radio("Matching companies", list(labels), index=None, key=radio_key, on_change=_remember_pick,
                 args=(radio_key, labels_key, selected_key, query_key if clear_query_on_pick else None, picked_key))
        if result.total > len(result.matches):
            st.caption(f"Showing the top {len(result.matches)} of {result.total} matches — "
                       "keep typing to narrow it down.")
    elif query.strip():
        st.warning(result.message)
    else:
        st.caption(result.message)

    chosen = universe.get(st.session_state.get(selected_key) or default)
    if st.session_state.get(selected_key) and chosen is None and default is None:
        st.session_state.pop(selected_key, None)   # symbol no longer in the list
    if chosen:
        note = card_note(chosen) if card_note else ""
        st.markdown(
            f'<div class="sa-selected"><div class="k">{html.escape(card_label)}</div>'
            f'<div class="v">{html.escape(chosen.name)}</div>'
            f'<div class="d">{html.escape(chosen.symbol)} · NSE · {html.escape(chosen.ticker)}{note}</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No company selected yet — pick one of the suggestions above." if result.matches
                   else "No company selected yet.")
    return chosen


@st.fragment
def chart_company_picker():
    universe = load_universe()
    company_picker("chart", universe, selected_key=CHART_SELECTED, default=CHART_DEFAULT,
                   label="Company name or NSE symbol", card_label="Charting",
                   rerun_on_pick=True, clear_query_on_pick=True)


def _clear_pick():
    st.session_state.pop(PF_SELECTED, None)


@st.fragment
def portfolio_search():
    """
    Search -> explicit selection -> confirm. A fragment, so typing re-runs only this widget group
    (not the holdings table and its price look-ups). The chosen company lives in
    st.session_state[PF_SELECTED] until it is added, cleared or replaced; it is never auto-picked.
    """
    flash = st.session_state.pop(PF_FLASH, None)
    if flash:
        getattr(st, flash[0])(flash[1])
    if st.session_state.pop(PF_RESET, False):
        st.session_state[PF_QUERY] = ""   # allowed: runs before the widget is created this run

    universe = load_universe()
    if not universe.ok:
        st.error(f"{universe.error} Company search is unavailable, but you can still remove holdings.")
        return

    def already_held(company) -> str:
        return " · already in your portfolio" if company.ticker in holding_tickers(portfolio_tool) else ""

    chosen = company_picker("pf", universe, selected_key=PF_SELECTED, card_note=already_held)

    add_col, clear_col = st.columns([3, 2])
    if add_col.button("➕ Add to Portfolio", type="primary", use_container_width=True, key="pf_add_btn"):
        outcome = add_selected(st.session_state.get(PF_SELECTED), universe, portfolio_tool)
        if outcome.added:
            st.session_state[PF_FLASH] = (outcome.level, outcome.message)
            st.session_state.pop(PF_SELECTED, None)
            st.session_state[PF_RESET] = True
            st.rerun()   # full rerun so the Holdings table refreshes
        getattr(st, outcome.level)(outcome.message)
    if chosen:
        clear_col.button("Clear", use_container_width=True, key="pf_clear_btn", on_click=_clear_pick)


def _remove_selected_holding():
    """'Remove selected' on_click: runs before the page, so the table below already reflects it."""
    ticker = st.session_state.get(PF_RM_LABELS, {}).get(st.session_state.get(PF_RM))
    if not ticker:
        st.session_state[PF_FLASH] = ("warning", "Choose a holding to remove first.")
        return
    try:
        message = portfolio_tool.remove_stock(ticker)
        gone = ticker not in holding_tickers(portfolio_tool)
    except Exception as exc:
        st.session_state[PF_FLASH] = ("error", f"Couldn't update your portfolio ({type(exc).__name__}: {exc}).")
        return
    st.session_state[PF_FLASH] = ("success" if gone else "warning", message)
    st.session_state[PF_RM] = None


def view_portfolio():
    if BACKEND_ERROR is not None:
        st.error("Portfolio tools need the backend to start (see the Assistant tab).")
        return

    try:
        holdings = portfolio_tool.load_portfolio()
    except (ValueError, OSError) as exc:
        st.error(f"Couldn't read your portfolio. {exc}")
        return
    with st.container(key="pf_layout"):    # keyed so the CSS below can make the two columns wrap
        left, right = st.columns([3, 2])

    with right:
        st.markdown("##### Manage")
        portfolio_search()
        if holdings:
            labels = {f'{h["company"]} ({h["ticker"]})': h["ticker"] for h in holdings}
            st.session_state[PF_RM_LABELS] = labels
            st.selectbox("Remove", list(labels), index=None, placeholder="Choose a holding", key=PF_RM)
            st.button("🗑️ Remove selected", use_container_width=True, on_click=_remove_selected_holding)

    with left:
        st.markdown("##### Holdings")
        if not holdings:
            st.info("Your portfolio is empty. Search for a company under Manage, select it, and press Add to Portfolio.")
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
PAGES = ["💬 Assistant", "📉 Charts", "💼 Portfolio"]
DEFAULT_PAGE = PAGES[0]

# Contextual sidebar copy. Keyed by the navigation labels so it can never disagree with the page shown.
ABOUT = {
    "💬 Assistant": {
        "title": "About Assistant",
        "summary": (
            "An AI-powered NSE stock research assistant that combines available market data, technical "
            "indicators, company information, financial metrics, and recent news to produce structured "
            "research reports."
        ),
        "points": [
            "**Analyze** a company, e.g. “Analyze Infosys”.",
            "**Compare** two stocks, e.g. “Compare Infosys and TCS”.",
            "**Research** technical indicators and financial metrics such as P/E.",
            "**News**: the latest headlines for a company.",
            "**Follow up** with “its P/E?” and the last company is remembered.",
            "**Portfolio**: add, remove or view holdings, or ask for “Analyze portfolio”.",
        ],
        "note": "Reports are written by Gemini from the data the app can fetch. They can be incomplete or wrong.",
    },
    "📉 Charts": {
        "title": "About Charts",
        "summary": (
            "Explore historical NSE stock prices with candlestick charts, moving averages, Bollinger Bands, "
            "RSI, MACD, and volume."
        ),
        "points": [
            "**Pick a stock**: type a company name or NSE symbol and choose a suggestion.",
            "**Choose a range**: 3M, 6M, 1Y, 2Y, 5Y or All Time (the full history available).",
            "**Overlays**: switch SMA 20, SMA 50, SMA 200 and Bollinger Bands on or off.",
            "**Panels**: RSI (14) is read against its 30 and 70 levels; MACD shows its line, signal line and histogram.",
            "**Read-out**: the cards under the chart summarise the latest RSI, MACD, trend and Bollinger position.",
        ],
        "note": "Historical indicators describe the past. They do not guarantee future performance.",
    },
    "💼 Portfolio": {
        "title": "About Portfolio",
        "summary": (
            "Build an NSE stock watchlist and review available market metrics for your selected companies "
            "in one place."
        ),
        "points": [
            "**Search** by company name or ticker, **select** a suggestion, then press Add to Portfolio.",
            "**Remove** a holding whenever you like.",
            "**Review** price, day change, P/E and market cap in the Holdings table, where available.",
            "**Analysis**: ask the Assistant to “Analyze portfolio”.",
        ],
        "note": "This is a watchlist. It does not trade, connect to a broker, or track quantities or returns.",
    },
}


def render_about(page: str):
    about = ABOUT.get(page, ABOUT[DEFAULT_PAGE])
    st.markdown(f"<div class=\"sa-about\"><h3>{html.escape(about['title'])}</h3></div>", unsafe_allow_html=True)
    st.markdown(f"<div class=\"sa-about\"><p>{html.escape(about['summary'])}</p></div>", unsafe_allow_html=True)
    st.markdown("\n".join(f"- {p}" for p in about["points"]))
    st.markdown(f"<div class=\"sa-about\"><p class=\"sa-note\">{html.escape(about['note'])}</p></div>", unsafe_allow_html=True)


st.markdown(
    '<div class="hero"><h1>AI Stock <span class="accent">Analyst</span></h1>'
    "<p>NSE equities · live data · technical indicators · news · Gemini-written research</p></div>",
    unsafe_allow_html=True,
)
st.write("")

# `page` is the single source of truth: the sidebar About and the view router both use this value
# (including the fallback when the active segment is clicked again and the control returns None).
page = st.segmented_control(
    "View", PAGES, default=DEFAULT_PAGE, key="page", label_visibility="collapsed",
) or DEFAULT_PAGE

with st.sidebar:
    render_about(page)
    st.divider()
    if MAX_QUERIES:
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

if page == "💬 Assistant":
    view_assistant()
elif page == "📉 Charts":
    view_charts()
else:
    view_portfolio()
