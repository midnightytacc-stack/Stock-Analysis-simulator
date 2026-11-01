"""Company search: data loading, ranking, validation. Representative CSV rows, no live data."""
import os
import time

import pytest

from utils import stock_search as ss
from utils.stock_search import (EXACT_NAME, EXACT_TICKER, NAME_PREFIX, PARTIAL, SIMILAR, TICKER_PREFIX,
                                load_universe, search)

# Mirrors the real file: header cells like " SERIES" have a leading space.
HEADER = "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
ROWS = [
    "INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5",
    "INFOBEAN,InfoBeans Technologies Limited,EQ,01-JAN-2020,10,1,INE000000001,10",
    "INFOMEDIA,Infomedia Press Limited,EQ,01-JAN-1990,10,1,INE000000002,10",
    "NAUKRI,Info Edge (India) Limited,EQ,01-JAN-2006,10,1,INE000000003,10",
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1",
    "TATASTEEL,Tata Steel Limited,EQ,01-JAN-1998,1,1,INE081A01020,1",
    "TATAPOWER,Tata Power Company Limited,EQ,01-JAN-1998,1,1,INE245A01021,1",
    "TATACHEM,Tata Chemicals Limited,EQ,01-JAN-1998,10,1,INE092A01019,10",
    "TMPV,Tata Motors Passenger Vehicles Limited,EQ,01-JAN-2025,2,1,INE155A01022,2",
    "RELIANCE,Reliance Industries Limited,EQ,01-JAN-1995,10,1,INE002A01018,10",
    "RPOWER,Reliance Power Limited,EQ,01-JAN-2008,10,1,INE614G01033,10",
    "RCOM,Reliance Communications Limited,BE,01-JAN-2005,5,1,INE330H01018,5",
    "RHFL,Reliance Home Finance Limited,BZ,01-JAN-2018,10,1,INE217K01011,10",
    "M&M,Mahindra & Mahindra Limited,EQ,01-JAN-1990,5,1,INE101A01026,5",
    "BAJAJ-AUTO,Bajaj Auto Limited,EQ,01-JAN-2008,10,1,INE917I01010,10",
    "ETERNAL,ETERNAL LIMITED,EQ,23-JUL-2021,1,1,INE758T01015,1",
    "SBIN,State Bank of India,EQ,01-JAN-1995,1,1,INE062A01020,1",
    "SBICARD,SBI Cards and Payment Services Limited,EQ,01-JAN-2020,10,1,INE018E01016,10",
    "HDFCBANK,HDFC Bank Limited,EQ,01-JAN-1995,1,1,INE040A01034,1",
    "NA,N A Holdings Limited,EQ,01-JAN-2000,10,1,INE000000004,10",      # 'NA' must not be read as NaN
    "dixon,Dixon Technologies (India) Limited,EQ,01-JAN-2017,2,1,INE935N01020,2",   # lower-case symbol
    "INFY,Infosys Limited duplicate,BE,08-FEB-1995,5,1,INE009A01021,5",  # duplicate symbol, worse series
    ",No Symbol Limited,EQ,01-JAN-2000,10,1,INE000000005,10",          # blank symbol
    "BAD SYM!,Malformed Symbol Limited,EQ,01-JAN-2000,10,1,INE000000006,10",
    "NONAME,,EQ,01-JAN-2000,10,1,INE000000007,10",                      # blank name
]


@pytest.fixture()
def csv_file(tmp_path):
    p = tmp_path / "nse.csv"
    p.write_text(HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def uni(csv_file):
    return load_universe(csv_file)


def symbols(result):
    return [m.company.symbol for m in result.matches]


# ---- loading ---------------------------------------------------------------------------
def test_loads_despite_leading_space_headers_and_skips_bad_rows(uni):
    assert uni.ok and uni.error is None
    assert uni.skipped_rows == 3                                         # blank symbol, malformed, blank name
    assert uni.get("INFY").series == "EQ"                                # duplicate kept its better series
    assert uni.get("NA").name == "N A Holdings Limited"                  # 'NA' is a symbol, not a missing value
    assert uni.get("dixon").symbol == "DIXON"                            # symbols are upper-cased
    assert uni.get("BAD SYM!") is None and uni.get("NONAME") is None
    assert len(uni) == 21                                                # 25 rows - 1 duplicate - 3 skipped


def test_validation_accepts_symbols_and_tickers_only_from_the_universe(uni):
    assert uni.get("infy.ns").symbol == "INFY" and uni.get(" TCS ").symbol == "TCS"
    assert uni.get("M&M.NS").name == "Mahindra & Mahindra Limited"
    for bad in ("", None, "NOTREAL", "INFY.NS; rm -rf /", 123):
        assert uni.get(bad) is None


@pytest.mark.parametrize("content,expect", [
    (None, "not found"),
    ("", "could not be read"),
    ("SYMBOL,SERIES\nINFY,EQ\n", "missing required column"),
    ("SYMBOL,NAME OF COMPANY, SERIES\n", "no usable rows"),
    (",,\n,,\n", "missing required column"),
])
def test_missing_empty_or_malformed_files_never_raise(tmp_path, content, expect):
    p = tmp_path / "x.csv"
    if content is not None:
        p.write_text(content)
    u = load_universe(p)
    assert not u.ok and expect in u.error
    r = search("infosys", u)
    assert r.matches == () and "disabled" in r.message and r.total == 0


def test_binary_garbage_file_is_handled(tmp_path):
    p = tmp_path / "x.csv"
    p.write_bytes(os.urandom(2048))
    assert not load_universe(p).ok


def test_universe_is_cached_and_reloaded_when_the_file_changes(csv_file):
    a, b = load_universe(csv_file), load_universe(csv_file)
    assert a is b                                                        # no re-read per keystroke
    csv_file.write_text(HEADER + "ZZZ,Zed Limited,EQ,01-JAN-2000,1,1,INE000000009,1\n")
    c = load_universe(csv_file)
    assert c is not a and [x.symbol for x in (c.get("ZZZ"),)] == ["ZZZ"] and c.get("INFY") is None


def test_headers_without_series_column_still_load(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("SYMBOL,NAME OF COMPANY\nINFY,Infosys Limited\n")
    assert load_universe(p).get("INFY").series == "EQ"


# ---- ranking ----------------------------------------------------------------------------
def test_exact_ticker_wins_in_any_case_and_with_exchange_suffix(uni):
    for q in ("INFY", "infy", "  Infy  ", "infy.ns"):
        r = search(q, uni)
        assert symbols(r)[0] == "INFY" and r.matches[0].tier == EXACT_TICKER


def test_exact_company_name_and_name_without_corporate_suffix(uni):
    for q in ("infosys", "Infosys Limited", "infosys ltd"):
        m = search(q, uni).matches[0]
        assert (m.company.symbol, m.tier) == ("INFY", EXACT_NAME)
    assert search("tata power", uni).matches[0].company.symbol == "TATAPOWER"
    assert search("mahindra and mahindra", uni).matches[0].company.symbol == "M&M"
    assert search("mahindra & mahindra limited", uni).matches[0].company.symbol == "M&M"


def test_exact_ticker_outranks_exact_name_outranks_prefixes(uni):
    assert [m.tier for m in search("reliance", uni).matches][:2] == [EXACT_TICKER, NAME_PREFIX]
    r = search("sbi", uni)                                              # alias 'sbi' -> SBIN (name tier)
    assert (symbols(r)[0], r.matches[0].tier) == ("SBIN", EXACT_NAME) and symbols(r)[1] == "SBICARD"


def test_ticker_prefix_before_name_prefix_before_partial(uni):
    r = search("info", uni)
    assert symbols(r)[:2] == ["INFOBEAN", "INFOMEDIA"] and [m.tier for m in r.matches[:2]] == [TICKER_PREFIX] * 2
    assert "INFY" in symbols(r) and "NAUKRI" in symbols(r)
    assert r.matches[symbols(r).index("INFY")].tier == NAME_PREFIX
    r = search("tata", uni)
    assert [m.tier for m in r.matches] == sorted(m.tier for m in r.matches)
    assert set(symbols(r)) == {"TATASTEEL", "TATAPOWER", "TATACHEM", "TCS", "TMPV"}
    assert search("consultancy", uni).matches[0].tier == PARTIAL and search("consultancy", uni).companies[0].symbol == "TCS"


def test_tiers_never_go_backwards_for_any_query(uni):
    for q in ("t", "tata", "re", "rel", "power", "bank", "in", "s", "m&m", "india", "limited", "a"):
        tiers = [m.tier for m in search(q, uni).matches]
        assert tiers == sorted(tiers), (q, tiers)


def test_series_preference_breaks_ties_eq_then_be_then_others(uni):
    assert symbols(search("reliance", uni))[1:] == ["RPOWER", "RCOM", "RHFL"]   # EQ, EQ, BE, BZ... alphabetical within EQ


def test_typos_are_found_but_rank_last(uni):
    for q, sym in (("infsys", "INFY"), ("relaince", "RELIANCE"), ("tatasteal", "TATASTEEL"), ("hdfc bnk", "HDFCBANK")):
        r = search(q, uni)
        assert sym in symbols(r) and all(m.tier == SIMILAR for m in r.matches), (q, symbols(r))


def test_special_character_symbols(uni):
    assert symbols(search("m&m", uni))[0] == "M&M"
    assert symbols(search("bajaj auto", uni))[0] == "BAJAJ-AUTO"
    assert symbols(search("bajajauto", uni))[0] == "BAJAJ-AUTO"
    assert uni.get("BAJAJ-AUTO").ticker == "BAJAJ-AUTO.NS" and uni.get("M&M").ticker == "M&M.NS"


def test_existing_aliases_are_reused_and_stale_ones_are_never_suggested(uni):
    assert symbols(search("zomato", uni)) == ["ETERNAL"]
    assert "tata motors" in uni.stale_aliases                          # alias target TATAMOTORS isn't in the file
    assert "TATAMOTORS" not in [c.symbol for c in (m.company for r in (search("tata motors", uni),) for m in r.matches)]
    assert "TMPV" in symbols(search("tata motors", uni))               # real listing is still found by name


# ---- display ---------------------------------------------------------------------------
def test_labels_limit_and_total(uni):
    r = search("infosys", uni)
    assert r.matches[0].company.label == "Infosys Limited — INFY" and r.matches[0].company.ticker == "INFY.NS"
    r = search("tata", uni, limit=3)
    assert len(r.matches) == 3 and r.total == 5
    assert len(search("a", uni).matches) <= 8


def test_default_limit_is_between_five_and_eight():
    assert 5 <= ss.DEFAULT_LIMIT <= 8


# ---- empty / unmatched / hostile input ---------------------------------------------------
@pytest.mark.parametrize("q", ["", "   ", None])
def test_empty_query_gives_guidance_not_results(uni, q):
    r = search(q, uni)
    assert r.matches == () and "Type a company name" in r.message


@pytest.mark.parametrize("q", ["xyzqq", "qwerty", "12345"])
def test_unmatched_query_says_so_and_never_picks_something_else(uni, q):
    r = search(q, uni)
    assert r.matches == () and r.total == 0 and q in r.message and "No NSE company matches" in r.message


@pytest.mark.parametrize("q", ["&", "...", "()", "***", "[a-z", "(?i)tata", "\\", "a" * 500, "टाटा", "tata\nsteel", "'; DROP TABLE x;--"])
def test_hostile_or_odd_input_does_not_crash(uni, q):
    r = search(q, uni)
    assert isinstance(r.matches, tuple) and len(r.matches) <= 8


def test_search_is_fast_enough_to_run_per_keystroke(uni):
    start = time.perf_counter()
    for q in ("i", "in", "inf", "info", "infos", "infosy", "zzzz") * 10:
        search(q, uni)
    assert time.perf_counter() - start < 2.0


# ---- the real data file --------------------------------------------------------------------
def test_real_nse_file_smoke():
    u = load_universe()
    assert u.ok and len(u) > 2000
    assert search("INFY", u).matches[0].company.name == "Infosys Limited"
    assert "INFY" in symbols(search("info", u))
    r = search("tata", u)
    assert len(r.matches) == 8 and r.total >= 10 and all("tata" in m.company.name.lower() for m in r.matches)
    assert symbols(search("reliance", u))[0] == "RELIANCE"
    assert symbols(search("zomato", u)) == ["ETERNAL"]
    assert all(u.get(c.symbol) is c for c in (m.company for m in search("bank", u).matches))
    assert "tata motors" in u.stale_aliases   # TATAMOTORS no longer exists in the real list
