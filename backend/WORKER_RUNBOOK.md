# Worker 运行手册（V1）

本手册只覆盖 V1 必需范围：`Celery ingest worker` 的启动命令、健康检查、故障恢复。

## 1. 适用范围

- 异步入库链路：`POST /api/v1/documents` -> Celery -> `GET /api/v1/ingest/jobs/{job_id}`
- 任务队列：`ingest`
- 手动重投递入口：`POST /api/v1/ingest/jobs/{job_id}/run`
- 状态机/错误码契约：见 `backend/INGEST_STATE_MACHINE.md`

## 2. 前置条件

- 已准备 `.env`（至少包含以下变量）
  - `RAG_CELERY_BROKER_URL`
  - `RAG_CELERY_RESULT_BACKEND`
  - `RAG_CELERY_INGEST_QUEUE`
  - `RAG_QDRANT_URL`
- Redis 与 Qdrant 可访问
- 本地模式使用 `conda` 环境 `rag_backend`

## 3. 启动命令

### 3.1 本地开发（推荐先这样）

先启动依赖：

```bash
docker compose up -d qdrant redis
```

启动 API：

```bash
conda run -n rag_backend uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

启动 worker：

```bash
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

### 3.2 Docker Compose 一次拉起

```bash
docker compose up -d api worker qdrant redis
```

查看日志：

```bash
docker compose logs -f worker
```

## 4. 健康检查

### 4.1 API 健康检查

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

重点确认：

- `queue.provider = celery`
- `queue.broker_url` 与当前运行环境一致
- `vector_store.url` 可达

### 4.2 Worker 存活检查

本地模式：

```bash
ps -ef | rg "celery -A backend.app.worker.celery_app:celery_app worker"
```

Compose 模式：

```bash
docker compose ps worker
```

### 4.3 端到端队列检查（最重要）

1. 上传一个小 txt/pdf 到 `POST /api/v1/documents`
2. 拿到 `job_id`
3. 轮询 `GET /api/v1/ingest/jobs/{job_id}`

期望状态流转：

- 正常：`queued -> parsing/chunking/embedding/indexing -> completed`
- 异常：`queued -> failed`（可自动重试窗口）或 `dead_letter`（达到上限）

## 5. 故障恢复

### 5.1 症状：任务一直停在 `queued`

排查顺序：

1. worker 进程是否存在
2. `RAG_CELERY_BROKER_URL` 是否与 Redis 实际地址一致
3. worker 队列名是否为 `ingest`（命令里 `-Q ingest`）
4. Redis 是否可达

恢复动作：

```bash
docker compose restart worker
```

或本地直接重启 worker 进程。

### 5.2 症状：任务进入 `failed`

含义：执行失败但未达到 `ingest_failure_retry_limit`，仍在自动重试窗口。

处理：

- 先修依赖故障（模型服务、Qdrant、文件权限）
- 再观察是否自动恢复到 `completed`
- 必要时可手动重投递 `/run`

### 5.3 症状：任务进入 `dead_letter`

含义：失败次数达到上限，不再自动重试。

处理：

1. 修复根因
2. 手动调用 `POST /api/v1/ingest/jobs/{job_id}/run` 重投递
3. 再次轮询任务状态确认是否回到 `completed`

### 5.4 调整重试策略（仅 V1 两个参数）

- `RAG_INGEST_FAILURE_RETRY_LIMIT`
- `RAG_INGEST_RETRY_DELAY_SECONDS`

修改 `.env` 后必须重启 API 与 worker 才会生效。

## 6. 运行基线（V1 建议）

- 不要把 worker 与 API 进程混在同一个命令里
- 默认先单 worker 跑通，再考虑并发
- `dead_letter` 任务必须人工确认后再 `/run`
- 故障恢复优先级：先恢复队列消费能力，再恢复入库吞吐
