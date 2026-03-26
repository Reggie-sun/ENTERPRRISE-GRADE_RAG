from pydantic import AliasChoices, BaseModel, Field  # 导入 Pydantic 基类、字段约束和别名工具。

from .query_profile import QueryMode


class ChatRequest(BaseModel):  # 定义问答接口的请求体结构。
    question: str = Field(min_length=1, max_length=4000)  # 用户输入的问题文本，限制最短和最长长度。
    top_k: int | None = Field(default=None, ge=1, le=20)  # 可选覆盖默认档位的返回数量；为空时由 fast/accurate 档位决定。
    mode: QueryMode | None = Field(default=None)  # 可选查询档位；为空时问答默认走 fast。
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("document_id", "doc_id"),  # 兼容历史客户端传 doc_id，统一归一到 document_id。
        serialization_alias="document_id",
    )  # 可选文档过滤条件，只在指定文档范围内召回引用。


class Citation(BaseModel):  # 定义回答里每条引用片段的结构。
    chunk_id: str  # 当前引用片段的 chunk 唯一标识。
    document_id: str  # 当前片段所属文档的唯一标识。
    document_name: str  # 当前片段所属文档名。
    snippet: str  # 当前引用片段的文本内容。
    score: float  # 当前片段的匹配分数。
    source_path: str  # 当前片段原始文件的路径。


class ChatResponse(BaseModel):  # 定义问答接口的响应体结构。
    question: str  # 原始用户问题。
    answer: str  # 生成出的回答内容。
    mode: str  # 当前回答模式，例如 rag / retrieval_fallback / no_context。
    model: str  # 当前使用的生成模型名称。
    citations: list[Citation]  # 回答中附带的引用片段列表。
