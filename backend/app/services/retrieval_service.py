from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.embeddings.client import EmbeddingClient  # 导入 embedding 客户端，用于把查询文本向量化。
from ..rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 向量存储，用于执行向量检索。
from ..schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk  # 导入检索请求、响应和结果模型。


class RetrievalService:  # 封装文档检索接口的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化检索服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.embedding_client = EmbeddingClient(self.settings)  # 创建 embedding 客户端，把查询问题转换成向量。
        self.vector_store = QdrantVectorStore(self.settings)  # 创建向量存储实例，负责执行 Qdrant 相似度检索。

    def search(self, request: RetrievalRequest) -> RetrievalResponse:  # 执行检索并返回结果。
        normalized_document_id = request.document_id.strip() if request.document_id else None  # 统一清洗 document_id，避免前后空白导致过滤失效。
        search_limit = request.top_k  # 默认按请求 top_k 检索。
        if normalized_document_id:  # 指定 document_id 时适度放大召回，给后置安全过滤留出余量。
            search_limit = min(max(request.top_k * 8, request.top_k), 200)  # top_k 最大 20，这里上限封顶 200，避免一次请求过大。

        query_vector = self.embedding_client.embed_texts([request.query])[0]  # 先对查询文本生成 embedding 向量。
        scored_points = self.vector_store.search(  # 用查询向量在 Qdrant 中检索候选 chunk。
            query_vector,
            limit=search_limit,
            document_id=normalized_document_id,
        )
        results: list[RetrievedChunk] = []  # 初始化检索结果列表。

        for point in scored_points:  # 遍历 Qdrant 返回的相似点位。
            payload = point.payload or {}  # 读取 payload，空值时回退到空字典。
            item = RetrievedChunk(  # 创建单条检索结果对象。
                chunk_id=str(payload.get("chunk_id") or point.id),  # 优先返回业务 chunk_id，缺失时回退到 point id。
                document_id=str(payload.get("document_id") or "unknown"),  # 返回文档 ID，缺失时用 unknown 兜底。
                document_name=str(payload.get("document_name") or "unknown"),  # 返回文档名，缺失时用 unknown 兜底。
                text=str(payload.get("text") or ""),  # 返回检索命中的 chunk 文本。
                score=float(point.score),  # 返回 Qdrant 的相似度分数。
                source_path=str(payload.get("source_path") or ""),  # 返回原始文档路径，缺失时返回空字符串。
            )
            if normalized_document_id and item.document_id != normalized_document_id:  # 二次安全过滤：即使向量库过滤异常也不允许串文档。
                continue
            results.append(item)  # 命中过滤条件后才加入返回列表。
            if len(results) >= request.top_k:  # 达到请求上限后提前结束，避免无意义遍历。
                break

        return RetrievalResponse(  # 组装最终检索响应。
            query=request.query,  # 返回原始查询文本。
            top_k=request.top_k,  # 返回请求的 top_k。
            mode="qdrant",  # 当前模式是 Qdrant 向量检索。
            results=results,  # 返回构造好的结果列表。
        )


def get_retrieval_service() -> RetrievalService:  # 提供 FastAPI 依赖注入入口。
    return RetrievalService()  # 返回一个检索服务实例。
