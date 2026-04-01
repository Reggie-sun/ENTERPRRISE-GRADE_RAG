"""Chat telemetry recorder 组件。

从 ChatService 中拆出的遥测职责：事件日志、请求追踪、请求快照、记忆轮次。
"""

from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.chat import (
    ChatRequest,
    Citation,
)
from ..schemas.query_profile import QueryProfile
from ..schemas.query_rewrite import QueryRewriteResult
from ..schemas.request_trace import RequestTraceStage
from .chat_memory_service import ChatMemoryService, get_chat_memory_service
from .event_log_service import EventLogService, get_event_log_service
from .request_snapshot_service import RequestSnapshotService
from .request_trace_service import RequestTraceService
from .chat_citation_pipeline import ChatCitationPipeline


class ChatTelemetryRecorder:
    """封装 chat 遥测记录：event log、request trace、request snapshot、memory turn。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        event_log_service: EventLogService | None = None,
        request_trace_service: RequestTraceService | None = None,
        request_snapshot_service: RequestSnapshotService | None = None,
        chat_memory_service: ChatMemoryService | None = None,
        citation_pipeline: ChatCitationPipeline | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.event_log_service = event_log_service or get_event_log_service()
        self.request_trace_service = request_trace_service or RequestTraceService(self.settings)
        self.request_snapshot_service = request_snapshot_service or RequestSnapshotService(self.settings)
        self.chat_memory_service = chat_memory_service or (
            ChatMemoryService(self.settings) if settings is not None else get_chat_memory_service()
        )
        self.citation_pipeline = citation_pipeline or ChatCitationPipeline(self.settings)

    def record_chat_event(
        self,
        *,
        action: str,
        outcome: str,
        request: ChatRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        response_mode: str,
        citation_count: int,
        rerank_strategy: str,
        duration_ms: int,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        details: dict[str, object] | None = None,
        memory_summary: str | None = None,
        rewrite_result: QueryRewriteResult | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        rerank_log_fields = self.citation_pipeline.build_rerank_log_fields(rerank_strategy)
        payload = {
            "question_length": len(request.question),
            "document_id": request.document_id,
            "response_mode": response_mode,
            "citation_count": citation_count,
            "rerank_strategy": rerank_strategy,
            "rerank_provider": rerank_log_fields["rerank_provider"],
            "rerank_model": rerank_log_fields["rerank_model"],
            "rerank_default_strategy": rerank_log_fields["rerank_default_strategy"],
            "rerank_effective_strategy": rerank_log_fields["rerank_effective_strategy"],
            "memory_turns_used": _memory_turn_count(memory_summary),
        }
        if memory_summary:
            payload["memory_summary"] = memory_summary
        if rewrite_result is not None:
            payload["rewrite_status"] = rewrite_result.status
            if rewrite_result.rewritten_question:
                payload["rewritten_question"] = rewrite_result.rewritten_question
            if rewrite_result.details:
                payload["rewrite_details"] = rewrite_result.details
        if trace_id:
            payload["trace_id"] = trace_id
        if request_id:
            payload["request_id"] = request_id
        if error_message:
            payload["error_message"] = error_message
        if details:
            payload.update(details)
        self.event_log_service.record(
            category="chat",
            action=action,
            outcome="success" if outcome == "success" else "failed",
            auth_context=auth_context,
            target_type="document" if request.document_id else None,
            target_id=request.document_id,
            mode=profile.mode,
            top_k=profile.top_k,
            candidate_top_k=profile.candidate_top_k,
            rerank_top_n=profile.rerank_top_n,
            rerank_strategy=rerank_log_fields["rerank_strategy"],
            rerank_provider=rerank_log_fields["rerank_provider"],
            rerank_model=rerank_log_fields["rerank_model"],
            duration_ms=duration_ms,
            downgraded_from=downgraded_from,
            details=payload,
        )

    def record_chat_trace(
        self,
        *,
        action: str,
        request: ChatRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        trace_id: str,
        request_id: str,
        stages: list[RequestTraceStage],
        outcome: str,
        response_mode: str,
        citation_count: int,
        rerank_strategy: str,
        duration_ms: int,
        model: str,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        details: dict[str, object] | None = None,
        rewrite_result: QueryRewriteResult | None = None,
    ) -> None:
        payload = {
            "question_length": len(request.question),
            "citation_count": citation_count,
            "rerank_strategy": rerank_strategy,
            "model": model,
        }
        if rewrite_result is not None:
            payload["rewrite_status"] = rewrite_result.status
            if rewrite_result.rewritten_question:
                payload["rewritten_question"] = rewrite_result.rewritten_question
            if rewrite_result.details:
                payload["rewrite_details"] = rewrite_result.details
        if details:
            payload.update(details)
        self.request_trace_service.record(
            trace_id=trace_id,
            request_id=request_id,
            category="chat",
            action=action,
            outcome="success" if outcome == "success" else "failed",
            auth_context=auth_context,
            target_type="document" if request.document_id else None,
            target_id=request.document_id,
            mode=profile.mode,
            top_k=profile.top_k,
            candidate_top_k=profile.candidate_top_k,
            rerank_top_n=profile.rerank_top_n,
            total_duration_ms=duration_ms,
            timeout_flag=_looks_like_timeout(error_message),
            downgraded_from=downgraded_from,
            response_mode=response_mode,
            error_message=error_message,
            stages=stages,
            details=payload,
        )

    def record_chat_snapshot(
        self,
        *,
        action: str,
        request: ChatRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        trace_id: str,
        request_id: str,
        outcome: str,
        response_mode: str,
        citations: list[Citation],
        rerank_strategy: str,
        model: str,
        answer_text: str | None,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        details: dict[str, object] | None = None,
        memory_summary: str | None = None,
        rewrite_result: QueryRewriteResult | None = None,
    ) -> None:
        self.request_snapshot_service.record_chat_snapshot(
            trace_id=trace_id,
            request_id=request_id,
            action=action,
            outcome=outcome,
            request=request,
            profile=profile,
            auth_context=auth_context,
            citations=citations,
            response_mode=response_mode,
            rerank_strategy=rerank_strategy,
            model=model,
            answer_text=answer_text,
            downgraded_from=downgraded_from,
            error_message=error_message,
            details=details,
            memory_summary=memory_summary,
            rewrite_status=(rewrite_result.status if rewrite_result is not None else "skipped"),
            rewritten_question=(rewrite_result.rewritten_question if rewrite_result is not None else None),
        )

    def record_memory_turn(
        self,
        *,
        request: ChatRequest,
        auth_context: AuthContext | None,
        answer_text: str,
        response_mode: str,
        citation_count: int,
        error_message: str | None,
    ) -> None:
        if error_message:
            return
        if response_mode == "no_context":
            return
        self.chat_memory_service.record_turn(
            session_id=request.session_id,
            auth_context=auth_context,
            document_id=request.document_id,
            question=request.question,
            answer=answer_text,
            response_mode=response_mode,
            citation_count=citation_count,
        )


def _memory_turn_count(memory_summary: str | None) -> int:
    if not memory_summary:
        return 0
    return memory_summary.count("[Recent Turn ")


def _looks_like_timeout(error_message: str | None) -> bool:
    if not error_message:
        return False
    lowered = error_message.lower()
    return "timed out" in lowered or "timeout" in lowered
