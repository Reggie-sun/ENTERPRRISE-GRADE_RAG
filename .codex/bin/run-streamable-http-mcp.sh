#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/reggie/vscode_folder/Enterprise-grade_RAG"
RUN_DIR="$PROJECT_ROOT/.codex/run"
LOG_DIR="$PROJECT_ROOT/.codex/logs"
PID_FILE="$RUN_DIR/mcp-streamable-http.pid"
LOG_FILE="$LOG_DIR/mcp-streamable-http.log"
SERVER_SCRIPT="/home/reggie/vscode_folder/MCP/mcp-streamable-http/python-example/server/weather.py"
PYTHON_BIN="/home/reggie/.venvs/mcp-streamable-http/bin/python"
PORT="${STREAMABLE_HTTP_PORT:-8123}"
BASE_URL="http://127.0.0.1:${PORT}"
MCP_URL="${BASE_URL}/mcp"

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_listening() {
  python3 - "$PORT" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.2)
result = sock.connect_ex(("127.0.0.1", int(sys.argv[1])))
sock.close()
raise SystemExit(0 if result == 0 else 1)
PY
}

if ! is_listening; then
  nohup "$PYTHON_BIN" "$SERVER_SCRIPT" --port="$PORT" >>"$LOG_FILE" 2>&1 &
  echo "$!" >"$PID_FILE"

  for _ in {1..50}; do
    if is_listening; then
      break
    fi
    sleep 0.2
  done
fi

if ! is_listening; then
  echo "Failed to start streamable HTTP example server at ${BASE_URL}" >&2
  exit 1
fi

exec npx -y mcp-remote "$MCP_URL" --allow-http --transport http-only --silent
