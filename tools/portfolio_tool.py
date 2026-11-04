import json
import os

from tools.stock_tool import (
    get_company_info,
    get_market_data
)

PORTFOLIO_FILE = "memory/portfolio.json"


def initialize_portfolio():

    os.makedirs("memory", exist_ok=True)

    if not os.path.exists(PORTFOLIO_FILE):

        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as file:

            json.dump([], file, indent=4)


def _clean_holdings(raw):
    """
    Keep only well-formed holdings ({"ticker": <non-empty str>, "company": <str>}), with tickers
    upper-cased and duplicates (same ticker) collapsed to the first one. Hand-edited or
    half-written entries are dropped instead of crashing every page that lists the portfolio.
    """

    cleaned = []
    seen = set()

    for item in raw:

        if not isinstance(item, dict):
            continue

        ticker = str(item.get("ticker") or "").strip().upper()

        if not ticker or ticker in seen:
            continue

        seen.add(ticker)

        company = str(item.get("company") or "").strip() or ticker

        cleaned.append({"ticker": ticker, "company": company})

    return cleaned


def load_portfolio():
    """
    Return the saved holdings. Raises ValueError (with a readable message) if the file is not
    valid portfolio JSON, rather than treating it as empty and overwriting the user's data.
    """

    initialize_portfolio()

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as file:

        try:
            data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"The portfolio file is not valid JSON ({exc.msg} at line {exc.lineno}). "
                "Fix or delete memory/portfolio.json."
            ) from exc

    if not isinstance(data, list):
        raise ValueError(
            "The portfolio file must contain a list of holdings. "
            "Fix or delete memory/portfolio.json."
        )

    return _clean_holdings(data)


def save_portfolio(portfolio):

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as file:

        json.dump(portfolio, file, indent=4)


def add_stock(ticker, company_name=None):

    ticker = str(ticker or "").strip().upper()

    if not ticker:
        return "No company was given, so nothing was added to your portfolio."

    portfolio = load_portfolio()

    for stock in portfolio:

        if stock["ticker"] == ticker:
            return f"'{stock['company']}' is already in your portfolio."

    if company_name:
        company = company_name
    else:
        info = get_company_info(ticker)
        company = info.get("company_name") or ticker

    portfolio.append({
        "ticker": ticker,
        "company": company
    })

    save_portfolio(portfolio)

    return f"'{company}' has been added to your portfolio."
def remove_stock(ticker):

    ticker = str(ticker or "").strip().upper()

    portfolio = load_portfolio()

    for stock in portfolio:

        if stock["ticker"] == ticker:

            portfolio.remove(stock)

            save_portfolio(portfolio)

            return f"'{stock['company']}' has been removed from your portfolio."

    return "This company is not present in your portfolio."


def view_portfolio():

    portfolio = load_portfolio()

    if not portfolio:

        return (
            "\n"
            "==============================\n"
            "📂 YOUR PORTFOLIO\n"
            "==============================\n\n"
            "Your portfolio is currently empty."
        )

    output = []

    output.append(
        "=============================="
    )

    output.append(
        "📂 YOUR PORTFOLIO"
    )

    output.append(
        "==============================\n"
    )

    for index, stock in enumerate(portfolio, start=1):

        output.append(f"{index}. {stock['company']}")

        output.append(
            f"   Ticker : {stock['ticker']}"
        )

        output.append("")

    output.append(
        f"Total Stocks : {len(portfolio)}"
    )

    return "\n".join(output)


def analyze_portfolio():

    portfolio = load_portfolio()

    if not portfolio:

        return (
            "\n"
            "Portfolio is empty."
        )

    output = []

    output.append(
        "========================================================"
    )

    output.append(
        "📈 PORTFOLIO ANALYSIS"
    )

    output.append(
        "========================================================\n"
    )

    for stock in portfolio:

        market = get_market_data(stock["ticker"])

        output.append(
            f"Company        : {stock['company']}"
        )

        output.append(
            f"Ticker         : {stock['ticker']}"
        )

        output.append(
            f"Current Price  : ₹{market.get('current_price')}"
        )

        output.append(
            f"Previous Close : ₹{market.get('previous_close')}"
        )

        output.append(
            f"Day High       : ₹{market.get('day_high')}"
        )

        output.append(
            f"Day Low        : ₹{market.get('day_low')}"
        )

        output.append(
            "-" * 55
        )

    output.append(
        f"\nTotal Stocks Tracked : {len(portfolio)}"
    )

    return "\n".join(output)


def clear_portfolio():

    save_portfolio([])

    return "Portfolio cleared successfully."