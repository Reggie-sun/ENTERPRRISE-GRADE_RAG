# Ingest 状态机与错误码（V1）

本文件冻结 V1 的 ingest 任务状态机和错误码语义，避免实现与文档漂移。

## 1. 任务状态定义

- `queued`：任务已创建并入队，等待 worker 消费。
- `parsing` / `ocr_processing` / `chunking` / `embedding` / `indexing`：处理中状态。
- `completed`：任务成功完成，文档状态应为 `active`。
- `failed`：本次执行失败，但还未达到 `ingest_failure_retry_limit`。
- `dead_letter`：失败次数达到上限，停止自动重试，仅允许人工重投递。

## 2. 状态流转（V1）

正常链路：

`queued -> parsing -> chunking -> embedding -> indexing -> completed`

失败链路：

`queued -> parsing/... -> failed`

当 `retry_count >= ingest_failure_retry_limit` 时：

`failed -> dead_letter`

人工重投递：

`failed|dead_letter|queued -> /api/v1/ingest/jobs/{job_id}/run -> queued`

## 3. `failed` 与 `dead_letter` 的边界

- `failed`：仍处于自动重试窗口内。
  - 判定：`status == failed` 且 `retry_count < ingest_failure_retry_limit`
  - 接口字段：`auto_retry_eligible=true`
- `dead_letter`：已超出自动重试窗口。
  - 判定：`retry_count >= ingest_failure_retry_limit`
  - 接口字段：`auto_retry_eligible=false`，`manual_retry_allowed=true`

## 4. 错误码冻结（V1）

只允许以下错误码：

- `INGEST_DISPATCH_ERROR`
- `INGEST_DISPATCH_ERROR_DEAD_LETTER`
- `INGEST_VALIDATION_ERROR`
- `INGEST_VALIDATION_ERROR_DEAD_LETTER`
- `INGEST_RUNTIME_ERROR`
- `INGEST_RUNTIME_ERROR_DEAD_LETTER`

规则：

- 基础错误码表示“失败但未进死信”。
- 进入 `dead_letter` 时统一追加后缀 `_DEAD_LETTER`。

## 5. 文档状态联动

- 任务 `completed` 时：文档状态置为 `active`。
- 任务 `failed` / `dead_letter` 时：文档状态置为 `failed`。
- 管理端重投递成功入队后：文档状态回到 `queued`。

## 6. 管理端可用判定

- `manual_retry_allowed`：`status` 不在处理中，且不为 `completed`。
- `auto_retry_eligible`：仅 `failed` 且未达到失败上限时为 `true`。
