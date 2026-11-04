# Browser (end-to-end) tests

These drive the real Streamlit app in headless Chromium. They use **offline stand-ins** for Yahoo Finance and
Gemini (`yf_stub.py`, `genai_stub.py`, loaded through `sitecustomize.py`) so no network or API key is needed.
The stubs live only here; the app itself never uses fake data.

Needs: `pip install playwright pytest` and a Chromium for Playwright (`playwright install chromium`).

```
# from the project root
bash tests/e2e/with_server.sh . 8603 tests/e2e/e2e_portfolio_charts.py   # portfolio, charts autocomplete, All Time
QUERY_COOLDOWN_SECONDS=0.3 bash tests/e2e/with_server.sh . 8604 tests/e2e/e2e_assistant.py   # 20+ turns, sticky nav, 429 + retry
bash tests/e2e/run_env_test.sh                                          # .env: ISOLATE_SESSIONS=0 persistence + optional cap
pytest tests/test_update5.py                                            # fast unit tests
```
Run these from the project root as shown. `PLAYWRIGHT_BROWSERS_PATH` is honoured if your Chromium is installed elsewhere.
The theme variables it sets mirror the app's colour tokens (needed so the sticky navigation background matches the page).
