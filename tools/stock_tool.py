import yfinance as yf
import pandas as pd


def _get_stock(ticker: str) -> yf.Ticker:
    return yf.Ticker(ticker)


def _get_stock_info(ticker: str) -> dict:
    stock = _get_stock(ticker)
    return stock.info


def get_company_info(ticker: str) -> dict:
    try:
        info = _get_stock_info(ticker)

        return {
            "company_name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "employees": info.get("fullTimeEmployees")
        }

    except Exception as e:
        return {
            "error": f"Failed to fetch company information: {str(e)}"
        }


def get_market_data(ticker: str) -> dict:
    try:
        info = _get_stock_info(ticker)

        return {
            "current_price": info.get("currentPrice"),
            "previous_close": info.get("previousClose"),
            "open": info.get("open"),
            "day_high": info.get("dayHigh"),
            "day_low": info.get("dayLow"),
            "volume": info.get("volume")
        }

    except Exception as e:
        return {
            "error": f"Failed to fetch market data: {str(e)}"
        }


def get_financial_ratios(ticker: str) -> dict:
    try:
        info = _get_stock_info(ticker)

        return {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "book_value": info.get("bookValue"),
            "price_to_book": info.get("priceToBook")
        }

    except Exception as e:
        return {
            "error": f"Failed to fetch financial ratios: {str(e)}"
        }


def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame | dict:

    try:
        stock = _get_stock(ticker)

        history = stock.history(period=period)

        if history.empty:
            return {
                "error": "No historical data found for the given ticker."
            }

        return history

    except Exception as e:
        return {
            "error": f"Failed to fetch historical data: {str(e)}"
        }