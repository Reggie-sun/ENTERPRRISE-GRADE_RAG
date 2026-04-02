# Local Dev Runbook / 本地开发运行手册

本手册覆盖两种运行方式：

- 方式 A（默认，开发推荐）：前端 + API + worker 全在本机
- 方式 B（可选，试点/演示）：前端本机，API + worker 在服务器

当前基础设施默认仍在服务器：

- Qdrant：`http://192.168.10.200:6333`
- Redis：`redis://192.168.10.200:6379`
- Embedding：`http://192.168.10.200:8002/v1`
- LLM：`http://192.168.10.200:8000/v1`

## 1. 配置文件

后端使用项目根目录 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env)。
前端开发代理使用 [`frontend/.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/.env)。

方式 A（本机 API）时前端必须保证：

```env
VITE_API_TARGET=http://127.0.0.1:8020
```

方式 B（服务器 API）时前端改为：

```env
VITE_API_TARGET=http://192.168.10.200:8020
```

## 2. 启动顺序

### 2.1 方式 A（默认）：本机启动 API + worker + 前端

启动 API：

```bash
conda run -n rag_backend uvicorn backend.app.main:app --host 0.0.0.0 --port 8020
```

启动 worker：

```bash
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

或本机 Compose 一次拉起 API + worker：

```bash
docker compose up -d
```

启动前端：

```bash
cd frontend
npm run dev
```

### 2.2 方式 B（可选）：服务器启动 API + worker，本机只跑前端

在服务器仓库目录执行：

```bash
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml ps
```

本机前端改 `frontend/.env` 为服务器 API 并启动：

```env
VITE_API_TARGET=http://192.168.10.200:8020
```

```bash
cd frontend
npm run dev
```

## 3. 最小验证

主业务接口默认要求 `Bearer` 认证，只有 `GET /api/v1/health` 和 `POST /api/v1/auth/login` 属于公开入口。

本地联调可先拿一个 demo token：

```bash
curl -X POST http://127.0.0.1:8020/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"sys.admin.demo","password":"sys-admin-demo-pass"}'
```

返回里的 `access_token` 可直接拿去调用 `documents / ingest / retrieval / chat / sops / logs / ops / system-config` 这些主业务接口。

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
- 进入 `3000` 主前端后，先登录再做上传 / 检索 / 问答；本地默认可用 demo 账号是 `sys.admin.demo / sys-admin-demo-pass`

### 3.4 一键 smoke test（v0.1.2 主链路）

仓库已提供可执行脚本：

```bash
bash scripts/smoke_test.sh
```

脚本覆盖链路：

- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `POST /api/v1/documents`（异步创建 job）
- `GET /api/v1/ingest/jobs/{job_id}`（轮询到 `completed`）
- `POST /api/v1/retrieval/search`（`document_id` 过滤）
- `POST /api/v1/chat/ask`（`document_id` 过滤 + 引用检查）

可选参数（按需覆盖）：

```bash
API_BASE_URL=http://127.0.0.1:8020 \
TENANT_ID=wl \
TOP_K=3 \
AUTH_USERNAME=sys.admin.demo \
AUTH_PASSWORD=sys-admin-demo-pass \
POLL_TIMEOUT_SECONDS=180 \
bash scripts/smoke_test.sh
```

说明：

- 脚本会先调用 `POST /api/v1/auth/login` 再访问受保护接口
- 默认使用本地 bootstrap demo 账号；如果你在当前环境禁用了这组账号，直接覆盖 `AUTH_USERNAME / AUTH_PASSWORD` 即可

### 3.5 一键 smoke test（v0.2 文档管理）

仓库已提供 `v0.2` 文档管理回归脚本：

```bash
bash scripts/smoke_test_v02.sh
```

脚本覆盖链路：

- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `POST /api/v1/documents/batch`（批量上传）
- `GET /api/v1/ingest/jobs/{job_id}`（轮询两个 job 到 `completed`）
- `GET /api/v1/documents`（关键字筛选）
- `GET /api/v1/documents/{doc_id}/preview`（在线预览）
- `POST /api/v1/documents/{doc_id}/rebuild`（重建向量并轮询完成）
- `DELETE /api/v1/documents/{doc_id}` + `GET /api/v1/documents/{doc_id}`（删除状态校验）

可选参数（按需覆盖）：

```bash
API_BASE_URL=http://127.0.0.1:8020 \
TENANT_ID=wl \
AUTH_USERNAME=sys.admin.demo \
AUTH_PASSWORD=sys-admin-demo-pass \
POLL_TIMEOUT_SECONDS=240 \
bash scripts/smoke_test_v02.sh
```

说明：

- 脚本会先登录，再跑文档列表 / 预览 / 重建 / 删除这些受保护接口
- 默认 demo 账号可覆盖为你当前环境实际可用的账号密码

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

### 4.4 接口直接返回 `401`

先确认是不是拿了 token 但没带上：

```bash
curl http://127.0.0.1:8020/api/v1/documents
```

如果返回 `401`，这是预期行为，因为主业务接口默认需要 `Authorization: Bearer <token>`。

先重新登录：

```bash
curl -X POST http://127.0.0.1:8020/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"sys.admin.demo","password":"sys-admin-demo-pass"}'
```

然后带上返回的 `access_token` 再访问业务接口。

### 4.5 上传后检索不到内容

先看 job 是否真的完成：

```bash
curl -H "Authorization: Bearer <token>" \
  http://127.0.0.1:8020/api/v1/ingest/jobs/<job_id>
```

如果还没到 `completed`，不要先怀疑前端。

### 4.6 页面打不开 / 前端空白

按这个顺序排查：

1. 前端进程是否在跑：`cd frontend && npm run dev`
2. 前端地址是否正确：`http://127.0.0.1:3000`
3. 前端代理是否正确：`cat frontend/.env`，确认 `VITE_API_TARGET=http://127.0.0.1:8020`
4. 后端是否可达：`curl http://127.0.0.1:8020/api/v1/health`

### 4.7 worker 未启动（任务卡 queued）

按这个顺序排查：

1. `ps -ef | rg "celery -A backend.app.worker.celery_app:celery_app worker"`
2. `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8020/api/v1/ingest/jobs/<job_id>`
3. `redis-cli -u redis://192.168.10.200:6379/0 ping`

### 4.8 向量入库失败 / 检索为空

按这个顺序排查：

1. 任务状态是否 `completed`：`GET /api/v1/ingest/jobs/<job_id>`
2. Embedding 服务是否可达：`curl http://192.168.10.200:8002/health`
3. Qdrant 是否可达：`curl http://192.168.10.200:6333/collections`
4. 直接跑一次仓库脚本：`bash scripts/smoke_test.sh`
5. 如果是文档列表/预览/删除/重建向量问题，再跑：`bash scripts/smoke_test_v02.sh`

## 5. 相关文档

- [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md)
- [backend/LOCAL_MODEL_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/LOCAL_MODEL_RUNBOOK.md)
- [backend/POSTGRES_METADATA_MIGRATION.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/POSTGRES_METADATA_MIGRATION.md)
- [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)
