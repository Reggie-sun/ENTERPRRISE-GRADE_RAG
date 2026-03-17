from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..schemas.chat import ChatRequest, ChatResponse, Citation  # 导入问答请求、响应和引用片段模型。
from ..schemas.retrieval import RetrievalRequest  # 导入检索请求模型，问答前要先做检索。
from .retrieval_service import RetrievalService  # 导入检索服务。


class ChatService:  # 封装问答接口的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化问答服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.retrieval_service = RetrievalService(self.settings)  # 创建检索服务实例，问答前先做召回。

    def answer(self, request: ChatRequest) -> ChatResponse:  # 根据用户问题生成问答响应。
        retrieval_result = self.retrieval_service.search(  # 先调用检索服务拿候选片段。
            RetrievalRequest(query=request.question, top_k=request.top_k)  # 把问答请求转换成检索请求。
        )

        citations = [  # 把检索结果转换成问答响应里需要的引用结构。
            Citation(  # 为每条检索结果创建一条 Citation。
                chunk_id=result.chunk_id,  # 复制 chunk 唯一标识。
                document_id=result.document_id,  # 复制文档唯一标识。
                document_name=result.document_name,  # 复制文档名称。
                snippet=result.text,  # 把检索文本作为引用片段内容。
                score=result.score,  # 复制相似度分数。
                source_path=result.source_path,  # 复制原始文件路径。
            )
            for result in retrieval_result.results  # 遍历所有检索结果。
        ]

        if citations:  # 如果已经有检索结果，就返回一个占位回答。
            answer = (  # 当前还没接真实 LLM，所以这里只返回说明性质的文本。
                "This is a placeholder answer. The API flow is ready, but embeddings, "  # 说明主流程已经通了。
                "Qdrant retrieval, rerank, and Ollama generation still need to be connected."  # 说明还没完成的部分。
            )
        else:  # 如果连引用都没有，说明还没有可用文档。
            answer = "No uploaded documents are available yet. Upload a document before asking questions."  # 返回提示信息。

        return ChatResponse(  # 组装最终问答响应。
            question=request.question,  # 返回原始问题。
            answer=answer,  # 返回回答文本。
            mode="placeholder",  # 当前模式还是占位模式。
            model=self.settings.ollama_model,  # 返回当前配置的生成模型名称。
            citations=citations,  # 返回引用片段列表。
        )


def get_chat_service() -> ChatService:  # 提供 FastAPI 依赖注入入口。
    return ChatService()  # 返回一个问答服务实例。
