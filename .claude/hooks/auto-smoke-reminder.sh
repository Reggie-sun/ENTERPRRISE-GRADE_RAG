#!/usr/bin/env bash
# auto-feature-smoke-test hook
# Triggered after Write/Edit operations to remind running smoke tests.
# This hook does NOT auto-run tests — it injects a system reminder so Claude
# suggests running /auto-feature-smoke-test when appropriate.

set -euo pipefail

# Read hook input (JSON from Claude Code)
INPUT=$(cat)

# Extract the file path that was edited
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || echo "")

# Only trigger for backend/frontend source files, skip docs/config
if [[ -n "$FILE_PATH" ]]; then
  case "$FILE_PATH" in
    *.md|*.txt|*.json|*.yml|*.yaml|.gitignore|.env*)
      # Docs/config only — skip reminder
      echo '{"decision": "approve"}'
      exit 0
      ;;
    *)
      # Source file changed — inject reminder
      cat <<'REMINDER'
{"decision": "approve", "systemMessage": "A source file was modified. If this completes a feature slice, consider running /auto-feature-smoke-test to validate the change before final handoff."}
REMINDER
      ;;
  esac
else
  echo '{"decision": "approve"}'
fi
