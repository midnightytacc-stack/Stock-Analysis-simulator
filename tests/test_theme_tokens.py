"""Update 1 checks: theme tokens, native-theme sync, KPI contrast, CSS hygiene."""
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = (ROOT / "app.py").read_text(encoding="utf-8")


def _load_theme():
    """Exec only the theme-related block of app.py (no Streamlit run needed)."""
    start = APP_SRC.index("THEME = {")
    end = APP_SRC.index("st.markdown(\n    \"<style>")
    ns: dict = {}
    exec(APP_SRC[start:end], ns)
    return ns


NS = _load_theme()
THEME = NS["THEME"]
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]


def _lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


@pytest.mark.parametrize("idx,mode", [(0, "light"), (1, "dark")])
def test_config_matches_app_tokens(idx, mode):
    c = CONFIG[mode]
    pairs = {
        "backgroundColor": "bg", "secondaryBackgroundColor": "surface",
        "textColor": "text", "primaryColor": "accent", "borderColor": "border",
        "greenColor": "pos", "redColor": "neg",
    }
    for key, tok in pairs.items():
        assert c[key].lower() == THEME[tok][idx].lower(), f"{mode}.{key} != THEME[{tok}]"
    assert c["sidebar"]["backgroundColor"].lower() in (THEME["card"][idx].lower(),)


@pytest.mark.parametrize("idx", [0, 1])
@pytest.mark.parametrize("fg", ["text", "text-2", "accent", "pos", "neg", "neu"])
def test_kpi_text_contrast_on_card(idx, fg):
    assert _ratio(THEME[fg][idx], THEME["card"][idx]) >= 4.5


@pytest.mark.parametrize("idx", [0, 1])
def test_card_distinct_from_page_background_and_opaque(idx):
    assert THEME["card"][idx] != THEME["bg"][idx]
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", THEME["card"][idx])  # opaque hex, no alpha


def test_css_variables_both_themes():
    css = NS["theme_variables_css"]()
    assert "light-dark(" in css and "prefers-color-scheme: dark" in css
    for tok in THEME:
        assert f"--sa-{tok}:" in css
    assert css.count("{") == css.count("}")


def test_component_css_hygiene():
    css = NS["COMPONENT_CSS"]
    assert css.count("{") == css.count("}")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", css), "hardcoded colour in component CSS"
    assert "opacity" not in css, "low-opacity text can become unreadable on white"
    assert "[class*=" not in css
    # every non-@ rule is scoped under .stApp or is the footer/deploy hider
    for sel in re.findall(r"^([^\s@/}{][^{]*)\{", css, flags=re.M):
        assert sel.strip().startswith((".stApp", "footer")), f"unscoped selector: {sel!r}"
