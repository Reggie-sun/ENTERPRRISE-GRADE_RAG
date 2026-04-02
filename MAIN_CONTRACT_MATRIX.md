# Main Contract Matrix

这份文档把当前 V1 已冻结的主契约面收成一张矩阵，供前端、外部系统、企业微信入口和 smoke 回归直接对照。

使用原则：

- 这里列出的字段，视为当前 V1 的稳定主契约
- 未列入“稳定字段”的内容，默认属于诊断面或可演进字段
- 如果要改这里列出的字段，必须同步更新：
  - `V1_PLAN.md`
  - `RAG架构.md`
  - `backend/tests/test_main_contract_endpoints.py`
  - `backend/tests/test_main_contract_errors.py`

---

## 0. Common Conventions

### 主字段与兼容别名

- 外部统一主字段使用 `document_id`
- `doc_id` 只作为过渡期兼容别名保留
- 请求体里只有明确标注支持别名的接口才接受 `doc_id`
- 响应体里只有 `documents / ingest` 当前仍同时返回 `document_id + doc_id`

### 时间与分页

- 时间字段统一使用 ISO 8601 datetime
- 分页统一使用：
  - `total`
  - `page`
  - `page_size`
  - `items`

### 认证与访问

- `GET /api/v1/health` 与 `POST /api/v1/auth/login` 属于公开入口
- 本文第 2-5 节列出的主业务路由默认都要求 `Bearer` 认证，除非某个接口在文档里明确另行说明
- `GET /api/v1/auth/bootstrap` 不属于稳定匿名契约；只有在显式开启 `auth_identity_bootstrap_public_enabled=true` 时才允许未登录访问
- `GET /api/v1/auth/users/{user_id}` 需要认证，且只允许 `sys_admin` 或用户本人访问

### 资源引用字段

- `storage_path` 与 `source_path` 是稳定字段名
- 它们的值语义是“对外安全的资源引用”，而不是“本地文件系统真实路径”
- 调用方必须接受这类值可能是 `asset://...`、`document://...`、`/api/v1/...` 这类可公开引用形式，而不是磁盘绝对路径

### 错误包

- 主业务接口统一保留兼容字段 `detail`
- 同时返回结构化错误字段：
  - `error.code`
  - `error.message`
  - `error.status_code`
- `422` 请求校验错误继续保留 FastAPI 风格 `detail[]`
- `POST /api/v1/chat/ask/stream` 的 `error` 事件固定返回：
  - `code`
  - `message`
  - `retryable`
  - `retry_after_seconds`

### 稳定面与诊断面

- 这里列出的“稳定字段”视为当前 V1 主契约
- 同一对象里未列入稳定字段的内容，默认属于诊断面
- 诊断字段可以继续扩展，但不能静默替换稳定字段语义

---

## 1. Health / Auth

### `GET /api/v1/health`

稳定顶层字段：
- `status`
- `app_name`
- `environment`
- `vector_store`
- `llm`
- `embedding`
- `reranker`
- `queue`
- `metadata_store`
- `ocr`
- `tokenizer`

稳定嵌套字段：
- `vector_store.provider / url / collection`
- `llm.provider / base_url / model`
- `embedding.provider / base_url / model`
- `reranker.provider / base_url / model / default_strategy / timeout_seconds / failure_cooldown_seconds / effective_provider / effective_model / effective_strategy / fallback_enabled / lock_active / cooldown_remaining_seconds / ready`
- `queue.provider / broker_url / result_backend / ingest_queue`
- `metadata_store.provider / postgres_enabled / dsn_configured`
- `ocr.provider / language / enabled / ready / pdf_native_text_min_chars / angle_cls_enabled`
- `tokenizer.provider / model / ready / trust_remote_code`

诊断字段：
- `reranker.lock_source`
- `reranker.detail`
- `ocr.detail`
- `tokenizer.detail`
- `tokenizer.error`

### `POST /api/v1/auth/login`

稳定字段：
- `access_token`
- `token_type`
- `expires_in_seconds`
- `user`
- `role`
- `department`
- `accessible_department_ids`
- `department_query_isolation_enabled`

### `GET /api/v1/auth/me`

稳定字段：
- `user`
- `role`
- `department`
- `accessible_department_ids`
- `department_query_isolation_enabled`

---

## 2. Documents / Ingest

### `POST /api/v1/documents`

稳定字段：
- `document_id`
- `doc_id`
- `job_id`
- `status`

说明：
- 当前仍处于 `document_id + doc_id` 双字段过渡期
- 外部统一主字段是 `document_id`

### `POST /api/v1/documents/batch`

稳定字段：
- 单条结果至少应稳定包含：
  - `document_id`
  - `doc_id`
  - `job_id`
  - `status`

### `GET /api/v1/documents`

稳定字段：
- `total`
- `page`
- `page_size`
- `items`

每条 item 的稳定字段：
- `document_id`
- `filename`
- `size_bytes`
- `parse_supported`
- `storage_path`
- `status`
- `ingest_status`
- `latest_job_id`
- `department_id`
- `category_id`
- `uploaded_by`
- `updated_at`

### `GET /api/v1/documents/{doc_id}`

稳定字段：
- `document_id`
- `doc_id`
- `file_name`
- `status`
- `ingest_status`
- `department_id`
- `category_id`
- `uploaded_by`
- `current_version`
- `latest_job_id`
- `created_at`
- `updated_at`

### `GET /api/v1/ingest/jobs/{job_id}`

稳定字段：
- `job_id`
- `document_id`
- `doc_id`
- `status`
- `progress`
- `stage`
- `retry_count`
- `max_retry_limit`
- `auto_retry_eligible`
- `manual_retry_allowed`
- `error_code`
- `error_message`
- `created_at`
- `updated_at`

---

## 3. Retrieval / Chat

### `POST /api/v1/retrieval/search`

稳定请求字段：
- `query`
- `top_k`
- `mode`
- `document_id`

稳定响应字段：
- `query`
- `top_k`
- `mode`
- `results`

响应顶层诊断字段：
- `diagnostic`

每条 `results[]` 的稳定字段：
- `chunk_id`
- `document_id`
- `document_name`
- `text`
- `score`
- `source_path`
- `retrieval_strategy`
- `ocr_used`
- `parser_name`
- `page_no`

诊断字段：
- `vector_score`
- `lexical_score`
- `fused_score`
- `ocr_confidence`
- `quality_score`

### `POST /api/v1/chat/ask`

稳定请求字段：
- `question`
- `mode`
- `session_id`
- `document_id`

稳定响应字段：
- `question`
- `answer`
- `mode`
- `model`
- `citations`

每条 `citations[]` 的稳定字段：
- `chunk_id`
- `document_id`
- `document_name`
- `snippet`
- `score`
- `source_path`
- `retrieval_strategy`
- `ocr_used`
- `parser_name`
- `page_no`

诊断字段：
- `vector_score`
- `lexical_score`
- `fused_score`
- `ocr_confidence`
- `quality_score`

### `POST /api/v1/chat/ask/stream`

稳定 SSE 事件：
- `meta`
- `answer_delta`
- `done`
- `error`

稳定 payload 约束：
- `meta`：
  - `question`
  - `mode`
  - `model`
  - `citations`
- `answer_delta`：
  - `delta`
- `done`：
  - `question`
  - `answer`
  - `mode`
  - `model`
  - `citations`
- `error`：
  - `code`
  - `message`
  - `retryable`
  - `retry_after_seconds`

---

## 4. SOP Mainline

### `GET /api/v1/sops`

稳定字段：
- `total`
- `page`
- `page_size`
- `items`

每条 `items[]` 的稳定字段：
- `sop_id`
- `title`
- `department_id`
- `department_name`
- `process_name`
- `scenario_name`
- `version`
- `status`
- `preview_available`
- `downloadable_formats`
- `updated_at`

### `GET /api/v1/sops/{sop_id}`

稳定字段：
- `sop_id`
- `title`
- `tenant_id`
- `department_id`
- `department_name`
- `process_name`
- `scenario_name`
- `version`
- `status`
- `preview_resource_path`
- `preview_resource_type`
- `download_docx_available`
- `download_pdf_available`
- `tags`
- `source_document_id`
- `created_by`
- `updated_by`
- `created_at`
- `updated_at`

### `GET /api/v1/sops/{sop_id}/preview`

稳定字段：
- `sop_id`
- `title`
- `preview_type`
- `content_type`
- `text_content`
- `preview_file_url`
- `updated_at`

### `POST /api/v1/sops/generate/document`

稳定字段：
- `snapshot_id`
- `request_mode`
- `generation_mode`
- `title`
- `department_id`
- `department_name`
- `process_name`
- `scenario_name`
- `topic`
- `content`
- `model`
- `citations`

每条 `citations[]` 的稳定字段：
- `chunk_id`
- `document_id`
- `document_name`
- `snippet`
- `score`
- `source_path`
- `retrieval_strategy`
- `ocr_used`
- `parser_name`
- `page_no`

诊断字段：
- `vector_score`
- `lexical_score`
- `fused_score`
- `ocr_confidence`
- `quality_score`

### `POST /api/v1/sops/export`

稳定请求字段：
- `title`
- `content`
- `format`

稳定行为：
- 未保存草稿可直接导出
- 当前 API 主格式：
  - `docx`
  - `pdf`

说明：
- `Markdown` 草稿下载当前属于前端工作流能力，不属于 `/api/v1/sops/export` 主契约

---

## 5. System Config / Logs / Ops

### `GET /api/v1/system-config`
### `PUT /api/v1/system-config`

稳定顶层字段：
- `query_profiles`
- `model_routing`
- `reranker_routing`
- `degrade_controls`
- `retry_controls`
- `concurrency_controls`
- `prompt_budget`
- `updated_at`
- `updated_by`

稳定组内字段：
- `query_profiles.fast|accurate`：
  - `top_k_default`
  - `candidate_multiplier`
  - `lexical_top_k`
  - `rerank_top_n`
  - `timeout_budget_seconds`
- `model_routing`：
  - `fast_model`
  - `accurate_model`
  - `sop_generation_model`
- `reranker_routing`：
  - `provider`
  - `default_strategy`
  - `model`
  - `timeout_seconds`
  - `failure_cooldown_seconds`
- `degrade_controls`：
  - `rerank_fallback_enabled`
  - `accurate_to_fast_fallback_enabled`
  - `retrieval_fallback_enabled`
- `retry_controls`：
  - `llm_retry_enabled`
  - `llm_retry_max_attempts`
  - `llm_retry_backoff_ms`
- `concurrency_controls`：
  - `fast_max_inflight`
  - `accurate_max_inflight`
  - `sop_generation_max_inflight`
  - `per_user_online_max_inflight`
  - `acquire_timeout_ms`
  - `busy_retry_after_seconds`
- `prompt_budget`：
  - `max_prompt_tokens`
  - `reserved_completion_tokens`
  - `memory_prompt_tokens`

### `GET /api/v1/logs`

稳定字段：
- `items`
- `total`
- `page`
- `page_size`

每条 `items[]` 的稳定字段：
- `event_id`
- `category`
- `action`
- `outcome`
- `occurred_at`
- `actor`
- `target_id`
- `mode`
- `rerank_strategy`
- `rerank_provider`
- `duration_ms`
- `downgraded_from`

`actor` 的稳定字段：
- `tenant_id`
- `user_id`
- `username`
- `role_id`
- `department_id`

诊断字段：
- `target_type`
- `top_k`
- `candidate_top_k`
- `rerank_top_n`
- `rerank_model`
- `timeout_flag`
- `details`

### `GET /api/v1/ops/summary`

稳定顶层字段：
- `checked_at`
- `health`
- `queue`
- `runtime_gate`
- `recent_window`
- `rerank_usage`
- `rerank_decision`
- `categories`
- `recent_failures`
- `recent_degraded`
- `config`

稳定嵌套字段：
- `queue`：
  - `available`
  - `ingest_queue`
  - `backlog`
  - `error`
- `runtime_gate`：
  - `acquire_timeout_ms`
  - `busy_retry_after_seconds`
  - `per_user_online_max_inflight`
  - `active_users`
  - `max_user_inflight`
  - `channels`
- `runtime_gate.channels[]`：
  - `channel`
  - `inflight`
  - `limit`
  - `available_slots`
- `recent_window`：
  - `sample_size`
  - `failed_count`
  - `timeout_count`
  - `downgraded_count`
  - `duration_count`
  - `duration_p50_ms`
  - `duration_p95_ms`
  - `duration_p99_ms`
- `rerank_usage`：
  - `sample_size`
  - `provider_count`
  - `heuristic_count`
  - `skipped_count`
  - `document_preview_count`
  - `fallback_profile_count`
  - `unknown_count`
  - `other_count`
- `rerank_decision`：
  - `decision`
  - `message`
  - `min_provider_samples`
  - `provider_sample_count`
  - `heuristic_sample_count`
  - `should_promote_to_provider`
  - `should_rollback_to_heuristic`
- `categories[]`：
  - `category`
  - `total`
  - `failed_count`
  - `timeout_count`
  - `downgraded_count`

诊断字段：
- `rerank_usage.last_provider_at`
- `rerank_usage.last_heuristic_at`
- `categories[].last_event_at`
- `categories[].last_failed_at`
- `stuck_ingest_jobs`
- `recent_traces`
- `recent_snapshots`

---

## 6. Error Contract

主业务接口统一遵循：

- 保留兼容字段：`detail`
- 同时补结构化字段：
  - `error.code`
  - `error.message`
  - `error.status_code`

请求校验错误（422）继续保留：
- FastAPI 风格的 `detail[]`

---

## 7. Diagnostic Surfaces

下面这些当前仍视为诊断面，可用但不作为 V1 主契约承诺：

- `POST /api/v1/retrieval/rerank-compare`
- `GET /api/v1/traces`
- `GET /api/v1/request-snapshots`
- replay endpoints
- OCR artifact JSON 结构
- `ops.rerank_canary`

如果这些路径未来要升级成稳定契约，先改 `V1_PLAN.md` 和 `RAG架构.md`，再补主契约回归。
