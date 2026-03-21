# Local Dev Runbook / 本地开发运行手册

本手册覆盖当前已验证的 `v0.1.2` 开发基线：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8020`
- Qdrant：`http://127.0.0.1:6333`
- Redis：`redis://127.0.0.1:6379`
- Embedding：`http://127.0.0.1:8002/v1`
- LLM：服务器 vLLM，当前工作区示例为 `http://192.168.10.200:8000/v1`

## 1. 配置文件

后端使用项目根目录 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env)。
前端开发代理使用 [`frontend/.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/.env)。

前端必须保证：

```env
VITE_API_TARGET=http://127.0.0.1:8020
```

## 2. 启动顺序

### 2.1 启动基础依赖

```bash
docker compose up -d qdrant redis
```

### 2.2 启动 embedding 服务

```bash
conda run -n rag-embed python scripts/local_embedding_server.py \
  --model-path /home/reggie/bge-m3 \
  --host 127.0.0.1 \
  --port 8002
```

### 2.3 启动后端 API

```bash
conda run -n rag_backend uvicorn backend.app.main:app --host 0.0.0.0 --port 8020
```

### 2.4 启动 Celery worker

```bash
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

### 2.5 启动前端

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

- `vector_store.url = http://localhost:6333`
- `embedding.base_url = http://127.0.0.1:8002/v1`
- `llm.base_url` 指向当前可用的 vLLM 服务器

### 3.2 vLLM 可用性检查

```bash
curl http://192.168.10.200:8000/v1/models
```

如果你换了服务器地址，检查命令和 [`.env`](/home/reggie/vscode_folder/Enterprise-grade_RAG/.env) 里的 `RAG_LLM_BASE_URL` 要一起改。

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

## 5. 相关文档

- [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md)
- [backend/LOCAL_MODEL_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/LOCAL_MODEL_RUNBOOK.md)
- [backend/POSTGRES_METADATA_MIGRATION.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/POSTGRES_METADATA_MIGRATION.md)
- [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)
