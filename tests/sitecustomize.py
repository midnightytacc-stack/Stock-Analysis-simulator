import os, sys
if os.environ.get("STUB_YF") == "1":
    import types, yf_stub
    import yfinance
    yfinance.Ticker = yf_stub.Ticker
if os.environ.get("STUB_GENAI") == "1":
    import genai_stub
    from google import genai
    genai.Client = genai_stub.Client
