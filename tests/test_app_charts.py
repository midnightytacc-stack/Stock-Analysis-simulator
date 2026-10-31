"""End-to-end: the real app, fake market data."""
import numpy as np
import pandas as pd
import pytest

from tests.apphelpers import cards, decode, figures, run_app, trace_names, trend_hist
from tests.test_indicators import make_hist
from utils.charting import BB_LOWER, BB_UPPER, OVERLAY_OPTIONS, compute_indicator_frame

PERIOD_BARS = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 1250}
CORE = {"Price", "Volume", "RSI (14)", "MACD line", "Signal line (9)",
        "Histogram (positive)", "Histogram (negative)"}


def no_errors(at):
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("period,bars", PERIOD_BARS.items())
def test_every_period_renders_all_panels(period, bars):
    at = run_app(state={"chart_period": period})
    no_errors(at)
    (fig,) = figures(at)
    got = set(trace_names(fig))
    assert CORE <= got and {"SMA 20", "SMA 50", BB_UPPER, BB_LOWER} <= got
    price = next(t for t in fig["data"] if t["name"] == "Price")
    assert len(price["x"]) == bars
    assert at.get("plotly_chart")[0].proto.theme == "streamlit"      # live Streamlit theme is applied


def test_overlay_multiselect_toggles_every_overlay():
    at = run_app()
    ms = at.multiselect(key="chart_overlays")
    assert ms.options == OVERLAY_OPTIONS
    for chosen in (OVERLAY_OPTIONS, ["SMA 200"], ["SMA 20"], ["Bollinger Bands"], []):
        ms.set_value(chosen)
        at.run()
        no_errors(at)
        ms = at.multiselect(key="chart_overlays")
        got = set(trace_names(figures(at)[0]))
        for sma in ("SMA 20", "SMA 50", "SMA 200"):
            assert (sma in got) == (sma in chosen), (chosen, sma)
        assert ({BB_UPPER, BB_LOWER} <= got) == ("Bollinger Bands" in chosen)
        assert CORE <= got


def test_assistant_expander_chart_has_all_overlays_available():
    msgs = [{"role": "user", "content": "Analyze Reliance"},
            {"role": "assistant", "content": "## Report\nbody", "tickers": ["RELIANCE.NS"]}]
    at = run_app(page="💬 Assistant", state={"messages": msgs})
    no_errors(at)
    ms = at.multiselect(key="assistant_chart_overlays")
    assert ms.options == OVERLAY_OPTIONS
    (fig,) = figures(at)
    assert CORE <= set(trace_names(fig)) and "SMA 200" not in trace_names(fig)
    assert next(t for t in fig["data"] if t["name"] == "Price")["x"].__len__() == 126
    ms.set_value(OVERLAY_OPTIONS)
    at.run()
    no_errors(at)
    assert {"SMA 20", "SMA 50", "SMA 200", BB_UPPER, BB_LOWER} <= set(trace_names(figures(at)[0]))


def test_assistant_and_charts_page_use_the_same_figure_builder():
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "x", "tickers": ["RELIANCE.NS"]}]
    a = figures(run_app(page="💬 Assistant", state={"messages": msgs}))[0]
    c = figures(run_app(page="📉 Charts", state={"chart_period": "6M"}))[0]
    assert trace_names(a) == trace_names(c)
    assert a["layout"]["yaxis3"]["range"] == c["layout"]["yaxis3"]["range"] == [0, 100]


def test_short_history_shows_a_useful_message_and_still_renders():
    at = run_app(history=make_hist(30), state={"chart_overlays": OVERLAY_OPTIONS})
    no_errors(at)
    captions = " ".join(c.value for c in at.caption)
    assert "SMA 200 isn't shown" in captions and "SMA 50 isn't shown" in captions
    assert "signal line" in captions.lower()
    got = trace_names(figures(at)[0])
    assert "SMA 200" not in got and "SMA 50" not in got and "SMA 20" in got
    assert "MACD line" in got and "Signal line (9)" not in got
    sig = cards(at)
    assert sig["Trend"][1] == "—"                                   # unavailable state, not a fake value


@pytest.mark.parametrize("hist,raises,expected", [
    (pd.DataFrame(), None, "No price history found"),
    (make_hist(1), None, "Not enough complete price history"),
    (None, "boom", "Could not download price history: boom"),
])
def test_missing_or_insufficient_data_message(hist, raises, expected):
    at = run_app(history=hist if hist is not None else make_hist(10), raises=raises)
    assert not at.exception
    assert any(expected in e.value for e in at.error), [e.value for e in at.error]
    assert not figures(at)


def test_rows_with_nan_ohlc_are_dropped_not_plotted_as_zero():
    h = make_hist(400)
    h.iloc[-1, h.columns.get_loc("Close")] = np.nan          # e.g. an unfinished trading day
    at = run_app(history=h)
    no_errors(at)
    price = next(t for t in figures(at)[0]["data"] if t["name"] == "Price")
    assert len(price["x"]) == 126 and price["x"][-1].startswith(str(h.index[-2].date()))
    close = decode(price["close"])
    assert not np.isnan(close).any() and close.min() > 0


def expected_cards(hist):
    """Signal-card state derived independently (manual rolling/EWM maths, same documented rules)."""
    c = hist["Close"].astype(float)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    s50, s200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    mid, sd = c.rolling(20).mean().iloc[-1], c.rolling(20).std(ddof=0).iloc[-1]
    p = c.iloc[-1]
    trend = ("Uptrend", "pos") if p > s50 > s200 else ("Downtrend", "neg") if p < s50 < s200 else ("Mixed", "neu")
    bb = (("Upper band", "neg") if p >= mid + 2 * sd else ("Lower band", "pos") if p <= mid - 2 * sd
          else ("Within bands", "neu"))
    return {"MACD": ("pos", "Bullish") if macd.iloc[-1] > sig.iloc[-1] else ("neg", "Bearish"),
            "Trend": (trend[1], trend[0]), "Bollinger": (bb[1], bb[0])}


@pytest.mark.parametrize("name", ["up", "down", "walk"])
def test_signal_cards_are_derived_from_the_correct_data(name):
    hist = make_hist(1250, seed=21) if name == "walk" else trend_hist(name)
    at = run_app(history=hist)
    no_errors(at)
    sig = cards(at)
    assert set(sig) == {"RSI (14)", "MACD", "Trend", "Bollinger"}
    for card, expected in expected_cards(hist).items():
        assert sig[card] == expected, (name, card, sig[card], expected)
    rsi = compute_indicator_frame(hist)["RSI"].iloc[-1]
    tone = "neg" if rsi > 70 else "pos" if rsi < 30 else "neu"
    assert sig["RSI (14)"] == (tone, f"{rsi:.1f}")
    assert sig["Trend"][1] == {"up": "Uptrend", "down": "Downtrend"}.get(name, sig["Trend"][1])
    # the read-out is computed from the full history, not the selected chart range
    assert cards(run_app(history=hist, state={"chart_period": "3M"})) == sig


def test_kpi_metrics_still_render():
    at = run_app()
    assert [m.label for m in at.metric] == ["Price", "Day range", "52-week range", "Market cap", "P/E"]


def test_portfolio_and_assistant_workflows_remain_intact(monkeypatch):
    # Portfolio page + sample portfolio
    at = run_app(page="💼 Portfolio")
    assert not at.exception
    load = next(b for b in at.button if "Load sample portfolio" in b.label)
    load.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # Assistant: ask a question end-to-end with the agent stubbed
    from agents import manager_agent
    monkeypatch.setattr(manager_agent, "chat_with_agent", lambda q: "## Infosys\nStub report body")
    at = run_app(page="💬 Assistant")
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    no_errors(at)
    roles = [m["role"] for m in at.session_state["messages"]]
    assert roles == ["user", "assistant"]
    assert figures(at) and at.multiselect(key="assistant_chart_overlays")
