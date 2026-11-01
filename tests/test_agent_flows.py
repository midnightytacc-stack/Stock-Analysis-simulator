"""Assistant back end (agents/manager_agent.py) with Gemini and the data tools stubbed: no network, no keys."""
import os

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("NEWS_API_KEY", "test-key")

from agents import manager_agent as ma  # noqa: E402


class FakeGemini:
    def __init__(self):
        self.calls = []

        class Models:
            def generate_content(inner, model, contents, config):
                self.calls.append({"model": model, "contents": contents, "system": config.system_instruction})
                return type("R", (), {"text": "REPORT TEXT"})()
        self.models = Models()


@pytest.fixture()
def agent(monkeypatch):
    gem, log = FakeGemini(), {"saved": [], "tools": [], "portfolio": []}
    monkeypatch.setattr(ma, "client", gem)
    monkeypatch.setattr(ma, "get_company_info", lambda t: log["tools"].append(("info", t)) or
                        {"company_name": {"INFY.NS": "Infosys Limited", "TCS.NS": "Tata Consultancy Services Limited",
                                          "HDFCBANK.NS": "HDFC Bank Limited"}.get(t, t)})
    monkeypatch.setattr(ma, "get_market_data", lambda t: {"price": 1432.55, "ticker": t})
    monkeypatch.setattr(ma, "get_financial_ratios", lambda t: {"pe_ratio": 24.3})
    monkeypatch.setattr(ma, "get_technical_indicators", lambda t: {"rsi": 59.6, "macd": "bullish"})
    monkeypatch.setattr(ma, "get_company_news", lambda name: log["tools"].append(("news", name)) or
                        [{"title": f"{name} headline one"}])
    monkeypatch.setattr(ma, "compare_companies", lambda a, b: log["tools"].append(("compare", a, b)) or
                        {"left": a, "right": b})
    monkeypatch.setattr(ma, "get_recent_history", lambda: [])
    monkeypatch.setattr(ma, "save_conversation", lambda **kw: log["saved"].append(kw))
    monkeypatch.setattr(ma, "get_last_company", lambda: log.get("last"))
    for name in ("view_portfolio", "analyze_portfolio", "clear_portfolio"):
        monkeypatch.setattr(ma, name, lambda n=name: log["portfolio"].append(n) or f"{n} done")
    monkeypatch.setattr(ma, "add_stock", lambda t: log["portfolio"].append(("add", t)) or "added")
    monkeypatch.setattr(ma, "remove_stock", lambda t: log["portfolio"].append(("remove", t)) or "removed")
    return gem, log


def test_single_stock_analysis_collects_every_data_source_and_asks_gemini(agent):
    gem, log = agent
    assert ma.chat_with_agent("Analyze Infosys") == "REPORT TEXT"
    (call,) = gem.calls
    assert call["model"] == "gemini-3.5-flash" and call["system"] == ma.SYSTEM_PROMPT
    for evidence in ("Infosys Limited", "1432.55", "pe_ratio", "rsi", "Infosys Limited headline one"):
        assert evidence in call["contents"]
    assert ("news", "Infosys Limited") in log["tools"]
    assert log["saved"][0]["ticker"] == "INFY.NS" and log["saved"][0]["assistant_response"] == "REPORT TEXT"


def test_news_question_resolves_the_company_and_fetches_its_news(agent):
    gem, log = agent
    ma.chat_with_agent("Show latest news for HDFC Bank")
    assert ("news", "HDFC Bank Limited") in log["tools"]
    assert "HDFC Bank Limited headline one" in gem.calls[0]["contents"]


def test_comparison_uses_both_tickers_and_the_comparison_prompt(agent):
    gem, log = agent
    assert ma.chat_with_agent("Compare Infosys and TCS") == "REPORT TEXT"
    assert ("compare", "INFY.NS", "TCS.NS") in log["tools"]
    assert gem.calls[0]["system"] == ma.COMPARISON_PROMPT and log["saved"] == []   # single-stock path not taken


def test_follow_up_uses_the_previous_company(agent):
    gem, log = agent
    log["last"] = {"ticker": "TCS.NS", "company": "Tata Consultancy Services Limited"}
    assert ma.chat_with_agent("What is its PE ratio?") == "REPORT TEXT"
    assert log["saved"][0]["ticker"] == "TCS.NS"
    assert "Tata Consultancy Services Limited" in gem.calls[0]["contents"]


def test_follow_up_without_history_asks_for_a_company_and_never_calls_gemini(agent):
    gem, log = agent
    reply = ma.chat_with_agent("What about its PE ratio?")
    assert "couldn't identify the company" in reply and gem.calls == []


def test_unknown_company_gets_examples_not_a_guess(agent):
    gem, _ = agent
    assert "Analyze Infosys" in ma.chat_with_agent("Analyze Zzyzzx Quux") and gem.calls == []


@pytest.mark.parametrize("query,expected", [
    ("Show portfolio", "view_portfolio"), ("Analyze portfolio", "analyze_portfolio"),
    ("Clear my portfolio", "clear_portfolio"), ("Add TCS to my portfolio", ("add", "TCS.NS")),
    ("Remove Infosys from my portfolio", ("remove", "INFY.NS")),
])
def test_portfolio_commands_route_to_the_portfolio_tools(agent, query, expected):
    gem, log = agent
    ma.chat_with_agent(query)
    assert log["portfolio"] == [expected] and gem.calls == []


@pytest.mark.parametrize("error,expected", [
    ("429 RESOURCE_EXHAUSTED quota", "free quota is used up"),
    ("403 permission denied", "rejected the API key"),
    ("503 UNAVAILABLE", "Something went wrong while generating the analysis"),
])
def test_backend_failures_reach_the_ui_as_friendly_messages(monkeypatch, error, expected):
    from tests.apphelpers import run_app
    monkeypatch.setattr(ma, "chat_with_agent", lambda q: (_ for _ in ()).throw(RuntimeError(error)))
    at = run_app(page="💬 Assistant")
    at.button(key="quick-Analyze Infosys").click()
    at.run()
    assert not at.exception
    last = at.session_state["messages"][-1]
    assert last["role"] == "assistant" and expected in last["content"]
    assert at.session_state["n_queries"] == 1                     # the attempt still counts toward the limit
