from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "nse_symbols.csv"

COMPANIES = pd.read_csv(CSV_PATH)

ALIASES = {
    "infosys": "INFY.NS",
    "tcs": "TCS.NS",
    "reliance": "RELIANCE.NS",
    "tata motors": "TATAMOTORS.NS",
    "sbi": "SBIN.NS",
    "state bank of india": "SBIN.NS",
    "hdfc bank": "HDFCBANK.NS",
    "icici bank": "ICICIBANK.NS",
    "kotak": "KOTAKBANK.NS",
    "kotak mahindra bank": "KOTAKBANK.NS",
    "wipro": "WIPRO.NS",
    "ongc": "ONGC.NS",
    "irctc": "IRCTC.NS",
    "dixon": "DIXON.NS",
    "dixon technologies": "DIXON.NS",
    "zomato": "ETERNAL.NS"
}


def clean_text(text: str) -> str:

    text = text.lower()

    words_to_remove = [
        "limited",
        "ltd",
        "private",
        "pvt",
        "company",
        "co",
        "corporation",
        "corp",
        "industries",
        "industry",
        "india",
        "&",
        ",",
        "."
    ]

    for word in words_to_remove:
        text = text.replace(word, " ")

    return " ".join(text.split())


def extract_company_name(user_query: str) -> str:
    
    remove_words = {
        "analyze",
        "analyse",
        "stock",
        "stocks",
        "share",
        "shares",
        "price",
        "current",
        "latest",
        "today",
        "buy",
        "sell",
        "hold",
        "invest",
        "should",
        "can",
        "could",
        "would",
        "tell",
        "show",
        "about",
        "of",
        "for",
        "me",
        "please",
        "what",
        "is",
        "the",
        "it",
        "its",
        "this",
        "that",
        "do",
        "i",
        "my",
        "add",
        "remove",
        "portfolio",
        "to",
        "from",
    }

    words = user_query.lower().split()

    filtered = [
        word
        for word in words
        if word not in remove_words
    ]

    return " ".join(filtered)

def get_ticker(user_query: str) -> str | None:

    query = clean_text(extract_company_name(user_query))

    if not query:
        return None

    # ---------- Alias ----------
    if query in ALIASES:
        return ALIASES[query]

    # ---------- Exact Symbol ----------
    for _, row in COMPANIES.iterrows():

        symbol = str(row["SYMBOL"]).strip().lower()

        if query == symbol:
            return f"{row['SYMBOL']}.NS"

    # ---------- Company Contains Query ----------
    for _, row in COMPANIES.iterrows():

        company = clean_text(str(row["NAME OF COMPANY"]))

        if query == company:
            return f"{row['SYMBOL']}.NS"

        if query in company:
            return f"{row['SYMBOL']}.NS"

    # Don't fuzzy match very short queries.
    if len(query) < 3:
        return None

    # ---------- Fuzzy Match ----------
    best_score = 0
    best_symbol = None

    for _, row in COMPANIES.iterrows():

        company = clean_text(str(row["NAME OF COMPANY"]))

        score = fuzz.token_set_ratio(query, company)

        if score > best_score:
            best_score = score
            best_symbol = row["SYMBOL"]

    # Require a stronger match than before.
    if best_score >= 90:
        return f"{best_symbol}.NS"

    return None

def get_multiple_tickers(user_query: str) -> list:

    query = user_query.lower()

    separators = [
        " and ",
        " with ",
        ",",
        " vs ",
        " versus "
    ]

    companies = [query]

    for separator in separators:

        if separator in query:

            companies = query.split(separator)

            break

    tickers = []

    for company in companies:

        ticker = get_ticker(company.strip())

        if ticker and ticker not in tickers:

            tickers.append(ticker)

    return tickers