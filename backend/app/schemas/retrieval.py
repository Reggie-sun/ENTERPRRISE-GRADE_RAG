from pydantic import BaseModel, Field  # 导入 Pydantic 基类和字段约束工具。


class RetrievalRequest(BaseModel):  # 定义检索接口的请求结构。
    query: str = Field(min_length=1, max_length=2000)  # 用户输入的检索问题。
    top_k: int = Field(default=5, ge=1, le=20)  # 要返回的检索结果数量。


class RetrievedChunk(BaseModel):  # 定义单条检索结果的结构。
    chunk_id: str  # chunk 唯一标识。
    document_id: str  # chunk 所属文档唯一标识。
    document_name: str  # chunk 所属文档名称。
    text: str  # chunk 文本内容。
    score: float  # chunk 匹配分数。
    source_path: str  # 原始文档路径。


class RetrievalResponse(BaseModel):  # 定义检索接口的响应结构。
    query: str  # 原始查询文本。
    top_k: int  # 本次请求的 top_k 值。
    mode: str  # 当前检索模式，例如 placeholder 或 real。
    results: list[RetrievedChunk]  # 返回的检索结果列表。
