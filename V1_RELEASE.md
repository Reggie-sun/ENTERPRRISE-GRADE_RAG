# V1 Release / Current Branch Status

## Status / 状态

This file describes the **current runnable state of the branch** as of `2026-03-28`.
这份说明描述的是 **`2026-03-28` 当前分支的可运行状态**，不是最终 GA 发布声明。

The branch is no longer at the old `v0.1.2` baseline. The codebase already includes:
当前分支已经不再停留在旧的 `v0.1.2` 基线，代码现实已包含：

- Employee login and department-scoped access
- Document management, preview, rebuild, and batch upload
- OCR for image files and scanned/image-based PDFs
- `DOCX` embedded image OCR in the async ingest pipeline
- Employee-side SOP direct generation and draft download
- Logs, config, ops, request trace, request snapshot, and replay
- Online concurrency gates and per-user concurrency protection

## Current Runnable Baseline / 当前可运行基线

The current branch is expected to run with:
当前分支应按下面这套基线运行：

- Frontend: `127.0.0.1:3000`
- Backend API: `127.0.0.1:8020`
- Redis + Celery worker for async ingest
- Qdrant for vector retrieval
- Remote or local embedding service
- Remote `vLLM` through an OpenAI-compatible endpoint
- PaddleOCR available in the backend image when OCR is enabled

## Delivered Capabilities / 当前已交付能力

### Document Understanding / 文档理解

- Async ingest:
  `upload -> job -> parse/native extract -> OCR when needed -> chunk -> embedding -> index`
- Native parsing for `PDF / DOCX / Markdown / TXT`
- OCR for:
  image files, scanned PDFs, image-based PDFs, and embedded images inside `DOCX`
- OCR artifacts persisted under `data/ocr_artifacts/`
- OCR metadata propagated into chunk metadata, retrieval results, citations, and request snapshots
- Hybrid retrieval main path:
  vector recall + lexical recall + weighted fusion + fallback

### Employee-Side SOP Flow / 员工端 SOP 主流程

- Employee portal entry:
  `/portal/sop`
- Main path:
  upload document -> generate SOP -> preview -> download
- Supported draft exports:
  `Markdown / DOCX / PDF`
- Unsaved drafts can be exported directly
- Source citations and traceability are returned with SOP generation
- `fast / accurate` profile wiring is connected

### Operations and Governance / 运行治理

- Event logs for `chat / document / sop_generation`
- Log query page:
  `/workspace/logs`
- System config page:
  `/workspace/admin`
- Ops page:
  `/workspace/ops`
- Request trace
- Request snapshot and replay
- Channel concurrency gates
- Per-user online concurrency protection
- Busy responses with `Retry-After`

## Not Final Yet / 仍不是最终交付的部分

The following are still incomplete, experimental, or not yet hardened enough to be presented as final V1 deliverables:
以下能力仍属于未完成、实验态或尚未收口，不应被表述为最终 V1 已完成交付：

- Model rerank is not yet the default production route
- Query Rewrite is not yet enabled in the main path
- Lightweight memory / multi-turn context is not yet in the main chat and SOP path
- Tokenizer-aware context budgeting and evidence trimming are not yet complete
- Enterprise WeCom messaging and contact sync are not yet connected
- Metrics/exporter is not yet at Prometheus / OpenTelemetry level
- Several governance objects still use file-based truth sources instead of database truth
- OCR still has remaining gaps:
  local-image OCR inside normal PDFs, OCR quality threshold governance, stronger frontend explainability

## High-Risk Gaps / 当前高风险缺口

The main high-risk items for the next phase are:
当前下一阶段的高风险缺口主要是：

- Production validation and default routing for model rerank
- Lightweight memory and multi-turn continuity
- Query Rewrite
- Tokenizer-aware prompt/context packing
- WeCom access and contact synchronization
- Gradual migration of logs/config/session/external identity mappings to database truth

## Experimental and File-Source Caveats / 实验态与文件真源边界

These areas currently work, but should still be treated as intermediate implementations:
以下能力当前可用，但仍应视为过渡实现：

- Some governance objects still persist to local files under `data/`
- System config is file-backed before database migration
- Request traces and request snapshots are file-backed
- Parts of SOP persistence still rely on repository abstractions over filesystem data

In other words:
换句话说：

- runnable: yes
- enterprise-finalized: not yet

## Recommended Next Step / 建议的下一步

Based on the current code, the highest-value next implementation is:
基于当前代码现实，下一步最值当的实施顺序是：

1. Finish rerank production validation and default-route hardening
2. Add lightweight memory / multi-turn context
3. Add Query Rewrite and tokenizer-aware context budgeting
4. Connect WeCom messaging and contact sync
5. Move governance truth sources from files to database incrementally

## Read Together With / 建议配套阅读

- [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)
- [OPS_SMOKE_TEST.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_SMOKE_TEST.md)
- [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md)
- [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md)
- [backend/LOCAL_MODEL_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/LOCAL_MODEL_RUNBOOK.md)

## Release Interpretation / 版本口径说明

Do not read this file as “V1 is fully complete”.
不要把这份说明理解成“V1 已完全完成”。

Read it as:
正确理解应是：

- the branch already has a substantial runnable V1 slice
- the plan has been rebaselined against current code
- the remaining work is now concentrated in quality hardening and governance completion
