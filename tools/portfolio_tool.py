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


def load_portfolio():

    initialize_portfolio()

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as file:

        return json.load(file)


def save_portfolio(portfolio):

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as file:

        json.dump(portfolio, file, indent=4)


def add_stock(ticker):

    portfolio = load_portfolio()

    for stock in portfolio:

        if stock["ticker"] == ticker:
            return f"'{stock['company']}' is already in your portfolio."

    info = get_company_info(ticker)

    company = info.get("company_name", ticker)

    portfolio.append({
        "ticker": ticker,
        "company": company
    })

    save_portfolio(portfolio)

    return f"'{company}' has been added to your portfolio."


def remove_stock(ticker):

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