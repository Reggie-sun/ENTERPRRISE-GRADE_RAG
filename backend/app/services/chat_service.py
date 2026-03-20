from ..core.config import Settings, get_llm_model, get_settings  # 导入配置对象和配置获取函数。
from ..rag.generators.client import LLMGenerationClient, LLMGenerationRetryableError  # 导入 LLM 生成客户端和可降级异常类型。
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
        retrieval_result = self.retrieval_service.search(  # 先调用检索服务拿候选片段。
            RetrievalRequest(query=request.question, top_k=request.top_k)  # 把问答请求转换成检索请求。
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

        citations = [  # 把检索结果转换成问答响应里需要的引用结构。
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

        if not citations:  # 如果连引用都没有，说明还没有可用上下文。
            return ChatResponse(  # 直接返回 no_context 响应。
                question=request.question,  # 返回原始问题。
                answer="No uploaded documents are available yet. Upload a document before asking questions.",  # 返回提示信息。
                mode="no_context",  # 标记当前模式为无上下文。
                model=self._response_model_name(),  # 返回当前模型标识。
                citations=citations,  # 引用列表为空。
            )

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

        return ChatResponse(  # 组装最终问答响应。
            question=request.question,  # 返回原始问题。
            answer=answer,  # 返回回答文本。
            mode=mode,  # 返回本次回答的模式标识。
            model=self._response_model_name(),  # 返回当前配置的生成模型名称。
            citations=citations,  # 返回引用片段列表。
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


def get_chat_service() -> ChatService:  # 提供 FastAPI 依赖注入入口。
    return ChatService()  # 返回一个问答服务实例。
