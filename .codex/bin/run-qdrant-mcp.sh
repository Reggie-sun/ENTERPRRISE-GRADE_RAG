#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/reggie/vscode_folder/Enterprise-grade_RAG"
ENV_FILE="$PROJECT_ROOT/.env"

get_env_value() {
  local key="$1"
  local value=""

  if [[ -f "$ENV_FILE" ]]; then
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | sed "s/^${key}=//")"
  fi

  printf '%s' "$value"
}

PROJECT_QDRANT_URL="$(get_env_value "RAG_QDRANT_URL")"

export QDRANT_URL="${QDRANT_URL:-${QDRANT_MCP_URL:-${PROJECT_QDRANT_URL:-http://127.0.0.1:6333}}}"
export COLLECTION_NAME="${COLLECTION_NAME:-${QDRANT_MCP_COLLECTION_NAME:-enterprise_rag_codex_memory}}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-${QDRANT_MCP_EMBEDDING_MODEL:-BAAI/bge-small-zh-v1.5}}"
export FASTMCP_LOG_LEVEL="${FASTMCP_LOG_LEVEL:-INFO}"

exec /home/reggie/.venvs/mcp-qdrant/bin/mcp-server-qdrant
