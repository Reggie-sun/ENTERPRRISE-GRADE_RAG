from dataclasses import dataclass
import logging

from fastapi import HTTPException, status  # 导入 HTTPException，用于越权检索时显式拒绝。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.embeddings.client import EmbeddingClient  # 导入 embedding 客户端，用于把查询文本向量化。
from ..rag.rerankers.client import RerankerClient
from ..rag.retrievers import LexicalMatch, QdrantLexicalRetriever
from ..rag.vectorstores.qdrant_store import QdrantVectorStore  # 导入 Qdrant 向量存储，用于执行向量检索。
from ..schemas.auth import AuthContext  # 导入统一鉴权上下文，供检索结果过滤复用。
from ..schemas.query_profile import QueryProfile
from ..schemas.retrieval import (  # 导入检索请求、响应和结果模型。
    RetrievalRerankCompareResponse,
    RetrievalRerankRouteStatus,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
    RerankPromotionRecommendation,
    RerankComparisonResult,
    RerankComparisonSummary,
)
from .document_service import DocumentService  # 导入文档服务，复用统一的文档读权限判断。
from .query_profile_service import QueryProfileService
from .retrieval_query_router import HybridBranchWeights, RetrievalQueryRouter

logger = logging.getLogger(__name__)

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
        query_router: RetrievalQueryRouter | None = None,
    ) -> None:  # 初始化检索服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.embedding_client = EmbeddingClient(self.settings)  # 创建 embedding 客户端，把查询问题转换成向量。
        self.vector_store = QdrantVectorStore(self.settings)  # 创建向量存储实例，负责执行 Qdrant 相似度检索。
        self.lexical_retriever = lexical_retriever  # 轻量关键词召回默认按需绑定当前 vector store，测试里可单独注入。
        self.document_service = document_service or DocumentService(self.settings)  # 复用同一份 settings 创建文档服务，避免自定义配置时又回退到全局 .env。
        self.query_profile_service = query_profile_service or QueryProfileService(self.settings)  # 统一解析 fast/accurate 档位，避免参数散落在检索服务里。
        self.system_config_service = self.query_profile_service.system_config_service  # 复用统一系统配置服务，保证检索和 rerank 读取的是同一份配置。
        self.reranker_client = RerankerClient(self.settings, system_config_service=self.system_config_service)  # 为 rerank 对比验证复用统一客户端。
        self.query_router = query_router or RetrievalQueryRouter(self.settings)  # 查询分类与 hybrid 动态权重策略统一收口到独立模块。

    def search(self, request: RetrievalRequest, *, auth_context: AuthContext | None = None) -> RetrievalResponse:  # 执行检索并返回结果。
        results, retrieval_mode, profile = self.search_candidates(
            request,
            auth_context=auth_context,
            truncate_to_top_k=True,
        )
        return RetrievalResponse(  # 组装最终检索响应。
            query=request.query,  # 返回原始查询文本。
            top_k=profile.top_k,  # 返回实际生效的 top_k。
            mode=retrieval_mode,  # 返回当前实际检索模式，便于前端和调试区分 qdrant / hybrid。
            results=results,  # 返回构造好的结果列表。
        )

    def search_candidates(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
        profile: QueryProfile | None = None,
        truncate_to_top_k: bool = True,
    ) -> tuple[list[RetrievedChunk], str, QueryProfile]:
        profile = profile or self.query_profile_service.resolve(
            purpose="retrieval",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )  # 先把 mode/top_k 展开为统一查询档位配置；内部调用可复用上层已解析档位。
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
        candidates, retrieval_mode, branch_weights = self._collect_candidates(
            query=request.query,
            vector_points=scored_points,
            profile=profile,
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

        result_limit = profile.top_k if truncate_to_top_k else None

        for candidate in candidates:  # 遍历最终候选结果，统一兼容纯向量与 hybrid 模式。
            payload = candidate.payload  # 读取 payload，空值在融合前已经归一成空字典。
            resolved_document_id = str(payload.get("document_id") or "unknown")  # 先解析文档 ID，供权限判断和结果对象复用。
            if auth_context is not None:
                can_read = readability_cache.get(resolved_document_id, False)
                if not can_read:
                    continue
            raw_score = float(candidate.score)  # 保留内部原始排序分，hybrid 模式下这是加权 RRF 原始值。
            output_score = self._response_score(
                raw_score,
                retrieval_mode=retrieval_mode,
                branch_weights=branch_weights,
            )  # 对外返回更可解释的相关度分数，避免直接暴露极低量级的 RRF 原始值。
            item = RetrievedChunk(  # 创建单条检索结果对象。
                chunk_id=str(payload.get("chunk_id") or candidate.candidate_id),  # 优先返回业务 chunk_id，缺失时回退到融合候选 id。
                document_id=resolved_document_id,  # 返回文档 ID，缺失时用 unknown 兜底。
                document_name=str(payload.get("document_name") or "unknown"),  # 返回文档名，缺失时用 unknown 兜底。
                text=str(payload.get("text") or ""),  # 返回检索命中的 chunk 文本。
                score=output_score,  # 返回对外相关度分数；hybrid 模式下归一化到更易解释的范围。
                source_path=str(payload.get("source_path") or ""),  # 返回原始文档路径，缺失时返回空字符串。
                retrieval_strategy=retrieval_mode,  # 返回召回策略，便于 trace/snapshot/调试解释为什么命中。
                vector_score=candidate.vector_score,  # 返回原始向量分数。
                lexical_score=candidate.lexical_score,  # 返回词项分数；纯向量召回时为空。
                fused_score=raw_score,  # 返回最终融合原始分数，便于调试真实排序依据。
                ocr_used=bool(payload.get("ocr_used") or False),  # 返回 OCR 标记，便于前端和生成链路判断文本来源。
                parser_name=str(payload.get("parser_name")) if payload.get("parser_name") else None,  # 返回解析器名称。
                page_no=int(payload["page_no"]) if payload.get("page_no") is not None else None,  # 返回 OCR 页码。
                ocr_confidence=float(payload["ocr_confidence"]) if payload.get("ocr_confidence") is not None else None,  # 返回 OCR 置信度摘要。
                quality_score=float(payload["quality_score"]) if payload.get("quality_score") is not None else None,  # 返回统一质量分。
            )
            if normalized_document_id and item.document_id != normalized_document_id:  # 二次安全过滤：即使向量库过滤异常也不允许串文档。
                continue
            results.append(item)  # 命中过滤条件后才加入返回列表。
            if result_limit is not None and len(results) >= result_limit:  # 对外检索保留 top_k，内部链路可显式拿到更大的融合候选。
                break

        return results, retrieval_mode, profile

    def compare_rerank(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
    ) -> RetrievalRerankCompareResponse:  # 在同一批检索候选上对比当前默认 rerank 路由与 heuristic 基线。
        response = self.search(request, auth_context=auth_context)  # 先复用现有检索链路，确保权限过滤和 hybrid 逻辑完全一致。
        profile = self.query_profile_service.resolve(
            purpose="retrieval",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )
        safe_top_n = min(profile.rerank_top_n, len(response.results))  # 没有足够候选时自动收敛实际返回数量。
        route = self.system_config_service.get_reranker_routing()
        configured_error_message: str | None = None
        provider_candidate_results: list[RetrievedChunk] | None = None
        provider_candidate_error_message: str | None = None

        if safe_top_n <= 0:
            empty_summary = RerankComparisonSummary(
                overlap_count=0,
                top1_same=False,
                configured_only_chunk_ids=[],
                heuristic_only_chunk_ids=[],
            )
            return RetrievalRerankCompareResponse(
                query=request.query,
                mode=response.mode,
                candidate_count=len(response.results),
                rerank_top_n=0,
                configured=RerankComparisonResult(
                    label="configured",
                    provider=route.provider,
                    model=route.model,
                    strategy="skipped",
                    results=[],
                ),
                heuristic=RerankComparisonResult(
                    label="heuristic",
                    provider="heuristic",
                    model=None,
                    strategy="skipped",
                    results=[],
                ),
                route_status=self._build_route_status(),
                summary=empty_summary,
                provider_candidate=None,
                provider_candidate_summary=None,
                recommendation=RerankPromotionRecommendation(
                    decision="hold",
                    should_switch_default_strategy=False,
                    message="当前没有可参与 rerank 验证的候选结果，保持 heuristic 默认。",
                ),
            )

        heuristic_results = self.reranker_client.rerank_heuristic(
            query=request.query,
            candidates=response.results,
            top_n=safe_top_n,
        )
        route_status = self._build_route_status()

        try:
            configured_results = self.reranker_client.rerank(
                query=request.query,
                candidates=response.results,
                top_n=safe_top_n,
            )
        except RuntimeError as exc:
            configured_error_message = str(exc)
            if not self.system_config_service.get_degrade_controls().rerank_fallback_enabled:
                configured_results = []
            else:
                configured_results = heuristic_results
            route_status = self._build_route_status()
        else:
            route_status = self._build_route_status()
        configured_strategy = route_status.effective_strategy
        provider_candidate: RerankComparisonResult | None = None
        provider_candidate_summary: RerankComparisonSummary | None = None

        if route.provider.lower().strip() != "heuristic":
            try:
                provider_candidate_results = self.reranker_client.rerank_provider_candidate(
                    query=request.query,
                    candidates=response.results,
                    top_n=safe_top_n,
                )
            except RuntimeError as exc:
                provider_candidate_error_message = str(exc)
                provider_candidate_results = []
            provider_candidate = RerankComparisonResult(
                label="provider_candidate",
                provider=route.provider,
                model=route.model,
                strategy="provider" if provider_candidate_error_message is None else "failed",
                error_message=provider_candidate_error_message,
                results=provider_candidate_results,
            )
            if provider_candidate_error_message is None:
                provider_candidate_summary = self._build_rerank_comparison_summary(
                    configured_results=provider_candidate_results,
                    heuristic_results=heuristic_results,
                )

        summary = self._build_rerank_comparison_summary(
            configured_results=configured_results,
            heuristic_results=heuristic_results,
        )
        recommendation = self._build_rerank_promotion_recommendation(
            route_status=route_status,
            provider=route.provider,
            provider_candidate=provider_candidate,
            provider_candidate_summary=provider_candidate_summary,
            rerank_top_n=safe_top_n,
        )
        return RetrievalRerankCompareResponse(
            query=request.query,
            mode=response.mode,
            candidate_count=len(response.results),
            rerank_top_n=safe_top_n,
            configured=RerankComparisonResult(
                label="configured",
                provider=route.provider,
                model=route.model,
                strategy=configured_strategy,
                error_message=configured_error_message,
                results=configured_results,
            ),
            heuristic=RerankComparisonResult(
                label="heuristic",
                provider="heuristic",
                model=None,
                strategy="heuristic",
                results=heuristic_results,
            ),
            route_status=route_status,
            summary=summary,
            provider_candidate=provider_candidate,
            provider_candidate_summary=provider_candidate_summary,
            recommendation=recommendation,
        )

    def _build_route_status(self) -> RetrievalRerankRouteStatus:
        status = self.reranker_client.get_runtime_status()
        return RetrievalRerankRouteStatus(
            provider=str(status["provider"]),
            model=str(status["model"]),
            default_strategy=str(status["default_strategy"]),
            failure_cooldown_seconds=float(status["failure_cooldown_seconds"]),
            effective_provider=str(status["effective_provider"]),
            effective_model=str(status["effective_model"]),
            effective_strategy=str(status["effective_strategy"]),
            fallback_enabled=bool(status["fallback_enabled"]),
            lock_active=bool(status["lock_active"]),
            lock_source=str(status["lock_source"]) if status["lock_source"] is not None else None,
            cooldown_remaining_seconds=float(status["cooldown_remaining_seconds"]),
            ready=bool(status["ready"]),
            detail=str(status["detail"]) if status["detail"] is not None else None,
        )

    def _collect_candidates(
        self,
        *,
        query: str,
        vector_points: list[object],
        profile: QueryProfile,
        limit: int,
        document_id: str | None,
    ) -> tuple[list[_RetrievalCandidate], str, HybridBranchWeights | None]:
        vector_candidates = [self._candidate_from_vector_point(point) for point in vector_points]
        if self._normalized_retrieval_strategy() != "hybrid":
            return vector_candidates, "qdrant", None

        branch_weights = self.query_router.resolve_branch_weights(query)
        logger.info(
            "hybrid retrieval query_type=%s dynamic=%s vector_weight=%.3f lexical_weight=%.3f exact_signals=%d semantic_signals=%d",
            branch_weights.query_type,
            branch_weights.dynamic_enabled,
            branch_weights.vector_weight,
            branch_weights.lexical_weight,
            branch_weights.exact_signals,
            branch_weights.semantic_signals,
        )
        lexical_retriever = self.lexical_retriever or QdrantLexicalRetriever(
            self.vector_store,
            chinese_tokenizer_mode=self.settings.retrieval_lexical_chinese_tokenizer,
            supplemental_bigram_weight=self.settings.retrieval_lexical_supplemental_bigram_weight,
        )
        try:
            lexical_matches = lexical_retriever.search(
                query,
                limit=min(profile.lexical_top_k, limit),
                document_id=document_id,
            )
        except RuntimeError:
            logger.warning("hybrid retrieval fallback_to=qdrant reason=lexical_error")
            return vector_candidates, "qdrant", None

        if not lexical_matches:
            return vector_candidates, "qdrant", None
        return (
            self._fuse_candidates(vector_candidates, lexical_matches, limit=limit, branch_weights=branch_weights),
            "hybrid",
            branch_weights,
        )

    def _fuse_candidates(
        self,
        vector_candidates: list[_RetrievalCandidate],
        lexical_matches: list[LexicalMatch],
        *,
        limit: int,
        branch_weights: HybridBranchWeights | None = None,
    ) -> list[_RetrievalCandidate]:
        fused_candidates: dict[str, _RetrievalCandidate] = {}
        rrf_k = self.settings.retrieval_hybrid_rrf_k
        weights = branch_weights or self.query_router.fixed_branch_weights()

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
            if weights.vector_weight > 0:
                fused.score += weights.vector_weight / (rrf_k + rank)

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
            if weights.lexical_weight > 0:
                fused.score += weights.lexical_weight / (rrf_k + rank)

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

    def _response_score(
        self,
        raw_score: float,
        *,
        retrieval_mode: str,
        branch_weights: HybridBranchWeights | None,
    ) -> float:
        if retrieval_mode != "hybrid" or branch_weights is None:
            return raw_score

        total_weight = max(branch_weights.vector_weight, 0.0) + max(branch_weights.lexical_weight, 0.0)
        if total_weight <= 0:
            return raw_score

        max_rrf_score = total_weight / (self.settings.retrieval_hybrid_rrf_k + 1)
        if max_rrf_score <= 0:
            return raw_score

        normalized_score = raw_score / max_rrf_score
        return min(max(normalized_score, 0.0), 1.0)

    @staticmethod
    def _build_rerank_comparison_summary(
        *,
        configured_results: list[RetrievedChunk],
        heuristic_results: list[RetrievedChunk],
    ) -> RerankComparisonSummary:
        configured_ids = [item.chunk_id for item in configured_results]
        heuristic_ids = [item.chunk_id for item in heuristic_results]
        configured_id_set = set(configured_ids)
        heuristic_id_set = set(heuristic_ids)
        return RerankComparisonSummary(
            overlap_count=len(configured_id_set & heuristic_id_set),
            top1_same=bool(configured_ids and heuristic_ids and configured_ids[0] == heuristic_ids[0]),
            configured_only_chunk_ids=[chunk_id for chunk_id in configured_ids if chunk_id not in heuristic_id_set],
            heuristic_only_chunk_ids=[chunk_id for chunk_id in heuristic_ids if chunk_id not in configured_id_set],
        )

    @staticmethod
    def _build_rerank_promotion_recommendation(
        *,
        route_status: RetrievalRerankRouteStatus,
        provider: str,
        provider_candidate: RerankComparisonResult | None,
        provider_candidate_summary: RerankComparisonSummary | None,
        rerank_top_n: int,
    ) -> RerankPromotionRecommendation:
        normalized_provider = provider.lower().strip()
        if normalized_provider == "heuristic":
            return RerankPromotionRecommendation(
                decision="not_applicable",
                should_switch_default_strategy=False,
                message="当前未配置模型级 rerank provider，继续保持 heuristic 默认。",
            )
        if route_status.default_strategy == "provider":
            if route_status.effective_strategy == "provider":
                return RerankPromotionRecommendation(
                    decision="provider_active",
                    should_switch_default_strategy=False,
                    message="provider 已作为默认主路径运行，无需再切换 default_strategy。",
                )
            return RerankPromotionRecommendation(
                decision="rollback_active",
                should_switch_default_strategy=False,
                message="provider 当前不可稳定使用，系统已保持 heuristic 回退，先排查远端 rerank 服务。",
            )
        if provider_candidate is None or provider_candidate.strategy != "provider" or provider_candidate.error_message:
            detail = provider_candidate.error_message if provider_candidate and provider_candidate.error_message else route_status.detail or "provider 候选当前不可用。"
            return RerankPromotionRecommendation(
                decision="hold",
                should_switch_default_strategy=False,
                message=f"继续保持 heuristic 默认。{detail}",
            )
        if provider_candidate_summary is not None and rerank_top_n > 0:
            if provider_candidate_summary.overlap_count >= rerank_top_n and provider_candidate_summary.top1_same:
                return RerankPromotionRecommendation(
                    decision="hold",
                    should_switch_default_strategy=False,
                    message="provider 候选已可用，但当前样本与 heuristic 结果一致，暂不建议切换默认。",
                )
        return RerankPromotionRecommendation(
            decision="eligible",
            should_switch_default_strategy=True,
            message="provider 候选已可用且与 heuristic 存在可观察差异，可以把 default_strategy 切到 provider 做真实流量验证。",
        )


def get_retrieval_service() -> RetrievalService:  # 提供 FastAPI 依赖注入入口。
    return RetrievalService()  # 返回一个检索服务实例。
