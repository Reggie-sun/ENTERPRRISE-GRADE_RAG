# 项目调试指南 / Debug Guide

本文档介绍如何在本地调试这个企业级 RAG 项目，包括环境搭建、启动流程、常见问题排查和调试技巧。

---

## 1. 项目架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (React + Vite)                        │
│                     http://127.0.0.1:3000                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │ 代理 /api -> :8020
┌───────────────────────────────▼─────────────────────────────────┐
│                      后端 API (FastAPI)                           │
│                     http://127.0.0.1:8020                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│    Qdrant     │     │     Redis     │     │ Embedding/LLM │
│  server:6333  │     │ server:6379   │     │ server:8002/8000 │
└───────────────┘     └───────────────┘     └───────────────┘
```

---

## 2. 环境准备

### 2.1 依赖安装

```bash
# 后端 Python 环境
conda create -n rag_backend python=3.11 -y
conda activate rag_backend
pip install -r requirements.txt

# 前端环境
cd frontend
npm install
```

### 2.2 配置文件

**后端配置** - 项目根目录 `.env`：

```env
# 必须确认的关键配置
RAG_QDRANT_URL=http://192.168.10.200:6333
RAG_CELERY_BROKER_URL=redis://192.168.10.200:6379/0
RAG_CELERY_RESULT_BACKEND=redis://192.168.10.200:6379/1

# Embedding 服务地址（远端）
RAG_EMBEDDING_PROVIDER=openai
RAG_EMBEDDING_BASE_URL=http://192.168.10.200:8002/v1
RAG_EMBEDDING_MODEL=BAAI/bge-m3

# LLM 服务地址（远端 vLLM）
RAG_LLM_PROVIDER=openai
RAG_LLM_BASE_URL=http://192.168.10.200:8000/v1
RAG_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

**前端配置** - `frontend/.env`：

```env
VITE_API_TARGET=http://127.0.0.1:8020
```

---

## 3. 启动顺序

**严格按照以下顺序启动：**

### Step 1: 启动 API + Worker

```bash
docker compose up -d
```

验证：

```bash
docker compose ps
```

### Step 2: 验证远端基础设施

```bash
curl http://192.168.10.200:6333/collections
redis-cli -u redis://192.168.10.200:6379/0 ping
curl http://192.168.10.200:8002/health
curl http://192.168.10.200:8000/v1/models
```

### Step 3: 启动前端

```bash
cd frontend
npm run dev
```

访问 http://127.0.0.1:3000

---

## 4. 调试技巧

### 4.1 后端调试

#### 方式一：添加日志

```python
import logging
logger = logging.getLogger(__name__)

# 在关键位置添加日志
logger.info(f"Processing document: {doc_id}")
logger.error(f"Failed to embed: {error}")
```

#### 方式二：使用调试器

在代码中添加断点：

```python
import pdb; pdb.set_trace()  # Python 内置
# 或
import debugpy; debugpy.listen(5678); debugpy.wait_for_client()  # VS Code 远程调试
```

#### 方式三：查看健康检查

```bash
curl -s http://127.0.0.1:8020/api/v1/health | jq
```

返回示例：

```json
{
  "status": "ok",
  "vector_store": {
    "url": "http://192.168.10.200:6333",
    "collection": "enterprise_rag_v1"
  },
  "embedding": {
    "base_url": "http://192.168.10.200:8002/v1",
    "model": "BAAI/bge-m3"
  },
  "llm": {
    "base_url": "http://192.168.10.200:8000/v1",
    "model": "Qwen/Qwen2.5-7B-Instruct"
  }
}
```

### 4.2 前端调试

#### 方式一：浏览器开发者工具

- 打开 http://127.0.0.1:3000
- 按 F12 打开开发者工具
- 查看 Network 面板观察 API 请求

#### 方式二：添加 console.log

```tsx
console.log('Upload result:', result);
console.error('Upload failed:', error);
```

#### 方式三：React DevTools

安装 React Developer Tools 浏览器扩展，检查组件状态和 props。

### 4.3 Celery Worker 调试

#### 查看 worker 日志

```bash
# 实时查看日志
docker compose logs -f worker

# 或本地模式直接在终端看输出
```

#### 检查队列状态

```bash
# 进入 Redis 查看队列
redis-cli -u redis://192.168.10.200:6379/0
> LLEN ingest  # 查看队列长度
> KEYS celery*  # 查看所有 Celery 键
```

#### 手动触发任务（测试用）

```bash
# 通过 API 手动触发
curl -X POST http://127.0.0.1:8020/api/v1/ingest/jobs/{job_id}/run
```

### 4.4 Qdrant 调试

#### 查看集合状态

```bash
curl http://192.168.10.200:6333/collections/enterprise_rag_v1
```

#### 查看向量数量

```bash
curl http://192.168.10.200:6333/collections/enterprise_rag_v1/points/count
```

#### 清空集合（重新测试）

```bash
curl -X DELETE http://192.168.10.200:6333/collections/enterprise_rag_v1
```

---

## 5. 测试方法

### 5.1 运行全部测试

```bash
python -m pytest backend/tests -v
```

### 5.2 运行特定测试文件

```bash
# 测试文档上传和入库
python -m pytest backend/tests/test_document_ingestion.py -v

# 测试检索和问答
python -m pytest backend/tests/test_retrieval_chat.py -v
```

### 5.3 运行单个测试

```bash
python -m pytest backend/tests/test_retrieval_chat.py::test_chat_ask_uses_real_retrieval_citations -v
```

### 5.4 测试覆盖率

```bash
python -m pytest backend/tests --cov=backend --cov-report=html
```

---

## 6. 常见问题排查

### 6.1 前端报 500 错误

**原因：** 前端代理配置错误或后端未启动

**排查步骤：**

```bash
# 1. 检查前端配置
cat frontend/.env
# 必须有 VITE_API_TARGET=http://127.0.0.1:8020

# 2. 检查后端是否启动
curl http://127.0.0.1:8020/api/v1/health

# 3. 重启前端
cd frontend && npm run dev
```

### 6.2 文档上传后一直停在 queued

**原因：** Worker 未启动或未消费

**排查步骤：**

```bash
# 1. 检查 worker 进程
ps -ef | grep celery

# 2. 检查 Redis 连接
redis-cli -u redis://192.168.10.200:6379/0 ping

# 3. 检查 worker 日志是否有错误
docker compose logs -f worker

# 4. 重启 worker
docker compose restart worker
```

### 6.3 问答返回 retrieval_fallback

**原因：** LLM 服务不可用

**排查步骤：**

```bash
# 1. 检查 LLM 服务
curl http://192.168.10.200:8000/v1/models

# 2. 检查 .env 中的 LLM 配置
cat .env | grep LLM

# 3. 检查健康检查返回的 llm.base_url
curl http://127.0.0.1:8020/api/v1/health | jq .llm
```

### 6.4 检索不到内容

**原因：** 任务未完成或 embedding 服务异常

**排查步骤：**

```bash
# 1. 检查任务状态
curl http://127.0.0.1:8020/api/v1/ingest/jobs/{job_id}

# 2. 检查 Qdrant 中是否有数据
curl http://192.168.10.200:6333/collections/enterprise_rag_v1/points/count

# 3. 检查 embedding 服务
curl http://192.168.10.200:8002/health
```

### 6.5 向量维度不匹配

**原因：** 切换了 embedding 模型但未更换 collection

**解决：**

```env
# 使用新的 collection 名称
RAG_QDRANT_COLLECTION=enterprise_rag_v1_bge_m3
```

### 6.6 上传文件报 413

**原因：** 文件超过大小限制

**解决：**

```env
# 调整上传限制（默认 100MB）
RAG_UPLOAD_MAX_FILE_SIZE_BYTES=104857600
```

---

## 7. 快速验证脚本

仓库已内置 `v0.1.2` smoke 脚本，不需要再手工复制：

```bash
bash scripts/smoke_test.sh
```

默认覆盖链路：

- `health -> documents(create) -> ingest poll -> retrieval(document_id) -> chat(document_id)`

常用参数覆盖：

```bash
API_BASE_URL=http://127.0.0.1:8020 \
TENANT_ID=wl \
TOP_K=3 \
POLL_TIMEOUT_SECONDS=180 \
bash scripts/smoke_test.sh
```

---

## 8. IDE 调试配置

### VS Code launch.json

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI Backend",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "backend.app.main:app",
        "--host", "0.0.0.0",
        "--port", "8020",
        "--reload"
      ],
      "jinjaTemplates": true,
      "autoStartBrowser": false
    },
    {
      "name": "Celery Worker",
      "type": "python",
      "request": "launch",
      "module": "celery",
      "args": [
        "-A", "backend.app.worker.celery_app:celery_app",
        "worker",
        "--loglevel=info",
        "-Q", "ingest"
      ],
      "console": "integratedTerminal"
    },
    {
      "name": "Pytest Current File",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v"],
      "console": "integratedTerminal"
    }
  ]
}
```

---

## 9. 相关文档

- [LOCAL_DEV_RUNBOOK.md](LOCAL_DEV_RUNBOOK.md) - 本地开发运行手册
- [backend/WORKER_RUNBOOK.md](backend/WORKER_RUNBOOK.md) - Worker 运行手册
- [backend/LOCAL_MODEL_RUNBOOK.md](backend/LOCAL_MODEL_RUNBOOK.md) - 本地模型运行手册
- [V1_PLAN.md](V1_PLAN.md) - V1 版本计划
