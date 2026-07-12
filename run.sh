#!/usr/bin/env bash
# =====================================================
# Run the File Store bot in the background (long polling).
# No root needed. Uses nohup so it survives SSH disconnect.
#
# Usage:
#   bash run.sh start    # start in background
#   bash run.sh stop     # stop the running bot
#   bash run.sh restart  # stop + start
#   bash run.sh status   # show running / stopped
#   bash run.sh logs     # tail the log file
# =====================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/bot.pid"
LOG_FILE="$DIR/bot.log"
PHP_BIN="${PHP_BIN:-php}"

cmd="${1:-start}"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "$cmd" in
  start)
    if is_running; then
      echo "Bot already running (PID $(cat "$PID_FILE"))."; exit 0
    fi
    if ! command -v "$PHP_BIN" >/dev/null 2>&1; then
      echo "PHP not found. Install php-cli or set PHP_BIN." >&2; exit 1
    fi
    cd "$DIR"
    nohup "$PHP_BIN" run.php >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Bot started (PID $(cat "$PID_FILE")). Logs: $LOG_FILE"
    ;;
  stop)
    if is_running; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      sleep 2
      # Force kill if still alive
      kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
      echo "Bot stopped."
    else
      echo "Bot not running."
    fi
    rm -f "$PID_FILE"
    ;;
  restart)
    "$0" stop || true
    sleep 1
    "$0" start
    ;;
  status)
    if is_running; then
      echo "Running (PID $(cat "$PID_FILE"))."
    else
      echo "Stopped."
    fi
    ;;
  logs)
    tail -n 200 -f "$LOG_FILE"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
