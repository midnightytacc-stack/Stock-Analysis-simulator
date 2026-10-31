"""Independent re-computation of every indicator the chart draws."""
import numpy as np
import pandas as pd
import pytest

from utils.charting import MIN_BARS, compute_indicator_frame


def make_hist(n=700, seed=7, start=1500.0):
    idx = pd.bdate_range(end="2026-10-29", periods=n, tz="Asia/Kolkata")  # yfinance is tz-aware
    rng = np.random.default_rng(seed)
    close = start + np.cumsum(rng.normal(0.8, 14, n))
    return pd.DataFrame({
        "Open": close - rng.uniform(0, 4, n), "High": close + rng.uniform(2, 9, n),
        "Low": close - rng.uniform(2, 9, n), "Close": close,
        "Volume": rng.integers(1_000_000, 5_000_000, n),
        "Dividends": 0.0, "Stock Splits": 0.0,
    }, index=idx)


@pytest.fixture(scope="module")
def df():
    return compute_indicator_frame(make_hist())


def test_index_is_tz_naive_and_all_series_aligned(df):
    assert df.index.tz is None
    for col in ("SMA20", "SMA50", "SMA200", "BBU", "BBL", "RSI", "MACD", "SIG", "HIST"):
        assert df[col].index.equals(df.index), col


@pytest.mark.parametrize("window", [20, 50, 200])
def test_sma_matches_rolling_mean(df, window):
    expected = df["Close"].rolling(window).mean()
    pd.testing.assert_series_equal(df[f"SMA{window}"], expected, check_names=False, rtol=1e-9)


def test_bollinger_is_20_period_two_population_std(df):
    mid = df["Close"].rolling(20).mean()
    sd = df["Close"].rolling(20).std(ddof=0)  # Bollinger's own definition (population SD)
    pd.testing.assert_series_equal(df["BBU"], mid + 2 * sd, check_names=False, rtol=1e-9)
    pd.testing.assert_series_equal(df["BBL"], mid - 2 * sd, check_names=False, rtol=1e-9)


def _textbook_wilder_rsi(close, n=14):
    """Wilder's original RSI: first averages are plain means of the first n changes."""
    d = np.diff(close)
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    out = np.full(len(close), np.nan)
    ag, al = gain[:n].mean(), loss[:n].mean()
    out[n] = 100 - 100 / (1 + ag / al)
    for i in range(n, len(d)):
        ag, al = (ag * (n - 1) + gain[i]) / n, (al * (n - 1) + loss[i]) / n
        out[i + 1] = 100 - 100 / (1 + ag / al)
    return out


def test_rsi_uses_14_period_wilder_smoothing(df):
    # Same recursion `ta` uses (EWM alpha=1/14), where an undefined first change counts as 0.
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta).where(delta < 0, 0.0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    expected = 100 - 100 / (1 + gain / loss)
    valid = df["RSI"].notna()
    assert valid.sum() > 600
    np.testing.assert_allclose(df["RSI"][valid], expected[valid], rtol=1e-7)
    assert df["RSI"].dropna().between(0, 100).all()


def test_rsi_converges_to_textbook_wilder(df):
    textbook = _textbook_wilder_rsi(df["Close"].to_numpy())
    ours = df["RSI"].to_numpy()
    assert abs(ours[-1] - textbook[-1]) < 1e-6          # latest value: identical
    # The seed's weight decays as (13/14)^k: <0.01 RSI points after 100 bars, ~0 after 250.
    assert np.nanmax(np.abs(ours[100:] - textbook[100:])) < 0.01
    assert np.nanmax(np.abs(ours[250:] - textbook[250:])) < 1e-5
    # Documented limitation: the recursion's seed differs, so the first bars deviate a little.
    assert np.nanmax(np.abs(ours[14:60] - textbook[14:60])) < 5.0


def test_macd_12_26_9(df):
    c = df["Close"]
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    valid = df["MACD"].notna()
    np.testing.assert_allclose(df["MACD"][valid], macd[valid], rtol=1e-7, atol=1e-9)
    sig = df["MACD"].dropna().ewm(span=9, adjust=False).mean()
    valid_sig = df["SIG"].notna()
    np.testing.assert_allclose(df["SIG"][valid_sig], sig.reindex(df.index)[valid_sig], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(df["HIST"][valid_sig], (df["MACD"] - df["SIG"])[valid_sig], atol=1e-9)


def test_warmup_is_nan_not_zero_and_matches_documented_minimums(df):
    first_valid = {c: int(np.argmax(df[c].notna().values)) for c in
                   ("SMA20", "SMA50", "SMA200", "BBU", "RSI", "MACD", "SIG", "HIST")}
    assert first_valid["SMA20"] == MIN_BARS["SMA 20"] - 1
    assert first_valid["SMA50"] == MIN_BARS["SMA 50"] - 1
    assert first_valid["SMA200"] == MIN_BARS["SMA 200"] - 1
    assert first_valid["BBU"] == MIN_BARS["Bollinger Bands"] - 1
    assert first_valid["RSI"] == MIN_BARS["RSI (14)"] - 1   # 14 real changes = 15 closes
    assert first_valid["MACD"] == MIN_BARS["MACD"] - 1
    assert first_valid["SIG"] == MIN_BARS["MACD signal"] - 1
    assert first_valid["HIST"] == first_valid["SIG"]
    for col in ("SMA200", "RSI", "MACD", "SIG", "HIST"):
        warm = df[col].iloc[: first_valid[col]]
        assert warm.isna().all(), f"{col} warm-up must stay NaN (no fabricated zeros)"


def test_incomplete_rows_are_dropped_before_indicators():
    h = make_hist(300)
    h.iloc[-1, h.columns.get_loc("Close")] = np.nan  # e.g. unfinished trading day
    out = compute_indicator_frame(h)
    assert len(out) == 299 and out["Close"].notna().all()
    assert out["RSI"].iloc[-1] == out["RSI"].iloc[-1]  # not NaN


def test_chart_frame_agrees_with_report_tools(monkeypatch):
    """The AI report (tools/technical_tool.py) and the chart must show the same numbers."""
    import tools.technical_tool as tt
    hist = make_hist(400)
    monkeypatch.setattr(tt, "get_price_history", lambda ticker, period="1y": hist.copy())
    frame = compute_indicator_frame(hist)
    last = frame.iloc[-1]
    ma = tt.get_moving_averages("X")
    assert (ma["sma_20"], ma["sma_50"], ma["sma_200"]) == (round(last["SMA20"], 2), round(last["SMA50"], 2), round(last["SMA200"], 2))
    assert tt.get_rsi("X")["rsi"] == round(last["RSI"], 2)
    m = tt.get_macd("X")
    assert (m["macd"], m["signal"], m["histogram"]) == (round(last["MACD"], 2), round(last["SIG"], 2), round(last["HIST"], 2))
    b = tt.get_bollinger_bands("X")
    assert (b["upper_band"], b["lower_band"]) == (round(last["BBU"], 2), round(last["BBL"], 2))
