"""Citation pipeline 组件。

从 ChatService 中拆出的 retrieval + rerank + citation 构建职责。
执行检索、重排序，并组装成 CitationBuildResult 供 chat 主流程使用。
"""

from dataclasses import dataclass, field
from time import perf_counter

from ..core.config import Settings, get_settings
from ..rag.rerankers.client import RerankerClient
from ..schemas.auth import AuthContext
from ..schemas.chat import (
    ChatRequest,
    Citation,
)
from ..schemas.query_profile import QueryProfile
from ..schemas.request_trace import RequestTraceStage, RequestTraceStageName, RequestTraceStageStatus
from ..schemas.retrieval import RetrievalRequest
from .query_profile_service import QueryProfileService
from .retrieval_service import RetrievalService
from .system_config_service import SystemConfigService


@dataclass(frozen=True)
class CitationBuildResult:
    citations: list[Citation]
    rerank_strategy: str
    retrieved_count: int
    reranked_count: int
    details: dict[str, object] = field(default_factory=dict)


class ChatCitationPipeline:
    """封装 retrieval → rerank → citation 构建链路。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retrieval_service: RetrievalService | None = None,
        reranker_client: RerankerClient | None = None,
        query_profile_service: QueryProfileService | None = None,
        system_config_service: SystemConfigService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.system_config_service = system_config_service or SystemConfigService(self.settings)
        self.retrieval_service = retrieval_service or RetrievalService(self.settings)
        self.reranker_client = reranker_client or RerankerClient(
            self.settings,
            system_config_service=self.system_config_service,
        )
        if query_profile_service is None:
            self.query_profile_service = QueryProfileService(
                self.settings,
                system_config_service=self.system_config_service,
            )
        else:
            self.query_profile_service = query_profile_service

    def build_citations(
        self,
        request: ChatRequest,
        profile: QueryProfile,
        *,
        query_text: str,
        auth_context: AuthContext | None = None,
        trace_stages: list[RequestTraceStage] | None = None,
    ) -> CitationBuildResult:
        """统一执行检索+重排并产出引用列表。"""
        retrieval_started_at = perf_counter()
        retrieval_mode = "qdrant"
        _retrieval_diagnostic: dict[str, object] = {}
        try:
            retrieval_results, retrieval_mode, _ = self.retrieval_service.search_candidates(
                RetrievalRequest(
                    query=query_text,
                    top_k=profile.top_k,
                    mode=profile.mode,
                    candidate_top_k=profile.candidate_top_k,
                    document_id=request.document_id,
                ),
                auth_context=auth_context,
                profile=profile,
                truncate_to_top_k=False,
                diagnostic=_retrieval_diagnostic,
            )
        except Exception as exc:
            if trace_stages is not None:
                _append_trace_stage(
                    trace_stages,
                    stage="retrieval",
                    status="failed",
                    duration_ms=_elapsed_ms(retrieval_started_at),
                    input_size=len(query_text),
                    output_size=0,
                    cache_hit=False,
                    details={"document_id": request.document_id, "error_message": str(exc), "query_length": len(query_text)},
                )
            raise
        retrieval_details = (
            self.retrieval_service.build_observability_details(query=query_text, retrieval_mode=retrieval_mode)
            if hasattr(self.retrieval_service, "build_observability_details")
            else {"retrieval_mode": retrieval_mode}
        )
        if trace_stages is not None:
            _append_trace_stage(
                trace_stages,
                stage="retrieval",
                status="success",
                duration_ms=_elapsed_ms(retrieval_started_at),
                input_size=len(query_text),
                output_size=len(retrieval_results),
                cache_hit=False,
                details={
                    "document_id": request.document_id,
                    "query_length": len(query_text),
                    **retrieval_details,
                    **({"diagnostic": _retrieval_diagnostic} if _retrieval_diagnostic else {}),
                },
            )

        rerank_started_at = perf_counter()
        try:
            reranked_results, rerank_strategy = self.query_profile_service.rerank_with_fallback(
                query=query_text,
                candidates=retrieval_results,
                profile=profile,
                reranker_client=self.reranker_client,
                top_n=len(retrieval_results),
            )
        except Exception as exc:
            if trace_stages is not None:
                _append_trace_stage(
                    trace_stages,
                    stage="rerank",
                    status="failed",
                    duration_ms=_elapsed_ms(rerank_started_at),
                    input_size=len(retrieval_results),
                    output_size=0,
                    cache_hit=False,
                    details={"error_message": str(exc)},
                )
            raise
        citations_source = reranked_results[: min(profile.rerank_top_n, len(reranked_results))]
        rerank_log_fields = self.build_rerank_log_fields(rerank_strategy)
        if trace_stages is not None:
            _append_trace_stage(
                trace_stages,
                stage="rerank",
                status=_trace_status_for_rerank_strategy(rerank_strategy),
                duration_ms=_elapsed_ms(rerank_started_at),
                input_size=len(retrieval_results),
                output_size=len(citations_source),
                cache_hit=False,
                details={
                    "strategy": rerank_strategy,
                    "rerank_provider": rerank_log_fields["rerank_provider"],
                    "rerank_model": rerank_log_fields["rerank_model"],
                    "rerank_default_strategy": rerank_log_fields["rerank_default_strategy"],
                    "rerank_effective_strategy": rerank_log_fields["rerank_effective_strategy"],
                    "rerank_input_count": len(retrieval_results),
                    "rerank_output_count": len(reranked_results),
                    "citation_count": len(citations_source),
                },
            )

        return CitationBuildResult(
            citations=[
                Citation(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    document_name=result.document_name,
                    snippet=result.text,
                    score=result.score,
                    source_path=result.source_path,
                    retrieval_strategy=result.retrieval_strategy,
                    source_scope=result.source_scope,
                    vector_score=result.vector_score,
                    lexical_score=result.lexical_score,
                    fused_score=result.fused_score,
                    ocr_used=result.ocr_used,
                    parser_name=result.parser_name,
                    page_no=result.page_no,
                    ocr_confidence=result.ocr_confidence,
                    quality_score=result.quality_score,
                )
                for result in citations_source
            ],
            rerank_strategy=rerank_strategy,
            retrieved_count=len(retrieval_results),
            reranked_count=len(citations_source),
            details={
                **retrieval_details,
                "rerank_provider": rerank_log_fields["rerank_provider"],
                "rerank_model": rerank_log_fields["rerank_model"],
                "rerank_default_strategy": rerank_log_fields["rerank_default_strategy"],
                "rerank_effective_strategy": rerank_log_fields["rerank_effective_strategy"],
                "retrieved_count": len(retrieval_results),
                "rerank_input_count": len(retrieval_results),
                "rerank_output_count": len(reranked_results),
                "citation_count": len(citations_source),
            },
        )

    def build_degraded_citations(
        self,
        request: ChatRequest,
        profile: QueryProfile,
        *,
        query_text: str,
        auth_context: AuthContext | None = None,
    ) -> CitationBuildResult | None:
        """降级档位下重新执行 citation 构建。"""
        fallback_profile = self.query_profile_service.build_fallback_profile(profile)
        if fallback_profile is None:
            return None
        return self.build_citations(request, fallback_profile, query_text=query_text, auth_context=auth_context)

    def build_rerank_log_fields(self, rerank_strategy: str) -> dict[str, str | None]:
        """构建 rerank 日志字段，供 telemetry recorder 复用。"""
        normalized = rerank_strategy.strip().lower()
        if not normalized or normalized == "skipped":
            return {
                "rerank_strategy": normalized or None,
                "rerank_provider": None,
                "rerank_model": None,
                "rerank_default_strategy": None,
                "rerank_effective_strategy": None,
            }
        if normalized in {"document_preview", "fallback_profile"}:
            return {
                "rerank_strategy": normalized,
                "rerank_provider": None,
                "rerank_model": None,
                "rerank_default_strategy": None,
                "rerank_effective_strategy": None,
            }
        if not hasattr(self.reranker_client, "get_runtime_status"):
            fallback_provider = "heuristic" if normalized == "heuristic" else "provider"
            fallback_model = "heuristic" if normalized == "heuristic" else None
            return {
                "rerank_strategy": normalized,
                "rerank_provider": fallback_provider,
                "rerank_model": fallback_model,
                "rerank_default_strategy": None,
                "rerank_effective_strategy": normalized,
            }
        status = self.reranker_client.get_runtime_status()
        rerank_provider = "heuristic" if normalized == "heuristic" else str(status["effective_provider"])
        rerank_model = "heuristic" if normalized == "heuristic" else str(status["effective_model"])
        return {
            "rerank_strategy": normalized,
            "rerank_provider": rerank_provider,
            "rerank_model": rerank_model,
            "rerank_default_strategy": str(status["default_strategy"]),
            "rerank_effective_strategy": str(status["effective_strategy"]),
        }


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _trace_status_for_rerank_strategy(rerank_strategy: str) -> RequestTraceStageStatus:
    if rerank_strategy == "provider":
        return "success"
    if rerank_strategy == "heuristic":
        return "degraded"
    return "skipped"


def _append_trace_stage(
    stages: list[RequestTraceStage],
    *,
    stage: RequestTraceStageName,
    status: RequestTraceStageStatus,
    duration_ms: int | None,
    input_size: int | None,
    output_size: int | None,
    cache_hit: bool | None = None,
    details: dict[str, object] | None = None,
) -> None:
    stages.append(
        RequestTraceStage(
            stage=stage,
            status=status,
            duration_ms=duration_ms,
            input_size=input_size,
            output_size=output_size,
            cache_hit=cache_hit,
            details=details or {},
        )
    )
