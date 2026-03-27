# V1 Release / v0.1.2 Hardening Notes

## Status / 状态

The backend minimum closed loop is complete. The current working target is `v0.1.2`, focused on hardening the local development baseline and keeping the demo chain reproducible.
后端最小闭环已经完成。当前工作目标是 `v0.1.2`，重点是把本地开发基线和演示链路收口成可复现状态。

This does not mean the full enterprise feature set is complete. It means the current branch is expected to run with:
这并不代表企业级全部功能都完成了。它表示当前分支应按下面这套基线运行：

- Frontend: `127.0.0.1:3000`
- Backend API: `127.0.0.1:8020`
- Qdrant + Redis on remote server endpoints
- Embedding service on remote server endpoint
- Remote vLLM via an OpenAI-compatible endpoint

## Included In Current Baseline / 当前基线包含内容

- FastAPI API skeleton and routed endpoints / FastAPI API 骨架和路由端点
- Document upload and metadata persistence / 文档上传和元数据持久化
- Real async ingest with `Celery + Redis` / 使用 `Celery + Redis` 的真实异步入库
- Ingest job status query / 入库任务状态查询
- Manual job re-run endpoint: `POST /api/v1/ingest/jobs/{job_id}/run` / 手动重跑任务端点
- Retry-limit and `dead_letter` terminal semantics / 重试上限和 `dead_letter` 终态语义
- Document parsing for `PDF / DOCX / Markdown / TXT` / 支持 `PDF / DOCX / Markdown / TXT` 文档解析
- Chunking, embedding, vector upsert, retrieval, heuristic rerank, chat answer, citations / 切块、向量化、向量写入、检索、启发式重排、问答生成、引用返回
- React frontend panels for health, upload, retrieval, and chat / React 前端健康检查、上传、检索、问答面板
- Current-document UI state and `document_id` scoped retrieval/chat / 当前文档 UI 状态和按 `document_id` 过滤的检索/问答
- Vite proxy configurable through `VITE_API_TARGET` / 通过 `VITE_API_TARGET` 配置的前端代理
- Worker and local model runbooks / Worker 和本地模型运行手册

## Verification / 验证结果

Verified on `2026-03-20` in local development:
于 `2026-03-20` 在本地开发环境验证通过：

- Swagger MCP test passed for `POST /api/v1/documents` / 文档创建接口测试通过
- Swagger MCP test passed for `GET /api/v1/ingest/jobs/{job_id}` / 任务状态查询接口测试通过
- Swagger MCP test passed for `POST /api/v1/ingest/jobs/{job_id}/run` / 手动重跑接口测试通过
- `pytest backend/tests/test_retrieval_chat.py backend/tests/test_document_ingestion.py` passed: `28 passed` / 关键后端测试通过
- `frontend` build passed with `npm run build` / 前端构建通过

## Explicitly Out Of Scope / 明确不在当前版本范围内

The following are not part of the current patch release gate:
以下内容不属于当前补丁版本发布门槛：

- Full ACL / RBAC enforcement / 完整 ACL / RBAC 落地
- BM25 / RRF hybrid retrieval / BM25 / RRF 混合检索
- OCR for scanned PDFs and images / 扫描 PDF 与图片 OCR
- Model-based reranker service / 模型级 rerank 服务
- Office deep parsing beyond current DOCX XML extraction / 超出当前 DOCX XML 抽取范围的 Office 深度解析
- PostgreSQL true source migration / PostgreSQL 真源改造
- pgvector / pgvector
- Multi-tenant enterprise controls / 多租户企业级管控
- High-concurrency tuning / 高并发调优
- Full admin console / 完整管理后台
- Distributed scheduling / 分布式调度

## Release Interpretation / 当前版本口径

For `v0.1.2`, "rerank included" means the current branch already routes retrieval results through the existing heuristic rerank path. It does not mean a separate model-based reranker service is online.
对 `v0.1.2` 来说，“已包含 rerank”指的是当前分支已经接上现有的启发式重排路径，并不代表独立的模型级 rerank 服务已经上线。

For `v0.1.2`, "document parsing included" means native text extraction for supported text-based files. It does not mean scanned PDFs, screenshots, or image assets are already handled by an OCR pipeline.
对 `v0.1.2` 来说，“已包含文档解析”指的是对支持的文本型文件做原生文本抽取，并不代表扫描 PDF、截图或图片资料已经进入 OCR 主链路。

## Roadmap Alignment / 与计划对齐

The current release note should be read together with [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md):
当前发布说明应结合 [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md) 一起理解：

- `v0.1.2`: harden the current async ingest, retrieval, and chat baseline / 稳定当前异步入库、检索、问答基线
- `v0.4.0`: deliver SOP browsing, preview, and download as an independent asset flow / 先把 SOP 浏览、预览、下载作为独立资产流交付
- `v0.4.5`: add OCR for scanned/image documents and introduce model-based rerank on the online retrieval path / 为扫描件与图片资料补 OCR，并把模型级 rerank 接到在线检索链路
- `v0.5.0`: build SOP direct-generation on top of the OCR + rerank baseline rather than introducing a second document-understanding stack / 在 OCR + rerank 底座上做 SOP 直生，而不是再造第二套文档理解链路

## Local Baseline Docs / 本地基线文档

- [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md)
- [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md)
- [backend/LOCAL_MODEL_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/LOCAL_MODEL_RUNBOOK.md)
- [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)

## Tagging Rule / 打标签规则

Do not tag a release from a dirty worktree.
不要从脏工作区打版本标签。

Recommended release sequence:
推荐的发布流程：

1. Review local modifications / 检查本地修改
2. Confirm the local runbook still matches the actual ports and services / 确认运行手册与实际端口和服务一致
3. Commit the current hardening state / 提交当前稳定化状态
4. Create the next patch tag only after smoke tests pass / smoke test 通过后再打补丁版本标签
