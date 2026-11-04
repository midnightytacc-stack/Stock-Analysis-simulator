"""Update 5 regression tests (no browser, no network). Run:  pytest tests/test_update5.py"""
import ast
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GEMINI_API_KEY", "test-key")   # the Gemini client is built at import time; never called here

from tools import portfolio_tool            # noqa: E402
from utils import memory_manager            # noqa: E402
from utils.stock_search import search, load_universe   # noqa: E402


# ---------- helpers: pull pure functions out of app.py without running the Streamlit script ----------
def _app_namespace(*names):
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    wanted = [n for n in tree.body
              if (isinstance(n, ast.FunctionDef) and n.name in names)
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))]
    ns = {"re": re, "pd": pd}
    exec(compile(ast.Module(wanted, []), "app.py", "exec"), ns)
    return ns


APP = _app_namespace("PERIODS", "HISTORY_PERIOD", "history_period_for", "history_note",
                     "_retry_seconds", "classify_error", "friendly_error")


# ---------- 1. portfolio ----------
@pytest.fixture()
def pf(tmp_path, monkeypatch):
    f = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio_tool, "PORTFOLIO_FILE", str(f))
    return f


def test_add_persists_and_duplicates_are_refused(pf):
    assert "added" in portfolio_tool.add_stock("infy.ns", "Infosys Limited")
    assert "already in your portfolio" in portfolio_tool.add_stock("INFY.NS", "Infosys Limited")
    assert "already in your portfolio" in portfolio_tool.add_stock(" infy.ns ")
    assert json.loads(pf.read_text()) == [{"ticker": "INFY.NS", "company": "Infosys Limited"}]


def test_add_blank_ticker_is_rejected(pf):
    assert "nothing was added" in portfolio_tool.add_stock("  ")
    assert portfolio_tool.load_portfolio() == []


def test_remove_updates_the_file(pf):
    portfolio_tool.add_stock("INFY.NS", "Infosys Limited")
    portfolio_tool.add_stock("TCS.NS", "TCS")
    assert "removed" in portfolio_tool.remove_stock("infy.ns")
    assert [h["ticker"] for h in portfolio_tool.load_portfolio()] == ["TCS.NS"]
    assert "not present" in portfolio_tool.remove_stock("INFY.NS")


def test_malformed_and_duplicate_entries_are_cleaned(pf):
    pf.write_text(json.dumps([
        {"ticker": "tcs.ns", "company": "TCS"}, "junk", 5, {"company": "no ticker"}, {"ticker": ""},
        {"ticker": "TCS.NS", "company": "dup"}, {"ticker": "WIPRO.NS"},
    ]))
    assert portfolio_tool.load_portfolio() == [
        {"ticker": "TCS.NS", "company": "TCS"}, {"ticker": "WIPRO.NS", "company": "WIPRO.NS"}]


@pytest.mark.parametrize("content", ["{not json", '{"ticker": "X"}'])
def test_unreadable_portfolio_file_is_an_explicit_error_not_an_empty_list(pf, content):
    pf.write_text(content)
    with pytest.raises(ValueError, match="memory/portfolio.json"):
        portfolio_tool.load_portfolio()
    assert pf.read_text() == content              # and the user's data is left alone


# ---------- 2. shared company search used by Portfolio and Charts ----------
@pytest.mark.parametrize("text,ticker", [("reliance", "RELIANCE.NS"), ("INFY", "INFY.NS"),
                                        ("tcs", "TCS.NS"), ("zomato", "ETERNAL.NS")])
def test_search_finds_company_by_name_symbol_or_alias(text, ticker):
    universe = load_universe()
    assert universe.ok
    assert ticker in [c.ticker for c in search(text, universe).companies]


def test_search_no_match_gives_a_message():
    result = search("zzzzqqq", load_universe())
    assert not result.matches and result.message


# ---------- 3. All Time ----------
def test_all_time_asks_the_provider_for_max_not_5y():
    assert APP["history_period_for"]("All Time") == "max"
    for label in ("3M", "6M", "1Y", "2Y", "5Y"):
        assert APP["history_period_for"](label) == "5y"
    assert APP["PERIODS"]["All Time"] is None and APP["PERIODS"]["5Y"] == 5000


def _frame(days):
    idx = pd.bdate_range(end="2026-11-04", periods=days)
    return pd.DataFrame({"Close": range(days)}, index=idx)


def test_history_note_explains_all_time_and_short_history():
    long_frame, short_frame = _frame(5000), _frame(200)
    assert "full history" in APP["history_note"](long_frame, long_frame, "All Time")
    assert APP["history_note"](long_frame, long_frame.tail(63), "3M") is None
    assert "Only 200 trading days" in APP["history_note"](short_frame, short_frame, "5Y")


# ---------- 5. assistant limits / errors / history ----------
class _ApiError(Exception):
    def __init__(self, code, status, message):
        super().__init__(f"{code} {status}. {message}")
        self.code, self.status = code, status


def test_per_minute_429_is_reported_as_provider_limit_with_wait_time():
    msg, retry = APP["classify_error"](_ApiError(429, "RESOURCE_EXHAUSTED",
        "quotaId GenerateRequestsPerMinutePerProjectPerModel-FreeTier. Please retry in 34.2s."))
    assert retry and "per-minute" in msg and "35 seconds" in msg and "not a limit set by this app" in msg


def test_daily_429_says_retrying_now_will_not_help():
    msg, retry = APP["classify_error"](_ApiError(429, "RESOURCE_EXHAUSTED", "quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    assert "daily" in msg and "will not help" in msg


def test_bad_key_is_not_retryable():
    msg, retry = APP["classify_error"](_ApiError(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."))
    assert not retry and "GEMINI_API_KEY" in msg


def test_unavailable_is_retryable_and_the_word_rate_inside_other_words_is_not_a_quota_error():
    assert APP["classify_error"](_ApiError(503, "UNAVAILABLE", "The model is overloaded"))[1]
    msg, _ = APP["classify_error"](ValueError("failed to generate content: accurate parse error"))   # old code matched "rate"
    assert "rate limit" not in msg and "ValueError" in msg


def test_stored_history_is_bounded_but_recent_turns_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_manager, "MEMORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(memory_manager, "MAX_STORED_TURNS", 10)
    for i in range(25):
        memory_manager.save_conversation(f"q{i}", f"a{i}", "INFY.NS", "Infosys")
    stored = json.loads((tmp_path / "history.json").read_text())
    assert len(stored) == 10 and stored[-1]["user_query"] == "q24"
    assert [t["user_query"] for t in memory_manager.get_recent_history(5)][-1] == "q24"


def test_app_has_no_hardcoded_question_cap():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert re.search(r'MAX_QUERIES_PER_SESSION", "0"', src)      # default: no app-imposed cap
    assert "sample portfolio" not in src.lower()
