#!/usr/bin/env bash
set -euo pipefail

SERVER_DIR="/home/reggie/vscode_folder/MCP/next-ai-draw-io/packages/mcp-server"

export PORT="${PORT:-6002}"

cd "$SERVER_DIR"
exec npx --yes tsx src/index.ts
