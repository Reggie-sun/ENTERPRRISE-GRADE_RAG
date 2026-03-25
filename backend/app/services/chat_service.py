import json  # 导入 json，用于序列化 SSE 事件数据。
from typing import Iterator  # 导入 Iterator，用于声明流式输出类型。

from ..core.config import Settings, get_llm_model, get_settings  # 导入配置对象和配置获取函数。
from ..rag.generators.client import (  # 导入 LLM 生成客户端和异常类型。
    LLMGenerationClient,
    LLMGenerationFatalError,
    LLMGenerationRetryableError,
)
from ..rag.rerankers.client import RerankerClient  # 导入 rerank 客户端。
from ..schemas.chat import ChatRequest, ChatResponse, Citation  # 导入问答请求、响应和引用片段模型。
from ..schemas.retrieval import RetrievalRequest  # 导入检索请求模型，问答前要先做检索。
from .retrieval_service import RetrievalService  # 导入检索服务。


class ChatService:  # 封装问答接口的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化问答服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.retrieval_service = RetrievalService(self.settings)  # 创建检索服务实例，问答前先做召回。
        self.reranker_client = RerankerClient(self.settings)  # 创建 rerank 客户端，做二次排序。
        self.generation_client = LLMGenerationClient(self.settings)  # 创建生成客户端，负责最终回答。

    def answer(self, request: ChatRequest) -> ChatResponse:  # 根据用户问题生成问答响应。
        citations = self._build_citations(request)  # 先统一构造引用列表。
        if not citations:  # 如果连引用都没有，说明还没有可用上下文。
            return self._build_no_context_response(request.question, citations)  # 直接返回无上下文响应。

        contexts = [citation.snippet for citation in citations]  # 提取引用文本，作为生成模型的上下文输入。
        try:  # 优先调用 LLM 生成最终回答。
            answer = self.generation_client.generate(  # 执行回答生成。
                question=request.question,  # 传入用户问题。
                contexts=contexts,  # 传入检索证据上下文。
            )
            mode = "rag"  # 生成成功时标记为完整 RAG 模式。
        except LLMGenerationRetryableError:  # 仅在可恢复的远程故障时走降级，避免吞掉配置或协议错误。
            answer = self._build_retrieval_fallback_answer(citations)  # 用引用片段拼一个稳定可读的兜底回答。
            mode = "retrieval_fallback"  # 标记为检索兜底模式。

        return self._build_response(  # 组装最终问答响应。
            question=request.question,
            answer=answer,
            mode=mode,
            citations=citations,
        )

    def stream_answer_sse(self, request: ChatRequest) -> Iterator[str]:  # 以 SSE 方式流式返回回答内容。
        citations = self._build_citations(request)  # 先统一构造引用列表。
        if not citations:  # 没有引用时直接返回无上下文 done 事件。
            response = self._build_no_context_response(request.question, citations)
            yield self._to_sse("meta", self._build_meta_payload(response))
            yield self._to_sse("done", response.model_dump())
            return

        mode = "rag"  # 默认先按 rag 模式流式生成。
        contexts = [citation.snippet for citation in citations]  # 提取上下文列表。
        model = self._response_model_name()  # 提前计算响应模型名，给 meta 事件复用。
        yield self._to_sse(  # 首帧先发元数据，前端可立即渲染模式和引用占位。
            "meta",
            {
                "question": request.question,
                "mode": mode,
                "model": model,
                "citations": [citation.model_dump() for citation in citations],
            },
        )

        answer_parts: list[str] = []  # 累积回答片段，最后拼成完整 answer。
        try:  # 尝试真实流式生成。
            for delta in self.generation_client.generate_stream(question=request.question, contexts=contexts):
                if not delta:
                    continue
                answer_parts.append(delta)
                yield self._to_sse("answer_delta", {"delta": delta})  # 每个片段都立即推给前端。
            answer = "".join(answer_parts).strip()  # 汇总完整回答文本。
            if not answer:  # 理论上不应为空，兜底避免前端停在 loading。
                answer = "No answer content was generated."
        except LLMGenerationRetryableError:  # 远端临时不可用时切回检索兜底，并保持流式输出形态。
            mode = "retrieval_fallback"
            fallback_answer = self._build_retrieval_fallback_answer(citations)
            answer_parts = []
            for delta in self._chunk_text(fallback_answer):
                answer_parts.append(delta)
                yield self._to_sse("answer_delta", {"delta": delta})
            answer = "".join(answer_parts)
        except LLMGenerationFatalError as exc:  # 客户端错误/协议错误：流里返回 error 事件并结束。
            yield self._to_sse("error", {"message": str(exc)})
            return

        response = self._build_response(  # 发送最终 done 事件，包含完整结构化响应。
            question=request.question,
            answer=answer,
            mode=mode,
            citations=citations,
        )
        yield self._to_sse("done", response.model_dump())

    def _build_citations(self, request: ChatRequest) -> list[Citation]:  # 统一执行检索+重排并产出引用列表。
        retrieval_result = self.retrieval_service.search(  # 先调用检索服务拿候选片段。
            RetrievalRequest(  # 把问答请求转换成检索请求。
                query=request.question,
                top_k=request.top_k,
                document_id=request.document_id,
            )
        )
        rerank_top_n = max(1, min(request.top_k, self.settings.rerank_top_n))  # 计算 rerank 后保留数量。
        try:  # 优先使用 reranker 对候选片段做重排。
            reranked_results = self.reranker_client.rerank(  # 执行 rerank。
                query=request.question,  # 传入用户问题。
                candidates=retrieval_result.results,  # 传入检索候选。
                top_n=rerank_top_n,  # 传入重排后的保留数量。
            )
        except RuntimeError:  # rerank 配置不正确或 provider 不可用时，回退到检索原顺序。
            reranked_results = retrieval_result.results[:rerank_top_n]  # 使用原始检索顺序做兜底。

        return [  # 把检索结果转换成问答响应里需要的引用结构。
            Citation(  # 为每条检索结果创建一条 Citation。
                chunk_id=result.chunk_id,  # 复制 chunk 唯一标识。
                document_id=result.document_id,  # 复制文档唯一标识。
                document_name=result.document_name,  # 复制文档名称。
                snippet=result.text,  # 把检索文本作为引用片段内容。
                score=result.score,  # 复制相似度分数。
                source_path=result.source_path,  # 复制原始文件路径。
            )
            for result in reranked_results  # 遍历 rerank 后的结果。
        ]

    def _build_response(self, *, question: str, answer: str, mode: str, citations: list[Citation]) -> ChatResponse:  # 统一构造标准问答响应。
        return ChatResponse(
            question=question,
            answer=answer,
            mode=mode,
            model=self._response_model_name(),
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

    def _response_model_name(self) -> str:  # 根据 provider 返回当前响应里的模型标识。
        if self.settings.llm_provider.lower().strip() == "mock":  # mock 模式下直接返回 mock。
            return "mock"  # 返回 mock 作为模型名称。
        return get_llm_model(self.settings)  # 其他模式返回当前生效的模型名。

    @staticmethod
    def _build_retrieval_fallback_answer(citations: list[Citation]) -> str:  # 当 LLM 不可用时，基于引用内容生成兜底回答。
        lines = ["Generation model is unavailable. Returning evidence-based summary:"]  # 先写固定开头。
        for index, citation in enumerate(citations[:2], start=1):  # 最多引用前两条，避免回答过长。
            snippet = citation.snippet.strip().replace("\n", " ")  # 清理换行，避免格式杂乱。
            if len(snippet) > 180:  # 片段过长时截断。
                snippet = f"{snippet[:177]}..."
            lines.append(f"{index}. {snippet}")  # 追加编号片段摘要。
        return "\n".join(lines)  # 返回多行文本结果。

    @staticmethod
    def _to_sse(event: str, payload: dict[str, object]) -> str:  # 把事件和数据编码成标准 SSE 格式。
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _build_meta_payload(response: ChatResponse) -> dict[str, object]:  # 从最终响应提取前端流式渲染所需元数据。
        return {
            "question": response.question,
            "mode": response.mode,
            "model": response.model,
            "citations": [citation.model_dump() for citation in response.citations],
        }

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 32) -> Iterator[str]:  # 把文本切成小片段，流式输出兜底内容。
        safe_size = max(1, chunk_size)
        for start in range(0, len(text), safe_size):
            yield text[start : start + safe_size]


def get_chat_service() -> ChatService:  # 提供 FastAPI 依赖注入入口。
    return ChatService()  # 返回一个问答服务实例。
