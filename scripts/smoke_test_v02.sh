#!/usr/bin/env bash
set -euo pipefail

# v0.2 smoke test:
# health -> batch upload -> poll jobs -> list/filter -> preview -> rebuild -> delete

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8020}"
API_V1="${API_BASE_URL%/}/api/v1"
TENANT_ID="${TENANT_ID:-wl}"
CREATED_BY="${CREATED_BY:-smoke-v02-script}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-2}"
POLL_TIMEOUT_SECONDS="${POLL_TIMEOUT_SECONDS:-240}"
CURL_TIMEOUT_SECONDS="${CURL_TIMEOUT_SECONDS:-30}"

if ! command -v jq >/dev/null 2>&1; then
  echo "[FAIL] missing dependency: jq"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[FAIL] missing dependency: curl"
  exit 1
fi

PREFIX="v02_smoke_$(date +%s)"
FILE_A="$(mktemp "/tmp/${PREFIX}_a_XXXXXX.txt")"
FILE_B="$(mktemp "/tmp/${PREFIX}_b_XXXXXX.txt")"

cleanup() {
  rm -f "${FILE_A}" "${FILE_B}"
}
trap cleanup EXIT

validate_json() {
  local payload="$1"
  local step="$2"
  if ! echo "${payload}" | jq -e . >/dev/null 2>&1; then
    echo "[FAIL] ${step} returned non-JSON payload"
    echo "${payload}"
    exit 1
  fi
}

curl_json() {
  curl -sS --max-time "${CURL_TIMEOUT_SECONDS}" "$@"
}

cat > "${FILE_A}" <<EOF
v0.2 smoke file A
keyword: ${PREFIX}
generated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

cat > "${FILE_B}" <<EOF
v0.2 smoke file B
keyword: ${PREFIX}
generated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

echo "[STEP] 1/7 health check: ${API_V1}/health"
HEALTH_JSON="$(curl_json "${API_V1}/health")"
validate_json "${HEALTH_JSON}" "health check"
HEALTH_STATUS="$(echo "${HEALTH_JSON}" | jq -r '.status // empty')"
if [[ "${HEALTH_STATUS}" != "ok" ]]; then
  echo "[FAIL] health check failed"
  echo "${HEALTH_JSON}"
  exit 1
fi
echo "[PASS] health check ok"

echo "[STEP] 2/7 batch create documents: ${API_V1}/documents/batch"
BATCH_JSON="$(curl_json -X POST "${API_V1}/documents/batch" \
  -F "files=@${FILE_A};type=text/plain" \
  -F "files=@${FILE_B};type=text/plain" \
  -F "tenant_id=${TENANT_ID}" \
  -F "created_by=${CREATED_BY}")"
validate_json "${BATCH_JSON}" "batch create"

BATCH_TOTAL="$(echo "${BATCH_JSON}" | jq -r '.total // 0')"
BATCH_QUEUED="$(echo "${BATCH_JSON}" | jq -r '.queued // 0')"
BATCH_FAILED="$(echo "${BATCH_JSON}" | jq -r '.failed // 0')"

if [[ "${BATCH_TOTAL}" != "2" || "${BATCH_QUEUED}" != "2" || "${BATCH_FAILED}" != "0" ]]; then
  echo "[FAIL] batch create returned unexpected counts"
  echo "${BATCH_JSON}"
  exit 1
fi

DOC_ID_A="$(echo "${BATCH_JSON}" | jq -r '.items[0].doc_id // empty')"
DOC_ID_B="$(echo "${BATCH_JSON}" | jq -r '.items[1].doc_id // empty')"
JOB_ID_A="$(echo "${BATCH_JSON}" | jq -r '.items[0].job_id // empty')"
JOB_ID_B="$(echo "${BATCH_JSON}" | jq -r '.items[1].job_id // empty')"

if [[ -z "${DOC_ID_A}" || -z "${DOC_ID_B}" || -z "${JOB_ID_A}" || -z "${JOB_ID_B}" ]]; then
  echo "[FAIL] batch create missing doc_id/job_id"
  echo "${BATCH_JSON}"
  exit 1
fi
echo "[PASS] batch queued docs: ${DOC_ID_A}, ${DOC_ID_B}"

poll_job_until_completed() {
  local job_id="$1"
  local label="$2"
  local start_ts now_ts elapsed status stage progress job_json
  start_ts="$(date +%s)"
  while true; do
    job_json="$(curl_json "${API_V1}/ingest/jobs/${job_id}")"
    validate_json "${job_json}" "poll ingest job ${job_id}"
    status="$(echo "${job_json}" | jq -r '.status // empty')"
    stage="$(echo "${job_json}" | jq -r '.stage // empty')"
    progress="$(echo "${job_json}" | jq -r '.progress // empty')"
    echo "  - ${label}: status=${status} stage=${stage} progress=${progress}%"

    if [[ "${status}" == "completed" ]]; then
      return 0
    fi
    if [[ "${status}" == "failed" || "${status}" == "dead_letter" || "${status}" == "partial_failed" ]]; then
      echo "[FAIL] ${label} reached terminal failure status"
      echo "${job_json}"
      return 1
    fi

    now_ts="$(date +%s)"
    elapsed="$((now_ts - start_ts))"
    if (( elapsed >= POLL_TIMEOUT_SECONDS )); then
      echo "[FAIL] ${label} polling timeout after ${POLL_TIMEOUT_SECONDS}s"
      echo "${job_json}"
      return 1
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
  done
}

echo "[STEP] 3/7 poll ingest jobs until completed"
poll_job_until_completed "${JOB_ID_A}" "job_a"
poll_job_until_completed "${JOB_ID_B}" "job_b"
echo "[PASS] both jobs completed"

echo "[STEP] 4/7 document list filter check"
LIST_JSON="$(curl_json "${API_V1}/documents?page=1&page_size=20&keyword=${PREFIX}")"
validate_json "${LIST_JSON}" "document list filter"
LIST_TOTAL="$(echo "${LIST_JSON}" | jq -r '.total // 0')"
LIST_MATCH_A="$(echo "${LIST_JSON}" | jq -r --arg d "${DOC_ID_A}" '[.items[] | select(.document_id == $d)] | length')"
LIST_MATCH_B="$(echo "${LIST_JSON}" | jq -r --arg d "${DOC_ID_B}" '[.items[] | select(.document_id == $d)] | length')"

if (( LIST_TOTAL < 2 )) || (( LIST_MATCH_A < 1 )) || (( LIST_MATCH_B < 1 )); then
  echo "[FAIL] list/filter check failed"
  echo "${LIST_JSON}"
  exit 1
fi
echo "[PASS] list/filter returned both docs"

echo "[STEP] 5/7 preview check for doc_a"
PREVIEW_JSON="$(curl_json "${API_V1}/documents/${DOC_ID_A}/preview?max_chars=500")"
validate_json "${PREVIEW_JSON}" "document preview"
PREVIEW_TYPE="$(echo "${PREVIEW_JSON}" | jq -r '.preview_type // empty')"
PREVIEW_TEXT="$(echo "${PREVIEW_JSON}" | jq -r '.text_content // empty')"
if [[ "${PREVIEW_TYPE}" != "text" ]]; then
  echo "[FAIL] preview type mismatch"
  echo "${PREVIEW_JSON}"
  exit 1
fi
if ! grep -q "${PREFIX}" <<<"${PREVIEW_TEXT}"; then
  echo "[FAIL] preview text missing expected keyword"
  echo "${PREVIEW_JSON}"
  exit 1
fi
echo "[PASS] preview check ok"

echo "[STEP] 6/7 rebuild vectors for doc_a"
REBUILD_JSON="$(curl_json -X POST "${API_V1}/documents/${DOC_ID_A}/rebuild")"
validate_json "${REBUILD_JSON}" "rebuild vectors"
REBUILD_STATUS="$(echo "${REBUILD_JSON}" | jq -r '.status // empty')"
REBUILD_JOB_ID="$(echo "${REBUILD_JSON}" | jq -r '.job_id // empty')"
if [[ "${REBUILD_STATUS}" != "queued" || -z "${REBUILD_JOB_ID}" ]]; then
  echo "[FAIL] rebuild trigger failed"
  echo "${REBUILD_JSON}"
  exit 1
fi
poll_job_until_completed "${REBUILD_JOB_ID}" "rebuild_job_a"
echo "[PASS] rebuild completed"

echo "[STEP] 7/7 delete doc_b and verify status"
DELETE_JSON="$(curl_json -X DELETE "${API_V1}/documents/${DOC_ID_B}")"
validate_json "${DELETE_JSON}" "delete document"
DELETE_STATUS="$(echo "${DELETE_JSON}" | jq -r '.status // empty')"
if [[ "${DELETE_STATUS}" != "deleted" ]]; then
  echo "[FAIL] delete failed"
  echo "${DELETE_JSON}"
  exit 1
fi

DETAIL_JSON="$(curl_json "${API_V1}/documents/${DOC_ID_B}")"
validate_json "${DETAIL_JSON}" "document detail after delete"
DETAIL_STATUS="$(echo "${DETAIL_JSON}" | jq -r '.status // empty')"
if [[ "${DETAIL_STATUS}" != "deleted" ]]; then
  echo "[FAIL] delete status not persisted"
  echo "${DETAIL_JSON}"
  exit 1
fi
echo "[PASS] delete status persisted"

echo
echo "[DONE] v0.2 smoke test passed"
echo "doc_id_a=${DOC_ID_A}"
echo "doc_id_b=${DOC_ID_B}"
echo "job_id_a=${JOB_ID_A}"
echo "job_id_b=${JOB_ID_B}"
echo "rebuild_job_id_a=${REBUILD_JOB_ID}"
