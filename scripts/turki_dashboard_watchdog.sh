#!/usr/bin/env bash
# Turki Dashboard Watchdog — keeps Streamlit dashboard alive on port 5053
# Same pattern as Canvas watchdog: silent when OK, restart when dead.

PORT=5053
WORK_DIR="/home/andrew/turk-price-intelligence"
LOG_FILE="/home/andrew/turk-price-intelligence/logs/dashboard_watchdog.log"

mkdir -p "$(dirname "$LOG_FILE")"

# Check if port is listening
if curl -s "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null 2>&1; then
    echo "$(date -Iseconds) — Dashboard OK on port ${PORT}" >> "$LOG_FILE"
    exit 0
fi

echo "$(date -Iseconds) — Dashboard DOWN, restarting..." >> "$LOG_FILE"

# Kill any stale streamlit processes from this project
cd "$WORK_DIR" || exit 1
set -a
# shellcheck source=/dev/null
source /home/andrew/.hermes/.env 2>/dev/null
set +a

pkill -f "streamlit run dashboard.py" 2>/dev/null
sleep 2

# Start Streamlit in background
nohup ./venv/bin/python3 -m streamlit run dashboard.py --server.port "$PORT" --server.headless true --server.address 0.0.0.0 >> "$LOG_FILE" 2>&1 &

sleep 5
if curl -s "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null 2>&1; then
    echo "$(date -Iseconds) — Dashboard restarted successfully" >> "$LOG_FILE"
else
    echo "$(date -Iseconds) — Dashboard restart FAILED" >> "$LOG_FILE"
fi
