"""文档检索服务，封装向量召回、词法召回、RRF混合融合、部门优先检索和Rerank对比验证。"""
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
    FilteredCandidateSummary,
    ResultExplainability,
    RetrievalDiagnostic,
    RetrievalFilterStage,
    RetrievalFinalizationStage,
    RetrievalPrimaryRecallStage,
    RetrievalQueryStage,
    RetrievalRerankCompareResponse,
    RetrievalRerankRouteStatus,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalRoutingStage,
    RetrievalSupplementalRecallStage,
    RetrievedChunk,
    RerankPromotionRecommendation,
    RerankComparisonResult,
    RerankComparisonSummary,
)
from ..schemas.system_config import SupplementalQualityThresholdsConfig
from .document_service import DocumentService  # 导入文档服务，复用统一的文档读权限判断。
from .document_record_accessor import DocumentServiceRecordAccessor
from .retrieval_scope_policy import DepartmentPriorityRetrievalScope, RetrievalScopePolicy  # 导入检索权限策略。
from .query_profile_service import QueryProfileService
from .public_resource_refs import sanitize_source_path
from .rerank_canary_service import RerankCanaryService
from .retrieval_query_router import HybridBranchWeights, RetrievalQueryRouter

logger = logging.getLogger(__name__)
SUPPLEMENTAL_LOW_LEXICAL_SCORE_THRESHOLD = 10.0

@dataclass
class _RetrievalCandidate:
    """检索候选内部数据结构，用于融合阶段统一承载向量/词法/部门优先的候选信息。"""
    candidate_id: str
    payload: dict[str, object]
    score: float
    vector_score: float | None = None
    lexical_score: float | None = None
    source_scope: str | None = None
    department_hit: bool = False
    global_hit: bool = False


class RetrievalService:  # 封装文档检索接口的业务逻辑。
    """文档检索服务核心类。

    核心职责：
    1. 向量召回：通过 Qdrant 执行语义相似度检索；
    2. 词法召回：基于关键词/分片的精确匹配召回，与向量召回互为补充；
    3. RRF 混合融合：将向量与词法候选按 Reciprocal Rank Fusion 加权融合；
    4. 部门优先检索：在多租户场景下优先召回本部门文档，全局文档作为补充；
    5. OCR 质量治理：过滤低质量 OCR 识别结果，避免噪声进入生成链路；
    6. Rerank 对比验证：在相同候选集上对比 heuristic 与模型 rerank，为灰度切换提供数据支撑。
    """
    def __init__(
        self,
        settings: Settings | None = None,
        document_service: DocumentService | None = None,
        retrieval_scope_policy: RetrievalScopePolicy | None = None,
        query_profile_service: QueryProfileService | None = None,
        rerank_canary_service: RerankCanaryService | None = None,
        lexical_retriever: QdrantLexicalRetriever | None = None,
        query_router: RetrievalQueryRouter | None = None,
    ) -> None:  # 初始化检索服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.embedding_client = EmbeddingClient(self.settings)  # 创建 embedding 客户端，把查询问题转换成向量。
        self.vector_store = QdrantVectorStore(self.settings)  # 创建向量存储实例，负责执行 Qdrant 相似度检索。
        self.lexical_retriever = lexical_retriever  # 轻量关键词召回默认按需绑定当前 vector store，测试里可单独注入。
        self.document_service = document_service or DocumentService(self.settings)  # 复用同一份 settings 创建文档服务，避免自定义配置时又回退到全局 .env。
        self.retrieval_scope_policy = retrieval_scope_policy or RetrievalScopePolicy(
            self.settings,
            metadata_store=getattr(self.document_service, "metadata_store", None),
            record_accessor=DocumentServiceRecordAccessor(self.document_service),
        )  # 检索权限策略：优先注入，否则基于 document_service 自动构造。
        self.query_profile_service = query_profile_service or QueryProfileService(self.settings)  # 统一解析 fast/accurate 档位，避免参数散落在检索服务里。
        self.system_config_service = self.query_profile_service.system_config_service  # 复用统一系统配置服务，保证检索和 rerank 读取的是同一份配置。
        self.reranker_client = RerankerClient(self.settings, system_config_service=self.system_config_service)  # 为 rerank 对比验证复用统一客户端。
        self.rerank_canary_service = rerank_canary_service or RerankCanaryService(self.settings)  # compare 结果沉淀为 canary 样本，供 ops/策略决策复盘。
        self.query_router = query_router or RetrievalQueryRouter(self.settings)  # 查询分类与 hybrid 动态权重策略统一收口到独立模块。

    def search(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
        include_diagnostic: bool = True,
    ) -> RetrievalResponse:  # 执行检索并返回结果。
        """对外检索入口。

        功能：调用 search_candidates 获取候选并截断到 top_k，组装为 RetrievalResponse 返回。
        输入：RetrievalRequest（含查询文本、模式、top_k等），可选鉴权上下文。
        输出：RetrievalResponse，包含查询文本、top_k、检索模式、结果列表和可选诊断信息。
        """
        diagnostic: dict[str, object] = {} if include_diagnostic else {}
        results, retrieval_mode, profile = self.search_candidates(
            request,
            auth_context=auth_context,
            truncate_to_top_k=True,
            diagnostic=diagnostic if include_diagnostic else None,
        )
        structured_diagnostic = (
            self.build_structured_diagnostic(
                diagnostic=diagnostic,
                request=request,
                profile=profile,
                auth_context=auth_context,
                results=results,
            )
            if include_diagnostic
            else None
        )
        return RetrievalResponse(  # 组装最终检索响应。
            query=request.query,  # 返回原始查询文本。
            top_k=profile.top_k,  # 返回实际生效的 top_k。
            mode=retrieval_mode,  # 返回当前实际检索模式，便于前端和调试区分 qdrant / hybrid。
            results=results,  # 返回构造好的结果列表。
            diagnostic=structured_diagnostic,  # 返回结构化诊断信息。
        )

    def search_candidates(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
        profile: QueryProfile | None = None,
        truncate_to_top_k: bool = True,
        diagnostic: dict[str, object] | None = None,
    ) -> tuple[list[RetrievedChunk], str, QueryProfile]:
        """检索候选生成主流程。

        功能：解析查询档位 → 权限校验 → 向量/词法召回 → RRF融合 → OCR质量治理 → 权限过滤 → 截断返回。
        输入：RetrievalRequest、可选鉴权上下文、可选预解析档位、是否截断到top_k。
        输出：(检索结果列表, 实际检索模式字符串, 查询档位对象) 三元组。

        diagnostic: 可选的诊断字典，传入后本方法会在其中写入检索各阶段的摘要信息，
                     供上层（如 chat_service）合并进 trace 而不影响主契约字段。
        """
        # --- diagnostic: query metadata ---
        normalized_document_id = request.document_id.strip() if request.document_id else None
        if diagnostic is not None:
            diagnostic["raw_query"] = request.query
            diagnostic["requested_mode"] = str(request.mode) if request.mode is not None else None
            diagnostic["retrieval_mode"] = None
            diagnostic["document_id_filter_applied"] = normalized_document_id is not None
            if hasattr(self, "query_router") and self.query_router is not None:
                try:
                    bw = self.query_router.resolve_branch_weights(request.query)
                    diagnostic["query_type"] = bw.query_type
                    if hasattr(self.query_router, "infer_query_granularity"):
                        diagnostic["query_granularity"] = self.query_router.infer_query_granularity(request.query)
                    diagnostic["branch_weights"] = {
                        "vector_weight": bw.vector_weight,
                        "lexical_weight": bw.lexical_weight,
                        "dynamic_enabled": bw.dynamic_enabled,
                    }
                except Exception:
                    pass

        profile = profile or self.query_profile_service.resolve(
            purpose="retrieval",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )  # 先把 mode/top_k 展开为统一查询档位配置；内部调用可复用上层已解析档位。
        if normalized_document_id and auth_context is not None and not self.document_service.is_document_readable(normalized_document_id, auth_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested document.",
            )
        search_limit = request.candidate_top_k or profile.candidate_top_k  # 默认按档位配置放大候选量，内部调用可显式覆写候选召回量。
        if normalized_document_id:  # 指定 document_id 时适度放大召回，给后置安全过滤留出余量。
            search_limit = min(max(search_limit * 2, profile.top_k), 200)  # 单文档检索继续保留更大的安全余量，同时兼容内部显式 candidate_top_k。

        query_vector = self.embedding_client.embed_texts([request.query])[0]  # 先对查询文本生成 embedding 向量。
        if self._should_use_department_priority_routes(
            auth_context=auth_context,
            document_id=normalized_document_id,
        ) and hasattr(self.retrieval_scope_policy, "build_department_priority_retrieval_scope"):
            retrieval_scope = self.retrieval_scope_policy.build_department_priority_retrieval_scope(auth_context)
            candidates, retrieval_mode, branch_weights = self._collect_department_priority_candidates(
                query=request.query,
                query_vector=query_vector,
                profile=profile,
                limit=search_limit,
                scope=retrieval_scope,
                truncate_to_top_k=truncate_to_top_k,
                diagnostic=diagnostic,
            )
            if diagnostic is not None:
                diagnostic["department_priority_enabled"] = True
        else:
            candidates, retrieval_mode, branch_weights = self._collect_scoped_candidates(
                query=request.query,
                query_vector=query_vector,
                profile=profile,
                limit=search_limit,
                document_id=normalized_document_id,
            )

        # --- diagnostic: recall stage ---
        pre_filter_count = len(candidates)
        if diagnostic is not None:
            diagnostic["retrieval_mode"] = retrieval_mode
            diagnostic["recall_candidates"] = pre_filter_count
            recall_counts = diagnostic.get("recall_counts")
            if not isinstance(recall_counts, dict):
                recall_counts = {}
            recall_counts["total_candidates"] = pre_filter_count
            diagnostic["recall_counts"] = recall_counts

        candidates, ocr_filtered_candidates = self._apply_ocr_quality_governance(candidates)
        ocr_filtered_count = len(ocr_filtered_candidates)

        if diagnostic is not None and ocr_filtered_count > 0:
            diagnostic["ocr_quality_filtered"] = ocr_filtered_count

        results: list[RetrievedChunk] = []  # 初始化检索结果列表。
        # Use retrieval-scoped map for filtering (allows cross-department supplemental results)
        # instead of direct-access readability map (which enforces department isolation).
        retrievability_cache: dict[str, bool] = {}  # 同一次检索里缓存按文档判断结果，避免重复读 metadata。
        if auth_context is not None:
            retrievability_cache = self.retrieval_scope_policy.get_document_retrievability_map(
                [str(candidate.payload.get("document_id") or "") for candidate in candidates],
                auth_context,
            )

        result_limit = profile.top_k if truncate_to_top_k else None

        _permission_filtered = 0
        _scope_filtered = 0
        filtered_candidates: list[dict[str, str]] = [
            self._candidate_summary(
                candidate,
                filter_reason=f"ocr_quality_below_threshold({self.settings.ocr_low_quality_min_score:.2f})",
                filter_layer="ocr_governance",
            )
            for candidate in ocr_filtered_candidates
        ]
        truncated_candidates: list[dict[str, str]] = []

        for index, candidate in enumerate(candidates):  # 遍历最终候选结果，统一兼容纯向量与 hybrid 模式。
            payload = candidate.payload  # 读取 payload，空值在融合前已经归一成空字典。
            resolved_document_id = str(payload.get("document_id") or "unknown")  # 先解析文档 ID，供权限判断和结果对象复用。
            if auth_context is not None:
                can_read = retrievability_cache.get(resolved_document_id, False)
                if not can_read:
                    _permission_filtered += 1
                    filtered_candidates.append(
                        self._candidate_summary(
                            candidate,
                            filter_reason="not_retrievable_for_auth_context",
                            filter_layer="permission_check",
                        )
                    )
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
                source_path=sanitize_source_path(
                    document_id=resolved_document_id,
                    source_path=str(payload.get("source_path") or ""),
                ),  # 对外只返回脱敏后的资源引用，避免泄露内部存储路径。
                retrieval_strategy=retrieval_mode,  # 返回召回策略，便于 trace/snapshot/调试解释为什么命中。
                source_scope=candidate.source_scope,  # 返回部门优先融合后的来源范围，便于解释“本部门优先 / 全局补充”。
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
                _scope_filtered += 1
                filtered_candidates.append(
                    self._candidate_summary(
                        candidate,
                        filter_reason="document_scope_mismatch",
                        filter_layer="scope_check",
                    )
                )
                continue
            results.append(item)  # 命中过滤条件后才加入返回列表。
            if result_limit is not None and len(results) >= result_limit:  # 对外检索保留 top_k，内部链路可显式拿到更大的融合候选。
                truncated_candidates = [
                    self._candidate_summary(
                        remainder,
                        filter_reason="ranked_below_top_k",
                        filter_layer="top_k",
                    )
                    for remainder in candidates[index + 1 :]
                ]
                break

        # --- diagnostic: filter summary ---
        if diagnostic is not None:
            diagnostic["final_results"] = len(results)
            diagnostic["final_result_count"] = len(results)
            filters: dict[str, int] = {}
            if ocr_filtered_count:
                filters["ocr_quality"] = ocr_filtered_count
            if _permission_filtered:
                filters["permission"] = _permission_filtered
            if _scope_filtered:
                filters["document_scope"] = _scope_filtered
            truncated = pre_filter_count - len(results) - _permission_filtered - _scope_filtered - ocr_filtered_count
            if truncated > 0:
                filters["top_k_truncated"] = truncated
            if filters:
                diagnostic["filters"] = filters
                diagnostic["filter_counts"] = dict(filters)
            diagnostic["filtered_candidates"] = filtered_candidates + truncated_candidates[:10]

        return results, retrieval_mode, profile

    def compare_rerank(
        self,
        request: RetrievalRequest,
        *,
        auth_context: AuthContext | None = None,
    ) -> RetrievalRerankCompareResponse:  # 在同一批检索候选上对比当前默认 rerank 路由与 heuristic 基线。
        """Rerank 对比验证入口。

        功能：在同一批检索候选上分别执行 configured provider rerank 和 heuristic rerank，
              计算两者重合度，给出灰度切换建议，并沉淀为 canary 样本供运维复盘。
        输入：RetrievalRequest、可选鉴权上下文。
        输出：RetrievalRerankCompareResponse，包含双方排序结果、重合摘要和切换建议。
        """
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

        # 先执行 heuristic rerank 作为基线，用于后续对比
        heuristic_results = self.reranker_client.rerank_heuristic(
            query=request.query,
            candidates=response.results,
            top_n=safe_top_n,
        )
        route_status = self._build_route_status()

        # 执行当前配置的模型 rerank，失败时根据降级开关决定是否回退到 heuristic
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

        # 如果当前 provider 不是 heuristic，额外跑一轮 provider_candidate 用于灰度对比
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
        response_payload = RetrievalRerankCompareResponse(
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
        canary_sample = self.rerank_canary_service.record_compare_sample(
            query=request.query,
            mode=response.mode,
            target_id=request.document_id.strip() if request.document_id else None,
            auth_context=auth_context,
            response=response_payload,
        )
        return response_payload.model_copy(update={"canary_sample_id": canary_sample.sample_id})

    def build_observability_details(self, *, query: str, retrieval_mode: str) -> dict[str, object]:
        details: dict[str, object] = {"retrieval_mode": retrieval_mode}
        if retrieval_mode != "hybrid":
            return details

        branch_weights = self.query_router.resolve_branch_weights(query)
        details.update(
            {
                "query_type": branch_weights.query_type,
                "vector_weight": branch_weights.vector_weight,
                "lexical_weight": branch_weights.lexical_weight,
                "dynamic_weighting_enabled": branch_weights.dynamic_enabled,
            }
        )
        if branch_weights.exact_signals > 0:
            details["exact_signals"] = branch_weights.exact_signals
        if branch_weights.semantic_signals > 0:
            details["semantic_signals"] = branch_weights.semantic_signals
        return details

    @staticmethod
    def build_structured_diagnostic(
        *,
        diagnostic: dict[str, object],
        request: RetrievalRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        results: list[RetrievedChunk],
    ) -> RetrievalDiagnostic:
        """将 search_candidates 内部诊断字典转换为结构化 RetrievalDiagnostic。"""
        recall_counts = dict(diagnostic.get("recall_counts")) if isinstance(diagnostic.get("recall_counts"), dict) else {}
        filter_counts = dict(diagnostic.get("filter_counts", diagnostic.get("filters"))) if isinstance(diagnostic.get("filter_counts", diagnostic.get("filters")), dict) else {}
        branch_weights = diagnostic.get("branch_weights")
        retrieval_mode = str(diagnostic.get("retrieval_mode", "")) or None
        query_text = str(diagnostic.get("raw_query", request.query))
        department_priority_enabled = bool(diagnostic.get("department_priority_enabled", False))
        primary_effective_count = RetrievalService._as_int(diagnostic.get("primary_effective_count"))
        primary_threshold = RetrievalService._as_int(diagnostic.get("primary_threshold"))
        supplemental_triggered = bool(diagnostic.get("supplemental_triggered", False))
        filtered_candidates = RetrievalService._build_filtered_candidate_summaries(
            diagnostic.get("filtered_candidates"),
        )
        result_explainability = RetrievalService._build_result_explainability(
            results=results,
            department_priority_enabled=department_priority_enabled,
        )
        query_stage = RetrievalQueryStage(
            raw_query=query_text,
            normalized_query=None,
            query_type=RetrievalService._as_optional_str(diagnostic.get("query_type")),
            query_granularity=RetrievalService._as_optional_str(diagnostic.get("query_granularity")),
            requested_mode=str(request.mode) if request.mode is not None else None,
            effective_mode=retrieval_mode,
        )
        routing_stage = RetrievalRoutingStage(
            is_hybrid=retrieval_mode == "hybrid",
            vector_weight=RetrievalService._as_float((branch_weights or {}).get("vector_weight")) if isinstance(branch_weights, dict) else None,
            lexical_weight=RetrievalService._as_float((branch_weights or {}).get("lexical_weight")) if isinstance(branch_weights, dict) else None,
            is_document_id_exact=bool(diagnostic.get("document_id_filter_applied", False)),
            department_priority_enabled=department_priority_enabled,
            structured_routing_applied=bool(diagnostic.get("structured_routing_applied", False)),
        )
        primary_vector_count = RetrievalService._pick_count(recall_counts, "department_vector_count", "department_vector", "vector_count")
        primary_lexical_count = RetrievalService._pick_count(recall_counts, "department_lexical_count", "department_lexical", "lexical_count")
        primary_fused_count = RetrievalService._pick_count(recall_counts, "department_fused_count", "department_after_ocr", "fused_count", "total_candidates")
        effective_count = primary_effective_count if primary_effective_count is not None else primary_fused_count
        primary_recall_stage = RetrievalPrimaryRecallStage(
            vector_count=primary_vector_count,
            lexical_count=primary_lexical_count,
            fused_count=primary_fused_count,
            effective_count=effective_count,
            threshold=primary_threshold,
            whether_sufficient=(
                not supplemental_triggered
                if primary_threshold is None
                else (effective_count >= primary_threshold and not supplemental_triggered)
            ),
            top1_score=RetrievalService._as_float(diagnostic.get("primary_top1_score")),
            avg_top_n_score=RetrievalService._as_float(diagnostic.get("primary_avg_top_n_score")),
            quality_top1_threshold=RetrievalService._as_float(diagnostic.get("quality_top1_threshold")),
            quality_avg_threshold=RetrievalService._as_float(diagnostic.get("quality_avg_threshold")),
        )
        supplemental_recall_stage = RetrievalSupplementalRecallStage(
            triggered=supplemental_triggered,
            reason=RetrievalService._as_optional_str(diagnostic.get("supplemental_reason")),
            vector_count=RetrievalService._pick_count(recall_counts, "supplemental_vector_count", "supplemental_vector"),
            lexical_count=RetrievalService._pick_count(recall_counts, "supplemental_lexical_count", "supplemental_lexical"),
            fused_count=RetrievalService._pick_count(recall_counts, "supplemental_fused_count", "supplemental_recall"),
            trigger_basis=RetrievalService._as_optional_str(diagnostic.get("supplemental_trigger_basis")),
        )
        filter_stage = RetrievalFilterStage(
            ocr_quality_filtered_count=RetrievalService._pick_count(filter_counts, "ocr_quality_filtered_count", "ocr_quality_filtered", "ocr_quality"),
            permission_filtered_count=RetrievalService._pick_count(filter_counts, "permission_filtered_count", "permission_filtered", "permission"),
            document_scope_filtered_count=RetrievalService._pick_count(filter_counts, "document_scope_filtered_count", "document_scope_filtered", "document_scope"),
            top_k_truncated_count=RetrievalService._pick_count(filter_counts, "top_k_truncated_count", "top_k_truncated"),
            filtered_candidates=filtered_candidates,
        )
        final_result_count = int(diagnostic.get("final_result_count", diagnostic.get("final_results", 0)))
        finalization_stage = RetrievalFinalizationStage(
            final_result_count=final_result_count,
            returned_top_k=len(results),
            response_mode=retrieval_mode,
            backfilled_chunk_count=RetrievalService._as_int(diagnostic.get("backfilled_chunk_count")) or 0,
            result_explanations=result_explainability,
        )
        return RetrievalDiagnostic(
            query=query_text,
            query_type=RetrievalService._as_optional_str(diagnostic.get("query_type")),
            query_granularity=RetrievalService._as_optional_str(diagnostic.get("query_granularity")),
            requested_mode=str(request.mode) if request.mode is not None else None,
            retrieval_mode=retrieval_mode,
            document_id_filter_applied=bool(diagnostic.get("document_id_filter_applied", False)),
            department_priority_enabled=department_priority_enabled,
            primary_threshold=primary_threshold,
            primary_effective_count=primary_effective_count,
            supplemental_triggered=supplemental_triggered,
            supplemental_reason=RetrievalService._as_optional_str(diagnostic.get("supplemental_reason")),
            recall_counts=recall_counts,
            filter_counts=filter_counts,
            final_result_count=final_result_count,
            branch_weights=branch_weights if isinstance(branch_weights, dict) else None,
            stage_durations_ms=dict(diagnostic.get("stage_durations_ms")) if isinstance(diagnostic.get("stage_durations_ms"), dict) else {},
            query_stage=query_stage,
            routing_stage=routing_stage,
            primary_recall_stage=primary_recall_stage,
            supplemental_recall_stage=supplemental_recall_stage,
            filter_stage=filter_stage,
            finalization_stage=finalization_stage,
            result_explainability=result_explainability,
            filtered_candidates=filtered_candidates,
        )

    @staticmethod
    def _pick_count(record: dict[str, int], *keys: str) -> int:
        for key in keys:
            value = record.get(key)
            if isinstance(value, int):
                return value
        return 0

    @staticmethod
    def _as_int(value: object) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float(value: object) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_optional_str(value: object) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @staticmethod
    def _build_filtered_candidate_summaries(raw_items: object) -> list[FilteredCandidateSummary]:
        if not isinstance(raw_items, list):
            return []
        items: list[FilteredCandidateSummary] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            items.append(
                FilteredCandidateSummary(
                    document_id=str(raw.get("document_id") or ""),
                    chunk_id=str(raw.get("chunk_id") or ""),
                    filter_reason=str(raw.get("filter_reason") or ""),
                    filter_layer=str(raw.get("filter_layer") or ""),
                )
            )
        return items

    @staticmethod
    def _build_result_explainability(
        *,
        results: list[RetrievedChunk],
        department_priority_enabled: bool,
    ) -> list[ResultExplainability]:
        explainability: list[ResultExplainability] = []
        for rank, item in enumerate(results, start=1):
            source_scope = item.source_scope
            if source_scope in {"department", "global", "both"}:
                selected_via = source_scope
            elif department_priority_enabled:
                selected_via = "department"
            else:
                selected_via = "global"
            explainability.append(
                ResultExplainability(
                    rank=rank,
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    document_name=item.document_name,
                    source_scope=source_scope,
                    department_hit=source_scope in {"department", "both"},
                    supplemental_hit=source_scope in {"global", "both"},
                    vector_score=item.vector_score,
                    lexical_score=item.lexical_score,
                    fused_score=item.fused_score,
                    final_score=item.score,
                    selected_via=selected_via,
                    structured_backfill=False,
                    structured_backfill_reason=None,
                    why_included=RetrievalService._build_inclusion_reason(item=item, selected_via=selected_via),
                )
            )
        return explainability

    @staticmethod
    def _build_inclusion_reason(*, item: RetrievedChunk, selected_via: str | None) -> str:
        routing_text = "hybrid 融合排序" if item.retrieval_strategy == "hybrid" else (item.retrieval_strategy or "检索排序")
        via_text = {
            "department": "本部门命中",
            "supplemental": "补充命中",
            "global": "全局范围命中",
            "both": "部门与补充双重命中",
        }.get(selected_via, "检索命中")
        score_parts: list[str] = []
        if item.vector_score is not None:
            score_parts.append(f"向量 {item.vector_score:.4f}")
        if item.lexical_score is not None:
            score_parts.append(f"词法 {item.lexical_score:.4f}")
        if item.fused_score is not None:
            score_parts.append(f"融合 {item.fused_score:.4f}")
        score_text = "，".join(score_parts)
        if score_text:
            return f"{via_text}，按 {routing_text} 保留；{score_text}。"
        return f"{via_text}，按 {routing_text} 保留。"

    @staticmethod
    def _candidate_summary(candidate: _RetrievalCandidate, *, filter_reason: str, filter_layer: str) -> dict[str, str]:
        payload = candidate.payload
        return {
            "document_id": str(payload.get("document_id") or ""),
            "chunk_id": str(payload.get("chunk_id") or candidate.candidate_id),
            "filter_reason": filter_reason,
            "filter_layer": filter_layer,
        }

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
        document_ids: list[str] | None = None,
    ) -> tuple[list[_RetrievalCandidate], str, HybridBranchWeights | None]:
        """收集并融合向量与词法召回候选。

        功能：将向量召回结果与词法召回结果按 RRF 策略融合；若策略非 hybrid 或词法召回失败，则仅返回向量候选。
        输入：查询文本、向量召回原始点集、查询档位、召回上限、可选文档ID/文档ID列表。
        输出：(候选列表, 检索模式, 分支权重) 三元组。
        """
        vector_candidates = [self._candidate_from_vector_point(point) for point in vector_points]
        # 非混合策略时直接返回纯向量候选，无需执行词法召回
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
            lexical_search_kwargs: dict[str, object] = {
                "query": query,
                "limit": min(profile.lexical_top_k, limit),
            }
            if document_id is not None:
                lexical_search_kwargs["document_id"] = document_id
            if document_ids is not None:
                lexical_search_kwargs["document_ids"] = document_ids
            lexical_matches = lexical_retriever.search(**lexical_search_kwargs)
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

    def _collect_scoped_candidates(
        self,
        *,
        query: str,
        query_vector: list[float],
        profile: QueryProfile,
        limit: int,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> tuple[list[_RetrievalCandidate], str, HybridBranchWeights | None]:
        """带作用域限制的候选收集：先执行向量检索，再调用 _collect_candidates 完成融合。

        功能：根据文档ID或文档ID列表限定检索范围，执行向量检索后进入融合流程。
        输入：查询文本、查询向量、查询档位、召回上限、可选文档ID或文档ID列表。
        输出：(候选列表, 检索模式, 分支权重) 三元组。
        """
        if document_ids is not None and not document_ids:
            return [], "qdrant", None
        vector_points = self._search_vector_points(
            query_vector=query_vector,
            limit=limit,
            document_id=document_id,
            document_ids=document_ids,
        )
        return self._collect_candidates(
            query=query,
            vector_points=vector_points,
            profile=profile,
            limit=limit,
            document_id=document_id,
            document_ids=document_ids,
        )

    def _collect_department_priority_candidates(
        self,
        *,
        query: str,
        query_vector: list[float],
        profile: QueryProfile,
        limit: int,
        scope: DepartmentPriorityRetrievalScope | None,
        truncate_to_top_k: bool = True,
        diagnostic: dict[str, object] | None = None,
    ) -> tuple[list[_RetrievalCandidate], str, HybridBranchWeights | None]:
        """部门优先分阶段候选收集：先查本部门，不足时才补充同租户其他部门文档。

        阶段一：只在 department_document_ids 范围内检索。
        阶段二：仅当本部门有效结果数不足时，才查 supplemental pool（global_document_ids）。
        融合排序：本部门结果优先，补充结果在后。

        "有效结果数"仍按本部门候选经过 OCR 质量治理后的 chunk 数计算。
        但为了避免同一篇弱相关文档的多个 chunk 把 primary sufficiency 误判成“已足够”，
        会额外结合本部门 top1 lexical 信号做低质量判定。

        输入：查询文本、查询向量、查询档位、召回上限、部门优先作用域、是否截断到 top_k。
        输出：(融合后候选列表, 检索模式, 分支权重) 三元组。
        """
        if scope is None:
            return self._collect_scoped_candidates(
                query=query,
                query_vector=query_vector,
                profile=profile,
                limit=limit,
            )

        # --- Stage 1: department route only ---
        department_candidates, department_mode, department_branch_weights = self._collect_scoped_candidates(
            query=query,
            query_vector=query_vector,
            profile=profile,
            limit=limit,
            document_ids=scope.department_document_ids,
        )
        self._mark_candidates_source_scope(department_candidates, source_scope="department")
        department_vector_count = sum(1 for c in department_candidates if c.vector_score is not None)
        department_lexical_count = sum(1 for c in department_candidates if c.lexical_score is not None)
        department_fused_count = len(department_candidates)

        # Apply OCR quality governance to department candidates to get effective count
        department_after_ocr, _ocr_filtered = self._apply_ocr_quality_governance(department_candidates)
        department_after_ocr_count = len(department_after_ocr)
        department_unique_doc_count = self._count_unique_documents(department_after_ocr)
        department_effective_count = department_after_ocr_count
        required = self._required_primary_results(profile, truncate_to_top_k)
        primary_top1_score, primary_avg_top_n_score = self._summarize_primary_quality(
            department_after_ocr,
            retrieval_mode=department_mode,
            branch_weights=department_branch_weights,
            window_size=required,
        )
        primary_top1_lexical_score = self._top_candidate_lexical_score(department_after_ocr)
        query_granularity = (
            str(diagnostic.get("query_granularity") or "").strip().lower()
            if diagnostic is not None
            else ""
        )
        quality_thresholds = self._get_supplemental_quality_thresholds()
        quality_top1_threshold = quality_thresholds.top1_threshold
        quality_avg_threshold = quality_thresholds.avg_top_n_threshold
        if query_granularity == "fine":
            quality_top1_threshold = max(
                quality_top1_threshold,
                quality_thresholds.fine_query_top1_threshold,
            )
            quality_avg_threshold = max(
                quality_avg_threshold,
                quality_thresholds.fine_query_avg_top_n_threshold,
            )
        low_quality_by_score = (
            primary_top1_score is not None and primary_top1_score < quality_top1_threshold
        ) or (
            primary_avg_top_n_score is not None and primary_avg_top_n_score < quality_avg_threshold
        )
        low_quality_by_lexical = (
            department_mode == "hybrid"
            and primary_top1_lexical_score is not None
            and primary_top1_lexical_score < SUPPLEMENTAL_LOW_LEXICAL_SCORE_THRESHOLD
        )
        low_quality = low_quality_by_score or low_quality_by_lexical

        if department_effective_count >= required and not low_quality:
            # Department has sufficient and good-quality results — skip supplemental route entirely
            logger.info(
                "staged_retrieval stage=department_only department_effective=%d department_unique_docs=%d required=%d top1=%.4f avg_top_n=%.4f lexical_top1=%.4f supplemental=skipped",
                department_effective_count,
                department_unique_doc_count,
                required,
                primary_top1_score or 0.0,
                primary_avg_top_n_score or 0.0,
                primary_top1_lexical_score or 0.0,
            )
            if diagnostic is not None:
                diagnostic["primary_threshold"] = required
                diagnostic["primary_effective_count"] = department_effective_count
                diagnostic["supplemental_triggered"] = False
                diagnostic["supplemental_reason"] = "department_sufficient"
                diagnostic["supplemental_trigger_basis"] = "department_sufficient"
                diagnostic["primary_top1_score"] = primary_top1_score
                diagnostic["primary_avg_top_n_score"] = primary_avg_top_n_score
                diagnostic["quality_top1_threshold"] = quality_top1_threshold
                diagnostic["quality_avg_threshold"] = quality_avg_threshold
                diagnostic["recall_counts"] = {
                    "department_vector_count": department_vector_count,
                    "department_lexical_count": department_lexical_count,
                    "department_fused_count": department_fused_count,
                    "department_after_ocr": department_after_ocr_count,
                    "department_unique_docs_after_ocr": department_unique_doc_count,
                }
            return department_candidates, department_mode, department_branch_weights

        # --- Stage 2: supplemental route ---
        remaining_needed = max(required - department_effective_count, 0)
        if department_effective_count < required:
            supplemental_limit = min(limit, max(remaining_needed + required, 1))
        else:
            supplemental_limit = min(limit, max(required * 2, required, 1))

        global_candidates, global_mode, global_branch_weights = self._collect_scoped_candidates(
            query=query,
            query_vector=query_vector,
            profile=profile,
            limit=supplemental_limit,
            document_ids=scope.global_document_ids,
        )
        self._mark_candidates_source_scope(global_candidates, source_scope="global")
        supplemental_vector_count = sum(1 for c in global_candidates if c.vector_score is not None)
        supplemental_lexical_count = sum(1 for c in global_candidates if c.lexical_score is not None)
        supplemental_fused_count = len(global_candidates)

        logger.info(
            "staged_retrieval stage=supplemental department_effective=%d department_unique_docs=%d required=%d top1=%.4f avg_top_n=%.4f lexical_top1=%.4f supplemental_limit=%d supplemental_recall=%d",
            department_effective_count,
            department_unique_doc_count,
            required,
            primary_top1_score or 0.0,
            primary_avg_top_n_score or 0.0,
            primary_top1_lexical_score or 0.0,
            supplemental_limit,
            len(global_candidates),
        )

        if diagnostic is not None:
            trigger_basis = "department_insufficient" if department_effective_count < required else "department_low_quality"
            diagnostic["primary_threshold"] = required
            diagnostic["primary_effective_count"] = department_effective_count
            diagnostic["supplemental_triggered"] = True
            if trigger_basis == "department_insufficient":
                diagnostic["supplemental_reason"] = f"department_effective({department_effective_count})_below_threshold({required})"
            else:
                if low_quality_by_score and low_quality_by_lexical:
                    diagnostic["supplemental_reason"] = (
                        f"department_quality(top1={primary_top1_score:.4f},avg_top_n={primary_avg_top_n_score:.4f},"
                        f"lexical_top1={primary_top1_lexical_score:.4f})_below_thresholds("
                        f"{quality_top1_threshold:.2f},{quality_avg_threshold:.2f},{SUPPLEMENTAL_LOW_LEXICAL_SCORE_THRESHOLD:.2f})"
                    )
                elif low_quality_by_score:
                    diagnostic["supplemental_reason"] = (
                        f"department_quality(top1={primary_top1_score:.4f},avg_top_n={primary_avg_top_n_score:.4f})"
                        f"_below_thresholds({quality_top1_threshold:.2f},{quality_avg_threshold:.2f})"
                    )
                else:
                    diagnostic["supplemental_reason"] = (
                        f"department_lexical_top1({primary_top1_lexical_score:.4f})"
                        f"_below_threshold({SUPPLEMENTAL_LOW_LEXICAL_SCORE_THRESHOLD:.2f})"
                    )
            diagnostic["supplemental_trigger_basis"] = trigger_basis
            diagnostic["primary_top1_score"] = primary_top1_score
            diagnostic["primary_avg_top_n_score"] = primary_avg_top_n_score
            diagnostic["quality_top1_threshold"] = quality_top1_threshold
            diagnostic["quality_avg_threshold"] = quality_avg_threshold
            diagnostic["recall_counts"] = {
                "department_vector_count": department_vector_count,
                "department_lexical_count": department_lexical_count,
                "department_fused_count": department_fused_count,
                "department_after_ocr": department_after_ocr_count,
                "department_unique_docs_after_ocr": department_unique_doc_count,
                "supplemental_vector_count": supplemental_vector_count,
                "supplemental_lexical_count": supplemental_lexical_count,
                "supplemental_fused_count": supplemental_fused_count,
            }

        retrieval_mode = "hybrid" if "hybrid" in {department_mode, global_mode} else "qdrant"
        branch_weights = department_branch_weights or global_branch_weights
        fused_candidates = self._fuse_scope_candidates(
            department_candidates=department_candidates,
            global_candidates=global_candidates,
            limit=limit,
        )
        return fused_candidates, retrieval_mode, branch_weights

    @staticmethod
    def _required_primary_results(profile: QueryProfile, truncate_to_top_k: bool) -> int:
        """Calculate the minimum number of primary (department) results needed.

        When truncate_to_top_k=True (retrieval/search endpoint), use profile.top_k.
        When truncate_to_top_k=False (chat/SOP shared pipeline), use profile.rerank_top_n,
        because those callers need sufficient candidates for rerank/citation.
        """
        if truncate_to_top_k:
            return profile.top_k
        return profile.rerank_top_n

    def _get_supplemental_quality_thresholds(self) -> SupplementalQualityThresholdsConfig:
        try:
            controls = self.system_config_service.get_internal_retrieval_controls()
            return controls.supplemental_quality_thresholds
        except Exception:
            logger.warning(
                "failed to load internal retrieval quality thresholds from system config; using settings defaults",
                exc_info=True,
            )
            return SupplementalQualityThresholdsConfig(
                top1_threshold=self.settings.retrieval_quality_top1_threshold,
                avg_top_n_threshold=self.settings.retrieval_quality_avg_threshold,
                fine_query_top1_threshold=self.settings.retrieval_fine_query_quality_top1_threshold,
                fine_query_avg_top_n_threshold=self.settings.retrieval_fine_query_quality_avg_threshold,
            )

    def _summarize_primary_quality(
        self,
        candidates: list[_RetrievalCandidate],
        *,
        retrieval_mode: str,
        branch_weights: HybridBranchWeights | None,
        window_size: int,
    ) -> tuple[float | None, float | None]:
        if not candidates:
            return None, None

        normalized_scores = [
            self._response_score(
                float(candidate.score),
                retrieval_mode=retrieval_mode,
                branch_weights=branch_weights,
            )
            for candidate in candidates
        ]
        top1_score = normalized_scores[0]
        safe_window = max(1, min(window_size, len(normalized_scores)))
        avg_top_n_score = sum(normalized_scores[:safe_window]) / safe_window
        return top1_score, avg_top_n_score

    @staticmethod
    def _count_unique_documents(candidates: list[_RetrievalCandidate]) -> int:
        unique_document_ids: set[str] = set()
        for candidate in candidates:
            document_id = str(candidate.payload.get("document_id") or "").strip()
            unique_document_ids.add(document_id or candidate.candidate_id)
        return len(unique_document_ids)

    @staticmethod
    def _top_candidate_lexical_score(candidates: list[_RetrievalCandidate]) -> float | None:
        if not candidates:
            return None
        lexical_score = candidates[0].lexical_score
        if lexical_score is None:
            return None
        return float(lexical_score)

    def _apply_ocr_quality_governance(
        self,
        candidates: list[_RetrievalCandidate],
    ) -> tuple[list[_RetrievalCandidate], list[_RetrievalCandidate]]:
        """Filter low-quality OCR candidates.

        OCR 质量治理：过滤低质量 OCR 识别候选，防止噪声进入下游生成链路。
        若过滤后结果为空则保留原始候选，避免检索结果被完全打空。

        输入：候选列表。
        输出：(过滤后的候选列表, 被过滤的候选列表) 二元组。
        """
        if not self.settings.ocr_low_quality_filter_enabled or not candidates:
            return candidates, []

        kept_candidates: list[_RetrievalCandidate] = []
        filtered_candidates: list[_RetrievalCandidate] = []
        for candidate in candidates:
            if self._is_low_quality_ocr_candidate(candidate):
                filtered_candidates.append(candidate)
                continue
            kept_candidates.append(candidate)

        if not filtered_candidates:
            return candidates, []
        if not kept_candidates:  # 不让 OCR 质量治理把结果完全打空；极端情况下保留原始候选供后续链路继续工作。
            logger.info(
                "ocr quality governance skipped reason=all_candidates_low_quality filtered_count=%d threshold=%.3f",
                len(filtered_candidates),
                self.settings.ocr_low_quality_min_score,
            )
            return candidates, []

        logger.info(
            "ocr quality governance filtered_count=%d kept_count=%d threshold=%.3f",
            len(filtered_candidates),
            len(kept_candidates),
            self.settings.ocr_low_quality_min_score,
        )
        return kept_candidates, filtered_candidates

    def _is_low_quality_ocr_candidate(self, candidate: _RetrievalCandidate) -> bool:
        payload = candidate.payload
        if not bool(payload.get("ocr_used") or False):
            return False
        quality_score = payload.get("quality_score")
        if quality_score is None:
            return False
        try:
            normalized_quality = float(quality_score)
        except (TypeError, ValueError):
            return False
        return normalized_quality < self.settings.ocr_low_quality_min_score

    def _fuse_candidates(
        self,
        vector_candidates: list[_RetrievalCandidate],
        lexical_matches: list[LexicalMatch],
        *,
        limit: int,
        branch_weights: HybridBranchWeights | None = None,
    ) -> list[_RetrievalCandidate]:
        """RRF 混合融合：将向量候选与词法候选按加权 Reciprocal Rank Fusion 合并排序。

        功能：对向量候选和词法候选分别按排名计算 RRF 分数，同一 chunk 取最高分，最终按融合分数降序排列。
        输入：向量候选列表、词法匹配列表、召回上限、可选分支权重。
        输出：融合后按分数排序的候选列表（截断到 limit）。
        """
        fused_candidates: dict[str, _RetrievalCandidate] = {}
        rrf_k = self.settings.retrieval_hybrid_rrf_k
        weights = branch_weights or self.query_router.fixed_branch_weights()

        # 遍历向量候选，按排名计算加权 RRF 分数并累积到融合字典
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

        # 遍历词法候选，按排名计算加权 RRF 分数；已有 chunk 则累加分数并更新 payload
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

    def _fuse_scope_candidates(
        self,
        *,
        department_candidates: list[_RetrievalCandidate],
        global_candidates: list[_RetrievalCandidate],
        limit: int,
    ) -> list[_RetrievalCandidate]:
        """部门优先候选融合：将部门候选与全局候选按去重+优先部门命中规则合并排序。

        功能：合并部门候选和全局候选，同一 chunk 取最高分并标记来源范围；
              排序时部门命中优先，分数次之，最终截断到 limit。
        输入：部门候选列表、全局候选列表、召回上限。
        输出：按部门优先+分数排序的候选列表（截断到 limit）。
        """
        if limit <= 0:
            return []

        fused_candidates: dict[str, _RetrievalCandidate] = {}
        for candidate in [*department_candidates, *global_candidates]:
            fused = fused_candidates.get(candidate.candidate_id)
            if fused is None:
                fused_candidates[candidate.candidate_id] = _RetrievalCandidate(
                    candidate_id=candidate.candidate_id,
                    payload=dict(candidate.payload),
                    score=candidate.score,
                    vector_score=candidate.vector_score,
                    lexical_score=candidate.lexical_score,
                    source_scope=candidate.source_scope,
                    department_hit=candidate.department_hit,
                    global_hit=candidate.global_hit,
                )
                continue

            if candidate.score > fused.score:
                fused.payload = dict(candidate.payload)
                fused.score = candidate.score
            fused.vector_score = self._max_optional_score(fused.vector_score, candidate.vector_score)
            fused.lexical_score = self._max_optional_score(fused.lexical_score, candidate.lexical_score)
            fused.department_hit = fused.department_hit or candidate.department_hit
            fused.global_hit = fused.global_hit or candidate.global_hit
            fused.source_scope = self._resolve_source_scope(fused)

        ranked_candidates = sorted(
            fused_candidates.values(),
            key=lambda item: (
                int(item.department_hit),
                item.score,
                int(item.department_hit and item.global_hit),
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

    @staticmethod
    def _mark_candidates_source_scope(candidates: list[_RetrievalCandidate], *, source_scope: str) -> None:
        for candidate in candidates:
            candidate.source_scope = source_scope
            if source_scope == "department":
                candidate.department_hit = True
            elif source_scope == "global":
                candidate.global_hit = True

    @staticmethod
    def _resolve_source_scope(candidate: _RetrievalCandidate) -> str | None:
        if candidate.department_hit and candidate.global_hit:
            return "both"
        if candidate.department_hit:
            return "department"
        if candidate.global_hit:
            return "global"
        return candidate.source_scope

    @staticmethod
    def _max_optional_score(left: float | None, right: float | None) -> float | None:
        if left is None:
            return right
        if right is None:
            return left
        return max(left, right)

    @staticmethod
    def _should_use_department_priority_routes(
        *,
        auth_context: AuthContext | None,
        document_id: str | None,
    ) -> bool:
        if document_id is not None:
            return False
        if auth_context is None:
            return False
        return auth_context.role.data_scope != "global"

    def _search_vector_points(
        self,
        *,
        query_vector: list[float],
        limit: int,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[object]:
        search_kwargs: dict[str, object] = {"limit": limit}
        if document_id is not None:
            search_kwargs["document_id"] = document_id
        if document_ids is not None:
            search_kwargs["document_ids"] = document_ids
        return self.vector_store.search(query_vector, **search_kwargs)

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
        """将内部 RRF 原始分数归一化为 [0,1] 区间的对外相关度分数。

        功能：纯向量模式直接返回原始分；hybrid 模式下以理论最大 RRF 分数为基准做归一化，
              避免对外暴露量级极低的 RRF 原始值。
        输入：原始分数、检索模式、分支权重。
        输出：归一化后的 [0,1] 分数（纯向量模式为原始分）。
        """
        if retrieval_mode != "hybrid" or branch_weights is None:
            return raw_score

        total_weight = max(branch_weights.vector_weight, 0.0) + max(branch_weights.lexical_weight, 0.0)
        if total_weight <= 0:
            return raw_score

        # 计算理论最大 RRF 分数（权重 / (rrf_k + rank_1)），用于将原始分归一化到 [0,1]
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
        """根据 rerank 对比结果，判断是否建议将默认策略从 heuristic 切换到 provider。

        功能：综合路由状态、provider 候选可用性和与 heuristic 的重合度，输出灰度切换建议。
        输入：路由状态、provider 名称、provider 候选对比结果、重合摘要、rerank top_n。
        输出：RerankPromotionRecommendation，包含决策、是否建议切换和说明信息。
        """
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
