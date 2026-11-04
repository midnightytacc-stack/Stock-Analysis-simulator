import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "nse_symbols.csv"

COMPANIES = pd.read_csv(CSV_PATH, dtype=str).fillna("")

# Explicit aliases for common company names and abbreviations.
ALIASES = {
    "infosys": "INFY",
    "tcs": "TCS",
    "reliance": "RELIANCE",
    "tata motors": "TATAMOTORS",
    "tata steel": "TATASTEEL",
    "sbi": "SBIN",
    "state bank of india": "SBIN",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "kotak": "KOTAKBANK",
    "kotak mahindra bank": "KOTAKBANK",
    "wipro": "WIPRO",
    "ongc": "ONGC",
    "irctc": "IRCTC",
    "dixon": "DIXON",
    "dixon technologies": "DIXON",
    "zomato": "ETERNAL",
}


def normalize_text(text: str) -> str:
    """Normalize text and handle possessive forms."""

    text = str(text).lower().strip()

    # Handle possessive forms before removing punctuation
    text = re.sub(r"'s\b", "", text)

    text = text.replace("&", " and ")

    text = "".join(
        char if char.isalnum() or char.isspace() else " "
        for char in text
    )

    return " ".join(text.split())

def extract_company_name(user_query: str) -> str:
    """Remove common stock-question words while preserving company names."""
    query = normalize_text(user_query)

    remove_words = {
        "analyze", "analyse", "stock", "stocks", "share", "shares",
        "price", "prices", "current", "latest", "today", "buy", "sell",
        "hold", "invest", "cap", "health", "should", "can", "could",
        "would", "tell", "show", "about", "of", "for", "me", "please",
        "what", "is", "the", "do", "i", "my", "add", "remove",
        "portfolio", "to", "from", "get", "give", "check", "find",
        "company", "companies", "market", "value", "trading", "traded",
        "now", "right", "know", "how", "much", "does", "did", "was",
        "were", "are", "and", "its", "their", "in", "on", "at"
    }

    words = query.split()
    filtered = [word for word in words if word not in remove_words]

    return " ".join(filtered)

def get_ticker(user_query: str) -> str | None:
    """Resolve a query to an NSE ticker, avoiding weak fuzzy matches."""
    query = normalize_text(extract_company_name(user_query))

    if not query:
        return None

    # Match explicit aliases first.
    if query in ALIASES:
        return f"{ALIASES[query]}.NS"

    # Match exact company symbols or names.
    for _, row in COMPANIES.iterrows():
        symbol = str(row["SYMBOL"]).strip()
        company = normalize_text(row["NAME OF COMPANY"])

        if query == normalize_text(symbol):
            return f"{symbol}.NS"

        if query == company:
            return f"{symbol}.NS"


    # Match complete company names contained in longer queries.
    # Require at least two words to avoid matching generic words
    # such as "health", "technology", or "industries".

    matches = []

    if len(query.split()) >= 2:

        for _, row in COMPANIES.iterrows():
            symbol = str(row["SYMBOL"]).strip()
            company = normalize_text(row["NAME OF COMPANY"])

            if (
                f" {query} " in f" {company} "
                or f" {company} " in f" {query} "
            ):
                matches.append((len(company), symbol))

    if matches:
        matches.sort(reverse=True)
        return f"{matches[0][1]}.NS"

    # Fuzzy matching is deliberately conservative.
    # Very short names and ambiguous queries should not be guessed.
    if len(query) < 5:
        return None

    best_score = 0
    best_symbol = None
    second_best_score = 0

    for _, row in COMPANIES.iterrows():
        symbol = str(row["SYMBOL"]).strip()
        company = normalize_text(row["NAME OF COMPANY"])

        score = fuzz.ratio(query, company)

        if score > best_score:
            second_best_score = best_score
            best_score = score
            best_symbol = symbol
        elif score > second_best_score:
            second_best_score = score

    # Require a strong match and a clear lead over the next candidate.
    if best_score >= 92 and best_score - second_best_score >= 5:
        return f"{best_symbol}.NS"

    return None


def get_multiple_tickers(user_query: str) -> list:
    """Extract up to two distinct company tickers from a comparison query."""
    query = normalize_text(user_query)

    separators = [
        " versus ",
        " vs ",
        " compared with ",
        " compared to ",
        " and ",
        ",",
    ]

    for separator in separators:
        if separator in f" {query} ":
            parts = query.split(separator)

            tickers = []
            for part in parts:
                ticker = get_ticker(part.strip())
                if ticker and ticker not in tickers:
                    tickers.append(ticker)

            if len(tickers) >= 2:
                return tickers[:2]

    # Also support a query that contains two known aliases.
    tickers = []
    for alias, symbol in ALIASES.items():
        if f" {alias} " in f" {query} ":
            ticker = f"{symbol}.NS"
            if ticker not in tickers:
                tickers.append(ticker)

    return tickers[:2]
