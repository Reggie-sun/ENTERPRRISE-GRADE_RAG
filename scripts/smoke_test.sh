#!/usr/bin/env bash
set -euo pipefail

# Minimal v0.1.2 smoke test:
# health -> async ingest -> retrieval(document_id) -> chat(document_id)

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8020}"
API_V1="${API_BASE_URL%/}/api/v1"
TENANT_ID="${TENANT_ID:-wl}"
CREATED_BY="${CREATED_BY:-smoke-script}"
QUERY_TEXT="${QUERY_TEXT:-这份文档主要讲了什么？}"
QUESTION_TEXT="${QUESTION_TEXT:-请总结这份文档，并给出引用依据。}"
TOP_K="${TOP_K:-3}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-2}"
POLL_TIMEOUT_SECONDS="${POLL_TIMEOUT_SECONDS:-180}"

if ! command -v jq >/dev/null 2>&1; then
  echo "[FAIL] missing dependency: jq"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[FAIL] missing dependency: curl"
  exit 1
fi

TMP_FILE="$(mktemp /tmp/rag_smoke_XXXXXX.txt)"
cleanup() {
  rm -f "${TMP_FILE}"
}
trap cleanup EXIT

cat > "${TMP_FILE}" <<EOF
RAG v0.1.2 smoke file
keyword: E102
generated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

echo "[STEP] 1/5 health check: ${API_V1}/health"
HEALTH_JSON="$(curl -sS "${API_V1}/health")"
HEALTH_STATUS="$(echo "${HEALTH_JSON}" | jq -r '.status // empty')"
if [[ "${HEALTH_STATUS}" != "ok" ]]; then
  echo "[FAIL] health check failed"
  echo "${HEALTH_JSON}"
  exit 1
fi
echo "[PASS] health check ok"

echo "[STEP] 2/5 create async ingest job: ${API_V1}/documents"
CREATE_JSON="$(curl -sS -X POST "${API_V1}/documents" \
  -F "file=@${TMP_FILE};type=text/plain" \
  -F "tenant_id=${TENANT_ID}" \
  -F "created_by=${CREATED_BY}")"
DOC_ID="$(echo "${CREATE_JSON}" | jq -r '.doc_id // empty')"
JOB_ID="$(echo "${CREATE_JSON}" | jq -r '.job_id // empty')"
CREATE_STATUS="$(echo "${CREATE_JSON}" | jq -r '.status // empty')"
if [[ -z "${DOC_ID}" || -z "${JOB_ID}" || "${CREATE_STATUS}" != "queued" ]]; then
  echo "[FAIL] create document failed"
  echo "${CREATE_JSON}"
  exit 1
fi
echo "[PASS] created doc_id=${DOC_ID}, job_id=${JOB_ID}"

echo "[STEP] 3/5 poll ingest job until completed"
START_TS="$(date +%s)"
JOB_JSON=""
JOB_STATUS=""
while true; do
  JOB_JSON="$(curl -sS "${API_V1}/ingest/jobs/${JOB_ID}")"
  JOB_STATUS="$(echo "${JOB_JSON}" | jq -r '.status // empty')"
  JOB_STAGE="$(echo "${JOB_JSON}" | jq -r '.stage // empty')"
  JOB_PROGRESS="$(echo "${JOB_JSON}" | jq -r '.progress // empty')"
  echo "  - status=${JOB_STATUS} stage=${JOB_STAGE} progress=${JOB_PROGRESS}%"

  if [[ "${JOB_STATUS}" == "completed" ]]; then
    echo "[PASS] ingest completed"
    break
  fi
  if [[ "${JOB_STATUS}" == "failed" || "${JOB_STATUS}" == "dead_letter" || "${JOB_STATUS}" == "partial_failed" ]]; then
    echo "[FAIL] ingest reached terminal failure status"
    echo "${JOB_JSON}"
    exit 1
  fi

  NOW_TS="$(date +%s)"
  ELAPSED="$((NOW_TS - START_TS))"
  if (( ELAPSED >= POLL_TIMEOUT_SECONDS )); then
    echo "[FAIL] ingest polling timeout after ${POLL_TIMEOUT_SECONDS}s"
    echo "${JOB_JSON}"
    exit 1
  fi

  sleep "${POLL_INTERVAL_SECONDS}"
done

echo "[STEP] 4/5 retrieval with document_id filter"
RETRIEVAL_JSON="$(curl -sS -X POST "${API_V1}/retrieval/search" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg q "${QUERY_TEXT}" \
    --arg d "${DOC_ID}" \
    --argjson k "${TOP_K}" \
    '{query: $q, top_k: $k, document_id: $d}')")"
RESULT_COUNT="$(echo "${RETRIEVAL_JSON}" | jq -r '.results | length')"
FOREIGN_COUNT="$(echo "${RETRIEVAL_JSON}" | jq -r --arg d "${DOC_ID}" '[.results[] | select(.document_id != $d)] | length')"
if (( RESULT_COUNT < 1 )); then
  echo "[FAIL] retrieval returned empty results"
  echo "${RETRIEVAL_JSON}"
  exit 1
fi
if (( FOREIGN_COUNT > 0 )); then
  echo "[FAIL] retrieval returned chunks from other documents"
  echo "${RETRIEVAL_JSON}"
  exit 1
fi
echo "[PASS] retrieval returned ${RESULT_COUNT} results, all filtered by doc_id"

echo "[STEP] 5/5 chat with document_id filter"
CHAT_JSON="$(curl -sS -X POST "${API_V1}/chat/ask" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg q "${QUESTION_TEXT}" \
    --arg d "${DOC_ID}" \
    --argjson k "${TOP_K}" \
    '{question: $q, top_k: $k, document_id: $d}')")"
ANSWER_TEXT="$(echo "${CHAT_JSON}" | jq -r '.answer // empty')"
CITATION_COUNT="$(echo "${CHAT_JSON}" | jq -r '.citations | length')"
FOREIGN_CITATION_COUNT="$(echo "${CHAT_JSON}" | jq -r --arg d "${DOC_ID}" '[.citations[] | select(.document_id != $d)] | length')"
if [[ -z "${ANSWER_TEXT}" ]]; then
  echo "[FAIL] chat answer is empty"
  echo "${CHAT_JSON}"
  exit 1
fi
if (( CITATION_COUNT < 1 )); then
  echo "[FAIL] chat returned no citations"
  echo "${CHAT_JSON}"
  exit 1
fi
if (( FOREIGN_CITATION_COUNT > 0 )); then
  echo "[FAIL] chat citations contain other documents"
  echo "${CHAT_JSON}"
  exit 1
fi
echo "[PASS] chat returned answer with ${CITATION_COUNT} citations, all filtered by doc_id"

echo
echo "[DONE] v0.1.2 smoke test passed"
echo "doc_id=${DOC_ID}"
echo "job_id=${JOB_ID}"
