
import yfinance as yf


# Indian market indices and sector indices.
MARKET_INDICES = {
    "Nifty 50": "^NSEI",
    "Sensex": "^BSESN",
    "Nifty Bank": "^NSEBANK",
    "Nifty IT": "^CNXIT",
    "Nifty Pharma": "^CNXPHARMA",
    "Nifty FMCG": "^CNXFMCG",
}

VOLATILITY_INDICES = {
    "India VIX": "^INDIAVIX",
}


def _get_index_data(name: str, ticker: str) -> dict:
    """
    Fetch recent market data for an Indian market index.
    """

    try:
        stock = yf.Ticker(ticker)

        history = stock.history(
            period="5d",
            interval="1d",
            auto_adjust=False
        )

        if history.empty or len(history) < 2:
            return {
                "name": name,
                "ticker": ticker,
                "error": "Insufficient historical data available."
            }

        latest = history.iloc[-1]
        previous = history.iloc[-2]

        current_price = float(latest["Close"])
        previous_close = float(previous["Close"])

        if previous_close == 0:
            return {
                "name": name,
                "ticker": ticker,
                "error": "Previous closing price is unavailable."
            }

        change = current_price - previous_close

        change_percent = (
            change / previous_close
        ) * 100

        return {
            "name": name,
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "open": round(float(latest["Open"]), 2),
            "day_high": round(float(latest["High"]), 2),
            "day_low": round(float(latest["Low"]), 2),
            "volume": int(latest["Volume"]),
            "latest_trading_date": str(history.index[-1].date()),
            "direction": (
                "Positive" if change > 0
                else "Negative" if change < 0
                else "Unchanged"
            )
        }

    except Exception as e:
        return {
            "name": name,
            "ticker": ticker,
            "error": f"Failed to fetch index data: {str(e)}"
        }


def get_major_indices() -> dict:
    """
    Fetch performance data for major Indian market indices.
    """

    results = {}

    for name, ticker in MARKET_INDICES.items():
        results[name] = _get_index_data(name, ticker)

    return results


def get_market_volatility() -> dict:
    """
    Fetch India VIX data to understand market volatility.
    """

    results = {}

    for name, ticker in VOLATILITY_INDICES.items():
        results[name] = _get_index_data(name, ticker)

    return results


def get_sector_performance() -> dict:
    """
    Fetch performance data for major Indian market sectors.
    """

    sector_names = [
        "Nifty Bank",
        "Nifty IT",
        "Nifty Pharma",
        "Nifty FMCG",
    ]

    results = {}

    for name in sector_names:
        ticker = MARKET_INDICES[name]
        results[name] = _get_index_data(name, ticker)

    return results


def get_market_overview() -> dict:
    """
    Collect an overview of the Indian stock market,
    including benchmark indices, volatility and sectors.
    """

    indices = get_major_indices()
    volatility = get_market_volatility()
    sectors = get_sector_performance()

    successful_indices = [
        data for data in indices.values()
        if "error" not in data
    ]

    if not successful_indices:
        return {
            "error": "Unable to retrieve Indian market data."
        }

    return {
        "market": "Indian Stock Market",
        "indices": indices,
        "volatility": volatility,
        "sector_performance": sectors,
        "data_note": (
            "Data represents the latest available daily trading "
            "session from Yahoo Finance. It may not represent "
            "live intraday prices."
        )
    }
