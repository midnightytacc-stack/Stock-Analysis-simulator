#!/bin/bash
# usage: with_server.sh <appdir> <port> <e2e script>   (starts the app with offline yfinance/Gemini stubs,
#        runs the Playwright script against it, then stops the server)
APPDIR=$1; PORT=$2; TEST=$3
HARNESS="$(cd "$(dirname "$0")" && pwd)"
TEST="$(cd "$(dirname "$TEST")" && pwd)/$(basename "$TEST")"   # resolve before we cd
cd "$APPDIR" || exit 1
STREAMLIT_THEME_BASE=light STREAMLIT_THEME_BACKGROUND_COLOR='#F5F7FA' STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR='#EDF2F7' STREAMLIT_THEME_TEXT_COLOR='#172B4D' STREAMLIT_THEME_PRIMARY_COLOR='#0F766E' \
  GEMINI_API_KEY=dummy NEWS_API_KEY=dummy STUB_YF=1 STUB_GENAI=1 QUERY_COOLDOWN_SECONDS=${QUERY_COOLDOWN_SECONDS:-3} PYTHONPATH="$HARNESS" \
  streamlit run app.py --server.headless true --server.port $PORT --browser.gatherUsageStats false > /tmp/server_$PORT.log 2>&1 &
SP=$!
for i in $(seq 1 30); do curl -s -o /dev/null localhost:$PORT && break; sleep 1; done
cd "$HARNESS"
python3 "$TEST" http://localhost:$PORT
kill $SP 2>/dev/null; wait $SP 2>/dev/null
echo "--- server log tail ---"; grep -vE "Local URL|Network URL|You can now|^$|external IP|debugging hints|IPv6|Uvicorn" /tmp/server_$PORT.log | tail -15
