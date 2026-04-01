"""问答服务模块。

封装完整 RAG 问答链路：查询改写 → 检索 → 重排序 → LLM 生成/流式生成 → 引用构建。
同时负责对话记忆管理、请求追踪、快照记录和运行时并发控制。

核心类:
    ChatService — 问答服务，提供同步回答（answer）和 SSE 流式回答（stream_answer_sse）。

关键流程:
    1. 查询改写：短追问通过 QueryRewriteService 补全上下文
    2. 检索+重排：通过 CitationPipeline 组件获取引用
    3. LLM 生成：调用 LLMGenerationClient 生成最终回答
    4. 降级兜底：LLM 不可用时自动切换到 retrieval_fallback 模式
"""

import json  # 导入 json，用于序列化 SSE 事件数据。
from time import perf_counter
from typing import Iterator  # 导入 Iterator，用于声明流式输出类型。
from uuid import uuid4

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..rag.generators.client import (  # 导入 LLM 生成客户端和异常类型。
    LLMGenerationClient,
    LLMGenerationFatalError,
    LLMGenerationRetryableError,
)
from ..schemas.auth import AuthContext  # 导入统一鉴权上下文，问答要与检索保持同一份权限边界。
from ..schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatStreamDeltaPayload,
    ChatStreamErrorPayload,
    ChatStreamMetaPayload,
    Citation,
)  # 导入问答请求、响应和引用片段模型。
from ..schemas.query_profile import QueryProfile
from ..schemas.query_rewrite import QueryRewriteResult
from ..schemas.request_trace import RequestTraceStage, RequestTraceStageStatus
from .chat_citation_pipeline import ChatCitationPipeline, CitationBuildResult  # noqa: F401 — re-export for backward compat
from .chat_memory_service import ChatMemoryService, get_chat_memory_service
from .chat_telemetry_recorder import ChatTelemetryRecorder
from .event_log_service import EventLogService, get_event_log_service
from .query_profile_service import QueryProfileService
from .query_rewrite_service import QueryRewriteService, get_query_rewrite_service
from .request_snapshot_service import RequestSnapshotService
from .request_trace_service import RequestTraceService
from .runtime_gate_service import RuntimeGateBusyError, RuntimeGateLease, RuntimeGateService, get_runtime_gate_service
from .system_config_service import SystemConfigService


class ChatService:  # 封装问答接口的业务逻辑。
    def __init__(
        self,
        settings: Settings | None = None,
        query_profile_service: QueryProfileService | None = None,
        event_log_service: EventLogService | None = None,
        request_trace_service: RequestTraceService | None = None,
        request_snapshot_service: RequestSnapshotService | None = None,
        runtime_gate_service: RuntimeGateService | None = None,
        chat_memory_service: ChatMemoryService | None = None,
        query_rewrite_service: QueryRewriteService | None = None,
        citation_pipeline: ChatCitationPipeline | None = None,
        telemetry_recorder: ChatTelemetryRecorder | None = None,
    ) -> None:  # 初始化问答服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        if query_profile_service is None:
            self.system_config_service = SystemConfigService(self.settings)
            self.query_profile_service = QueryProfileService(
                self.settings,
                system_config_service=self.system_config_service,
            )
        else:
            self.query_profile_service = query_profile_service
            self.system_config_service = query_profile_service.system_config_service
        self.generation_client = LLMGenerationClient(
            self.settings,
            system_config_service=self.system_config_service,
        )  # 创建生成客户端，负责最终回答。
        self.runtime_gate_service = runtime_gate_service or (
            RuntimeGateService(self.settings, system_config_service=self.system_config_service)
            if settings is not None
            else get_runtime_gate_service()
        )
        self.chat_memory_service = chat_memory_service or (
            ChatMemoryService(self.settings) if settings is not None else get_chat_memory_service()
        )
        self.query_rewrite_service = query_rewrite_service or (
            QueryRewriteService(self.settings, chat_memory_service=self.chat_memory_service)
            if settings is not None
            else get_query_rewrite_service()
        )
        # 子组件：citation pipeline 和 telemetry recorder
        self.citation_pipeline = citation_pipeline or ChatCitationPipeline(
            self.settings,
            query_profile_service=self.query_profile_service,
            system_config_service=self.system_config_service,
        )
        self.telemetry_recorder = telemetry_recorder or ChatTelemetryRecorder(
            self.settings,
            event_log_service=event_log_service,
            request_trace_service=request_trace_service,
            request_snapshot_service=request_snapshot_service,
            chat_memory_service=self.chat_memory_service,
            citation_pipeline=self.citation_pipeline,
        )

    # -- 向后兼容代理属性：测试直接 patch/赋值这些属性 --
    @property
    def retrieval_service(self):
        return self.citation_pipeline.retrieval_service

    @retrieval_service.setter
    def retrieval_service(self, value):
        self.citation_pipeline.retrieval_service = value

    @property
    def reranker_client(self):
        return self.citation_pipeline.reranker_client

    @reranker_client.setter
    def reranker_client(self, value):
        self.citation_pipeline.reranker_client = value

    def answer(self, request: ChatRequest, *, auth_context: AuthContext | None = None) -> ChatResponse:  # 根据用户问题生成问答响应。
        started_at = perf_counter()
        trace_id, request_id = self._new_trace_identifiers()
        trace_stages: list[RequestTraceStage] = []
        profile = self.query_profile_service.resolve(
            purpose="chat",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )  # 先把请求展开为统一查询档位配置。
        citations: list[Citation] = []
        rerank_strategy = "skipped"
        response_mode = "failed"
        downgraded_from: str | None = None
        error_message: str | None = None
        response_model = self._response_model_name(profile=profile)
        answer_text = ""
        memory_summary = self._build_memory_summary(request=request, auth_context=auth_context)
        rewrite_result = self._rewrite_question(request=request, auth_context=auth_context)
        effective_question = rewrite_result.rewritten_question or request.question
        citation_details: dict[str, object] = {}
        self._append_trace_stage(
            trace_stages,
            stage="query_rewrite",
            status="success" if rewrite_result.status == "applied" else rewrite_result.status,
            duration_ms=0,
            input_size=len(request.question),
            output_size=len(effective_question),
            details=rewrite_result.details,
        )
        runtime_details: dict[str, object] = {}
        runtime_lease: RuntimeGateLease | None = None
        try:
            profile, runtime_lease, downgraded_from, runtime_details = self._acquire_chat_runtime_slot(
                profile,
                auth_context=auth_context,
            )
            response_model = self._response_model_name(profile=profile)
            citation_result = self.citation_pipeline.build_citations(
                request,
                profile,
                query_text=effective_question,
                auth_context=auth_context,
                trace_stages=trace_stages,
            )  # 先统一构造引用列表。
            citations = citation_result.citations
            rerank_strategy = citation_result.rerank_strategy
            citation_details = dict(citation_result.details)
            if not citations:  # 如果连引用都没有，说明还没有可用上下文。
                response = self._build_no_context_response(request.question, citations)
                response_mode = response.mode
                answer_text = response.answer
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="skipped",
                    duration_ms=0,
                    input_size=0,
                    output_size=0,
                    details={"reason": "No citations were retrieved for answer generation."},
                )
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="success",
                    duration_ms=0,
                    input_size=0,
                    output_size=len(response.answer),
                    details={"response_mode": response.mode, "model": response.model},
                )
                self.telemetry_recorder.record_chat_event(
                    action="answer",
                    outcome="success",
                    request=request,
                    profile=profile,
                    auth_context=auth_context,
                    response_mode=response.mode,
                    citation_count=0,
                    rerank_strategy=rerank_strategy,
                    duration_ms=self._elapsed_ms(started_at),
                    details={**citation_details, **runtime_details},
                    memory_summary=memory_summary,
                    rewrite_result=rewrite_result,
                    trace_id=trace_id,
                    request_id=request_id,
                )
                return response

            contexts = [citation.snippet for citation in citations]  # 提取引用文本，作为生成模型的上下文输入。
            prepared_prompt = (
                self.generation_client.prepare_prompt(
                    question=effective_question,
                    contexts=contexts,
                    memory_text=memory_summary,
                )
                if hasattr(self.generation_client, "prepare_prompt")
                else None
            )
            try:  # 优先调用 LLM 生成最终回答。
                llm_started_at = perf_counter()
                generation_kwargs = dict(
                    question=effective_question,  # 追问型问题先按最近一轮主题改写，再进入生成链路。
                    contexts=contexts,  # 传入检索证据上下文。
                    memory_text=memory_summary,  # 最近几轮上下文只做轻量承接，不替代检索证据。
                    timeout_seconds=profile.timeout_budget_seconds,  # 问答超时预算统一来自查询档位配置。
                    model_name=response_model,
                )
                if prepared_prompt is not None:
                    generation_kwargs["prepared_prompt"] = prepared_prompt
                answer = self.generation_client.generate(**generation_kwargs)  # 执行回答生成。
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="success",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=len(answer),
                    cache_hit=False,
                    details={
                        "context_chars": sum(len(context) for context in contexts),
                        "model": response_model,
                        **(
                            {
                                "prompt_context_count": prepared_prompt.prepared_context_count,
                                "prompt_context_original_count": prepared_prompt.original_context_count,
                                "prompt_context_deduplicated_count": prepared_prompt.deduplicated_context_count,
                                "prompt_pretrimmed_context_count": prepared_prompt.pretrimmed_context_count,
                                "prompt_truncated_context_count": prepared_prompt.truncated_context_count,
                                "prompt_context_token_estimate": prepared_prompt.context_token_estimate,
                                "prompt_memory_token_estimate": prepared_prompt.memory_token_estimate,
                                "prompt_token_estimate": prepared_prompt.prompt_token_estimate,
                            }
                            if prepared_prompt is not None
                            else {}
                        ),
                    },
                )
                mode = "rag"  # 生成成功时标记为完整 RAG 模式。
            except LLMGenerationRetryableError as exc:  # 仅在可恢复的远程故障时走降级，避免吞掉配置或协议错误。
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="failed",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=0,
                    cache_hit=False,
                    details={
                        "context_chars": sum(len(context) for context in contexts),
                        "error_message": str(exc),
                        "model": response_model,
                        **(
                            {
                                "prompt_context_count": prepared_prompt.prepared_context_count,
                                "prompt_context_original_count": prepared_prompt.original_context_count,
                                "prompt_context_deduplicated_count": prepared_prompt.deduplicated_context_count,
                                "prompt_pretrimmed_context_count": prepared_prompt.pretrimmed_context_count,
                                "prompt_truncated_context_count": prepared_prompt.truncated_context_count,
                                "prompt_context_token_estimate": prepared_prompt.context_token_estimate,
                                "prompt_memory_token_estimate": prepared_prompt.memory_token_estimate,
                                "prompt_token_estimate": prepared_prompt.prompt_token_estimate,
                            }
                            if prepared_prompt is not None
                            else {}
                        ),
                    },
                )
                degraded_result = self.citation_pipeline.build_degraded_citations(
                    request,
                    profile,
                    query_text=effective_question,
                    auth_context=auth_context,
                )
                if degraded_result is not None and degraded_result.citations:
                    citations = degraded_result.citations
                    rerank_strategy = degraded_result.rerank_strategy
                    downgraded_from = profile.mode
                    citation_details = dict(degraded_result.details)
                if not self.system_config_service.get_degrade_controls().retrieval_fallback_enabled:
                    raise
                answer = self._build_retrieval_fallback_answer(citations)  # 用引用片段拼一个稳定可读的兜底回答。
                mode = "retrieval_fallback"  # 标记为检索兜底模式。

            response = self._build_response(  # 组装最终问答响应。
                question=request.question,
                answer=answer,
                mode=mode,
                citations=citations,
                model=response_model,
            )
            response_mode = response.mode
            answer_text = response.answer
            self._append_trace_stage(
                trace_stages,
                stage="answer",
                status="degraded" if downgraded_from else "success",
                duration_ms=0,
                input_size=len(citations),
                output_size=len(response.answer),
                details={"response_mode": response.mode, "model": response.model},
            )
            self.telemetry_recorder.record_chat_event(
                action="answer",
                outcome="success",
                request=request,
                profile=profile,
                auth_context=auth_context,
                response_mode=response.mode,
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                details={**citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
                trace_id=trace_id,
                request_id=request_id,
            )
            return response
        except RuntimeGateBusyError as exc:
            error_message = exc.detail
            runtime_details = {
                **runtime_details,
                "runtime_channel": exc.channel,
                "busy_rejected": True,
                "busy_rejected_reason": exc.reason,
                "retry_after_seconds": exc.retry_after_seconds,
            }
            if not self._has_answer_stage(trace_stages):
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="failed",
                    duration_ms=0,
                    input_size=len(citations),
                    output_size=0,
                    details={"error_message": error_message, **runtime_details},
                )
            self.telemetry_recorder.record_chat_event(
                action="answer",
                outcome="failed",
                request=request,
                profile=profile,
                auth_context=auth_context,
                response_mode="failed",
                citation_count=0,
                rerank_strategy="skipped",
                duration_ms=self._elapsed_ms(started_at),
                error_message=error_message,
                details={**citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
                trace_id=trace_id,
                request_id=request_id,
            )
            raise exc.to_http_exception()
        except Exception as exc:
            error_message = str(exc)
            if not self._has_answer_stage(trace_stages):
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="failed",
                    duration_ms=0,
                    input_size=len(citations),
                    output_size=0,
                    details={"error_message": error_message, **runtime_details},
                )
            self.telemetry_recorder.record_chat_event(
                action="answer",
                outcome="failed",
                request=request,
                profile=profile,
                auth_context=auth_context,
                response_mode="failed",
                citation_count=0,
                rerank_strategy="skipped",
                duration_ms=self._elapsed_ms(started_at),
                error_message=error_message,
                details={**citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
                trace_id=trace_id,
                request_id=request_id,
            )
            raise
        finally:
            if runtime_lease is not None:
                runtime_lease.release()
            self.telemetry_recorder.record_chat_trace(
                action="answer",
                request=request,
                profile=profile,
                auth_context=auth_context,
                trace_id=trace_id,
                request_id=request_id,
                stages=trace_stages,
                outcome="failed" if error_message else "success",
                response_mode=response_mode,
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                error_message=error_message,
                model=response_model,
                details={**citation_details, **runtime_details},
                rewrite_result=rewrite_result,
            )
            self.telemetry_recorder.record_chat_snapshot(
                action="answer",
                request=request,
                profile=profile,
                auth_context=auth_context,
                trace_id=trace_id,
                request_id=request_id,
                outcome="failed" if error_message else "success",
                response_mode=response_mode,
                citations=citations,
                rerank_strategy=rerank_strategy,
                model=response_model,
                answer_text=answer_text,
                downgraded_from=downgraded_from,
                error_message=error_message,
                details={**citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
            )
            self.telemetry_recorder.record_memory_turn(
                request=request,
                auth_context=auth_context,
                answer_text=answer_text,
                response_mode=response_mode,
                citation_count=len(citations),
                error_message=error_message,
            )

    def stream_answer_sse(self, request: ChatRequest, *, auth_context: AuthContext | None = None) -> Iterator[str]:  # 以 SSE 方式流式返回回答内容。
        started_at = perf_counter()
        trace_id, request_id = self._new_trace_identifiers()
        trace_stages: list[RequestTraceStage] = []
        profile = self.query_profile_service.resolve(
            purpose="chat",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )  # 先把请求展开为统一查询档位配置。
        citations: list[Citation] = []
        rerank_strategy = "skipped"
        response_mode = "failed"
        downgraded_from: str | None = None
        error_message: str | None = None
        model = self._response_model_name(profile=profile)  # 提前计算响应模型名，给 meta 事件复用。
        answer_text = ""
        memory_summary = self._build_memory_summary(request=request, auth_context=auth_context)
        rewrite_result = self._rewrite_question(request=request, auth_context=auth_context)
        effective_question = rewrite_result.rewritten_question or request.question
        citation_details: dict[str, object] = {}
        self._append_trace_stage(
            trace_stages,
            stage="query_rewrite",
            status="success" if rewrite_result.status == "applied" else rewrite_result.status,
            duration_ms=0,
            input_size=len(request.question),
            output_size=len(effective_question),
            details=rewrite_result.details,
        )
        runtime_details: dict[str, object] = {}
        runtime_lease: RuntimeGateLease | None = None

        # 先发一个 SSE comment，尽早让浏览器收到首字节，避免首轮请求在重检索/重排前长时间保持 pending。
        yield self._to_sse_comment("keepalive")

        try:
            profile, runtime_lease, downgraded_from, runtime_details = self._acquire_chat_runtime_slot(
                profile,
                auth_context=auth_context,
            )
            model = self._response_model_name(profile=profile)
            citation_result = self.citation_pipeline.build_citations(
                request,
                profile,
                query_text=effective_question,
                auth_context=auth_context,
                trace_stages=trace_stages,
            )  # 先统一构造引用列表。
            citations = citation_result.citations
            rerank_strategy = citation_result.rerank_strategy
            citation_details = dict(citation_result.details)
            if not citations:  # 没有引用时直接返回无上下文 done 事件。
                response = self._build_no_context_response(request.question, citations)
                response_mode = response.mode
                answer_text = response.answer
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="skipped",
                    duration_ms=0,
                    input_size=0,
                    output_size=0,
                    details={"reason": "No citations were retrieved for streamed answer generation."},
                )
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="success",
                    duration_ms=0,
                    input_size=0,
                    output_size=len(response.answer),
                    details={"response_mode": response.mode, "model": response.model},
                )
                yield self._to_sse("meta", self._build_meta_payload(response))
                yield self._to_sse("done", response.model_dump())
                return

            mode = "rag"  # 默认先按 rag 模式流式生成。
            contexts = [citation.snippet for citation in citations]  # 提取上下文列表。
            prepared_prompt = (
                self.generation_client.prepare_prompt(
                    question=effective_question,
                    contexts=contexts,
                    memory_text=memory_summary,
                )
                if hasattr(self.generation_client, "prepare_prompt")
                else None
            )
            yield self._to_sse(  # 首帧先发元数据，前端可立即渲染模式和引用占位。
                "meta",
                ChatStreamMetaPayload(
                    question=request.question,
                    mode=mode,
                    model=model,
                    citations=citations,
                ).model_dump(mode="json"),
            )

            answer_parts: list[str] = []  # 累积回答片段，最后拼成完整 answer。
            llm_started_at = perf_counter()
            try:  # 尝试真实流式生成。
                generation_kwargs = dict(
                    question=effective_question,
                    contexts=contexts,
                    memory_text=memory_summary,
                    timeout_seconds=profile.timeout_budget_seconds,
                    model_name=model,
                )
                if prepared_prompt is not None:
                    generation_kwargs["prepared_prompt"] = prepared_prompt
                for delta in self.generation_client.generate_stream(**generation_kwargs):
                    if not delta:
                        continue
                    answer_parts.append(delta)
                    yield self._to_sse("answer_delta", self._build_stream_delta_payload(delta))  # 每个片段都立即推给前端。
                answer = "".join(answer_parts).strip()  # 汇总完整回答文本。
                if not answer:  # 理论上不应为空，兜底避免前端停在 loading。
                    answer = "No answer content was generated."
                answer_text = answer
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="success",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=len(answer),
                    cache_hit=False,
                    details={
                        "context_chars": sum(len(context) for context in contexts),
                        "model": model,
                        "streaming": True,
                        **(
                            {
                                "prompt_context_count": prepared_prompt.prepared_context_count,
                                "prompt_context_original_count": prepared_prompt.original_context_count,
                                "prompt_context_deduplicated_count": prepared_prompt.deduplicated_context_count,
                                "prompt_pretrimmed_context_count": prepared_prompt.pretrimmed_context_count,
                                "prompt_truncated_context_count": prepared_prompt.truncated_context_count,
                                "prompt_context_token_estimate": prepared_prompt.context_token_estimate,
                                "prompt_memory_token_estimate": prepared_prompt.memory_token_estimate,
                                "prompt_token_estimate": prepared_prompt.prompt_token_estimate,
                            }
                            if prepared_prompt is not None
                            else {}
                        ),
                    },
                )
            except LLMGenerationRetryableError as exc:  # 远端临时不可用时切回检索兜底，并保持流式输出形态。
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="failed",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=0,
                    cache_hit=False,
                    details={
                        "context_chars": sum(len(context) for context in contexts),
                        "error_message": str(exc),
                        "model": model,
                        "streaming": True,
                        **(
                            {
                                "prompt_context_count": prepared_prompt.prepared_context_count,
                                "prompt_context_original_count": prepared_prompt.original_context_count,
                                "prompt_context_deduplicated_count": prepared_prompt.deduplicated_context_count,
                                "prompt_pretrimmed_context_count": prepared_prompt.pretrimmed_context_count,
                                "prompt_truncated_context_count": prepared_prompt.truncated_context_count,
                                "prompt_context_token_estimate": prepared_prompt.context_token_estimate,
                                "prompt_memory_token_estimate": prepared_prompt.memory_token_estimate,
                                "prompt_token_estimate": prepared_prompt.prompt_token_estimate,
                            }
                            if prepared_prompt is not None
                            else {}
                        ),
                    },
                )
                mode = "retrieval_fallback"
                degraded_result = self.citation_pipeline.build_degraded_citations(
                    request,
                    profile,
                    query_text=effective_question,
                    auth_context=auth_context,
                )
                if degraded_result is not None and degraded_result.citations:
                    citations = degraded_result.citations
                    rerank_strategy = degraded_result.rerank_strategy
                    downgraded_from = profile.mode
                    citation_details = dict(degraded_result.details)
                if not self.system_config_service.get_degrade_controls().retrieval_fallback_enabled:
                    error_message = str(exc)
                    self._append_trace_stage(
                        trace_stages,
                        stage="answer",
                        status="failed",
                        duration_ms=0,
                        input_size=len(citations),
                        output_size=0,
                        details={"error_message": error_message, "streaming": True},
                    )
                    yield self._to_sse(
                        "error",
                        self._build_stream_error_payload(
                            code="llm_retryable",
                            message=error_message,
                            retryable=True,
                        ),
                    )
                    return
                fallback_answer = self._build_retrieval_fallback_answer(citations)
                answer_parts = []
                for delta in self._chunk_text(fallback_answer):
                    answer_parts.append(delta)
                    yield self._to_sse("answer_delta", self._build_stream_delta_payload(delta))
                answer = "".join(answer_parts)
                answer_text = answer
            except LLMGenerationFatalError as exc:  # 客户端错误/协议错误：流里返回 error 事件并结束。
                error_message = str(exc)
                answer_text = "".join(answer_parts).strip()
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="failed",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=0,
                    cache_hit=False,
                    details={"error_message": error_message, "model": model, "streaming": True},
                )
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="failed",
                    duration_ms=0,
                    input_size=len(citations),
                    output_size=0,
                    details={"error_message": error_message},
                )
                yield self._to_sse(
                    "error",
                    self._build_stream_error_payload(
                        code="llm_fatal",
                        message=error_message,
                    ),
                )
                return
            except Exception as exc:  # 已经开始推流后，任何未预期异常都要收口成 error 事件，避免浏览器只看到中断。
                error_message = str(exc) or "Unexpected stream error."
                answer_text = "".join(answer_parts).strip()
                self._append_trace_stage(
                    trace_stages,
                    stage="llm",
                    status="failed",
                    duration_ms=self._elapsed_ms(llm_started_at),
                    input_size=len(contexts),
                    output_size=0,
                    cache_hit=False,
                    details={"error_message": error_message, "model": model, "streaming": True, "unexpected_error": True},
                )
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="failed",
                    duration_ms=0,
                    input_size=len(citations),
                    output_size=0,
                    details={"error_message": error_message, "unexpected_error": True},
                )
                yield self._to_sse(
                    "error",
                    self._build_stream_error_payload(
                        code="unexpected_error",
                        message=error_message,
                    ),
                )
                return

            response = self._build_response(  # 发送最终 done 事件，包含完整结构化响应。
                question=request.question,
                answer=answer,
                mode=mode,
                citations=citations,
                model=model,
            )
            response_mode = response.mode
            answer_text = response.answer
            self._append_trace_stage(
                trace_stages,
                stage="answer",
                status="degraded" if downgraded_from else "success",
                duration_ms=0,
                input_size=len(citations),
                output_size=len(response.answer),
                details={"response_mode": response.mode, "model": response.model, "streaming": True},
            )
            yield self._to_sse("done", response.model_dump())
        except RuntimeGateBusyError as exc:
            error_message = exc.detail
            runtime_details = {
                **runtime_details,
                "runtime_channel": exc.channel,
                "busy_rejected": True,
                "busy_rejected_reason": exc.reason,
                "retry_after_seconds": exc.retry_after_seconds,
            }
            self._append_trace_stage(
                trace_stages,
                stage="answer",
                status="failed",
                duration_ms=0,
                input_size=len(citations),
                output_size=0,
                details={"error_message": error_message, **runtime_details},
            )
            yield self._to_sse(
                "error",
                self._build_stream_error_payload(
                    code="busy",
                    message=error_message,
                    retryable=True,
                    retry_after_seconds=exc.retry_after_seconds,
                ),
            )
            return
        except Exception as exc:
            error_message = str(exc)
            if not self._has_answer_stage(trace_stages):
                self._append_trace_stage(
                    trace_stages,
                    stage="answer",
                    status="failed",
                    duration_ms=0,
                    input_size=len(citations),
                    output_size=0,
                    details={"error_message": error_message, **runtime_details},
                )
            raise
        finally:
            if runtime_lease is not None:
                runtime_lease.release()
            outcome = "failed" if error_message else "success"
            self.telemetry_recorder.record_chat_event(
                action="stream_answer",
                outcome=outcome,
                request=request,
                profile=profile,
                auth_context=auth_context,
                response_mode=response_mode,
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                error_message=error_message,
                details={"streaming": True, **citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
                trace_id=trace_id,
                request_id=request_id,
            )
            self.telemetry_recorder.record_chat_trace(
                action="stream_answer",
                request=request,
                profile=profile,
                auth_context=auth_context,
                trace_id=trace_id,
                request_id=request_id,
                stages=trace_stages,
                outcome=outcome,
                response_mode=response_mode,
                citation_count=len(citations),
                rerank_strategy=rerank_strategy,
                duration_ms=self._elapsed_ms(started_at),
                downgraded_from=downgraded_from,
                error_message=error_message,
                model=model,
                details={"streaming": True, **citation_details, **runtime_details},
                rewrite_result=rewrite_result,
            )
            self.telemetry_recorder.record_chat_snapshot(
                action="stream_answer",
                request=request,
                profile=profile,
                auth_context=auth_context,
                trace_id=trace_id,
                request_id=request_id,
                outcome=outcome,
                response_mode=response_mode,
                citations=citations,
                rerank_strategy=rerank_strategy,
                model=model,
                answer_text=answer_text,
                downgraded_from=downgraded_from,
                error_message=error_message,
                details={"streaming": True, **citation_details, **runtime_details},
                memory_summary=memory_summary,
                rewrite_result=rewrite_result,
            )
            self.telemetry_recorder.record_memory_turn(
                request=request,
                auth_context=auth_context,
                answer_text=answer_text,
                response_mode=response_mode,
                citation_count=len(citations),
                error_message=error_message,
            )

    def _acquire_chat_runtime_slot(
        self,
        profile: QueryProfile,
        *,
        auth_context: AuthContext | None = None,
    ) -> tuple[QueryProfile, RuntimeGateLease, str | None, dict[str, object]]:
        concurrency_controls = self.system_config_service.get_concurrency_controls()
        primary_channel = "chat_accurate" if profile.mode == "accurate" else "chat_fast"
        owner_key = self._runtime_owner_key(auth_context)
        primary_lease, primary_reject_reason = self.runtime_gate_service.acquire_with_reason(
            primary_channel,
            timeout_ms=concurrency_controls.acquire_timeout_ms,
            owner_key=owner_key,
        )
        if primary_lease is not None:
            return (
                profile,
                primary_lease,
                None,
                {
                    "runtime_channel": primary_channel,
                    "acquire_timeout_ms": concurrency_controls.acquire_timeout_ms,
                    "runtime_owner_key": owner_key,
                },
            )

        fallback_profile = self.query_profile_service.build_fallback_profile(profile)
        if primary_channel == "chat_accurate" and fallback_profile is not None and primary_reject_reason != "user_limit":
            fallback_channel = "chat_fast"
            fallback_lease, _ = self.runtime_gate_service.acquire_with_reason(
                fallback_channel,
                timeout_ms=concurrency_controls.acquire_timeout_ms,
                owner_key=owner_key,
            )
            if fallback_lease is not None:
                return (
                    fallback_profile,
                    fallback_lease,
                    profile.mode,
                    {
                        "runtime_channel": fallback_channel,
                        "runtime_busy_fallback": True,
                        "acquire_timeout_ms": concurrency_controls.acquire_timeout_ms,
                        "runtime_owner_key": owner_key,
                    },
                )

        raise RuntimeGateBusyError(
            detail=self._busy_detail_for_chat_channel(primary_channel, reject_reason=primary_reject_reason or "channel_limit"),
            channel=primary_channel,
            reason=primary_reject_reason or "channel_limit",
            retry_after_seconds=concurrency_controls.busy_retry_after_seconds,
            requested_mode=profile.mode,
        )

    @staticmethod
    def _busy_detail_for_chat_channel(channel: str, *, reject_reason: str) -> str:
        if reject_reason == "user_limit":
            return "System is busy. Your concurrent request limit is reached. Wait for an earlier request to finish and retry."
        if channel == "chat_accurate":
            return "System is busy. Accurate chat capacity is saturated. Retry later or switch to fast mode."
        return "System is busy. Fast chat capacity is saturated. Retry later."

    @staticmethod
    def _runtime_owner_key(auth_context: AuthContext | None) -> str | None:
        if auth_context is None:
            return None
        return auth_context.user.user_id

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))

    @staticmethod
    def _new_trace_identifiers() -> tuple[str, str]:
        return f"trc_{uuid4().hex[:16]}", f"req_{uuid4().hex[:16]}"

    @staticmethod
    def _has_answer_stage(stages: list[RequestTraceStage]) -> bool:
        return any(stage.stage == "answer" for stage in stages)

    @staticmethod
    def _append_trace_stage(
        stages: list[RequestTraceStage],
        *,
        stage: str,
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

    def _build_response(
        self,
        *,
        question: str,
        answer: str,
        mode: str,
        citations: list[Citation],
        model: str,
    ) -> ChatResponse:  # 统一构造标准问答响应。
        return ChatResponse(
            question=question,
            answer=answer,
            mode=mode,
            model=model,
            citations=citations,
        )

    def _build_no_context_response(self, question: str, citations: list[Citation]) -> ChatResponse:  # 构造无上下文响应。
        return ChatResponse(
            question=question,
            answer="No uploaded documents are available yet. Upload a document before asking questions.",
            mode="no_context",
            model=self._response_model_name(),
            citations=citations,
        )

    def _response_model_name(self, *, profile: QueryProfile | None = None) -> str:  # 根据 provider 返回当前响应里的模型标识。
        if self.settings.llm_provider.lower().strip() == "mock":  # mock 模式下直接返回 mock。
            return "mock"  # 返回 mock 作为模型名称。
        resolved_profile = profile or self.query_profile_service.resolve(purpose="chat")
        return self.system_config_service.get_llm_model_for_request(
            purpose=resolved_profile.purpose,
            mode=resolved_profile.mode,
        )

    @staticmethod
    def _build_retrieval_fallback_answer(citations: list[Citation]) -> str:  # 当 LLM 不可用时，基于引用内容生成兜底回答。
        lines = ["Generation model is unavailable. Returning evidence-based summary:"]  # 先写固定开头。
        for index, citation in enumerate(citations[:2], start=1):  # 最多引用前两条，避免回答过长。
            snippet = citation.snippet.strip().replace("\n", " ")  # 清理换行，避免格式杂乱。
            if len(snippet) > 180:  # 片段过长时截断。
                snippet = f"{snippet[:177]}..."
            lines.append(f"{index}. {snippet}")  # 追加编号片段摘要。
        return "\n".join(lines)  # 返回多行文本结果。

    def _build_memory_summary(
        self,
        *,
        request: ChatRequest,
        auth_context: AuthContext | None,
    ) -> str | None:
        return self.chat_memory_service.build_memory_summary(
            session_id=request.session_id,
            auth_context=auth_context,
            document_id=request.document_id,
        )

    def _rewrite_question(
        self,
        *,
        request: ChatRequest,
        auth_context: AuthContext | None,
    ) -> QueryRewriteResult:
        return self.query_rewrite_service.rewrite_chat_question(
            question=request.question,
            session_id=request.session_id,
            auth_context=auth_context,
            document_id=request.document_id,
        )

    @staticmethod
    def _to_sse(event: str, payload: dict[str, object]) -> str:  # 把事件和数据编码成标准 SSE 格式。
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _to_sse_comment(comment: str) -> str:  # 发送标准 SSE comment，不影响主契约事件类型，只用于提前 flush 首字节。
        return f": {comment}\n\n"

    @staticmethod
    def _build_meta_payload(response: ChatResponse) -> dict[str, object]:  # 从最终响应提取前端流式渲染所需元数据。
        return ChatStreamMetaPayload(
            question=response.question,
            mode=response.mode,
            model=response.model,
            citations=response.citations,
        ).model_dump(mode="json")

    @staticmethod
    def _build_stream_delta_payload(delta: str) -> dict[str, object]:
        return ChatStreamDeltaPayload(delta=delta).model_dump(mode="json")

    @staticmethod
    def _build_stream_error_payload(
        *,
        code: str,
        message: str,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> dict[str, object]:
        return ChatStreamErrorPayload(
            code=code,  # type: ignore[arg-type]
            message=message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        ).model_dump(mode="json")

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 32) -> Iterator[str]:  # 把文本切成小片段，流式输出兜底内容。
        safe_size = max(1, chunk_size)
        for start in range(0, len(text), safe_size):
            yield text[start : start + safe_size]


def get_chat_service() -> ChatService:  # 提供 FastAPI 依赖注入入口。
    return ChatService()  # 返回一个问答服务实例。
