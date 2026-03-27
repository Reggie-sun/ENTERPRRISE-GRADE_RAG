from dataclasses import dataclass

from fastapi import HTTPException, status  # 导入 HTTPException，用于越权检索时显式拒绝。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.embeddings.client import EmbeddingClient  # 导入 embedding 客户端，用于把查询文本向量化。
from ..rag.retrievers import LexicalMatch, QdrantLexicalRetriever
from ..rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 向量存储，用于执行向量检索。
from ..schemas.auth import AuthContext  # 导入统一鉴权上下文，供检索结果过滤复用。
from ..schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk  # 导入检索请求、响应和结果模型。
from .document_service import DocumentService  # 导入文档服务，复用统一的文档读权限判断。
from .query_profile_service import QueryProfileService


@dataclass
class _RetrievalCandidate:
    candidate_id: str
    payload: dict[str, object]
    score: float
    vector_score: float | None = None
    lexical_score: float | None = None


class RetrievalService:  # 封装文档检索接口的业务逻辑。
    def __init__(
        self,
        settings: Settings | None = None,
        document_service: DocumentService | None = None,
        query_profile_service: QueryProfileService | None = None,
        lexical_retriever: QdrantLexicalRetriever | None = None,
    ) -> None:  # 初始化检索服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.embedding_client = EmbeddingClient(self.settings)  # 创建 embedding 客户端，把查询问题转换成向量。
        self.vector_store = QdrantVectorStore(self.settings)  # 创建向量存储实例，负责执行 Qdrant 相似度检索。
        self.lexical_retriever = lexical_retriever  # 轻量关键词召回默认按需绑定当前 vector store，测试里可单独注入。
        self.document_service = document_service or DocumentService(self.settings)  # 复用同一份 settings 创建文档服务，避免自定义配置时又回退到全局 .env。
        self.query_profile_service = query_profile_service or QueryProfileService(self.settings)  # 统一解析 fast/accurate 档位，避免参数散落在检索服务里。

    def search(self, request: RetrievalRequest, *, auth_context: AuthContext | None = None) -> RetrievalResponse:  # 执行检索并返回结果。
        profile = self.query_profile_service.resolve(
            purpose="retrieval",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )  # 先把 mode/top_k 展开为统一查询档位配置。
        normalized_document_id = request.document_id.strip() if request.document_id else None  # 统一清洗 document_id，避免前后空白导致过滤失效。
        if normalized_document_id and auth_context is not None and not self.document_service.is_document_readable(normalized_document_id, auth_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested document.",
            )
        search_limit = request.candidate_top_k or profile.candidate_top_k  # 默认按档位配置放大候选量，内部调用可显式覆写候选召回量。
        if normalized_document_id:  # 指定 document_id 时适度放大召回，给后置安全过滤留出余量。
            search_limit = min(max(search_limit * 2, profile.top_k), 200)  # 单文档检索继续保留更大的安全余量，同时兼容内部显式 candidate_top_k。

        query_vector = self.embedding_client.embed_texts([request.query])[0]  # 先对查询文本生成 embedding 向量。
        scored_points = self.vector_store.search(  # 用查询向量在 Qdrant 中检索候选 chunk。
            query_vector,
            limit=search_limit,
            document_id=normalized_document_id,
        )
        candidates, retrieval_mode = self._collect_candidates(
            query=request.query,
            vector_points=scored_points,
            limit=search_limit,
            document_id=normalized_document_id,
        )
        results: list[RetrievedChunk] = []  # 初始化检索结果列表。
        readability_cache: dict[str, bool] = {}  # 同一次检索里缓存按文档判断结果，避免重复读 metadata。
        if auth_context is not None:
            readability_cache = self.document_service.get_document_readability_map(
                [str(candidate.payload.get("document_id") or "") for candidate in candidates],
                auth_context,
            )

        for candidate in candidates:  # 遍历最终候选结果，统一兼容纯向量与 hybrid 模式。
            payload = candidate.payload  # 读取 payload，空值在融合前已经归一成空字典。
            resolved_document_id = str(payload.get("document_id") or "unknown")  # 先解析文档 ID，供权限判断和结果对象复用。
            if auth_context is not None:
                can_read = readability_cache.get(resolved_document_id, False)
                if not can_read:
                    continue
            item = RetrievedChunk(  # 创建单条检索结果对象。
                chunk_id=str(payload.get("chunk_id") or candidate.candidate_id),  # 优先返回业务 chunk_id，缺失时回退到融合候选 id。
                document_id=resolved_document_id,  # 返回文档 ID，缺失时用 unknown 兜底。
                document_name=str(payload.get("document_name") or "unknown"),  # 返回文档名，缺失时用 unknown 兜底。
                text=str(payload.get("text") or ""),  # 返回检索命中的 chunk 文本。
                score=float(candidate.score),  # 返回最终排序得分；hybrid 模式下这里是融合分数。
                source_path=str(payload.get("source_path") or ""),  # 返回原始文档路径，缺失时返回空字符串。
                ocr_used=bool(payload.get("ocr_used") or False),  # 返回 OCR 标记，便于前端和生成链路判断文本来源。
                parser_name=str(payload.get("parser_name")) if payload.get("parser_name") else None,  # 返回解析器名称。
                page_no=int(payload["page_no"]) if payload.get("page_no") is not None else None,  # 返回 OCR 页码。
                ocr_confidence=float(payload["ocr_confidence"]) if payload.get("ocr_confidence") is not None else None,  # 返回 OCR 置信度摘要。
            )
            if normalized_document_id and item.document_id != normalized_document_id:  # 二次安全过滤：即使向量库过滤异常也不允许串文档。
                continue
            results.append(item)  # 命中过滤条件后才加入返回列表。
            if len(results) >= profile.top_k:  # 达到请求上限后提前结束，避免无意义遍历。
                break

        return RetrievalResponse(  # 组装最终检索响应。
            query=request.query,  # 返回原始查询文本。
            top_k=profile.top_k,  # 返回实际生效的 top_k。
            mode=retrieval_mode,  # 返回当前实际检索模式，便于前端和调试区分 qdrant / hybrid。
            results=results,  # 返回构造好的结果列表。
        )

    def _collect_candidates(
        self,
        *,
        query: str,
        vector_points: list[object],
        limit: int,
        document_id: str | None,
    ) -> tuple[list[_RetrievalCandidate], str]:
        vector_candidates = [self._candidate_from_vector_point(point) for point in vector_points]
        if self._normalized_retrieval_strategy() != "hybrid":
            return vector_candidates, "qdrant"

        lexical_retriever = self.lexical_retriever or QdrantLexicalRetriever(self.vector_store)
        try:
            lexical_matches = lexical_retriever.search(
                query,
                limit=limit,
                document_id=document_id,
            )
        except RuntimeError:
            return vector_candidates, "qdrant"

        if not lexical_matches:
            return vector_candidates, "qdrant"
        return self._fuse_candidates(vector_candidates, lexical_matches, limit=limit), "hybrid"

    def _fuse_candidates(
        self,
        vector_candidates: list[_RetrievalCandidate],
        lexical_matches: list[LexicalMatch],
        *,
        limit: int,
    ) -> list[_RetrievalCandidate]:
        fused_candidates: dict[str, _RetrievalCandidate] = {}
        rrf_k = self.settings.retrieval_hybrid_rrf_k

        for rank, candidate in enumerate(vector_candidates, start=1):
            fused = fused_candidates.get(candidate.candidate_id)
            if fused is None:
                fused = _RetrievalCandidate(
                    candidate_id=candidate.candidate_id,
                    payload=dict(candidate.payload),
                    score=0.0,
                    vector_score=candidate.vector_score,
                )
                fused_candidates[candidate.candidate_id] = fused
            fused.vector_score = candidate.vector_score
            fused.score += 1.0 / (rrf_k + rank)

        for rank, lexical_match in enumerate(lexical_matches, start=1):
            candidate_id = str(lexical_match.payload.get("chunk_id") or lexical_match.point_id)
            fused = fused_candidates.get(candidate_id)
            if fused is None:
                fused = _RetrievalCandidate(
                    candidate_id=candidate_id,
                    payload=dict(lexical_match.payload),
                    score=0.0,
                    lexical_score=lexical_match.score,
                )
                fused_candidates[candidate_id] = fused
            else:
                fused.payload = dict(lexical_match.payload or fused.payload)
                fused.lexical_score = lexical_match.score
            fused.score += 1.0 / (rrf_k + rank)

        ranked_candidates = sorted(
            fused_candidates.values(),
            key=lambda item: (
                item.score,
                int(item.vector_score is not None) + int(item.lexical_score is not None),
                item.lexical_score if item.lexical_score is not None else -1.0,
                item.vector_score if item.vector_score is not None else -1.0,
            ),
            reverse=True,
        )
        return ranked_candidates[:limit]

    @staticmethod
    def _candidate_from_vector_point(point: object) -> _RetrievalCandidate:
        payload = dict(getattr(point, "payload", None) or {})
        point_id = str(getattr(point, "id", "unknown"))
        vector_score = float(getattr(point, "score", 0.0))
        return _RetrievalCandidate(
            candidate_id=str(payload.get("chunk_id") or point_id),
            payload=payload,
            score=vector_score,
            vector_score=vector_score,
        )

    def _normalized_retrieval_strategy(self) -> str:
        normalized = self.settings.retrieval_strategy_default.strip().lower()
        if normalized == "hybrid":
            return "hybrid"
        return "qdrant"


def get_retrieval_service() -> RetrievalService:  # 提供 FastAPI 依赖注入入口。
    return RetrievalService()  # 返回一个检索服务实例。
