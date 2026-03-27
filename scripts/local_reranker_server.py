from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_MODEL_PATH = Path(  # 默认读取本机 bge-reranker-v2-m3 模型目录。
    os.getenv("RAG_LOCAL_RERANKER_MODEL_PATH", "/home/reggie/bge-reranker-v2-m3")
)
DEFAULT_HOST = os.getenv("RAG_LOCAL_RERANKER_HOST", "127.0.0.1")  # 默认只监听本机，避免调试时意外对外暴露。
DEFAULT_PORT = int(os.getenv("RAG_LOCAL_RERANKER_PORT", "8003"))  # 默认端口与本地 vLLM(8001) / embedding(8002) 错开。
DEFAULT_BATCH_SIZE = int(os.getenv("RAG_LOCAL_RERANKER_BATCH_SIZE", "8"))  # rerank 属于交叉编码，默认批大小比 embedding 小。
DEFAULT_MAX_LENGTH = int(os.getenv("RAG_LOCAL_RERANKER_MAX_LENGTH", "1024"))  # 交叉编码总长度上限，先给一个稳妥值。


class RerankRequest(BaseModel):  # 定义 OpenAI-compatible rerank 接口的最小请求体。
    model: str | None = None  # 兼容 OpenAI 协议，允许调用方带模型名但不强依赖它。
    query: str = Field(min_length=1)  # 用户查询文本。
    documents: list[str] = Field(min_length=1)  # 候选文档列表。
    top_n: int | None = Field(default=None, ge=1)  # 可选只返回前 N 条结果。


class RerankResult(BaseModel):  # 定义返回中的单条 rerank 结果。
    object: str = "rerank_result"  # 与 embeddings 的 object 风格保持一致，便于调试。
    index: int  # 命中文档在原始 documents 列表中的位置。
    relevance_score: float  # 模型打分。
    document: str  # 返回对应文档文本，便于联调时直接核对。


class RerankResponse(BaseModel):  # 定义 OpenAI-compatible rerank 响应结构。
    model: str  # 当前服务实际加载的模型标识。
    results: list[RerankResult]  # 排序后的结果列表。
    usage: dict[str, int]  # 返回一个近似 usage，便于调试。


class LocalRerankerService:  # 封装本地 reranker 模型加载和推理逻辑。
    def __init__(self, *, model_path: Path, batch_size: int, max_length: int, use_fp16: bool) -> None:
        self.model_path = model_path  # 保存模型路径，启动时加载。
        self.batch_size = batch_size  # 保存批大小。
        self.max_length = max_length  # 保存最大长度。
        self.use_fp16 = use_fp16  # 保存是否启用 fp16。
        self.model: Any | None = None  # 运行时加载的模型实例。
        self.tokenizer: Any | None = None  # 运行时加载的 tokenizer。
        self.torch: Any | None = None  # 延迟保存 torch 模块，避免脚本导入即依赖重包。
        self.device: str = "cpu"  # 默认设备先标为 cpu，加载后再更新。

    def load(self) -> None:  # 启动时加载本地 reranker 模型。
        if not self.model_path.exists():  # 模型目录不存在时直接报错，避免服务启动后才发现路径错了。
            raise RuntimeError(f"Reranker model path does not exist: {self.model_path}")
        try:  # 延迟导入，避免没有装依赖时脚本一 import 就崩。
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # 导入失败时回传真实原因，避免把版本冲突误报成“未安装”。
            raise RuntimeError(
                "Failed to import reranker dependencies. "
                f"Original import error: {exc}. "
                "Install requirements/local-ml.txt together with a CUDA-matched torch build."
            ) from exc

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"  # 默认优先使用 GPU。
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path), trust_remote_code=True)

        load_kwargs: dict[str, Any] = {"trust_remote_code": True}
        if self.device == "cuda" and self.use_fp16:
            load_kwargs["torch_dtype"] = torch.float16  # 仅在 GPU 上启 fp16，避免 CPU 端不稳定。

        self.model = AutoModelForSequenceClassification.from_pretrained(str(self.model_path), **load_kwargs)
        self.model.to(self.device)
        self.model.eval()

    def rerank(self, *, query: str, documents: list[str], top_n: int | None = None) -> list[dict[str, Any]]:  # 对候选文档做交叉编码重排。
        if self.model is None or self.tokenizer is None or self.torch is None:  # 未加载模型时拒绝继续执行。
            raise RuntimeError("Reranker model is not loaded.")

        normalized_documents = _normalize_documents(documents)  # 先做最小输入归一，避免空白字符串混进模型。
        pairs = [(query, document) for document in normalized_documents]  # 组装 query-document 对。
        scores: list[float] = []  # 收集每条 document 的模型分数。

        for start in range(0, len(pairs), max(1, self.batch_size)):  # 按配置批量推理，避免单次请求过大。
            batch_pairs = pairs[start : start + max(1, self.batch_size)]
            queries = [item[0] for item in batch_pairs]
            docs = [item[1] for item in batch_pairs]
            encoded = self.tokenizer(
                queries,
                docs,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}  # 把输入张量迁移到目标设备。
            with self.torch.no_grad():  # 关闭梯度，减少显存占用。
                outputs = self.model(**encoded)
            batch_scores = self._extract_scores(outputs.logits)
            scores.extend(batch_scores)

        ranked = [
            {"index": index, "relevance_score": float(score), "document": normalized_documents[index]}
            for index, score in enumerate(scores)
        ]
        ranked.sort(key=lambda item: item["relevance_score"], reverse=True)  # 按模型分数从高到低排序。
        limit = min(top_n or len(ranked), len(ranked))
        return ranked[:limit]

    def _extract_scores(self, logits: Any) -> list[float]:  # 兼容单 logit / 多 logit 两类返回结构。
        if self.torch is None:
            raise RuntimeError("Torch runtime is not initialized.")
        tensor = logits.detach().float().cpu()
        if tensor.ndim == 0:
            return [float(tensor.item())]
        if tensor.ndim == 1:
            return [float(value) for value in tensor.tolist()]
        if tensor.ndim == 2 and tensor.shape[1] == 1:
            return [float(value) for value in tensor.squeeze(-1).tolist()]
        if tensor.ndim == 2:
            return [float(value) for value in tensor[:, -1].tolist()]  # 多分类时默认取最后一列作为相关性分数。
        raise RuntimeError("Unexpected reranker logits shape.")


def _normalize_documents(documents: list[str]) -> list[str]:  # 统一清洗文档列表，避免空白字符串进入模型。
    return [document.strip() for document in documents if isinstance(document, str) and document.strip()]


def _estimate_usage(query: str, documents: list[str]) -> dict[str, int]:  # 返回一个近似 usage，方便联调观察但不作为计费依据。
    prompt_chars = len(query) + sum(len(document) for document in documents)
    prompt_tokens = max(1, prompt_chars // 4)  # 粗略按 4 个字符约 1 token 估算体量。
    return {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens}


def create_app(service: LocalRerankerService) -> FastAPI:  # 创建 FastAPI 应用并绑定生命周期。
    @asynccontextmanager
    async def lifespan(_: FastAPI):  # 应用启动时加载模型。
        service.load()  # 只在启动时加载一次，避免每个请求重复加载。
        yield

    app = FastAPI(title="Local BGE Reranker Server", version="0.1.0", lifespan=lifespan)  # 创建服务实例。

    @app.get("/health")  # 提供最小健康检查接口。
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_path": str(service.model_path),
            "batch_size": service.batch_size,
            "max_length": service.max_length,
            "use_fp16": service.use_fp16,
            "device": service.device,
        }

    @app.post("/v1/rerank", response_model=RerankResponse)  # 提供 OpenAI-compatible rerank 接口。
    @app.post("/rerank", response_model=RerankResponse)  # 同时兼容不带 /v1 的调用方式。
    def rerank(request: RerankRequest) -> RerankResponse:
        documents = _normalize_documents(request.documents)
        if not request.query.strip():  # 空 query 直接拒绝。
            raise HTTPException(status_code=400, detail="query must be a non-empty string.")
        if not documents:  # 空文档列表也直接拒绝。
            raise HTTPException(status_code=400, detail="documents must contain at least one non-empty string.")
        try:  # 正常执行 rerank 推理。
            results = service.rerank(query=request.query.strip(), documents=documents, top_n=request.top_n)
        except RuntimeError as exc:  # 运行时错误统一转成 502，表示模型服务内部依赖异常。
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return RerankResponse(
            model=request.model or service.model_path.name,
            results=[RerankResult(**item) for item in results],
            usage=_estimate_usage(request.query, documents),
        )

    return app


def parse_args() -> argparse.Namespace:  # 解析命令行参数，便于本地直接启动。
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible reranker server.")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Local reranker model directory.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Reranker batch size.")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH, help="Maximum sequence length.")
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Disable fp16 and force fp32. Use this if fp16 causes instability on your machine.",
    )
    return parser.parse_args()


def main() -> None:  # 启动本地 reranker 服务。
    args = parse_args()  # 读取命令行参数。
    service = LocalRerankerService(  # 创建 reranker 服务实例。
        model_path=Path(args.model_path).expanduser().resolve(),
        batch_size=args.batch_size,
        max_length=args.max_length,
        use_fp16=not args.fp32,
    )
    app = create_app(service)  # 创建 FastAPI 应用。
    uvicorn.run(app, host=args.host, port=args.port)  # 直接启动服务。


if __name__ == "__main__":  # 允许用 python scripts/local_reranker_server.py 直接启动。
    main()
