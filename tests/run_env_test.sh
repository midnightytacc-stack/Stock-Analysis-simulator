#!/bin/bash
rm -rf /tmp/app_env_test /tmp/stock_assistant_sessions; cp -r "$(cd "$(dirname "$0")/../.." && pwd)" /tmp/app_env_test
printf 'ISOLATE_SESSIONS=0\nMAX_QUERIES_PER_SESSION=3\n' > /tmp/app_env_test/.env
echo '[]' > /tmp/app_env_test/memory/portfolio.json; echo '[]' > /tmp/app_env_test/memory/history.json
QUERY_COOLDOWN_SECONDS=0.3 "$(dirname "$0")/with_server.sh" /tmp/app_env_test 8605 "$(dirname "$0")/e2e_env.py"
