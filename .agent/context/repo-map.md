# Repo Map

这份 repo map 只描述当前 `Enterprise-grade_RAG` 仓库里对 coding agent 最重要的真实结构，目的是让规划、实现、review 都先建立在现有代码和文档之上，而不是照搬上游 workflow。

## 1. 开工前默认先读

- `MAIN_CONTRACT_MATRIX.md`
  - 稳定主契约硬约束。尤其关注：
    - `POST /api/v1/retrieval/search`
    - `POST /api/v1/chat/ask`
    - `GET /api/v1/system-config`
    - `PUT /api/v1/system-config`
- `RETRIEVAL_OPTIMIZATION_PLAN.md`
  - retrieval 优化顺序与阶段边界。
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
  - 当前 retrieval 优化现实状态、guardrails、缺口。
- `eval/README.md`
  - retrieval 样本、评分规则、当前 blocker 说明。
- `.agent/rules/coding-rules.md`
  - 本地最小 agent 规则。

如果任务与某条链路直接相关，再补读该链路的实现与测试文件，不要跳过代码直接下结论。

## 2. 运行入口与骨架

- `backend/app/main.py`
  - FastAPI 应用入口，注册 CORS、全局异常处理、根路由和 API 路由。
- `backend/app/api/v1/router.py`
  - V1 路由聚合层，挂载 `health / auth / documents / ingest / retrieval / chat / sops / logs / traces / request_snapshots / ops / system_config`。
- `backend/app/worker/celery_app.py`
  - ingest worker 入口。
- `frontend/src/main.tsx`
  - 前端挂载入口。
- `frontend/src/App.tsx`
  - 前端顶层路由，区分 `portal` 和 `workspace` 两条主路径。
- `Makefile`
  - 仓库统一的 dev / test / smoke / eval 入口。

## 3. 后端目录图

- `backend/app/api/v1/endpoints/`
  - HTTP 入口层。改 endpoint 时通常要同时核对 `schemas/`、`services/`、测试。
- `backend/app/schemas/`
  - Pydantic 请求/响应模型与错误包。
  - 高风险文件：
    - `retrieval.py`
    - `chat.py`
    - `system_config.py`
    - `document.py`
    - `errors.py`
- `backend/app/services/`
  - 主要业务逻辑层，是多数业务改动的真实落点。
  - 核心文件：
    - `retrieval_service.py`
    - `chat_service.py`
    - `chat_citation_pipeline.py`
    - `ingestion_service.py`
    - `document_service.py`
    - `system_config_service.py`
    - `retrieval_query_router.py`
    - `query_profile_service.py`
    - `retrieval_scope_policy.py`
    - `sop_service.py`
    - `sop_generation_service.py`
    - `sop_version_service.py`
    - `ops_service.py`
    - `health_service.py`
- `backend/app/rag/`
  - RAG 相关底层能力。
  - `chunkers/`
    - `text_chunker.py`
    - `structured_chunker.py`
  - `parsers/`
    - `document_parser.py`
  - `retrievers/`
    - `lexical_retriever.py`
  - `vectorstores/`
    - `qdrant_store.py`
  - `rerankers/`
    - `client.py`
  - `embeddings/`
    - `client.py`
  - `generators/`
    - `client.py`
  - `ocr/`
    - `client.py`
- `backend/app/db/`
  - PG metadata / asset / trace / snapshot / event log / system config repository 层。
- `backend/app/core/`
  - 配置与 provider wiring。
  - 高相关文件：
    - `config.py`
    - `_auth.py`
    - `_retrieval.py`
    - `_model.py`
    - `_ocr.py`
    - `_storage.py`
- `backend/app/bootstrap/`
  - demo identity / SOP bootstrap 数据。
- `backend/app/tools/`
  - 一次性 backfill / import 工具逻辑。

## 4. 前端目录图

- `frontend/src/api/`
  - 前端 API client 和类型定义。
  - 改后端稳定响应时，这里通常必须同步。
- `frontend/src/auth/`
  - 登录态、权限与角色体验封装。
- `frontend/src/app/`
  - workspace 级 shell、共享上下文、展示格式化辅助。
  - 关键文件：
    - `AppShell.tsx`
    - `UploadWorkspaceContext.tsx`
- `frontend/src/pages/`
  - workspace 页面：
    - `OverviewPage.tsx`
    - `DocumentsPage.tsx`
    - `RetrievalPage.tsx`
    - `ChatPage.tsx`
    - `LogsPage.tsx`
    - `OpsPage.tsx`
    - `SopPage.tsx`
    - `AdminPage.tsx`
- `frontend/src/panels/`
  - 文档、检索、问答、健康等功能面板。
- `frontend/src/portal/`
  - 门户视角页面与壳层。
- `frontend/src/components/`
  - 通用 UI 组件。

## 5. 核心业务链路

### 5.1 Retrieval

- 入口：
  - `backend/app/api/v1/endpoints/retrieval.py`
- 契约：
  - `backend/app/schemas/retrieval.py`
- 主逻辑：
  - `backend/app/services/retrieval_service.py`
- 关联模块：
  - `backend/app/services/retrieval_query_router.py`
  - `backend/app/services/query_profile_service.py`
  - `backend/app/services/retrieval_scope_policy.py`
  - `backend/app/rag/retrievers/lexical_retriever.py`
  - `backend/app/rag/vectorstores/qdrant_store.py`
  - `backend/app/rag/rerankers/client.py`

关键事实：

- `retrieval / chat / SOP` 预期继续共用同一套 retrieval 判定逻辑。
- retrieval 优化不能绕开 `RETRIEVAL_OPTIMIZATION_PLAN.md` 的顺序。
- 与 supplemental 阈值、router、hybrid、rerank 相关的改动，默认要补评估依据或明确缺口。

### 5.2 Chat

- 入口：
  - `backend/app/api/v1/endpoints/chat.py`
- 契约：
  - `backend/app/schemas/chat.py`
- 主逻辑：
  - `backend/app/services/chat_service.py`
- 关联模块：
  - `backend/app/services/chat_citation_pipeline.py`
  - `backend/app/services/chat_memory_service.py`
  - `backend/app/rag/generators/client.py`

### 5.3 Documents / Ingestion

- 入口：
  - `backend/app/api/v1/endpoints/documents.py`
  - `backend/app/api/v1/endpoints/ingest.py`
- 契约：
  - `backend/app/schemas/document.py`
- 主逻辑：
  - `backend/app/services/document_service.py`
  - `backend/app/services/ingestion_service.py`
- 关联模块：
  - `backend/app/rag/parsers/document_parser.py`
  - `backend/app/rag/chunkers/text_chunker.py`
  - `backend/app/rag/chunkers/structured_chunker.py`
  - `backend/app/rag/embeddings/client.py`
  - `backend/app/rag/vectorstores/qdrant_store.py`

### 5.4 SOP

- 入口：
  - `backend/app/api/v1/endpoints/sops.py`
- 契约：
  - `backend/app/schemas/sop.py`
  - `backend/app/schemas/sop_generation.py`
  - `backend/app/schemas/sop_version.py`
- 主逻辑：
  - `backend/app/services/sop_service.py`
  - `backend/app/services/sop_generation_service.py`
  - `backend/app/services/sop_version_service.py`

### 5.5 System Config / Ops / Diagnostics

- 配置：
  - `backend/app/api/v1/endpoints/system_config.py`
  - `backend/app/services/system_config_service.py`
  - `backend/app/db/system_config_repository.py`
- 运行态与排障：
  - `backend/app/api/v1/endpoints/ops.py`
  - `backend/app/api/v1/endpoints/logs.py`
  - `backend/app/api/v1/endpoints/traces.py`
  - `backend/app/api/v1/endpoints/request_snapshots.py`
  - `backend/app/services/ops_service.py`
  - `backend/app/services/event_log_service.py`
  - `backend/app/services/request_trace_service.py`
  - `backend/app/services/request_snapshot_service.py`

## 6. 测试、评估与脚本

- `backend/tests/`
  - 后端主测试目录。
  - 高相关测试：
    - `test_main_contract_endpoints.py`
    - `test_main_contract_errors.py`
    - `test_retrieval_chat.py`
    - `test_retrieval_query_router.py`
    - `test_retrieval_diagnostics.py`
    - `test_document_ingestion.py`
    - `test_system_config_endpoints.py`
    - `test_system_config_service.py`
    - `test_ops_endpoints.py`
    - `test_auth_endpoints.py`
- `eval/`
  - 当前主要 retrieval eval 目录。
  - 核心文件：
    - `README.md`
    - `retrieval_samples.yaml`
    - `baseline_config_snapshot.yaml`
    - `threshold_matrix.yaml`
    - `results/`
- `backend/eval/`
  - 仓库内另一套 eval 目录，修改时要先确认是维护旧脚本还是当前主链路，不要混用结论。
- `scripts/`
  - `eval_retrieval.py`
  - `eval_hybrid_query_router.py`
  - `smoke_test.sh`
  - `smoke_test_v02.sh`
  - `rebuild_documents.py`
  - `backfill_postgres_data.py`
  - `backfill_postgres_metadata.py`
  - `backfill_pgvector_embeddings.py`
  - `import_data_qdrant_to_rag_tables.py`
  - `local_embedding_server.py`
  - `local_reranker_server.py`

## 7. 常见改动的落点

### 7.1 改 stable API 或返回字段

先看：

- `MAIN_CONTRACT_MATRIX.md`
- 对应 endpoint
- 对应 schema
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- 主契约测试

### 7.2 改 retrieval 行为

先看：

- `RETRIEVAL_OPTIMIZATION_PLAN.md`
- `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- `backend/app/services/retrieval_service.py`

### 7.3 改 chunk / ingestion

先看：

- `backend/app/services/ingestion_service.py`
- `backend/app/rag/chunkers/text_chunker.py`
- `backend/app/rag/chunkers/structured_chunker.py`
- `scripts/rebuild_documents.py`
- `OPS_CHUNK_REBUILD_RUNBOOK.md`

### 7.4 改 rerank / router

先看：

- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/rag/rerankers/client.py`
- `backend/tests/test_hybrid_query_router_samples.py`
- `backend/tests/test_reranker_client.py`
- `scripts/eval_hybrid_query_router.py`

### 7.5 改 auth / scope / 访问隔离

先看：

- `backend/app/api/v1/endpoints/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/identity_service.py`
- `backend/app/services/retrieval_scope_policy.py`
- `backend/tests/test_auth_endpoints.py`
- `backend/tests/test_authorization_filters.py`

### 7.6 改前端页面行为

先看：

- `frontend/src/App.tsx`
- 对应 page / panel
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/auth/`

## 8. 最小验证入口

- 后端针对性测试：
  - `pytest backend/tests/<target_file>.py -v`
- 前端 lint：
  - `cd frontend && npm run lint`
- 前端构建：
  - `cd frontend && npm run build`
- 文档/ingestion smoke：
  - `make test-smoke-v02`
- retrieval eval：
  - `make eval-retrieval`
- 本地运行：
  - `make dev-api`
  - `make dev-worker`
  - `make dev-frontend`

## 9. 本地 workflow 约定

- `.agent/` 是这套最小 workflow 的主目录。
- 当前仓库里虽然还有 `.claude/` 等其他目录，但本轮最小 workflow 不依赖 hooks、MCP、memory、security scanning 体系。
- 如果 `.agent` 与其他上游模板写法冲突，以：
  - `AGENTS.md`
  - `.agent/rules/coding-rules.md`
  - 本 repo 的真实代码与文档
  为准。
