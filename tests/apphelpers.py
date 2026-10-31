"""Drive the real Streamlit app through AppTest with a fake yfinance (no network, no API keys)."""
import base64
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from tests.test_indicators import make_hist

APP = str(Path(__file__).resolve().parent.parent / "app.py")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("NEWS_API_KEY", "test-key")

INFO = dict(longName="Reliance Industries Ltd", sector="Energy", industry="Oil & Gas", currentPrice=1432.55,
            previousClose=1418.2, dayLow=1410.1, dayHigh=1440.9, fiftyTwoWeekLow=1114.85,
            fiftyTwoWeekHigh=1608.95, marketCap=19_385_400_000_000, trailingPE=24.3)


def trend_hist(kind, n=1250):
    idx = pd.bdate_range(end="2026-10-29", periods=n, tz="Asia/Kolkata")
    rng = np.random.default_rng(5)
    base = np.linspace(1000, 2200, n) if kind == "up" else np.linspace(2200, 1000, n)
    close = base + rng.normal(0, 4, n)
    return pd.DataFrame({"Open": close - 1, "High": close + 4, "Low": close - 4, "Close": close,
                         "Volume": rng.integers(1e6, 4e6, n)}, index=idx)


def run_app(history=None, page="📉 Charts", state=None, raises=None):
    """Return a ready AppTest. `history` may be a DataFrame, or None for the default random walk."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    hist = make_hist(1250) if history is None else history

    class FakeTicker:
        def __init__(self, t):
            self.t = t
        info = INFO

        def history(self, period="5y", **kw):
            if raises:
                raise RuntimeError(raises)
            return hist.copy()

    yf.Ticker = FakeTicker
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.session_state["page"] = page
    return at.run()


def figures(at):
    return [json.loads(el.proto.spec) for el in at.get("plotly_chart")]


def trace_names(fig):
    return [t.get("name") for t in fig["data"]]


def cards(at):
    out = {}
    for m in at.markdown:
        if 'class="signal"' in m.value:
            k = re.search(r'class="k">([^<]+)', m.value).group(1)
            v = re.search(r'class="v (\w+)">([^<]*)', m.value)
            out[k] = (v.group(1), v.group(2))
    return out


def decode(v):
    """Plotly typed arrays reach the browser as {"dtype": "f8", "bdata": base64}."""
    if isinstance(v, dict) and "bdata" in v:
        return np.frombuffer(base64.b64decode(v["bdata"]), dtype=np.dtype(v["dtype"]).newbyteorder("<")).astype(float)
    return np.asarray(v, dtype=float)
