"""Update 4: contextual About, final polish, and cross-feature regression checks."""
import hashlib
import re
import time
import tomllib
from pathlib import Path

import pytest

from tests.apphelpers import (click, holdings, pick, run_app, trace_names, figures, type_query)
from tests.test_chart import _ratio  # WCAG contrast helper

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = (ROOT / "app.py").read_text(encoding="utf-8")
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
PAGES = ["💬 Assistant", "📉 Charts", "💼 Portfolio"]


def _ns():
    start, end = APP_SRC.index("PAGES = ["), APP_SRC.index("def render_about")
    ns: dict = {}
    exec(APP_SRC[start:end], ns)
    return ns


ABOUT = _ns()["ABOUT"]
SPEC_SUMMARY = {
    "💬 Assistant": "An AI-powered NSE stock research assistant that combines available market data, technical "
                    "indicators, company information, financial metrics, and recent news to produce structured "
                    "research reports.",
    "📉 Charts": "Explore historical NSE stock prices with candlestick charts, moving averages, Bollinger Bands, "
                 "RSI, MACD, and volume.",
    "💼 Portfolio": "Build an NSE stock watchlist and review available market metrics for your selected companies "
                    "in one place.",
}


def sidebar_text(at):
    return " ".join(m.value for m in at.sidebar.markdown)


# ---- About content -------------------------------------------------------------------------
@pytest.mark.parametrize("page,heading", list(zip(PAGES, ["About Assistant", "About Charts", "About Portfolio"])))
def test_about_headings_and_summaries_match_the_brief(page, heading):
    assert ABOUT[page]["title"] == heading and ABOUT[page]["summary"] == SPEC_SUMMARY[page]


@pytest.mark.parametrize("page", PAGES)
def test_about_is_concise_not_a_manual(page):
    a = ABOUT[page]
    assert len(a["points"]) <= 6
    assert len(a["summary"]) + sum(map(len, a["points"])) + len(a["note"]) < 900


def test_about_makes_no_claims_the_app_cannot_back_up():
    portfolio = " ".join([ABOUT["💼 Portfolio"]["summary"], *ABOUT["💼 Portfolio"]["points"]]).lower()
    for word in ("trade", "broker", "profit", "loss", "return", "quantit", "order", "invested"):
        assert word not in portfolio, word
    assert "does not trade, connect to a broker, or track quantities or returns" in ABOUT["💼 Portfolio"]["note"]
    everything = " ".join(" ".join([a["summary"], *a["points"], a["note"]]) for a in ABOUT.values()).lower()
    for claim in ("guarantee profit", "execute", "place orders", "real-time quotes", "buy and sell"):
        assert claim not in everything
    assert "do not guarantee future performance" in ABOUT["📉 Charts"]["note"]
    gemini = [k for k, a in ABOUT.items() if "gemini" in " ".join([a["summary"], *a["points"], a["note"]]).lower()]
    assert gemini == ["💬 Assistant"]                              # mentioned only as the AI provider, only there


def test_about_only_describes_controls_that_exist():
    charts = " ".join(ABOUT["📉 Charts"]["points"])
    for token in ("3M", "6M", "1Y", "2Y", "5Y", "SMA 20", "SMA 50", "SMA 200", "Bollinger", "RSI", "MACD"):
        assert token in charts or token in ABOUT["📉 Charts"]["summary"]
    assert "Load sample portfolio".lower() in " ".join(ABOUT["💼 Portfolio"]["points"]).lower() or \
        "sample" in " ".join(ABOUT["💼 Portfolio"]["points"]).lower()


# ---- Live behaviour -----------------------------------------------------------------------------
@pytest.mark.parametrize("page,heading", list(zip(PAGES, ["About Assistant", "About Charts", "About Portfolio"])))
def test_sidebar_about_matches_the_selected_page(page, heading):
    at = run_app(page=page)
    assert not at.exception
    text = sidebar_text(at)
    assert heading in text and SPEC_SUMMARY[page] in text
    others = [h for h in ("About Assistant", "About Charts", "About Portfolio") if h != heading]
    assert not any(h in text for h in others)


def test_about_follows_every_switch_and_never_disagrees_with_the_view():
    at = run_app(page="💬 Assistant")
    for page, heading in [("📉 Charts", "About Charts"), ("💼 Portfolio", "About Portfolio"),
                          ("💬 Assistant", "About Assistant"), ("💼 Portfolio", "About Portfolio")]:
        at.session_state["page"] = page
        at.run()
        assert heading in sidebar_text(at) and not at.exception
        assert at.session_state["page"] == page                # the one navigation state, unchanged


def test_deselecting_the_nav_falls_back_to_assistant_for_both_view_and_about():
    at = run_app(page="📉 Charts")
    at.session_state["page"] = None                            # clicking the active segment clears it
    at.run()
    assert not at.exception
    assert "About Assistant" in sidebar_text(at) and "About Charts" not in sidebar_text(at)
    assert len([b for b in at.button if b.key and b.key.startswith("quick-")]) == 6   # Assistant view is shown


def test_switching_pages_keeps_unrelated_session_state():
    at = run_app(page="💼 Portfolio")
    at = pick(type_query(at, "info"), "Infosys")
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a", "tickers": []}]
    at.session_state["messages"] = msgs
    at.session_state["n_queries"] = 4
    sid = at.session_state["sid"]
    for page in ("📉 Charts", "💬 Assistant", "💼 Portfolio"):
        at.session_state["page"] = page
        at.run()
        assert not at.exception
    assert at.session_state["messages"] == msgs and at.session_state["n_queries"] == 4
    assert at.session_state["sid"] == sid and at.session_state["pf_selected"] == "INFY"


def test_sidebar_keeps_branding_limit_clear_action_and_disclaimer():
    at = run_app(page="💬 Assistant")
    assert any("AI questions left this session: 15/15" in str(p.proto.text) for p in at.sidebar.get("progress"))
    assert any("Clear conversation" in b.label for b in at.sidebar.button)
    assert "Not financial or investment advice" in sidebar_text(at)


# ---- Assistant polish ---------------------------------------------------------------------------
QUICK = ["Analyze Infosys", "Compare Infosys vs TCS", "Reliance P/E ratio", "HDFC Bank news",
         "Add TCS to portfolio", "Analyze portfolio"]


def test_the_six_quick_prompts_are_preserved_and_send_their_query(monkeypatch):
    from agents import manager_agent
    sent = []
    monkeypatch.setattr(manager_agent, "chat_with_agent", lambda q: sent.append(q) or "ok")
    at = run_app(page="💬 Assistant")
    assert [b.label for b in at.button if b.key and b.key.startswith("quick-")] == QUICK
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    assert sent == ["Analyze Infosys"] and not at.exception


def test_rate_limit_and_cooldown_still_apply(monkeypatch):
    from agents import manager_agent
    calls = []
    monkeypatch.setattr(manager_agent, "chat_with_agent", lambda q: calls.append(q) or "ok")
    at = run_app(page="💬 Assistant", state={"n_queries": 15})
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    assert any("Demo limit reached (15 questions per session)" in w.value for w in at.warning) and calls == []

    at = run_app(page="💬 Assistant", state={"last_query_at": time.time()})
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    assert any("give it a couple of seconds" in i.value for i in at.info) and calls == []
    assert at.session_state["n_queries"] == 0                   # a refused question isn't counted


def test_a_question_is_counted_once_and_shown_in_the_sidebar(monkeypatch):
    from agents import manager_agent
    monkeypatch.setattr(manager_agent, "chat_with_agent", lambda q: "## Report")
    at = run_app(page="💬 Assistant")
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    assert at.session_state["n_queries"] == 1 and len(at.session_state["messages"]) == 2
    assert any("14/15" in str(p.proto.text) for p in at.sidebar.get("progress"))


# ---- Charts polish ----------------------------------------------------------------------------------
def test_chart_choices_survive_a_round_trip_to_another_page():
    at = run_app(page="📉 Charts")
    assert at.session_state["chart_period"] == "6M" and at.multiselect(key="chart_overlays").value == \
        ["SMA 20", "SMA 50", "Bollinger Bands"]                   # first-visit defaults unchanged
    at.session_state["chart_period"] = "1Y"
    at.multiselect(key="chart_overlays").set_value(["SMA 200", "Bollinger Bands"])
    at.run()
    for page in ("💼 Portfolio", "💬 Assistant", "📉 Charts"):
        at.session_state["page"] = page
        at.run()
    assert at.session_state["chart_period"] == "1Y"
    assert at.multiselect(key="chart_overlays").value == ["SMA 200", "Bollinger Bands"]
    assert {"SMA 200", "Bollinger upper (2σ)"} <= set(trace_names(figures(at)[0]))


def test_changing_period_or_overlays_does_not_reset_the_other_controls():
    at = run_app(page="📉 Charts", state={"chart_company": "TCS"})
    at.multiselect(key="chart_overlays").set_value(["SMA 50"])
    at.run()
    at.session_state["chart_period"] = "3M"
    at.run()
    assert at.multiselect(key="chart_overlays").value == ["SMA 50"] and at.text_input(key="chart_company").value == "TCS"
    at.multiselect(key="chart_overlays").set_value(["SMA 20", "SMA 200"])
    at.run()
    assert at.session_state["chart_period"] == "3M" and at.text_input(key="chart_company").value == "TCS"


def test_chart_data_fetches_are_cached_across_reruns():
    counter = {}
    at = run_app(page="📉 Charts", counter=counter)
    first = counter["history"]
    assert first >= 1
    at.multiselect(key="chart_overlays").set_value(["SMA 200"])
    at.run()
    at.session_state["chart_period"] = "1Y"
    at.run()
    assert counter["history"] == first                         # overlays/period changes never refetch


# ---- Session isolation -----------------------------------------------------------------------------
def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_sessions_are_isolated_and_shared_memory_files_are_untouched():
    shared = [ROOT / "memory" / "portfolio.json", ROOT / "memory" / "history.json"]
    before = [_sha(p) for p in shared]
    a = pick(type_query(run_app(page="💼 Portfolio"), "info"), "Infosys")
    a = click(a, "pf_add_btn")
    b = run_app(page="💼 Portfolio")
    assert a.session_state["sid"] != b.session_state["sid"]
    assert [h["ticker"] for h in holdings(a)] == ["INFY.NS"] and holdings(b) == []
    assert [_sha(p) for p in shared] == before


# ---- Theme & CSS guarantees ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_info_boxes_use_the_teal_palette_with_readable_text(mode):
    c = CONFIG[mode]
    assert _ratio(c["blueTextColor"], c["blueBackgroundColor"]) >= 4.5
    assert c["blueColor"].lower() == c["primaryColor"].lower()


def test_final_css_guarantees():
    css = _css()
    assert '[data-testid="stMetricValue"] p { white-space: normal' in css          # long values wrap, never clip
    media = css[css.index("@media (min-width: 641px)"):]
    assert "min-height: 5.2rem" in media.split("}")[0] + "}"                         # equal card heights only on wide screens
    assert css.count("min-height: 5.2rem") == 1
    phone = css[css.index("@media (max-width: 640px)"):]
    assert ".modebar-container { display: none; }" in phone                       # toolbar vs legend collision
    assert ".st-key-pf_layout" in css and "flex-wrap: wrap" in css                 # holdings table never needs a sideways scroll
    assert 'initial_sidebar_state="auto"' in APP_SRC and 'initial_sidebar_state="expanded"' not in APP_SRC


def _css():
    start = APP_SRC.index("COMPONENT_CSS = \"\"\"") + len("COMPONENT_CSS = \"\"\"")
    return APP_SRC[start:APP_SRC.index("\"\"\"", start)]


# ---- Secrets -------------------------------------------------------------------------------------------
def test_no_api_keys_or_secrets_in_the_source_tree():
    patterns = [r"AIza[0-9A-Za-z_\-]{30,}", r"\bsk-[A-Za-z0-9]{20,}", r"\bghp_[A-Za-z0-9]{30,}",
                r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"]
    offenders = []
    for path in ROOT.rglob("*"):
        if path.suffix not in {".py", ".toml", ".md", ".txt", ".json", ".yml", ".yaml", ".env"} or \
                any(part in {"__pycache__", ".pytest_cache"} for part in path.parts) or path.name == "test_update4.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders += [f"{path.relative_to(ROOT)}: {p}" for p in patterns if re.search(p, text)]
    assert offenders == []
    config = (ROOT / "config.py").read_text()
    assert 'os.getenv("GEMINI_API_KEY")' in config and 'os.getenv("NEWS_API_KEY")' in config
    ignore = (ROOT / ".gitignore").read_text()
    assert ".env" in ignore and ".streamlit/secrets.toml" in ignore
