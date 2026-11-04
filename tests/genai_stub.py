"""TEST HARNESS ONLY: offline stand-in for the Gemini client. Control files (touch to trigger once):
   /tmp/genai_fail_minute  -> next call raises a real google.genai ClientError 429 (per-minute)
   /tmp/genai_fail_day     -> next call raises 429 (per-day)
   /tmp/genai_fail_key     -> next call raises 403/401-style key error"""
import os, types
from google.genai import errors

def _report(n):
    paras = "\n\n".join(
        f"Paragraph {i}: this is deliberately long assistant text used to make the page taller than the screen. "
        "It talks about market performance, ratios, RSI, MACD and Bollinger Bands in enough words to wrap." for i in range(1, 9))
    return (f"==================================================\n📈 STOCK ANALYSIS REPORT\n==================================================\n\n"
            f"🏢 Company Overview\n\nReply number {n}.\n\n{paras}\n\n📊 Market Performance\n\n{paras}\n\n✅ Overall Summary\n\nDone {n}.")

class _Models:
    n = 0
    def generate_content(self, model=None, contents=None, config=None):
        for flag, code, status, msg in (
            ("/tmp/genai_fail_minute", 429, "RESOURCE_EXHAUSTED", "You exceeded your current quota. Quota exceeded for metric generate_content_free_tier_requests, quotaId GenerateRequestsPerMinutePerProjectPerModel-FreeTier. Please retry in 34.2s."),
            ("/tmp/genai_fail_day", 429, "RESOURCE_EXHAUSTED", "You exceeded your current quota. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
            ("/tmp/genai_fail_key", 400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.")):
            if os.path.exists(flag):
                os.remove(flag)
                raise errors.ClientError(code, {"error": {"code": code, "message": msg, "status": status}})
        _Models.n += 1
        return types.SimpleNamespace(text=_report(_Models.n))

class Client:
    def __init__(self, *a, **k): self.models = _Models()
