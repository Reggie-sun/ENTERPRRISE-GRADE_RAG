# Local Model Runbook / 本地模型运行手册

> 注意：这是一份“本地模型专用”替代运行手册，不是当前项目默认基线。
> 当前默认基线请以 [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md) 为准。

This project can now be tested locally with:
本项目现在可以在本地使用以下服务进行测试：

- `vLLM` for generation on `http://127.0.0.1:8001/v1` / 用于生成回答的 vLLM 服务
- `bge-m3` for embeddings on `http://127.0.0.1:8002/v1` / 用于向量化的 bge-m3 服务
- `bge-reranker-v2-m3` on `http://127.0.0.1:8003/v1` / 用于候选片段重排的 reranker 服务

## 1. Start local vLLM / 启动本地 vLLM

Example / 示例：

```bash
docker run -d \
  --name vllm \
  --gpus all \
  --ipc=host \
  -p 8001:8000 \
  -e HF_ENDPOINT=https://hf-mirror.com \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --gpu-memory-utilization 0.8
```

## 2. Start local embedding server / 启动本地 embedding 服务

Create one dedicated Python 3.10 environment for `embedding + rerank`, and install torch separately (`>=2.6` required by current transformers safety check):
为 `embedding + rerank` 共用一个专用 Python 3.10 环境，并单独安装 torch（当前 transformers 的安全检查要求 `>=2.6`）：

```bash
conda create -n rag-ml python=3.10 -y
conda activate rag-ml
pip install --upgrade "torch>=2.6,<2.8" --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements/embedding.txt
pip install -r requirements/local-ml.txt
```

Run the local embedding server / 运行本地 embedding 服务：

```bash
python scripts/local_embedding_server.py \
  --model-path /home/reggie/bge-m3 \
  --host 127.0.0.1 \
  --port 8002
```

Health check / 健康检查：

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-m3","input":["alarm E102 handling guide"]}'
```

## 3. Start local reranker server / 启动本地 reranker 服务

Use the same `rag-ml` environment as embedding. Do not mix this with the vLLM runtime.
继续复用上面的 `rag-ml` 环境，不要和 vLLM 运行时混在一起。

```bash
conda activate rag-ml
python scripts/local_reranker_server.py \
  --model-path /home/reggie/bge-reranker-v2-m3 \
  --host 127.0.0.1 \
  --port 8003
```

Health check / 健康检查：

```bash
curl http://127.0.0.1:8003/health
curl http://127.0.0.1:8003/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-reranker-v2-m3","query":"报警 E102 怎么处理","documents":["先检查电压并复位设备","确认风扇转速传感器和灰尘堆积"],"top_n":2}'
```

## 4. Local backend `.env` / 本地后端 `.env` 配置

Use this configuration for local model testing:
使用此配置进行本地模型测试：

```env
RAG_LLM_PROVIDER=openai
RAG_LLM_BASE_URL=http://127.0.0.1:8001/v1
RAG_LLM_API_KEY=
RAG_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct

RAG_EMBEDDING_PROVIDER=openai
RAG_EMBEDDING_BASE_URL=http://127.0.0.1:8002/v1
RAG_EMBEDDING_API_KEY=
RAG_EMBEDDING_MODEL=BAAI/bge-m3

RAG_RERANKER_PROVIDER=openai
RAG_RERANKER_BASE_URL=http://127.0.0.1:8003/v1
RAG_RERANKER_API_KEY=
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANKER_TIMEOUT_SECONDS=12
RAG_QDRANT_COLLECTION=enterprise_rag_v1_local_bge_m3
```

If you previously ingested documents with `mock` embeddings (32-dim), do not reuse the old collection.
如果之前使用 `mock` embedding（32 维）入库过文档，不要复用旧的 collection。
Use a new collection name for bge-m3 (1024-dim), otherwise Qdrant will return vector dimension errors.
为 bge-m3（1024 维）使用新的 collection 名称，否则 Qdrant 会返回向量维度错误。

If you want to keep the current zero-dependency fallback, leave `RAG_RERANKER_PROVIDER=heuristic`.
如果你暂时还不想启模型级 rerank，可以继续保留 `RAG_RERANKER_PROVIDER=heuristic`。

## 5. Start backend / 启动后端服务

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8020
```

Then open / 然后访问：

- API docs / API 文档：`http://127.0.0.1:8020/docs`
- Demo page / 演示页面：`http://127.0.0.1:8020/demo`

Use `/demo` only as a backend-built smoke page. The primary frontend for local development is the React app on `http://127.0.0.1:3000`.
