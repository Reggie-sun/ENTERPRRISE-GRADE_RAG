from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_MODEL_PATH = Path(os.getenv("RAG_LOCAL_EMBEDDING_MODEL_PATH", "/home/reggie/bge-m3"))  # 默认读取本机 bge-m3 模型目录。
DEFAULT_HOST = os.getenv("RAG_LOCAL_EMBEDDING_HOST", "127.0.0.1")  # 默认只监听本机，避免调试时意外对外暴露。
DEFAULT_PORT = int(os.getenv("RAG_LOCAL_EMBEDDING_PORT", "8001"))  # 默认端口与本地 vLLM 的 8000 错开。
DEFAULT_BATCH_SIZE = int(os.getenv("RAG_LOCAL_EMBEDDING_BATCH_SIZE", "16"))  # 默认批大小与后端配置对齐。
DEFAULT_MAX_LENGTH = int(os.getenv("RAG_LOCAL_EMBEDDING_MAX_LENGTH", "8192"))  # bge-m3 支持长文本，这里先给一个稳妥上限。


class EmbeddingRequest(BaseModel):  # 定义 OpenAI 兼容 embeddings 接口的最小请求体。
    input: str | list[str]  # 支持单条字符串或字符串列表。
    model: str | None = None  # 兼容 OpenAI 协议，允许调用方带模型名但不强依赖它。


class EmbeddingData(BaseModel):  # 定义返回中的单条 embedding 结构。
    object: str = "embedding"  # 与 OpenAI embeddings 返回格式保持一致。
    embedding: list[float]  # 实际向量内容。
    index: int  # 当前向量在输入列表中的位置。


class EmbeddingResponse(BaseModel):  # 定义 OpenAI 兼容 embeddings 响应结构。
    object: str = "list"  # 外层固定返回 list。
    data: list[EmbeddingData]  # 所有 embedding 结果。
    model: str  # 当前服务实际加载的模型标识。
    usage: dict[str, int]  # 返回一个近似 usage，便于调试。


class LocalEmbeddingService:  # 封装本地 bge-m3 模型加载和推理逻辑。
    def __init__(self, *, model_path: Path, batch_size: int, max_length: int, use_fp16: bool) -> None:
        self.model_path = model_path  # 保存模型路径，启动时加载。
        self.batch_size = batch_size  # 保存批大小。
        self.max_length = max_length  # 保存最大长度。
        self.use_fp16 = use_fp16  # 保存是否启用 fp16。
        self.model: Any | None = None  # 运行时加载的模型实例。

    def load(self) -> None:  # 启动时加载 FlagEmbedding 模型。
        if not self.model_path.exists():  # 模型目录不存在时直接报错，避免服务启动后才发现路径错了。
            raise RuntimeError(f"Embedding model path does not exist: {self.model_path}")
        try:  # 延迟导入，避免没有装依赖时脚本一 import 就崩。
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:  # 依赖缺失时给出明确提示。
            raise RuntimeError("FlagEmbedding is not installed. Install requirements/embedding.txt first.") from exc

        self.model = BGEM3FlagModel(str(self.model_path), use_fp16=self.use_fp16)  # 加载本地 bge-m3 模型。

    def embed(self, texts: list[str]) -> list[list[float]]:  # 对输入文本批量生成 dense embedding。
        if self.model is None:  # 未加载模型时拒绝继续执行。
            raise RuntimeError("Embedding model is not loaded.")
        encoded = self.model.encode(  # 调用 bge-m3 编码接口。
            texts,
            batch_size=self.batch_size,
            max_length=self.max_length,
        )
        dense_vectors = encoded.get("dense_vecs") if isinstance(encoded, dict) else encoded  # 兼容 FlagEmbedding 返回字典或数组两种形式。
        if dense_vectors is None:  # 返回结构异常时直接报错。
            raise RuntimeError("Unexpected BGEM3 encoding response: dense_vecs is missing.")
        return [  # 统一把向量转成纯 Python float 列表，便于 JSON 序列化。
            vector.tolist() if hasattr(vector, "tolist") else [float(value) for value in vector]
            for vector in dense_vectors
        ]


def _normalize_inputs(value: str | list[str]) -> list[str]:  # 统一把输入转换成字符串列表。
    if isinstance(value, str):  # 单条字符串输入时包装成列表。
        return [value]
    return value  # 已经是列表时直接返回。


def _estimate_usage(texts: list[str]) -> dict[str, int]:  # 返回一个近似 usage，方便联调观察但不作为计费依据。
    prompt_tokens = sum(max(1, len(text) // 4) for text in texts)  # 粗略按 4 个字符约 1 token 估算输入体量。
    return {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens}  # embeddings 场景没有 completion tokens。


def create_app(service: LocalEmbeddingService) -> FastAPI:  # 创建 FastAPI 应用并绑定生命周期。
    @asynccontextmanager
    async def lifespan(_: FastAPI):  # 应用启动时加载模型。
        service.load()  # 只在启动时加载一次，避免每个请求重复加载。
        yield

    app = FastAPI(title="Local BGE-M3 Embedding Server", version="0.1.0", lifespan=lifespan)  # 创建服务实例。

    @app.get("/health")  # 提供最小健康检查接口。
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_path": str(service.model_path),
            "batch_size": service.batch_size,
            "max_length": service.max_length,
            "use_fp16": service.use_fp16,
        }

    @app.post("/v1/embeddings", response_model=EmbeddingResponse)  # 提供 OpenAI 兼容 embeddings 接口。
    @app.post("/embeddings", response_model=EmbeddingResponse)  # 同时兼容不带 /v1 的调用方式。
    def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
        texts = _normalize_inputs(request.input)  # 统一成字符串列表。
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):  # 空输入直接拒绝。
            raise HTTPException(status_code=400, detail="input must contain at least one non-empty string.")
        try:  # 正常执行 embedding 推理。
            vectors = service.embed(texts)
        except RuntimeError as exc:  # 运行时错误统一转成 502，表示模型服务内部依赖异常。
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return EmbeddingResponse(
            data=[EmbeddingData(embedding=vector, index=index) for index, vector in enumerate(vectors)],
            model=request.model or service.model_path.name,
            usage=_estimate_usage(texts),
        )

    return app


def parse_args() -> argparse.Namespace:  # 解析命令行参数，便于本地直接启动。
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible embedding server for BGE-M3.")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Local BGE-M3 model directory.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Embedding batch size.")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH, help="Maximum sequence length.")
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Disable fp16 and force fp32. Use this if fp16 causes instability on your machine.",
    )
    return parser.parse_args()


def main() -> None:  # 启动本地 embedding 服务。
    args = parse_args()  # 读取命令行参数。
    service = LocalEmbeddingService(  # 创建 embedding 服务实例。
        model_path=Path(args.model_path).expanduser().resolve(),
        batch_size=args.batch_size,
        max_length=args.max_length,
        use_fp16=not args.fp32,
    )
    app = create_app(service)  # 创建 FastAPI 应用。
    uvicorn.run(app, host=args.host, port=args.port)  # 直接启动服务。


if __name__ == "__main__":  # 允许用 python scripts/local_embedding_server.py 直接启动。
    main()
