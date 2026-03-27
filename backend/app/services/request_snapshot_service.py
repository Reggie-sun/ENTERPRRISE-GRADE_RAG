from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException, status

from ..core.config import Settings, get_llm_base_url, get_settings
from ..db.request_snapshot_repository import FilesystemRequestSnapshotRepository, RequestSnapshotRepository
from ..schemas.auth import AuthContext
from ..schemas.chat import ChatRequest, ChatResponse, Citation
from ..schemas.event_log import EventLogActor
from ..schemas.query_profile import QueryProfile
from ..schemas.request_snapshot import (
    RequestSnapshotComponentVersions,
    RequestSnapshotContext,
    RequestSnapshotRequestPayload,
    RequestSnapshotListResponse,
    RequestSnapshotModelRoute,
    RequestSnapshotQueryFilters,
    RequestSnapshotRecord,
    RequestSnapshotReplayMode,
    RequestSnapshotReplayResponse,
    RequestSnapshotResult,
    RequestSnapshotRewrite,
)
from ..schemas.sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerateByScenarioRequest,
    SopGenerateByTopicRequest,
    SopGenerationCitation,
    SopGenerationDraftResponse,
    SopGenerationRequestMode,
)

if TYPE_CHECKING:
    from .chat_service import ChatService
    from .sop_generation_service import SopGenerationService


class RequestSnapshotService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: RequestSnapshotRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or FilesystemRequestSnapshotRepository(self.settings.request_snapshot_dir)

    def record_chat_snapshot(
        self,
        *,
        trace_id: str,
        request_id: str,
        action: str,
        outcome: str,
        request: ChatRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        citations: list[Citation],
        response_mode: str,
        rerank_strategy: str,
        model: str,
        answer_text: str | None = None,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        details: dict[str, object] | None = None,
        memory_summary: str | None = None,
        rewrite_status: str = "skipped",
        rewritten_question: str | None = None,
        prompt_version: str = "chat-rag-v1",
    ) -> RequestSnapshotRecord:
        safe_answer = (answer_text or "").strip()
        record = RequestSnapshotRecord(
            snapshot_id=self._new_snapshot_id(),
            trace_id=trace_id,
            request_id=request_id,
            category="chat",
            action=action,
            outcome="success" if outcome == "success" else "failed",
            occurred_at=datetime.now(timezone.utc),
            actor=self._build_actor(auth_context),
            target_type="document" if request.document_id else None,
            target_id=request.document_id,
            request=request.model_copy(deep=True),
            profile=profile.model_copy(deep=True),
            memory_summary=memory_summary,
            rewrite=RequestSnapshotRewrite(
                status=rewrite_status,
                original_question=request.question,
                rewritten_question=rewritten_question,
                details={"reason": "query rewrite is not enabled in the current V1 slice."} if rewrite_status == "skipped" else {},
            ),
            contexts=self._build_contexts(citations),
            citations=[citation.model_copy(deep=True) for citation in citations],
            model_route=RequestSnapshotModelRoute(
                provider=self.settings.llm_provider,
                base_url=None if self.settings.llm_provider == "mock" else get_llm_base_url(self.settings),
                model=model,
            ),
            component_versions=RequestSnapshotComponentVersions(
                prompt_version=prompt_version,
                embedding_provider=self.settings.embedding_provider,
                embedding_model=self.settings.embedding_model,
                reranker_provider=self.settings.reranker_provider,
                reranker_model=self.settings.reranker_model,
            ),
            result=RequestSnapshotResult(
                response_mode=response_mode,
                model=model,
                answer_preview=self._truncate_answer_preview(safe_answer),
                answer_chars=len(safe_answer),
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                downgraded_from=downgraded_from,
                timeout_flag=self._looks_like_timeout(error_message),
                error_message=error_message,
            ),
            details=dict(details or {}),
        )
        try:
            self.repository.append(record)
        except Exception:
            return record
        return record

    def record_sop_snapshot(
        self,
        *,
        request_mode: SopGenerationRequestMode,
        outcome: str,
        request: SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest,
        profile: QueryProfile,
        auth_context: AuthContext | None,
        citations: list[SopGenerationCitation],
        response: SopGenerationDraftResponse | None = None,
        rerank_strategy: str,
        model: str,
        content: str | None = None,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        details: dict[str, object] | None = None,
        rewrite_status: str = "skipped",
        rewritten_question: str | None = None,
        prompt_version: str = "sop-generation-v1",
    ) -> RequestSnapshotRecord:
        safe_content = (content or "").strip()
        trace_id = self._new_trace_id(prefix="sop")
        request_id = self._new_request_id(prefix="sop")
        record = RequestSnapshotRecord(
            snapshot_id=self._new_snapshot_id(),
            trace_id=trace_id,
            request_id=request_id,
            category="sop_generation",
            action=f"generate_{request_mode}",
            outcome="success" if outcome == "success" else "failed",
            occurred_at=datetime.now(timezone.utc),
            actor=self._build_actor(auth_context),
            target_type="document" if getattr(request, "document_id", None) else None,
            target_id=getattr(request, "document_id", None),
            request=request.model_copy(deep=True),
            profile=profile.model_copy(deep=True),
            memory_summary=None,
            rewrite=RequestSnapshotRewrite(
                status=rewrite_status,
                original_question=self._build_snapshot_prompt(request=request, request_mode=request_mode),
                rewritten_question=rewritten_question,
                details={"reason": "query rewrite is not enabled in the current V1 slice."} if rewrite_status == "skipped" else {},
            ),
            contexts=self._build_sop_contexts(citations),
            citations=self._build_sop_citation_records(citations),
            model_route=RequestSnapshotModelRoute(
                provider=self.settings.llm_provider,
                base_url=None if self.settings.llm_provider == "mock" else get_llm_base_url(self.settings),
                model=model,
            ),
            component_versions=RequestSnapshotComponentVersions(
                prompt_version=prompt_version,
                embedding_provider=self.settings.embedding_provider,
                embedding_model=self.settings.embedding_model,
                reranker_provider=self.settings.reranker_provider,
                reranker_model=self.settings.reranker_model,
            ),
            result=RequestSnapshotResult(
                response_mode=response.generation_mode if response is not None else "failed",
                model=model,
                answer_preview=self._truncate_answer_preview(response.content if response is not None else safe_content),
                answer_chars=len(response.content if response is not None else safe_content),
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                downgraded_from=downgraded_from,
                timeout_flag=self._looks_like_timeout(error_message),
                error_message=error_message,
            ),
            details=dict(details or {}),
        )
        try:
            self.repository.append(record)
        except Exception:
            return record
        return record

    def list_recent(
        self,
        *,
        auth_context: AuthContext,
        limit: int = 20,
    ) -> list[RequestSnapshotRecord]:
        records = self.repository.list_records(limit=limit)
        return self._filter_records_by_scope(records=records, auth_context=auth_context)

    def list_snapshots(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: RequestSnapshotQueryFilters | None = None,
        auth_context: AuthContext,
    ) -> RequestSnapshotListResponse:
        resolved_filters = filters or RequestSnapshotQueryFilters()
        self._validate_snapshot_access(auth_context=auth_context, department_id=resolved_filters.department_id)
        if (
            resolved_filters.date_from is not None
            and resolved_filters.date_to is not None
            and resolved_filters.date_to < resolved_filters.date_from
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_to must be greater than or equal to date_from.",
            )
        records = self.repository.list_records(
            category=resolved_filters.category,
            action=resolved_filters.action,
            outcome=resolved_filters.outcome,
            username=resolved_filters.username,
            user_id=resolved_filters.user_id,
            department_id=resolved_filters.department_id,
            trace_id=resolved_filters.trace_id,
            request_id=resolved_filters.request_id,
            snapshot_id=resolved_filters.snapshot_id,
            target_id=resolved_filters.target_id,
            date_from=resolved_filters.date_from,
            date_to=resolved_filters.date_to,
            limit=None,
        )
        scoped_records = self._filter_records_by_scope(records=records, auth_context=auth_context)
        start = (page - 1) * page_size
        end = start + page_size
        return RequestSnapshotListResponse(
            items=scoped_records[start:end],
            total=len(scoped_records),
            page=page,
            page_size=page_size,
        )

    def get_snapshot(self, snapshot_id: str, *, auth_context: AuthContext) -> RequestSnapshotRecord:
        self._validate_snapshot_access(auth_context=auth_context, department_id=None)
        record = self.repository.get(snapshot_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested snapshot was not found.",
            )
        self._ensure_record_access(record=record, auth_context=auth_context)
        return record

    def replay_snapshot(
        self,
        *,
        snapshot_id: str,
        replay_mode: RequestSnapshotReplayMode,
        auth_context: AuthContext,
        chat_service: ChatService,
        sop_generation_service: SopGenerationService,
    ) -> RequestSnapshotReplayResponse:
        record = self.get_snapshot(snapshot_id, auth_context=auth_context)
        replay_request = record.request.model_copy(deep=True)
        if hasattr(replay_request, "mode") and hasattr(replay_request, "top_k"):
            if replay_mode == "original":
                replay_request.mode = record.profile.mode
                replay_request.top_k = record.profile.top_k
            else:
                replay_request.mode = None
                replay_request.top_k = None
        response = self._dispatch_replay(
            record=record,
            replay_request=replay_request,
            auth_context=auth_context,
            chat_service=chat_service,
            sop_generation_service=sop_generation_service,
        )
        return RequestSnapshotReplayResponse(
            snapshot_id=record.snapshot_id,
            replay_mode=replay_mode,
            original_trace_id=record.trace_id,
            original_request_id=record.request_id,
            replayed_request=replay_request,
            response=response,
        )

    @staticmethod
    def _build_actor(auth_context: AuthContext | None) -> EventLogActor:
        user = getattr(auth_context, "user", None)
        if auth_context is None or user is None:
            return EventLogActor()
        return EventLogActor(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            username=user.username,
            role_id=user.role_id,
            department_id=user.department_id,
        )

    @staticmethod
    def _build_contexts(citations: list[Citation]) -> list[RequestSnapshotContext]:
        return [
            RequestSnapshotContext(
                rank=index,
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                document_name=citation.document_name,
                snippet=citation.snippet,
                score=citation.score,
                source_path=citation.source_path,
            )
            for index, citation in enumerate(citations, start=1)
        ]

    @staticmethod
    def _build_sop_contexts(citations: list[SopGenerationCitation]) -> list[RequestSnapshotContext]:
        return [
            RequestSnapshotContext(
                rank=index,
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                document_name=citation.document_name,
                snippet=citation.snippet,
                score=citation.score,
                source_path=citation.source_path,
            )
            for index, citation in enumerate(citations, start=1)
        ]

    @staticmethod
    def _build_sop_citation_records(citations: list[SopGenerationCitation]) -> list[Citation]:
        return [
            Citation(
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                document_name=citation.document_name,
                snippet=citation.snippet,
                score=citation.score,
                source_path=citation.source_path,
            )
            for citation in citations
        ]

    @staticmethod
    def _truncate_answer_preview(answer_text: str, *, max_chars: int = 300) -> str | None:
        if not answer_text:
            return None
        if len(answer_text) <= max_chars:
            return answer_text
        return f"{answer_text[: max_chars - 3]}..."

    @staticmethod
    def _looks_like_timeout(error_message: str | None) -> bool:
        if not error_message:
            return False
        lowered = error_message.lower()
        return "timed out" in lowered or "timeout" in lowered

    @staticmethod
    def _new_snapshot_id() -> str:
        return f"rsp_{uuid4().hex[:16]}"

    @staticmethod
    def _new_trace_id(*, prefix: str) -> str:
        return f"trc_{prefix}_{uuid4().hex[:16]}"

    @staticmethod
    def _new_request_id(*, prefix: str) -> str:
        return f"req_{prefix}_{uuid4().hex[:16]}"

    @staticmethod
    def _build_snapshot_prompt(
        *,
        request: SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest,
        request_mode: SopGenerationRequestMode,
    ) -> str:
        if request_mode == "document":
            return f"根据文档 {request.document_id} 生成 SOP 草稿"
        if request_mode == "scenario":
            process_name = request.process_name or "未指定工序"
            return f"按场景生成 SOP：{process_name} / {request.scenario_name}"
        scenario_name = request.scenario_name or "未指定场景"
        process_name = request.process_name or "未指定工序"
        return f"按主题生成 SOP：{request.topic} / {process_name} / {scenario_name}"

    @staticmethod
    def _dispatch_replay(
        *,
        record: RequestSnapshotRecord,
        replay_request: RequestSnapshotRequestPayload,
        auth_context: AuthContext,
        chat_service: ChatService,
        sop_generation_service: SopGenerationService,
    ) -> ChatResponse | SopGenerationDraftResponse:
        if record.category == "chat":
            if not isinstance(replay_request, ChatRequest):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Snapshot payload does not match chat replay requirements.",
                )
            return chat_service.answer(replay_request, auth_context=auth_context)

        if record.category == "sop_generation":
            if isinstance(replay_request, SopGenerateByDocumentRequest):
                return sop_generation_service.generate_from_document(replay_request, auth_context=auth_context)
            if isinstance(replay_request, SopGenerateByScenarioRequest):
                return sop_generation_service.generate_from_scenario(replay_request, auth_context=auth_context)
            if isinstance(replay_request, SopGenerateByTopicRequest):
                return sop_generation_service.generate_from_topic(replay_request, auth_context=auth_context)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Snapshot payload does not match SOP replay requirements.",
            )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Replay is not supported for snapshot category '{record.category}'.",
        )

    @staticmethod
    def _validate_snapshot_access(*, auth_context: AuthContext, department_id: str | None) -> None:
        if auth_context.user.role_id == "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to request snapshots.",
            )
        if department_id is not None and department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested department.",
            )

    def _ensure_record_access(self, *, record: RequestSnapshotRecord, auth_context: AuthContext) -> None:
        if auth_context.role.data_scope == "global":
            return
        if record.actor.department_id not in set(auth_context.accessible_department_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested snapshot.",
            )

    def _filter_records_by_scope(
        self,
        *,
        records: list[RequestSnapshotRecord],
        auth_context: AuthContext,
    ) -> list[RequestSnapshotRecord]:
        if auth_context.role.data_scope == "global":
            return records
        allowed_departments = set(auth_context.accessible_department_ids)
        return [record for record in records if record.actor.department_id in allowed_departments]


@lru_cache
def get_request_snapshot_service() -> RequestSnapshotService:
    return RequestSnapshotService()
