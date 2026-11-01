"""add_selected() over the real tools.portfolio_tool (file redirected to tmp), plus add_stock compatibility."""
import json

import pytest

from tests.test_stock_search import csv_file, uni  # noqa: F401  (fixtures)
from tools import portfolio_tool
from utils.portfolio_actions import add_selected, holding_tickers
from utils.stock_search import load_universe


@pytest.fixture()
def pf(tmp_path, monkeypatch):
    path = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio_tool, "PORTFOLIO_FILE", str(path))

    def no_network(ticker):  # the CSV name is passed in, so no lookup may happen
        raise AssertionError("get_company_info must not be called when the company name is known")
    monkeypatch.setattr(portfolio_tool, "get_company_info", no_network)
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_add_saves_the_selected_ticker_with_the_csv_name_in_the_existing_schema(pf, uni):
    out = add_selected("INFY", uni, portfolio_tool)
    assert (out.level, out.added) == ("success", True) and "Infosys Limited (INFY)" in out.message
    assert read(pf) == [{"ticker": "INFY.NS", "company": "Infosys Limited"}]      # unchanged schema


def test_special_character_ticker_is_saved_correctly(pf, uni):
    assert add_selected("M&M", uni, portfolio_tool).added
    assert read(pf) == [{"ticker": "M&M.NS", "company": "Mahindra & Mahindra Limited"}]


def test_duplicate_is_rejected_and_the_file_is_untouched(pf, uni):
    add_selected("INFY", uni, portfolio_tool)
    before = pf.read_bytes()
    out = add_selected("INFY", uni, portfolio_tool)
    assert (out.level, out.added) == ("warning", False) and "already in your portfolio" in out.message
    assert pf.read_bytes() == before


def test_duplicate_detection_is_case_insensitive_for_existing_data(pf, uni):
    pf.write_text(json.dumps([{"ticker": "infy.ns", "company": "Infosys"}]))
    out = add_selected("INFY", uni, portfolio_tool)
    assert not out.added and out.level == "warning" and len(read(pf)) == 1


@pytest.mark.parametrize("symbol", [None, "", "   "])
def test_empty_selection_is_rejected_with_a_helpful_message(pf, uni, symbol):
    out = add_selected(symbol, uni, portfolio_tool)
    assert (out.level, out.added) == ("warning", False) and "pick one of the suggestions" in out.message
    assert not pf.exists() or read(pf) == []


@pytest.mark.parametrize("symbol", ["NOTREAL", "INFY.NS; DROP", "../../etc/passwd", "TATAMOTORS"])
def test_symbols_outside_the_universe_are_rejected(pf, uni, symbol):
    out = add_selected(symbol, uni, portfolio_tool)
    assert (out.level, out.added) == ("error", False) and "isn't in the NSE company list" in out.message
    assert not pf.exists() or read(pf) == []


def test_unusable_company_list_blocks_adding(pf, tmp_path):
    out = add_selected("INFY", load_universe(tmp_path / "missing.csv"), portfolio_tool)
    assert (out.level, out.added) == ("error", False) and "not found" in out.message


def test_existing_portfolio_data_is_preserved_and_stays_readable(pf, uni):
    legacy = [{"ticker": "TCS.NS", "company": "Tata Consultancy Services Limited"},
              {"ticker": "WIPRO.NS", "company": "Wipro Limited"}]
    pf.write_text(json.dumps(legacy, indent=4))
    assert add_selected("INFY", uni, portfolio_tool).added
    assert read(pf) == legacy + [{"ticker": "INFY.NS", "company": "Infosys Limited"}]
    assert holding_tickers(portfolio_tool) == {"TCS.NS", "WIPRO.NS", "INFY.NS"}


def test_backend_failure_is_reported_not_raised(uni):
    class Broken:
        @staticmethod
        def load_portfolio():
            return []
        @staticmethod
        def add_stock(*a):
            raise OSError("disk full")
    out = add_selected("INFY", uni, Broken)
    assert (out.level, out.added) == ("error", False) and "Nothing was added" in out.message


def test_a_write_that_silently_did_not_persist_is_not_reported_as_success(uni):
    class Lossy:
        @staticmethod
        def load_portfolio():
            return []
        @staticmethod
        def add_stock(*a):
            return "ok"
    out = add_selected("INFY", uni, Lossy)
    assert (out.level, out.added) == ("error", False)


def test_unreadable_portfolio_file_is_an_error_not_a_crash(pf, uni):
    pf.write_text("{not json")
    out = add_selected("INFY", uni, portfolio_tool)
    assert (out.level, out.added) == ("error", False)
    assert pf.read_text() == "{not json"                                             # nothing overwritten


def test_repeated_calls_add_exactly_once(pf, uni):
    outcomes = [add_selected("INFY", uni, portfolio_tool) for _ in range(5)]
    assert [o.added for o in outcomes] == [True, False, False, False, False]
    assert len(read(pf)) == 1


# ---- existing backend API stays compatible ----------------------------------------------------
def test_add_stock_one_argument_form_still_looks_the_name_up(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_tool, "PORTFOLIO_FILE", str(tmp_path / "p.json"))
    monkeypatch.setattr(portfolio_tool, "get_company_info", lambda t: {"company_name": "Looked Up Ltd"})
    assert portfolio_tool.add_stock("TCS.NS") == "'Looked Up Ltd' has been added to your portfolio."
    assert portfolio_tool.add_stock("TCS.NS") == "'Looked Up Ltd' is already in your portfolio."
    assert json.loads((tmp_path / "p.json").read_text()) == [{"ticker": "TCS.NS", "company": "Looked Up Ltd"}]


def test_remove_and_sample_style_save_still_work(pf, uni):
    add_selected("INFY", uni, portfolio_tool)
    add_selected("TCS", uni, portfolio_tool)
    assert "removed" in portfolio_tool.remove_stock("INFY.NS")
    assert [h["ticker"] for h in portfolio_tool.load_portfolio()] == ["TCS.NS"]
    portfolio_tool.save_portfolio([{"ticker": "INFY.NS", "company": "Infosys Limited"}])
    assert holding_tickers(portfolio_tool) == {"INFY.NS"}
