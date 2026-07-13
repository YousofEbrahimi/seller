#!/usr/bin/env bash
# run.sh — manage the File Store Telegram bot process (long polling)
# Usage:  bash run.sh start | stop | restart | status | logs
#
# No root needed. Uses nohup + PID file. Designed for alwaysdata / any Linux VPS.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PID_FILE="$DIR/bot.pid"
LOG_FILE="$DIR/bot.log"
PYTHON="${PYTHON:-python3}"

b() { printf '\033[1;36m%s\033[0m\n' "$*"; }
g() { printf '\033[1;32m%s\033[0m\n' "$*"; }
r() { printf '\033[1;31m%s\033[0m\n' "$*"; }

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

start() {
  if is_running; then
    g "Bot is already running (PID $(cat "$PID_FILE"))."
    return 0
  fi
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    r "Python ($PYTHON) not found. Install python3 or set PYTHON env var."
    exit 1
  fi
  # Check .env exists
  if [ ! -f "$DIR/.env" ]; then
    r ".env not found. Copy .env.example to .env and fill in your settings."
    exit 1
  fi
  # Check pip dependencies
  b "Checking dependencies..."
  "$PYTHON" -c "import telegram, sqlalchemy, dotenv" 2>/dev/null || {
    r "Dependencies not installed. Run:  pip install -r requirements.txt"
    echo "  If pip is not available, try:  $PYTHON -m pip install -r requirements.txt"
    exit 1
  }
  b "Starting bot..."
  nohup "$PYTHON" "$DIR/main.py" >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 2
  if is_running; then
    g "Bot started (PID $(cat "$PID_FILE")). Logs: $LOG_FILE"
  else
    r "Bot failed to start. Check $LOG_FILE"
    tail -20 "$LOG_FILE" 2>/dev/null
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop() {
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    b "Stopping bot (PID $pid)..."
    kill "$pid" 2>/dev/null
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
      r "Process did not stop, sending SIGKILL..."
      kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    g "Bot stopped."
  else
    r "Bot is not running."
    rm -f "$PID_FILE"
  fi
}

status_cmd() {
  if is_running; then
    g "Bot is running (PID $(cat "$PID_FILE"))."
  else
    r "Bot is not running."
  fi
}

logs_cmd() {
  if [ -f "$LOG_FILE" ]; then
    tail -f "$LOG_FILE"
  else
    r "No log file found at $LOG_FILE"
  fi
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status_cmd ;;
  logs)    logs_cmd ;;
  *)
    echo "Usage: bash run.sh {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
