"""Figure structure, overlay toggles, theme neutrality and insufficient-data handling."""
import itertools
import re
import tomllib
from pathlib import Path

import numpy as np
import pytest

from tests.test_indicators import make_hist
from utils import charting as ch
from utils.charting import (BB_LOWER, BB_UPPER, GRID_COLOR, OVERLAY_OPTIONS, SERIES, build_chart,
                            chart_notes, compute_indicator_frame)

CONFIG = tomllib.loads((Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text())["theme"]


def names(fig):
    return [t.name for t in fig.data]


@pytest.fixture(scope="module")
def frame():
    return compute_indicator_frame(make_hist(1250))


@pytest.fixture(scope="module")
def full_fig(frame):
    return build_chart(frame.tail(126), OVERLAY_OPTIONS)


# ---- overlays ---------------------------------------------------------------
@pytest.mark.parametrize("n", range(len(OVERLAY_OPTIONS) + 1))
def test_every_overlay_combination_toggles_exactly_its_traces(frame, n):
    for combo in itertools.combinations(OVERLAY_OPTIONS, n):
        got = names(build_chart(frame.tail(126), list(combo)))
        for sma in ("SMA 20", "SMA 50", "SMA 200"):
            assert (sma in got) == (sma in combo), (combo, sma)
        assert (BB_UPPER in got and BB_LOWER in got) == ("Bollinger Bands" in combo)
        assert (BB_UPPER in got) == (BB_LOWER in got)          # never one band without the other
        # panels that are not overlays are always present
        assert {"Price", "Volume", "RSI (14)", "MACD line", "Signal line (9)"} <= set(got)


def test_all_three_smas_and_bands_have_descriptive_names_in_legend(full_fig):
    legend_items = {t.name for t in full_fig.data if t.showlegend is not False and t.legend in (None, "legend")}
    assert legend_items == {"Price", "SMA 20", "SMA 50", "SMA 200", BB_UPPER, BB_LOWER}


def test_bollinger_shading_is_drawn_before_candles_and_smas(full_fig):
    order = names(full_fig)
    assert order.index(BB_UPPER) < order.index("Price") < order.index("SMA 20")
    upper = next(t for t in full_fig.data if t.name == BB_UPPER)
    assert upper.fill == "tonexty" and upper.legendgroup == next(t for t in full_fig.data if t.name == BB_LOWER).legendgroup


# ---- panels -----------------------------------------------------------------
def test_panel_order_and_readable_heights(full_fig):
    L = full_fig.layout
    doms = [L[a].domain for a in ("yaxis", "yaxis2", "yaxis3", "yaxis4")]
    assert all(doms[i][0] > doms[i + 1][1] for i in range(3))         # stacked top -> bottom, no overlap
    heights = [d[1] - d[0] for d in doms]
    assert heights[0] > 0.38 and heights[2] >= 0.17 and heights[3] >= 0.17
    assert heights[2] > heights[1] and heights[3] > heights[1]        # RSI/MACD taller than volume


def test_rsi_panel(full_fig):
    L = full_fig.layout
    rsi = next(t for t in full_fig.data if t.name == "RSI (14)")
    assert rsi.yaxis == "y3" and rsi.line.color == SERIES["rsi"]
    assert tuple(L.yaxis3.range) == (0, 100) and L.yaxis3.fixedrange is True
    lines = {s.y0 for s in L.shapes if s.yref == "y3" and s.y0 == s.y1}
    assert lines == {30, 70}
    assert L.yaxis3.hoverformat == ".1f" and list(L.yaxis3.ticktext) == ["0", "30", "50", "70", "100"]
    assert "<b>RSI (14)</b>" in [a.text for a in L.annotations]


def test_macd_panel_has_line_signal_and_histogram(full_fig):
    macd = [t for t in full_fig.data if t.yaxis == "y4"]
    assert {t.name for t in macd} == {"MACD line", "Signal line (9)", "Histogram (positive)", "Histogram (negative)"}
    assert all(t.legend == "legend2" for t in macd)
    line = next(t for t in macd if t.name == "MACD line")
    sig = next(t for t in macd if t.name == "Signal line (9)")
    assert line.line.color != sig.line.color and line.line.dash != sig.line.dash   # not colour alone
    assert "<b>MACD (12, 26, 9)</b>" in [a.text for a in full_fig.layout.annotations]


def test_histogram_sign_split_never_fabricates_zeros(frame):
    view = frame.tail(126)
    fig = build_chart(view, [])
    pos = next(t for t in fig.data if t.name == "Histogram (positive)")
    neg = next(t for t in fig.data if t.name == "Histogram (negative)")
    py, ny = np.asarray(pos.y, float), np.asarray(neg.y, float)
    assert (py[~np.isnan(py)] >= 0).all() and (ny[~np.isnan(ny)] < 0).all()
    assert (np.isnan(py) | np.isnan(ny)).all()                         # each bar belongs to exactly one trace
    both = np.where(np.isnan(py), ny, py)
    np.testing.assert_allclose(both, view["HIST"].to_numpy(), equal_nan=True)


def test_warmup_values_stay_nan_in_traces(frame):
    fig = build_chart(frame.head(250), ["SMA 200"])
    sma200 = np.asarray(next(t for t in fig.data if t.name == "SMA 200").y, float)
    assert np.isnan(sma200[:199]).all() and not np.isnan(sma200[199:]).any()
    assert not (sma200 == 0).any()


# ---- theming ----------------------------------------------------------------
def test_figure_does_not_force_a_dark_theme(full_fig):
    L = full_fig.layout
    tpl = L.template.to_plotly_json()                                    # Plotly's empty "none" template,
    assert tpl.get("layout", {}) == {}                                           # not plotly_dark / plotly
    assert tpl["data"] == {"scatter": [{"type": "scatter"}]}
    assert L.paper_bgcolor == L.plot_bgcolor == "rgba(0,0,0,0)"        # page / card surface shows through
    assert L.font.color is None                                          # text colour comes from the live Streamlit theme
    assert L.hoverlabel.bgcolor is None and L.legend.bgcolor == "rgba(0,0,0,0)"


def test_grid_and_reference_colours_are_visible_on_light_and_dark(full_fig):
    L = full_fig.layout
    for ax in [a for a in L if re.fullmatch(r"[xy]axis\d*", a)]:
        grid = L[ax].gridcolor
        assert grid == GRID_COLOR and "255,255,255" not in grid and L[ax].showgrid is True
    assert all(s.line.color in (SERIES["reference"], None) for s in L.shapes if s.line.color)


def _lum(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


def _surfaces():
    out = []
    for mode in ("light", "dark"):
        out += [CONFIG[mode]["backgroundColor"], CONFIG[mode]["secondaryBackgroundColor"],
                CONFIG[mode]["sidebar"]["backgroundColor"]]
    return out + ["#FFFFFF"]


@pytest.mark.parametrize("key", sorted(SERIES))
def test_series_colours_reach_3_to_1_on_every_theme_surface(key):
    for bg in _surfaces():
        assert _ratio(SERIES[key], bg) >= 3.0, (key, SERIES[key], bg)


def test_series_colours_are_pairwise_distinct():
    distinct = ["sma20", "sma50", "sma200", "rsi", "macd", "signal", "band"]
    assert len({SERIES[k] for k in distinct}) == len(distinct)


def test_hover_formats(full_fig):
    L = full_fig.layout
    assert (L.yaxis.hoverformat, L.yaxis2.hoverformat, L.yaxis4.hoverformat) == (",.2f", ",.0f", ".2f")
    assert L.hovermode == "x unified" and L.xaxis.hoverformat == "%a, %d %b %Y"


# ---- insufficient data --------------------------------------------------------
def test_short_history_drops_unavailable_series_and_explains(frame):
    short = compute_indicator_frame(make_hist(30))
    fig = build_chart(short, OVERLAY_OPTIONS)
    got = names(fig)
    assert "SMA 200" not in got and "SMA 50" not in got and "SMA 20" in got
    assert "MACD line" in got and "Signal line (9)" not in got
    notes = " ".join(chart_notes(short, OVERLAY_OPTIONS))
    assert "SMA 200" in notes and "SMA 50" in notes and "signal line" in notes.lower()


def test_tiny_history_builds_without_error_and_labels_empty_panels():
    tiny = compute_indicator_frame(make_hist(10))
    fig = build_chart(tiny, OVERLAY_OPTIONS)
    texts = [a.text for a in fig.layout.annotations]
    assert any("Not enough history for RSI" in t for t in texts)
    assert any("Not enough history for MACD" in t for t in texts)
    assert "RSI (14)" not in names(fig) and "MACD line" not in names(fig)
    assert len(chart_notes(tiny, OVERLAY_OPTIONS)) >= 5


def test_full_history_has_no_notes(frame):
    assert chart_notes(frame.tail(126), OVERLAY_OPTIONS) == []
