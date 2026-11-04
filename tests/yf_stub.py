"""TEST HARNESS ONLY (not part of the app): offline stand-in for yfinance so the UI can be exercised
without Yahoo access. Imported via sitecustomize when STUB_YF=1."""
import numpy as np, pandas as pd

class _T:
    def __init__(self, t): self.t = t
    @property
    def info(self):
        return {"longName": self.t.replace(".NS", "") + " Limited", "currentPrice": 1000.0, "previousClose": 990.0,
                "dayLow": 985.0, "dayHigh": 1010.0, "fiftyTwoWeekLow": 800.0, "fiftyTwoWeekHigh": 1200.0,
                "volume": 123456, "marketCap": 5e12, "trailingPE": 22.5, "trailingEps": 40.0, "priceToBook": 5.0,
                "beta": 0.9, "dividendRate": 20.0, "sector": "Tech", "industry": "IT"}
    def history(self, period="1y", **kw):
        years = {"max": 20, "5y": 5, "1y": 1}.get(period, 5)
        if self.t.startswith("ETERNAL"): years = 1         # short-history ticker (listed ~1y ago)
        if self.t == "WIPRO.NS": raise RuntimeError("simulated Yahoo outage")
        n = int(252 * years)
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n, tz="Asia/Kolkata")
        rng = np.random.default_rng(abs(hash(self.t)) % 2**32)
        close = 100 + np.cumsum(rng.normal(0.1, 1.5, n)); close = np.abs(close) + 10
        df = pd.DataFrame({"Open": close * .995, "High": close * 1.01, "Low": close * .99, "Close": close,
                           "Volume": rng.integers(1e5, 1e6, n)}, index=idx)
        df.attrs["period_requested"] = period
        _T.last_period = period
        return df
CALLS = []
def Ticker(t):
    CALLS.append(t); return _T(t)
