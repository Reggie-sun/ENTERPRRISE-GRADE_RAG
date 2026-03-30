import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..rag.generators.client import (
    LLMGenerationClient,
    LLMGenerationRetryableError,
)
from ..rag.rerankers.client import RerankerClient
from ..schemas.auth import AuthContext, DepartmentRecord
from ..schemas.query_profile import QueryMode, QueryProfile
from ..schemas.retrieval import RetrievalRequest, RetrievedChunk
from ..schemas.request_snapshot import RequestSnapshotRecord
from ..schemas.sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerateByScenarioRequest,
    SopGenerateByTopicRequest,
    SopGenerationCitation,
    SopGenerationDraftResponse,
    SopGenerationRequestMode,
)
from .document_service import DocumentService, get_document_service
from .event_log_service import EventLogService, get_event_log_service
from .identity_service import IdentityService, get_identity_service
from .query_profile_service import QueryProfileService
from .request_snapshot_service import RequestSnapshotService, get_request_snapshot_service
from .retrieval_service import RetrievalService, get_retrieval_service
from .runtime_gate_service import RuntimeGateBusyError, RuntimeGateLease, RuntimeGateService, get_runtime_gate_service
from .system_config_service import SystemConfigService


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True)
class SopCitationBuildResult:
    citations: list[SopGenerationCitation]
    rerank_strategy: str
    details: dict[str, object] = field(default_factory=dict)


class SopGenerationService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        identity_service: IdentityService | None = None,
        retrieval_service: RetrievalService | None = None,
        document_service: DocumentService | None = None,
        reranker_client: RerankerClient | None = None,
        generation_client: LLMGenerationClient | None = None,
        query_profile_service: QueryProfileService | None = None,
        event_log_service: EventLogService | None = None,
        request_snapshot_service: RequestSnapshotService | None = None,
        runtime_gate_service: RuntimeGateService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if query_profile_service is None:
            self.system_config_service = SystemConfigService(self.settings)
            self.query_profile_service = QueryProfileService(
                self.settings,
                system_config_service=self.system_config_service,
            )
        else:
            self.query_profile_service = query_profile_service
            self.system_config_service = query_profile_service.system_config_service
        self.identity_service = identity_service or get_identity_service()
        self.retrieval_service = retrieval_service or get_retrieval_service()
        self.document_service = document_service or get_document_service()
        self.reranker_client = reranker_client or RerankerClient(
            self.settings,
            system_config_service=self.system_config_service,
        )
        self.generation_client = generation_client or LLMGenerationClient(
            self.settings,
            system_config_service=self.system_config_service,
        )
        self.event_log_service = event_log_service or get_event_log_service()
        self.request_snapshot_service = request_snapshot_service or get_request_snapshot_service()
        self.runtime_gate_service = runtime_gate_service or (
            RuntimeGateService(self.settings, system_config_service=self.system_config_service)
            if settings is not None
            else get_runtime_gate_service()
        )

    def generate_from_scenario(
        self,
        request: SopGenerateByScenarioRequest,
        *,
        auth_context: AuthContext,
    ) -> SopGenerationDraftResponse:
        department = self._resolve_generation_department(auth_context, request.department_id)
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = request.scenario_name.strip()
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        search_query = self._build_search_query(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
        )
        instruction = self._build_generation_instruction(
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
        )
        return self._generate_draft(
            request_mode="scenario",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=request.document_id,
            auth_context=auth_context,
        )

    def generate_from_topic(
        self,
        request: SopGenerateByTopicRequest,
        *,
        auth_context: AuthContext,
    ) -> SopGenerationDraftResponse:
        department = self._resolve_generation_department(auth_context, request.department_id)
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = _normalize_optional_str(request.scenario_name)
        normalized_topic = request.topic.strip()
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        search_query = self._build_search_query(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        instruction = self._build_generation_instruction(
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        return self._generate_draft(
            request_mode="topic",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=request.document_id,
            auth_context=auth_context,
        )

    def generate_from_document(
        self,
        request: SopGenerateByDocumentRequest,
        *,
        auth_context: AuthContext,
    ) -> SopGenerationDraftResponse:
        document_detail = self.document_service.get_document(request.document_id, auth_context=auth_context)
        document_department_id = _normalize_optional_str(document_detail.department_id)
        requested_department_id = _normalize_optional_str(request.department_id)
        if requested_department_id and document_department_id and requested_department_id != document_department_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="department_id does not match the selected document department.",
            )

        department = self._resolve_generation_department(
            auth_context,
            document_department_id or requested_department_id or auth_context.department.department_id,
        )
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = _normalize_optional_str(request.scenario_name)
        document_label = self._build_document_label(document_detail.file_name)
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=document_label,
        )
        search_query = self._build_document_search_query(
            department=department,
            document_name=document_detail.file_name,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        instruction = self._build_document_generation_instruction(
            title=title,
            department=department,
            document_name=document_detail.file_name,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        return self._generate_draft(
            request_mode="document",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=document_label,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=document_detail.doc_id,
            auth_context=auth_context,
        )

    def stream_generate_from_scenario_sse(
        self,
        request: SopGenerateByScenarioRequest,
        *,
        auth_context: AuthContext,
    ) -> Iterator[str]:
        department = self._resolve_generation_department(auth_context, request.department_id)
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = request.scenario_name.strip()
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        search_query = self._build_search_query(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
        )
        instruction = self._build_generation_instruction(
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
        )
        yield from self._stream_draft_sse(
            request_mode="scenario",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=None,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=request.document_id,
            auth_context=auth_context,
        )

    def stream_generate_from_topic_sse(
        self,
        request: SopGenerateByTopicRequest,
        *,
        auth_context: AuthContext,
    ) -> Iterator[str]:
        department = self._resolve_generation_department(auth_context, request.department_id)
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = _normalize_optional_str(request.scenario_name)
        normalized_topic = request.topic.strip()
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        search_query = self._build_search_query(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        instruction = self._build_generation_instruction(
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
        )
        yield from self._stream_draft_sse(
            request_mode="topic",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=normalized_topic,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=request.document_id,
            auth_context=auth_context,
        )

    def stream_generate_from_document_sse(
        self,
        request: SopGenerateByDocumentRequest,
        *,
        auth_context: AuthContext,
    ) -> Iterator[str]:
        document_detail = self.document_service.get_document(request.document_id, auth_context=auth_context)
        document_department_id = _normalize_optional_str(document_detail.department_id)
        requested_department_id = _normalize_optional_str(request.department_id)
        if requested_department_id and document_department_id and requested_department_id != document_department_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="department_id does not match the selected document department.",
            )

        department = self._resolve_generation_department(
            auth_context,
            document_department_id or requested_department_id or auth_context.department.department_id,
        )
        normalized_process_name = _normalize_optional_str(request.process_name)
        normalized_scenario_name = _normalize_optional_str(request.scenario_name)
        document_label = self._build_document_label(document_detail.file_name)
        title = _normalize_optional_str(request.title_hint) or self._build_title(
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=document_label,
        )
        search_query = self._build_document_search_query(
            department=department,
            document_name=document_detail.file_name,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        instruction = self._build_document_generation_instruction(
            title=title,
            department=department,
            document_name=document_detail.file_name,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
        )
        yield from self._stream_draft_sse(
            request_mode="document",
            request_payload=request,
            title=title,
            department=department,
            process_name=normalized_process_name,
            scenario_name=normalized_scenario_name,
            topic=document_label,
            search_query=search_query,
            generation_instruction=instruction,
            requested_mode=request.mode,
            requested_top_k=request.top_k,
            document_id=document_detail.doc_id,
            auth_context=auth_context,
        )

    def _generate_draft(
        self,
        *,
        request_mode: SopGenerationRequestMode,
        request_payload: SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest,
        title: str,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
        search_query: str,
        generation_instruction: str,
        requested_mode: QueryMode | None,
        requested_top_k: int | None,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> SopGenerationDraftResponse:
        started_at = perf_counter()
        profile = self.query_profile_service.resolve(
            purpose="sop_generation",
            requested_mode=requested_mode,
            requested_top_k=requested_top_k,
        )
        rerank_strategy = "skipped"
        snapshot_record: RequestSnapshotRecord | None = None
        runtime_details: dict[str, object] = {}
        runtime_lease: RuntimeGateLease | None = None
        citation_details: dict[str, object] = {}
        try:
            runtime_lease, runtime_details = self._acquire_generation_runtime_slot(
                profile,
                auth_context=auth_context,
            )
            citation_result = self._build_citations(
                search_query=search_query,
                target_department_id=department.department_id,
                profile=profile,
                document_id=document_id,
                auth_context=auth_context,
            )
            citations = citation_result.citations
            citation_details = dict(citation_result.details)
            if citations:
                rerank_strategy = citation_result.rerank_strategy
            if not citations and request_mode == "document" and document_id is not None:
                citations = self._build_document_preview_citations(
                    document_id=document_id,
                    auth_context=auth_context,
                )
                if citations:
                    rerank_strategy = "document_preview"
                    citation_details = {
                        "retrieval_mode": "document_preview",
                        "retrieved_count": 0,
                        "rerank_input_count": 0,
                        "rerank_output_count": 0,
                        "citation_count": len(citations),
                    }
            if not citations:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No relevant evidence was retrieved for SOP generation.",
                )

            contexts = [item.snippet for item in citations]
            prepared_prompt = (
                self.generation_client.prepare_prompt(
                    question=generation_instruction,
                    contexts=contexts,
                )
                if hasattr(self.generation_client, "prepare_prompt")
                else None
            )
            downgraded_from: str | None = None
            response_model = self._response_model_name(profile=profile)
            try:
                generation_kwargs = dict(
                    question=generation_instruction,
                    contexts=contexts,
                    timeout_seconds=profile.timeout_budget_seconds,
                    model_name=response_model,
                )
                if prepared_prompt is not None:
                    generation_kwargs["prepared_prompt"] = prepared_prompt
                content = self._strip_markdown_code_fence(
                    self.generation_client.generate(**generation_kwargs)
                )
                generation_mode = "rag"
            except LLMGenerationRetryableError:
                degraded_citation_result = self._build_degraded_citations(
                    search_query=search_query,
                    target_department_id=department.department_id,
                    profile=profile,
                    document_id=document_id,
                    auth_context=auth_context,
                )
                degraded_citations = degraded_citation_result.citations
                if degraded_citations:
                    citations = degraded_citations
                    rerank_strategy = "fallback_profile"
                    downgraded_from = profile.mode
                    citation_details = dict(degraded_citation_result.details)
                if not self.system_config_service.get_degrade_controls().retrieval_fallback_enabled:
                    raise
                content = self._build_retrieval_fallback_draft(
                    title=title,
                    department=department,
                    process_name=process_name,
                    scenario_name=scenario_name,
                    topic=topic,
                    citations=citations,
                )
                generation_mode = "retrieval_fallback"

            response = SopGenerationDraftResponse(
                request_mode=request_mode,
                generation_mode=generation_mode,
                title=title,
                department_id=department.department_id,
                department_name=department.department_name,
                process_name=process_name,
                scenario_name=scenario_name,
                topic=topic,
                content=content,
                model=response_model,
                citations=citations,
            )
            self._record_generation_event(
                request_mode=request_mode,
                outcome="success",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode=response.generation_mode,
                citation_count=len(response.citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                extra_details={**citation_details, **runtime_details},
            )
            snapshot_record = self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="success",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=citations,
                response=response,
                rerank_strategy=rerank_strategy,
                model=response_model,
                content=response.content,
                downgraded_from=downgraded_from,
                details={
                    "title": title,
                    "generation_mode": response.generation_mode,
                    "citation_count": len(response.citations),
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    **citation_details,
                    **runtime_details,
                },
            )
            response.snapshot_id = snapshot_record.snapshot_id
            return response
        except RuntimeGateBusyError as exc:
            runtime_details = {
                **runtime_details,
                "runtime_channel": exc.channel,
                "busy_rejected": True,
                "busy_rejected_reason": exc.reason,
                "retry_after_seconds": exc.retry_after_seconds,
            }
            self._record_generation_event(
                request_mode=request_mode,
                outcome="failed",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode="failed",
                citation_count=0,
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                error_message=exc.detail,
                extra_details={**citation_details, **runtime_details},
            )
            self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="failed",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=[],
                response=None,
                rerank_strategy=rerank_strategy,
                model=self._response_model_name(profile=profile),
                content=None,
                error_message=exc.detail,
                details={
                    "title": title,
                    "generation_mode": "failed",
                    "citation_count": 0,
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    **citation_details,
                    **runtime_details,
                },
            )
            raise exc.to_http_exception()
        except Exception as exc:
            self._record_generation_event(
                request_mode=request_mode,
                outcome="failed",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode="failed",
                citation_count=0,
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                error_message=str(exc),
                extra_details={**citation_details, **runtime_details},
            )
            self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="failed",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=[],
                response=None,
                rerank_strategy=rerank_strategy,
                model=self._response_model_name(profile=profile),
                content=None,
                error_message=str(exc),
                details={
                    "title": title,
                    "generation_mode": "failed",
                    "citation_count": 0,
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    **citation_details,
                    **runtime_details,
                },
            )
            raise
        finally:
            if runtime_lease is not None:
                runtime_lease.release()

    def _stream_draft_sse(
        self,
        *,
        request_mode: SopGenerationRequestMode,
        request_payload: SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest,
        title: str,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
        search_query: str,
        generation_instruction: str,
        requested_mode: QueryMode | None,
        requested_top_k: int | None,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> Iterator[str]:
        started_at = perf_counter()
        profile = self.query_profile_service.resolve(
            purpose="sop_generation",
            requested_mode=requested_mode,
            requested_top_k=requested_top_k,
        )
        rerank_strategy = "skipped"
        runtime_details: dict[str, object] = {}
        runtime_lease: RuntimeGateLease | None = None
        citations: list[SopGenerationCitation] = []
        response_model = self._response_model_name(profile=profile)
        downgraded_from: str | None = None
        citation_details: dict[str, object] = {}

        try:
            runtime_lease, runtime_details = self._acquire_generation_runtime_slot(
                profile,
                auth_context=auth_context,
            )
            citation_result = self._build_citations(
                search_query=search_query,
                target_department_id=department.department_id,
                profile=profile,
                document_id=document_id,
                auth_context=auth_context,
            )
            citations = citation_result.citations
            citation_details = dict(citation_result.details)
            if citations:
                rerank_strategy = citation_result.rerank_strategy
            if not citations and request_mode == "document" and document_id is not None:
                citations = self._build_document_preview_citations(
                    document_id=document_id,
                    auth_context=auth_context,
                )
                if citations:
                    rerank_strategy = "document_preview"
                    citation_details = {
                        "retrieval_mode": "document_preview",
                        "retrieved_count": 0,
                        "rerank_input_count": 0,
                        "rerank_output_count": 0,
                        "citation_count": len(citations),
                    }
            if not citations:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No relevant evidence was retrieved for SOP generation.",
                )

            contexts = [item.snippet for item in citations]
            response_model = self._response_model_name(profile=profile)
            generation_mode = "rag"
            yield self._to_sse(
                "meta",
                self._build_stream_meta_payload(
                    request_mode=request_mode,
                    generation_mode=generation_mode,
                    title=title,
                    department=department,
                    process_name=process_name,
                    scenario_name=scenario_name,
                    topic=topic,
                    model=response_model,
                    citations=citations,
                ),
            )

            answer_parts: list[str] = []
            prepared_prompt = (
                self.generation_client.prepare_prompt(
                    question=generation_instruction,
                    contexts=contexts,
                )
                if hasattr(self.generation_client, "prepare_prompt")
                else None
            )
            try:
                generation_kwargs = dict(
                    question=generation_instruction,
                    contexts=contexts,
                    timeout_seconds=profile.timeout_budget_seconds,
                    model_name=response_model,
                )
                if prepared_prompt is not None:
                    generation_kwargs["prepared_prompt"] = prepared_prompt
                for delta in self.generation_client.generate_stream(**generation_kwargs):
                    if not delta:
                        continue
                    answer_parts.append(delta)
                    yield self._to_sse("content_delta", {"delta": delta})
                content = self._strip_markdown_code_fence("".join(answer_parts))
                if not content:
                    content = "No SOP draft content was generated."
            except LLMGenerationRetryableError:
                degraded_citations = self._build_degraded_citations(
                    search_query=search_query,
                    target_department_id=department.department_id,
                    profile=profile,
                    document_id=document_id,
                    auth_context=auth_context,
                )
                if degraded_citations:
                    citations = degraded_citations.citations
                    rerank_strategy = "fallback_profile"
                    downgraded_from = profile.mode
                    citation_details = dict(degraded_citations.details)
                if not self.system_config_service.get_degrade_controls().retrieval_fallback_enabled:
                    raise
                generation_mode = "retrieval_fallback"
                yield self._to_sse(
                    "meta",
                    self._build_stream_meta_payload(
                        request_mode=request_mode,
                        generation_mode=generation_mode,
                        title=title,
                        department=department,
                        process_name=process_name,
                        scenario_name=scenario_name,
                        topic=topic,
                        model=response_model,
                        citations=citations,
                    ),
                )
                content = self._build_retrieval_fallback_draft(
                    title=title,
                    department=department,
                    process_name=process_name,
                    scenario_name=scenario_name,
                    topic=topic,
                    citations=citations,
                )
                for delta in self._chunk_text(content):
                    yield self._to_sse("content_delta", {"delta": delta})

            response = SopGenerationDraftResponse(
                request_mode=request_mode,
                generation_mode=generation_mode,
                title=title,
                department_id=department.department_id,
                department_name=department.department_name,
                process_name=process_name,
                scenario_name=scenario_name,
                topic=topic,
                content=content,
                model=response_model,
                citations=citations,
            )
            self._record_generation_event(
                request_mode=request_mode,
                outcome="success",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode=response.generation_mode,
                citation_count=len(response.citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                extra_details={"streaming": True, **citation_details, **runtime_details},
            )
            snapshot_record = self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="success",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=citations,
                response=response,
                rerank_strategy=rerank_strategy,
                model=response_model,
                content=response.content,
                downgraded_from=downgraded_from,
                details={
                    "title": title,
                    "generation_mode": response.generation_mode,
                    "citation_count": len(response.citations),
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    "streaming": True,
                    **citation_details,
                    **runtime_details,
                },
            )
            response.snapshot_id = snapshot_record.snapshot_id
            yield self._to_sse("done", response.model_dump())
        except RuntimeGateBusyError as exc:
            runtime_details = {
                **runtime_details,
                "runtime_channel": exc.channel,
                "busy_rejected": True,
                "busy_rejected_reason": exc.reason,
                "retry_after_seconds": exc.retry_after_seconds,
            }
            self._record_generation_event(
                request_mode=request_mode,
                outcome="failed",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode="failed",
                citation_count=0,
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                error_message=exc.detail,
                extra_details={"streaming": True, **citation_details, **runtime_details},
            )
            self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="failed",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=[],
                response=None,
                rerank_strategy=rerank_strategy,
                model=response_model,
                content=None,
                error_message=exc.detail,
                details={
                    "title": title,
                    "generation_mode": "failed",
                    "citation_count": 0,
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    "streaming": True,
                    **citation_details,
                    **runtime_details,
                },
            )
            yield self._to_sse(
                "error",
                {
                    "message": exc.detail,
                    "busy": True,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
        except Exception as exc:
            error_message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            self._record_generation_event(
                request_mode=request_mode,
                outcome="failed",
                auth_context=auth_context,
                profile=profile,
                document_id=document_id,
                title=title,
                generation_mode="failed",
                citation_count=0,
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                error_message=str(error_message),
                extra_details={"streaming": True, **citation_details, **runtime_details},
            )
            self.request_snapshot_service.record_sop_snapshot(
                request_mode=request_mode,
                outcome="failed",
                request=request_payload,
                profile=profile,
                auth_context=auth_context,
                citations=[],
                response=None,
                rerank_strategy=rerank_strategy,
                model=response_model,
                content=None,
                error_message=str(error_message),
                details={
                    "title": title,
                    "generation_mode": "failed",
                    "citation_count": 0,
                    "document_id": document_id,
                    "department_id": department.department_id,
                    "department_name": department.department_name,
                    "process_name": process_name,
                    "scenario_name": scenario_name,
                    "topic": topic,
                    "streaming": True,
                    **citation_details,
                    **runtime_details,
                },
            )
            yield self._to_sse("error", {"message": str(error_message)})
        finally:
            if runtime_lease is not None:
                runtime_lease.release()

    def _build_citations(
        self,
        *,
        search_query: str,
        target_department_id: str,
        profile: QueryProfile,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> SopCitationBuildResult:
        retrieval_results, retrieval_mode, _ = self.retrieval_service.search_candidates(
            RetrievalRequest(
                query=search_query,
                top_k=profile.top_k,
                mode=profile.mode,
                candidate_top_k=profile.candidate_top_k,
                document_id=document_id,
            ),
            auth_context=auth_context,
            profile=profile,
            truncate_to_top_k=False,
        )
        retrieval_details = (
            self.retrieval_service.build_observability_details(query=search_query, retrieval_mode=retrieval_mode)
            if hasattr(self.retrieval_service, "build_observability_details")
            else {"retrieval_mode": retrieval_mode}
        )
        filtered_results = self._filter_results_by_department(
            retrieval_results,
            target_department_id=target_department_id,
            auth_context=auth_context,
        )
        if not filtered_results:
            return SopCitationBuildResult(
                citations=[],
                rerank_strategy="skipped",
                details={
                    **retrieval_details,
                    "retrieved_count": len(retrieval_results),
                    "rerank_input_count": 0,
                    "rerank_output_count": 0,
                    "citation_count": 0,
                },
            )

        reranked_results, rerank_strategy = self.query_profile_service.rerank_with_fallback(
            query=search_query,
            candidates=filtered_results,
            profile=profile,
            reranker_client=self.reranker_client,
            top_n=len(filtered_results),
        )
        citations_source = reranked_results[: min(profile.rerank_top_n, len(reranked_results))]

        return SopCitationBuildResult(
            citations=[
                SopGenerationCitation(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    document_name=item.document_name,
                    snippet=item.text,
                    score=item.score,
                    source_path=item.source_path,
                    retrieval_strategy=item.retrieval_strategy,
                    source_scope=item.source_scope,
                    vector_score=item.vector_score,
                    lexical_score=item.lexical_score,
                    fused_score=item.fused_score,
                    ocr_used=item.ocr_used,
                    parser_name=item.parser_name,
                    page_no=item.page_no,
                    ocr_confidence=item.ocr_confidence,
                    quality_score=item.quality_score,
                )
                for item in citations_source
            ],
            rerank_strategy=rerank_strategy,
            details={
                **retrieval_details,
                "retrieved_count": len(retrieval_results),
                "rerank_input_count": len(filtered_results),
                "rerank_output_count": len(reranked_results),
                "citation_count": len(citations_source),
            },
        )

    def _build_degraded_citations(
        self,
        *,
        search_query: str,
        target_department_id: str,
        profile: QueryProfile,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> SopCitationBuildResult:
        fallback_profile = self.query_profile_service.build_fallback_profile(profile)
        if fallback_profile is None:
            return SopCitationBuildResult(citations=[], rerank_strategy="skipped")
        return self._build_citations(
            search_query=search_query,
            target_department_id=target_department_id,
            profile=fallback_profile,
            document_id=document_id,
            auth_context=auth_context,
        )

    def _acquire_generation_runtime_slot(
        self,
        profile: QueryProfile,
        *,
        auth_context: AuthContext,
    ) -> tuple[RuntimeGateLease, dict[str, object]]:
        concurrency_controls = self.system_config_service.get_concurrency_controls()
        owner_key = auth_context.user.user_id
        lease, reject_reason = self.runtime_gate_service.acquire_with_reason(
            "sop_generation",
            timeout_ms=concurrency_controls.acquire_timeout_ms,
            owner_key=owner_key,
        )
        if lease is not None:
            return lease, {
                "runtime_channel": "sop_generation",
                "acquire_timeout_ms": concurrency_controls.acquire_timeout_ms,
                "requested_mode": profile.mode,
                "runtime_owner_key": owner_key,
            }
        raise RuntimeGateBusyError(
            detail=(
                "System is busy. Your concurrent request limit is reached. Wait for an earlier request to finish and retry."
                if reject_reason == "user_limit"
                else "System is busy. SOP generation capacity is saturated. Retry later."
            ),
            channel="sop_generation",
            reason=reject_reason or "channel_limit",
            retry_after_seconds=concurrency_controls.busy_retry_after_seconds,
            requested_mode=profile.mode,
        )

    def _build_document_preview_citations(
        self,
        *,
        document_id: str,
        auth_context: AuthContext,
    ) -> list[SopGenerationCitation]:
        preview = self.document_service.get_document_preview(
            document_id,
            max_chars=12_000,
            auth_context=auth_context,
        )
        preview_text = (preview.text_content or "").strip()
        if not preview_text:
            return []

        normalized_text = preview_text.replace("\r\n", "\n")
        snippets = [
            chunk.strip()
            for chunk in normalized_text.split("\n\n")
            if chunk.strip()
        ] or [normalized_text]

        citations: list[SopGenerationCitation] = []
        for index, snippet in enumerate(snippets[:3]):
            trimmed_snippet = snippet[:1200].strip()
            if not trimmed_snippet:
                continue
            citations.append(
                SopGenerationCitation(
                    chunk_id=f"{document_id}-preview-{index}",
                    document_id=document_id,
                    document_name=preview.file_name,
                    snippet=trimmed_snippet,
                    score=1.0 - (index * 0.01),
                    source_path=preview.preview_file_url or f"document-preview://{document_id}",
                    retrieval_strategy="document_preview",
                    ocr_used=False,
                    parser_name="document_preview",
                )
            )
        return citations

    def _filter_results_by_department(
        self,
        results: list[RetrievedChunk],
        *,
        target_department_id: str,
        auth_context: AuthContext,
    ) -> list[RetrievedChunk]:
        filtered: list[RetrievedChunk] = []
        department_cache: dict[str, str | None] = {}
        for item in results:
            resolved_department_id = department_cache.get(item.document_id)
            if item.document_id not in department_cache:
                document_detail = self.document_service.get_document(item.document_id, auth_context=auth_context)
                resolved_department_id = document_detail.department_id
                department_cache[item.document_id] = resolved_department_id
            if resolved_department_id == target_department_id:
                filtered.append(item)
        return filtered

    def _resolve_generation_department(self, auth_context: AuthContext, requested_department_id: str | None) -> DepartmentRecord:
        normalized_requested_department_id = _normalize_optional_str(requested_department_id)
        if normalized_requested_department_id is None:
            normalized_requested_department_id = auth_context.department.department_id

        if normalized_requested_department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot generate SOP drafts outside your accessible departments.",
            )
        return self.identity_service.get_department(normalized_requested_department_id)

    @staticmethod
    def _build_title(
        *,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None = None,
    ) -> str:
        if topic:
            if process_name:
                return f"{department.department_name}{process_name}{topic} SOP 草稿"
            return f"{department.department_name}{topic} SOP 草稿"
        if process_name and scenario_name:
            return f"{department.department_name}{process_name}{scenario_name} SOP 草稿"
        if scenario_name:
            return f"{department.department_name}{scenario_name} SOP 草稿"
        if process_name:
            return f"{department.department_name}{process_name} SOP 草稿"
        return f"{department.department_name}标准 SOP 草稿"

    @staticmethod
    def _build_search_query(
        *,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
    ) -> str:
        parts = [department.department_name]
        if process_name:
            parts.append(process_name)
        if scenario_name:
            parts.append(scenario_name)
        if topic:
            parts.append(topic)
        parts.append("SOP 操作步骤 注意事项")
        return " ".join(parts)

    @staticmethod
    def _build_document_search_query(
        *,
        department: DepartmentRecord,
        document_name: str,
        process_name: str | None,
        scenario_name: str | None,
    ) -> str:
        parts = [department.department_name, SopGenerationService._build_document_label(document_name)]
        if process_name:
            parts.append(process_name)
        if scenario_name:
            parts.append(scenario_name)
        parts.append("SOP 操作步骤 异常处理 注意事项 标准流程")
        return " ".join(parts)

    @staticmethod
    def _build_generation_instruction(
        *,
        title: str,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
    ) -> str:
        process_text = process_name or "未指定工序"
        scenario_text = scenario_name or "未指定场景"
        topic_text = topic or "按场景生成"
        return (
            "请基于提供的证据，用中文起草一份企业 SOP 草稿。"
            "输出尽量结构化，至少包含：目的、适用范围、前置检查、操作步骤、异常处理、记录要求。"
            "如果证据不足，请在文中明确写出“证据不足/待补充”。\n"
            f"标题：{title}\n"
            f"部门：{department.department_name}\n"
            f"工序：{process_text}\n"
            f"场景：{scenario_text}\n"
            f"主题：{topic_text}\n"
        )

    @staticmethod
    def _build_document_generation_instruction(
        *,
        title: str,
        department: DepartmentRecord,
        document_name: str,
        process_name: str | None,
        scenario_name: str | None,
    ) -> str:
        process_text = process_name or "未指定工序"
        scenario_text = scenario_name or "未指定场景"
        return (
            "请基于提供的单份来源文档证据，用中文直接生成一份可执行的企业 SOP 草稿。"
            "输出请使用 Markdown，并尽量包含：目的、适用范围、前置检查、操作步骤、异常处理、记录要求。"
            "不要写空泛说明；如果证据不足，请明确标注“证据不足/待补充”。\n"
            f"标题：{title}\n"
            f"部门：{department.department_name}\n"
            f"来源文档：{document_name}\n"
            f"工序：{process_text}\n"
            f"场景：{scenario_text}\n"
        )

    @staticmethod
    def _build_retrieval_fallback_draft(
        *,
        title: str,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
        citations: list[SopGenerationCitation],
    ) -> str:
        lines = [
            f"# {title}",
            "",
            f"适用部门：{department.department_name}",
            f"工序：{process_name or '未指定'}",
            f"场景：{scenario_name or '未指定'}",
            f"主题：{topic or '按场景生成'}",
            "",
            "## 证据摘要",
        ]
        for index, citation in enumerate(citations[:3], start=1):
            snippet = citation.snippet.strip().replace("\n", " ")
            if len(snippet) > 180:
                snippet = f"{snippet[:177]}..."
            lines.append(f"{index}. {snippet}")
        lines.extend(
            [
                "",
                "## 待补充",
                "- 当前为检索兜底草稿，请在在线编辑页补充标准步骤、责任人与记录要求。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _build_document_label(document_name: str) -> str:
        normalized = Path(document_name).stem.strip()
        return normalized or document_name.strip() or "来源文档"

    @staticmethod
    def _strip_markdown_code_fence(content: str) -> str:
        normalized = content.strip()
        if not normalized.startswith("```"):
            return normalized

        lines = normalized.splitlines()
        if len(lines) < 3:
            return normalized

        first_line = lines[0].strip()
        if first_line not in {"```", "```markdown", "```md"}:
            return normalized

        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip().startswith("```"):
                closing_index = index
                break

        if closing_index is None:
            return normalized

        inner_lines = lines[1:closing_index]
        trailing_lines = lines[closing_index + 1:]
        merged_lines = inner_lines + trailing_lines
        return "\n".join(merged_lines).strip()

    @staticmethod
    def _to_sse(event: str, payload: dict[str, object]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 48) -> Iterator[str]:
        safe_size = max(1, chunk_size)
        for start in range(0, len(text), safe_size):
            yield text[start : start + safe_size]

    @staticmethod
    def _build_stream_meta_payload(
        *,
        request_mode: SopGenerationRequestMode,
        generation_mode: str,
        title: str,
        department: DepartmentRecord,
        process_name: str | None,
        scenario_name: str | None,
        topic: str | None,
        model: str,
        citations: list[SopGenerationCitation],
    ) -> dict[str, object]:
        return {
            "request_mode": request_mode,
            "generation_mode": generation_mode,
            "title": title,
            "department_id": department.department_id,
            "department_name": department.department_name,
            "process_name": process_name,
            "scenario_name": scenario_name,
            "topic": topic,
            "model": model,
            "citations": [citation.model_dump() for citation in citations],
        }

    def _response_model_name(self, *, profile: QueryProfile | None = None) -> str:
        if self.settings.llm_provider.lower().strip() == "mock":
            return "mock"
        resolved_profile = profile or self.query_profile_service.resolve(purpose="sop_generation")
        return self.system_config_service.get_llm_model_for_request(
            purpose=resolved_profile.purpose,
            mode=resolved_profile.mode,
        )

    def _record_generation_event(
        self,
        *,
        request_mode: SopGenerationRequestMode,
        outcome: str,
        auth_context: AuthContext,
        profile: QueryProfile,
        document_id: str | None,
        title: str,
        generation_mode: str,
        citation_count: int,
        rerank_strategy: str,
        duration_ms: int,
        downgraded_from: str | None = None,
        error_message: str | None = None,
        extra_details: dict[str, object] | None = None,
    ) -> None:
        rerank_log_fields = self._build_rerank_log_fields(rerank_strategy)
        payload: dict[str, object] = {
            "request_mode": request_mode,
            "title": title,
            "generation_mode": generation_mode,
            "citation_count": citation_count,
            "rerank_strategy": rerank_strategy,
            "rerank_provider": rerank_log_fields["rerank_provider"],
            "rerank_model": rerank_log_fields["rerank_model"],
            "rerank_default_strategy": rerank_log_fields["rerank_default_strategy"],
            "rerank_effective_strategy": rerank_log_fields["rerank_effective_strategy"],
            "document_id": document_id,
        }
        if error_message:
            payload["error_message"] = error_message
        if extra_details is not None:
            payload.update(extra_details)
        self.event_log_service.record(
            category="sop_generation",
            action=f"generate_{request_mode}",
            outcome="success" if outcome == "success" else "failed",
            auth_context=auth_context,
            target_type="document" if document_id else None,
            target_id=document_id,
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

    def _build_rerank_log_fields(self, rerank_strategy: str) -> dict[str, str | None]:
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

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))


@lru_cache
def get_sop_generation_service() -> SopGenerationService:
    return SopGenerationService()
