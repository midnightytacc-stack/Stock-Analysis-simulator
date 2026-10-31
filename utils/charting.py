"""
Technical-chart construction shared by the Charts page and the Assistant's chart
expander. Pure pandas/Plotly (no Streamlit), so it can be unit-tested.

Theming
-------
Backgrounds, fonts, axis text, hover labels and legend text are NOT set here: the
figure is rendered through st.plotly_chart(theme="streamlit"), which writes the
*active* Streamlit theme (the light/dark tokens in .streamlit/config.toml) into the
figure's template, live, including after a theme switch. Anything set explicitly on
the figure beats the template, so only colours that read on both light and dark
surfaces are set here:

* paper/plot backgrounds are transparent (the page or card shows through),
* grid / reference / band colours are a mid-tone slate,
* every series colour has >= 3:1 contrast against the light AND dark backgrounds
  (checked in tests/test_chart.py against the values in .streamlit/config.toml).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

OVERLAY_OPTIONS = ["SMA 20", "SMA 50", "SMA 200", "Bollinger Bands"]
DEFAULT_OVERLAYS = ["SMA 20", "SMA 50", "Bollinger Bands"]

SERIES = {
    "up": "#12985F",
    "down": "#E5384F",
    "sma20": "#BF7A00",     # amber
    "sma50": "#2F7DE1",     # blue
    "sma200": "#8B5CF6",    # purple
    "band": "#76859C",      # muted neutral (Bollinger lines)
    "rsi": "#12988F",       # teal
    "macd": "#D63F9A",      # magenta
    "signal": "#E25E12",    # orange (dashed)
    "reference": "#76859C",
}
GRID_COLOR = "rgba(118,133,156,0.22)"
BAND_FILL = "rgba(118,133,156,0.12)"
TRANSPARENT = "rgba(0,0,0,0)"

BB_UPPER = "Bollinger upper (20, 2σ)"
BB_LOWER = "Bollinger lower (20, 2σ)"

# Trading days of closes an indicator needs before its first value (verified in
# tests/test_indicators.py against the `ta` outputs).
MIN_BARS = {
    "SMA 20": 20, "SMA 50": 50, "SMA 200": 200, "Bollinger Bands": 20,
    "RSI (14)": 15, "MACD": 26, "MACD signal": 34,
}
_OVERLAY_COLUMNS = {
    "SMA 20": ["SMA20"], "SMA 50": ["SMA50"], "SMA 200": ["SMA200"],
    "Bollinger Bands": ["BBU", "BBL"],
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def compute_indicator_frame(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Candles + every indicator the AI report uses, aligned to the price index.

    Rows without a full OHLC quote (e.g. an unfinished trading day) are dropped
    first so a NaN close can never reach the signal cards or the candles. Warm-up
    values stay NaN - they are never filled with zeros.
    """
    df = hist.copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    close = df["Close"]
    for window in (20, 50, 200):
        df[f"SMA{window}"] = SMAIndicator(close, window).sma_indicator()
    bands = BollingerBands(close, 20, 2)
    df["BBU"], df["BBL"] = bands.bollinger_hband(), bands.bollinger_lband()
    rsi = RSIIndicator(close, 14).rsi()
    # `ta` turns the undefined first price change (NaN) into 0.0, so its first RSI value
    # (bar 14) rests on a fabricated zero. A genuine RSI(14) needs 14 changes = 15 closes.
    rsi.iloc[:14] = np.nan
    df["RSI"] = rsi
    macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df["MACD"], df["SIG"], df["HIST"] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    return df


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df and bool(df[col].notna().any())


def chart_notes(df: pd.DataFrame, overlays: list[str]) -> list[str]:
    """Plain-language reasons why a requested series cannot be drawn."""
    notes = []
    for name in overlays or []:
        cols = _OVERLAY_COLUMNS.get(name)
        if cols and not all(_has(df, c) for c in cols):
            notes.append(
                f"{name} isn't shown: it needs {MIN_BARS[name]} trading days of price "
                f"history and this ticker doesn't have enough."
            )
    if not _has(df, "RSI"):
        notes.append(f"RSI (14) needs {MIN_BARS['RSI (14)']} closes of history; not enough data yet.")
    if not _has(df, "MACD"):
        notes.append(f"MACD needs {MIN_BARS['MACD']} closes of history; not enough data yet.")
    elif not _has(df, "SIG"):
        notes.append(
            f"The MACD signal line needs {MIN_BARS['MACD signal']} closes of history; "
            f"only the MACD line is drawn."
        )
    return notes


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------
def _panel_title(fig: go.Figure, axis: str, text: str) -> None:
    top = fig.layout[axis].domain[1]
    fig.add_annotation(xref="paper", yref="paper", x=0, y=top, xanchor="left", yanchor="bottom",
                       text=f"<b>{text}</b>", showarrow=False, font=dict(size=13))


def _unavailable(fig: go.Figure, axis: str, text: str) -> None:
    lo, hi = fig.layout[axis].domain
    fig.add_annotation(xref="paper", yref="paper", x=0.5, y=(lo + hi) / 2, text=text,
                       showarrow=False, font=dict(size=12))


def build_chart(df: pd.DataFrame, overlays: list[str], height: int = 920) -> go.Figure:
    """Price + overlays, volume, RSI (14), MACD (12, 26, 9) in four stacked panels."""
    overlays = set(overlays or [])
    c = SERIES
    x = df.index
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.045,
        row_heights=[0.46, 0.12, 0.21, 0.21],
    )

    # -- Row 1: bands first so the shading sits *behind* the candles ------------
    if "Bollinger Bands" in overlays and _has(df, "BBU") and _has(df, "BBL"):
        fig.add_trace(go.Scatter(
            x=x, y=df["BBL"], name=BB_LOWER, legendgroup="bb", legendrank=6,
            line=dict(color=c["band"], width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=x, y=df["BBU"], name=BB_UPPER, legendgroup="bb", legendrank=5,
            line=dict(color=c["band"], width=1), fill="tonexty", fillcolor=BAND_FILL),
            row=1, col=1)

    fig.add_trace(go.Candlestick(
        x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price", legendrank=1,
        increasing_line_color=c["up"], decreasing_line_color=c["down"],
        increasing_fillcolor=c["up"], decreasing_fillcolor=c["down"],
    ), row=1, col=1)

    for rank, (window, key) in enumerate(((20, "sma20"), (50, "sma50"), (200, "sma200")), start=2):
        if f"SMA {window}" in overlays and _has(df, f"SMA{window}"):
            fig.add_trace(go.Scatter(
                x=x, y=df[f"SMA{window}"], name=f"SMA {window}", legendrank=rank,
                line=dict(color=c[key], width=1.3)), row=1, col=1)

    # -- Row 2: volume ----------------------------------------------------------
    vol_colors = np.where(df["Close"] >= df["Open"], c["up"], c["down"])
    fig.add_trace(go.Bar(x=x, y=df["Volume"], name="Volume", marker_color=list(vol_colors),
                         marker_line_width=0, opacity=0.6, showlegend=False), row=2, col=1)

    # -- Row 3: RSI (14) --------------------------------------------------------
    fig.add_hrect(y0=70, y1=100, fillcolor=c["down"], opacity=0.07, line_width=0,
                  layer="below", row=3, col=1)
    fig.add_hrect(y0=0, y1=30, fillcolor=c["up"], opacity=0.07, line_width=0,
                  layer="below", row=3, col=1)
    if _has(df, "RSI"):
        fig.add_trace(go.Scatter(x=x, y=df["RSI"], name="RSI (14)", showlegend=False,
                                 line=dict(color=c["rsi"], width=1.6)), row=3, col=1)
    ref = dict(color=c["reference"], width=1.2, dash="dash")
    fig.add_hline(y=70, line=ref, row=3, col=1, annotation_text="Overbought 70",
                  annotation_position="top right", annotation_font_size=11)
    fig.add_hline(y=30, line=ref, row=3, col=1, annotation_text="Oversold 30",
                  annotation_position="bottom right", annotation_font_size=11)

    # -- Row 4: MACD (12, 26, 9) - histogram split by sign so the sign is in the
    #    legend and hover text, not only in the bar colour. NaN stays NaN. --------
    hist = df["HIST"]
    for name, series, color in (("Histogram (positive)", hist.where(hist >= 0), c["up"]),
                                ("Histogram (negative)", hist.where(hist < 0), c["down"])):
        if series.notna().any():
            fig.add_trace(go.Bar(x=x, y=series, name=name, marker_color=color, marker_line_width=0,
                                 opacity=0.75, legend="legend2"), row=4, col=1)
    if _has(df, "MACD"):
        fig.add_trace(go.Scatter(x=x, y=df["MACD"], name="MACD line", legend="legend2",
                                 line=dict(color=c["macd"], width=1.6)), row=4, col=1)
    if _has(df, "SIG"):
        fig.add_trace(go.Scatter(x=x, y=df["SIG"], name="Signal line (9)", legend="legend2",
                                 line=dict(color=c["signal"], width=1.6, dash="dash")), row=4, col=1)
    fig.add_hline(y=0, line=dict(color=c["reference"], width=1), row=4, col=1)

    # -- Layout -----------------------------------------------------------------
    fig.update_layout(
        template="none",  # no foreign template; Streamlit injects the active theme
        height=height, margin=dict(l=10, r=10, t=56, b=44),
        paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT,
        hovermode="x unified", xaxis_rangeslider_visible=False, barmode="relative",
        font=dict(family="IBM Plex Sans, sans-serif"),
        legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom",
                    bgcolor=TRANSPARENT, font=dict(size=12)),
        legend2=dict(orientation="h", x=1, xanchor="right", y=fig.layout.yaxis4.domain[1],
                     yanchor="bottom", bgcolor=TRANSPARENT, font=dict(size=12)),
    )
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])], showgrid=True, gridcolor=GRID_COLOR,
        showspikes=True, spikemode="across", spikesnap="cursor", spikedash="dot",
        spikethickness=1, spikecolor=c["reference"], hoverformat="%a, %d %b %Y",
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID_COLOR, zeroline=False, automargin=True)
    fig.update_yaxes(title_text="Price (₹)", hoverformat=",.2f", row=1, col=1)
    fig.update_yaxes(hoverformat=",.0f", row=2, col=1)
    fig.update_yaxes(range=[0, 100], fixedrange=True, hoverformat=".1f", row=3, col=1,
                     tickvals=[0, 30, 50, 70, 100], ticktext=["0", "30", "50", "70", "100"])
    fig.update_yaxes(hoverformat=".2f", row=4, col=1)

    _panel_title(fig, "yaxis2", "Volume")
    _panel_title(fig, "yaxis3", "RSI (14)")
    _panel_title(fig, "yaxis4", "MACD (12, 26, 9)")
    if not _has(df, "RSI"):
        _unavailable(fig, "yaxis3", f"Not enough history for RSI (14) — needs {MIN_BARS['RSI (14)']} closes")
    if not _has(df, "MACD"):
        _unavailable(fig, "yaxis4", f"Not enough history for MACD — needs {MIN_BARS['MACD']} closes")
    return fig
