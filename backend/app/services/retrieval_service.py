from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk  # 导入检索请求、响应和结果模型。
from .document_service import DocumentService  # 导入文档服务，用来获取已上传文档列表。


class RetrievalService:  # 封装文档检索接口的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化检索服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.document_service = DocumentService(self.settings)  # 创建文档服务实例，当前占位检索从文档列表构造结果。

    def search(self, request: RetrievalRequest) -> RetrievalResponse:  # 执行检索并返回结果。
        uploaded_documents = self.document_service.list_documents().items  # 先取出所有已上传文档。
        results: list[RetrievedChunk] = []  # 初始化检索结果列表。

        for index, document in enumerate(uploaded_documents[: request.top_k], start=1):  # 只取前 top_k 个文档构造占位结果。
            results.append(  # 把当前文档转换成一条占位检索结果。
                RetrievedChunk(  # 创建单条检索结果对象。
                    chunk_id=f"{document.document_id}-chunk-{index}",  # 用文档 ID 和序号拼一个占位 chunk_id。
                    document_id=document.document_id,  # 复制文档 ID。
                    document_name=document.filename,  # 复制文档名。
                    text=(  # 用说明性文本代替真实检索出的 chunk 内容。
                        f"Placeholder retrieval result for '{document.filename}'. "  # 说明这是一条占位结果。
                        "Vector search, embeddings, and rerank are not wired yet."  # 说明真实检索链路还没接。
                    ),
                    score=max(0.95 - index * 0.05, 0.5),  # 人工给一个递减分数，便于前端联调。
                    source_path=document.storage_path,  # 返回原始文件路径。
                )
            )

        return RetrievalResponse(  # 组装最终检索响应。
            query=request.query,  # 返回原始查询文本。
            top_k=request.top_k,  # 返回请求的 top_k。
            mode="placeholder",  # 当前模式是占位检索。
            results=results,  # 返回构造好的结果列表。
        )


def get_retrieval_service() -> RetrievalService:  # 提供 FastAPI 依赖注入入口。
    return RetrievalService()  # 返回一个检索服务实例。
