# Local Model Runbook / 本地模型运行手册

This project can now be tested locally with:
本项目现在可以在本地使用以下服务进行测试：

- `vLLM` for generation on `http://127.0.0.1:8001/v1` / 用于生成回答的 vLLM 服务
- `bge-m3` for embeddings on `http://127.0.0.1:8002/v1` / 用于向量化的 bge-m3 服务

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

Create a dedicated Python 3.10 environment and install torch separately:
创建一个专用的 Python 3.10 环境并单独安装 torch：

```bash
conda create -n rag-embed python=3.10 -y
conda activate rag-embed
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements/embedding.txt
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

## 3. Local backend `.env` / 本地后端 `.env` 配置

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

RAG_RERANKER_PROVIDER=heuristic
RAG_QDRANT_COLLECTION=enterprise_rag_v1_local_bge_m3
```

If you previously ingested documents with `mock` embeddings (32-dim), do not reuse the old collection.
如果之前使用 `mock` embedding（32 维）入库过文档，不要复用旧的 collection。
Use a new collection name for bge-m3 (1024-dim), otherwise Qdrant will return vector dimension errors.
为 bge-m3（1024 维）使用新的 collection 名称，否则 Qdrant 会返回向量维度错误。

## 4. Start backend / 启动后端服务

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8020
```

Then open / 然后访问：

- API docs / API 文档：`http://127.0.0.1:8020/docs`
- Demo page / 演示页面：`http://127.0.0.1:8020/demo`
