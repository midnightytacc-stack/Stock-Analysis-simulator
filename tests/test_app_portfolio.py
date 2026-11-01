"""The Portfolio page end to end: search -> explicit selection -> confirm. Fake market data, real app."""
import pytest

from tests.apphelpers import (click, holdings, pick, run_app, seed_portfolio, selected_card, table_tickers,
                              type_query)

SAMPLE = [{"ticker": "INFY.NS", "company": "Infosys Limited"},
          {"ticker": "TCS.NS", "company": "Tata Consultancy Services Limited"},
          {"ticker": "RELIANCE.NS", "company": "Reliance Industries Limited"}]


def page():
    return run_app(page="💼 Portfolio")


def clean(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_page_starts_with_guidance_empty_state_and_nothing_selected():
    at = clean(page())
    assert at.text_input(key="pf_query").label == "Search NSE companies"
    captions = " ".join(c.value for c in at.caption)
    assert "Type a company name or ticker" in captions and "No company selected yet" in captions
    assert not at.radio and selected_card(at) is None
    assert any("Search for a company under Manage" in i.value for i in at.info)
    assert holdings(at) == []


@pytest.mark.parametrize("query,first", [("info", "Infosys Limited — INFY"), ("INFY", "Infosys Limited — INFY"),
                                         ("reliance", "Reliance Industries Limited — RELIANCE"),
                                         ("zomato", "ETERNAL LIMITED — ETERNAL")])
def test_typing_shows_readable_ranked_suggestions(query, first):
    at = clean(type_query(page(), query))
    options = at.radio[0].options
    assert first in options and 1 <= len(options) <= 8
    assert at.radio[0].index is None                       # never auto-selected
    assert selected_card(at) is None
    assert holdings(at) == []                              # searching alone adds nothing


def test_tata_returns_eight_suggestions_and_says_there_are_more():
    at = clean(type_query(page(), "tata"))
    assert len(at.radio[0].options) == 8 and all("tata" in o.lower() for o in at.radio[0].options)
    assert any("Showing the top 8 of" in c.value for c in at.caption)


def test_unmatched_search_warns_and_does_not_pick_anything():
    at = clean(type_query(page(), "xyzqq"))
    assert any("No NSE company matches “xyzqq”" in w.value for w in at.warning)
    assert not at.radio and selected_card(at) is None
    at = click(at, "pf_add_btn")
    assert any("pick one of the suggestions" in w.value for w in at.warning) and holdings(at) == []


def test_selection_is_explicit_and_stays_visible_across_reruns():
    at = clean(pick(type_query(page(), "info"), "Infosys"))
    card = selected_card(at)
    assert "Infosys Limited" in card and "INFY" in card and "INFY.NS" in card
    for _ in range(3):                                      # plain reruns must not clear it
        at = clean(at.run())
        assert at.session_state["pf_selected"] == "INFY" and "Infosys Limited" in selected_card(at)
    assert at.radio[0].value == "Infosys Limited — INFY"
    assert holdings(at) == []                               # still not added until confirmed


def test_selection_survives_editing_the_query_and_leaving_the_page():
    at = pick(type_query(page(), "info"), "Infosys")
    at = clean(type_query(at, "tata"))                      # new query: fresh, unselected radio...
    assert at.radio[0].index is None and "Infosys Limited" in selected_card(at)   # ...chosen stock kept
    at.session_state["page"] = "📉 Charts"
    at.run()
    at.session_state["page"] = "💼 Portfolio"
    at = clean(at.run())
    assert "Infosys Limited" in selected_card(at)


def test_picking_another_suggestion_replaces_the_selection_and_clear_removes_it():
    at = pick(type_query(page(), "tata"), "Tata Steel")
    assert at.session_state["pf_selected"] == "TATASTEEL"
    at = pick(at, "Tata Power")
    assert at.session_state["pf_selected"] == "TATAPOWER" and "Tata Power" in selected_card(at)
    at = clean(click(at, "pf_clear_btn"))
    assert selected_card(at) is None and holdings(at) == []


def test_confirming_adds_the_correct_ticker_once_and_resets_the_form():
    at = pick(type_query(page(), "info"), "Infosys")
    at = clean(click(at, "pf_add_btn"))
    assert holdings(at) == [{"ticker": "INFY.NS", "company": "Infosys Limited"}]
    assert any("Added Infosys Limited (INFY)" in s.value for s in at.success)
    assert at.text_input(key="pf_query").value == "" and selected_card(at) is None and not at.radio
    assert table_tickers(at) == ["INFY.NS"]                 # Holdings table updated
    for _ in range(3):                                      # reruns never re-add
        clean(at.run())
    assert len(holdings(at)) == 1


def test_special_character_company_is_escaped_in_the_card_and_saved_correctly():
    at = clean(pick(type_query(page(), "m&m"), "Mahindra"))
    assert "Mahindra &amp; Mahindra Limited" in selected_card(at)
    clean(click(at, "pf_add_btn"))
    assert holdings(at) == [{"ticker": "M&M.NS", "company": "Mahindra & Mahindra Limited"}]


def test_duplicate_is_flagged_before_and_after_clicking_and_changes_nothing():
    at = seed_portfolio(page(), SAMPLE)
    at = pick(type_query(at, "INFY"), "Infosys")
    assert "already in your portfolio" in selected_card(at)
    at = clean(click(at, "pf_add_btn"))
    assert any("already in your portfolio — nothing was changed" in w.value for w in at.warning)
    assert holdings(at) == SAMPLE and table_tickers(at) == ["INFY.NS", "TCS.NS", "RELIANCE.NS"]


def test_adding_to_an_existing_portfolio_preserves_everything_else():
    at = seed_portfolio(page(), SAMPLE)
    at = pick(type_query(at, "wipro"), "Wipro")
    clean(click(at, "pf_add_btn"))
    assert holdings(at) == SAMPLE + [{"ticker": "WIPRO.NS", "company": "Wipro Limited"}]


def test_existing_portfolio_data_stays_readable_and_the_table_still_has_its_metrics():
    at = clean(seed_portfolio(page(), SAMPLE))
    df = at.dataframe[0].value
    assert list(df.columns) == ["Company", "Ticker", "Price (₹)", "Day %", "P/E", "Market cap"]
    assert len(df) == 3 and df["Price (₹)"].notna().all()


def test_remove_still_works():
    at = seed_portfolio(page(), SAMPLE)
    at.selectbox(key="pf_rm").select("Infosys Limited (INFY.NS)")
    at = clean(at.run())
    next(b for b in at.button if "Remove selected" in b.label).click()
    at = clean(at.run())
    assert [h["ticker"] for h in holdings(at)] == ["TCS.NS", "RELIANCE.NS"]


def test_sample_portfolio_still_loads():
    at = clean(page())
    next(b for b in at.button if "Load sample portfolio" in b.label).click()
    at = clean(at.run())
    assert [h["ticker"] for h in holdings(at)] == ["INFY.NS", "TCS.NS", "RELIANCE.NS"]


def test_missing_company_list_degrades_gracefully(monkeypatch, tmp_path):
    from utils import stock_search
    monkeypatch.setattr(stock_search, "CSV_PATH", tmp_path / "gone.csv")
    at = clean(seed_portfolio(page(), SAMPLE))
    assert any("company list" in e.value and "unavailable" in e.value for e in at.error)
    assert not at.text_input and table_tickers(at) == ["INFY.NS", "TCS.NS", "RELIANCE.NS"]   # rest still works
    assert any("Remove selected" in b.label for b in at.button)


def test_corrupt_company_list_degrades_gracefully(monkeypatch, tmp_path):
    from utils import stock_search
    bad = tmp_path / "bad.csv"
    bad.write_text("SYMBOL,SERIES\nINFY,EQ\n")
    monkeypatch.setattr(stock_search, "CSV_PATH", bad)
    at = clean(page())
    assert any("missing required column" in e.value for e in at.error) and not at.text_input


def test_assistant_and_charts_pages_are_unaffected():
    assert not run_app(page="💬 Assistant").exception
    at = run_app(page="📉 Charts")
    assert not at.exception and at.get("plotly_chart")


# ---- Streamlit-version compatibility of the as-you-type search ---------------------------------
def test_live_search_is_requested_when_streamlit_supports_it(monkeypatch):
    import functools
    import inspect

    import streamlit as st
    original = st.text_input
    if "live" not in inspect.signature(original).parameters:
        pytest.skip("installed Streamlit has no text_input(live=...)")
    seen = {}

    @functools.wraps(original)
    def spy(*a, **kw):
        if kw.get("key") == "pf_query":
            seen.update(kw)
        return original(*a, **kw)
    monkeypatch.setattr(st, "text_input", spy)
    clean(page())
    assert seen.get("live") is True


def test_search_flow_still_works_on_a_streamlit_without_live_support(monkeypatch):
    import streamlit as st
    original = st.text_input

    def legacy_text_input(label, value="", max_chars=None, key=None, type="default", help=None,
                          autocomplete=None, on_change=None, args=None, kwargs=None, *,
                          placeholder=None, disabled=False, label_visibility="visible"):
        return original(label, value, max_chars=max_chars, key=key, type=type, help=help,
                        autocomplete=autocomplete, on_change=on_change, args=args, kwargs=kwargs,
                        placeholder=placeholder, disabled=disabled, label_visibility=label_visibility)
    monkeypatch.setattr(st, "text_input", legacy_text_input)       # no `live` parameter, like Streamlit 1.40
    at = pick(type_query(page(), "info"), "Infosys")
    clean(click(at, "pf_add_btn"))
    assert holdings(at) == [{"ticker": "INFY.NS", "company": "Infosys Limited"}]
