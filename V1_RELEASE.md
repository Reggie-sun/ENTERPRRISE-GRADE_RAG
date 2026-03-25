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
- Document parsing for `PDF / Markdown / TXT` / 支持 `PDF / Markdown / TXT` 文档解析
- Chunking, embedding, vector upsert, retrieval, rerank, chat answer, citations / 切块、向量化、向量写入、检索、重排、问答生成、引用返回
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
- OCR and Office deep parsing / OCR 和 Office 深度解析
- PostgreSQL true source migration / PostgreSQL 真源改造
- pgvector / pgvector
- Multi-tenant enterprise controls / 多租户企业级管控
- High-concurrency tuning / 高并发调优
- Full admin console / 完整管理后台
- Distributed scheduling / 分布式调度

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
