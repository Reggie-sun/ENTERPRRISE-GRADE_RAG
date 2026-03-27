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
from .retrieval_service import RetrievalService, get_retrieval_service
from .system_config_service import SystemConfigService


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
        self.reranker_client = reranker_client or RerankerClient(self.settings)
        self.generation_client = generation_client or LLMGenerationClient(
            self.settings,
            system_config_service=self.system_config_service,
        )
        self.event_log_service = event_log_service or get_event_log_service()

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
        try:
            citations = self._build_citations(
                search_query=search_query,
                target_department_id=department.department_id,
                profile=profile,
                document_id=document_id,
                auth_context=auth_context,
            )
            if citations:
                rerank_strategy = "provider_or_fallback"
            if not citations and request_mode == "document" and document_id is not None:
                citations = self._build_document_preview_citations(
                    document_id=document_id,
                    auth_context=auth_context,
                )
                if citations:
                    rerank_strategy = "document_preview"
            if not citations:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No relevant evidence was retrieved for SOP generation.",
                )

            contexts = [item.snippet for item in citations]
            downgraded_from: str | None = None
            response_model = self._response_model_name(profile=profile)
            try:
                content = self._strip_markdown_code_fence(
                    self.generation_client.generate(
                        question=generation_instruction,
                        contexts=contexts,
                        timeout_seconds=profile.timeout_budget_seconds,
                        model_name=response_model,
                    )
                )
                generation_mode = "rag"
            except LLMGenerationRetryableError:
                degraded_citations = self._build_degraded_citations(
                    search_query=search_query,
                    target_department_id=department.department_id,
                    profile=profile,
                    document_id=document_id,
                    auth_context=auth_context,
                )
                if degraded_citations:
                    citations = degraded_citations
                    rerank_strategy = "fallback_profile"
                    downgraded_from = profile.mode
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
            )
            return response
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
            )
            raise

    def _build_citations(
        self,
        *,
        search_query: str,
        target_department_id: str,
        profile: QueryProfile,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> list[SopGenerationCitation]:
        retrieval_result = self.retrieval_service.search(
            RetrievalRequest(
                query=search_query,
                top_k=profile.top_k,
                mode=profile.mode,
                candidate_top_k=profile.candidate_top_k,
                document_id=document_id,
            ),
            auth_context=auth_context,
        )
        filtered_results = self._filter_results_by_department(
            retrieval_result.results,
            target_department_id=target_department_id,
            auth_context=auth_context,
        )
        if not filtered_results:
            return []

        reranked_results, _ = self.query_profile_service.rerank_with_fallback(
            query=search_query,
            candidates=filtered_results,
            profile=profile,
            reranker_client=self.reranker_client,
        )

        return [
            SopGenerationCitation(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_name=item.document_name,
                snippet=item.text,
                score=item.score,
                source_path=item.source_path,
            )
            for item in reranked_results
        ]

    def _build_degraded_citations(
        self,
        *,
        search_query: str,
        target_department_id: str,
        profile: QueryProfile,
        document_id: str | None,
        auth_context: AuthContext,
    ) -> list[SopGenerationCitation]:
        fallback_profile = self.query_profile_service.build_fallback_profile(profile)
        if fallback_profile is None:
            return []
        return self._build_citations(
            search_query=search_query,
            target_department_id=target_department_id,
            profile=fallback_profile,
            document_id=document_id,
            auth_context=auth_context,
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
    ) -> None:
        details: dict[str, object] = {
            "request_mode": request_mode,
            "title": title,
            "generation_mode": generation_mode,
            "citation_count": citation_count,
            "rerank_strategy": rerank_strategy,
            "document_id": document_id,
        }
        if error_message:
            details["error_message"] = error_message
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
            duration_ms=duration_ms,
            downgraded_from=downgraded_from,
            details=details,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))


@lru_cache
def get_sop_generation_service() -> SopGenerationService:
    return SopGenerationService()
