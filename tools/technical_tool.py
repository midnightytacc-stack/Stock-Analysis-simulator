from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

from tools.stock_tool import get_price_history


def _get_close_prices(ticker: str):
    history = get_price_history(ticker)

    if isinstance(history, dict) and "error" in history:
        return history

    return history["Close"]


def get_moving_averages(ticker: str) -> dict:

    try:
        close_prices = _get_close_prices(ticker)

        if isinstance(close_prices, dict):
            return close_prices

        sma_20 = SMAIndicator(
            close=close_prices,
            window=20
        ).sma_indicator()

        sma_50 = SMAIndicator(
            close=close_prices,
            window=50
        ).sma_indicator()

        sma_200 = SMAIndicator(
            close=close_prices,
            window=200
        ).sma_indicator()

        return {
            "sma_20": round(float(sma_20.iloc[-1]), 2),
            "sma_50": round(float(sma_50.iloc[-1]), 2),
            "sma_200": round(float(sma_200.iloc[-1]), 2)
        }

    except Exception as e:
        return {
            "error": f"Failed to calculate moving averages: {str(e)}"
        }


def get_rsi(ticker: str) -> dict:

    try:
        close_prices = _get_close_prices(ticker)

        if isinstance(close_prices, dict):
            return close_prices

        rsi = RSIIndicator(
            close=close_prices,
            window=14
        ).rsi()

        return {
            "rsi": round(float(rsi.iloc[-1]), 2)
        }

    except Exception as e:
        return {
            "error": f"Failed to calculate RSI: {str(e)}"
        }


def get_macd(ticker: str) -> dict:
    
    try:
        close_prices = _get_close_prices(ticker)

        if isinstance(close_prices, dict):
            return close_prices

        macd = MACD(close=close_prices)

        return {
            "macd": round(float(macd.macd().iloc[-1]), 2),
            "signal": round(float(macd.macd_signal().iloc[-1]), 2),
            "histogram": round(float(macd.macd_diff().iloc[-1]), 2)
        }

    except Exception as e:
        return {
            "error": f"Failed to calculate MACD: {str(e)}"
        }


def get_bollinger_bands(ticker: str) -> dict:

    try:
        close_prices = _get_close_prices(ticker)

        if isinstance(close_prices, dict):
            return close_prices

        bollinger = BollingerBands(
            close=close_prices,
            window=20,
            window_dev=2
        )

        return {
            "upper_band": round(float(bollinger.bollinger_hband().iloc[-1]), 2),
            "middle_band": round(float(bollinger.bollinger_mavg().iloc[-1]), 2),
            "lower_band": round(float(bollinger.bollinger_lband().iloc[-1]), 2)
        }

    except Exception as e:
        return {
            "error": f"Failed to calculate Bollinger Bands: {str(e)}"
        }


def get_technical_indicators(ticker: str) -> dict:
    return {
        "moving_averages": get_moving_averages(ticker),
        "rsi": get_rsi(ticker),
        "macd": get_macd(ticker),
        "bollinger_bands": get_bollinger_bands(ticker)
    }