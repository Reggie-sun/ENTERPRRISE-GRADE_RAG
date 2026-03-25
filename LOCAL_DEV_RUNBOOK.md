# Local Dev Runbook / 本地开发运行手册

本手册覆盖当前已验证的 `v0.1.2` 开发基线：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8020`
- Qdrant：服务器 `http://192.168.10.200:6333`
- Redis：服务器 `redis://192.168.10.200:6379`
- Embedding：服务器 `http://192.168.10.200:8002/v1`
- LLM：服务器 `http://192.168.10.200:8000/v1`

## 1. 配置文件

后端使用项目根目录 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env)。
前端开发代理使用 [`frontend/.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/.env)。

前端必须保证：

```env
VITE_API_TARGET=http://127.0.0.1:8020
```

## 2. 启动顺序

### 2.1 启动后端 API

```bash
conda run -n rag_backend uvicorn backend.app.main:app --host 0.0.0.0 --port 8020
```

或使用 Docker Compose：

```bash
docker compose up -d
```

### 2.2 启动 Celery worker

```bash
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

如果你已经执行了 `docker compose up -d`，这一步会由 Compose 一起拉起。

### 2.3 启动前端

```bash
cd frontend
npm run dev
```

## 3. 最小验证

### 3.1 后端健康检查

```bash
curl http://127.0.0.1:8020/api/v1/health
```

至少确认：

- `vector_store.url = http://192.168.10.200:6333`
- `embedding.base_url = http://192.168.10.200:8002/v1`
- `queue.broker_url = redis://192.168.10.200:6379/0`
- `llm.base_url` 指向当前可用的 vLLM 服务器

如果你走 Compose 模式，当前默认只会启动本地 `api + worker` 两个容器，Qdrant / Redis / PostgreSQL / LLM / Embedding 继续使用 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env) 里配置的服务器地址。

### 3.2 基础设施可用性检查

```bash
curl http://192.168.10.200:6333/collections
redis-cli -u redis://192.168.10.200:6379/0 ping
curl http://192.168.10.200:8002/health
curl http://192.168.10.200:8000/v1/models
```

如果你换了服务器地址，检查命令和 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env) 里的 `RAG_QDRANT_URL`、`RAG_CELERY_BROKER_URL`、`RAG_CELERY_RESULT_BACKEND`、`RAG_LLM_BASE_URL`、`RAG_EMBEDDING_BASE_URL` 要一起改。

### 3.3 前端联调检查

打开：

- `http://127.0.0.1:3000`
- `http://127.0.0.1:8020/demo` 仅作为后端内置 smoke page，不是主前端

期望流程：

1. 健康检查返回成功
2. 上传一个 `.txt` 或 `.pdf`
3. 页面显示当前文档名称和 `doc_id`
4. ingest job 状态推进到 `completed`
5. 检索和问答只返回当前文档的结果

说明：

- `3000` 的 React 页面是当前主前端
- `8020/demo` 只用于后端单页联调和快速 smoke test

### 3.4 一键 smoke test（推荐）

仓库已提供可执行脚本：

```bash
bash scripts/smoke_test.sh
```

脚本覆盖链路：

- `GET /api/v1/health`
- `POST /api/v1/documents`（异步创建 job）
- `GET /api/v1/ingest/jobs/{job_id}`（轮询到 `completed`）
- `POST /api/v1/retrieval/search`（`document_id` 过滤）
- `POST /api/v1/chat/ask`（`document_id` 过滤 + 引用检查）

可选参数（按需覆盖）：

```bash
API_BASE_URL=http://127.0.0.1:8020 \
TENANT_ID=wl \
TOP_K=3 \
POLL_TIMEOUT_SECONDS=180 \
bash scripts/smoke_test.sh
```

## 4. 常见故障

### 4.1 前端上传时报 `500`

优先检查前端代理目标：

```bash
cat frontend/.env
```

必须看到：

```env
VITE_API_TARGET=http://127.0.0.1:8020
```

修改后要重启前端：

```bash
cd frontend
npm run dev
```

### 4.2 文档一直停在 `queued`

说明 worker 没消费。

先检查：

```bash
ps -ef | rg "celery -A backend.app.worker.celery_app:celery_app worker"
```

没有进程就重新启动 worker。

### 4.3 问答返回 `retrieval_fallback`

说明检索成功，但 LLM 不可用。

先检查：

```bash
curl http://192.168.10.200:8000/v1/models
```

如果不通，优先处理服务器 vLLM。

### 4.4 上传后检索不到内容

先看 job 是否真的完成：

```bash
curl http://127.0.0.1:8020/api/v1/ingest/jobs/<job_id>
```

如果还没到 `completed`，不要先怀疑前端。

### 4.5 页面打不开 / 前端空白

按这个顺序排查：

1. 前端进程是否在跑：`cd frontend && npm run dev`
2. 前端地址是否正确：`http://127.0.0.1:3000`
3. 前端代理是否正确：`cat frontend/.env`，确认 `VITE_API_TARGET=http://127.0.0.1:8020`
4. 后端是否可达：`curl http://127.0.0.1:8020/api/v1/health`

### 4.6 worker 未启动（任务卡 queued）

按这个顺序排查：

1. `ps -ef | rg "celery -A backend.app.worker.celery_app:celery_app worker"`
2. `curl http://127.0.0.1:8020/api/v1/ingest/jobs/<job_id>`
3. `redis-cli -u redis://192.168.10.200:6379/0 ping`

### 4.7 向量入库失败 / 检索为空

按这个顺序排查：

1. 任务状态是否 `completed`：`GET /api/v1/ingest/jobs/<job_id>`
2. Embedding 服务是否可达：`curl http://192.168.10.200:8002/health`
3. Qdrant 是否可达：`curl http://192.168.10.200:6333/collections`
4. 直接跑一次仓库脚本：`bash scripts/smoke_test.sh`

## 5. 相关文档

- [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md)
- [backend/LOCAL_MODEL_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/LOCAL_MODEL_RUNBOOK.md)
- [backend/POSTGRES_METADATA_MIGRATION.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/POSTGRES_METADATA_MIGRATION.md)
- [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)
