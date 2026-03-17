from pydantic import BaseModel, Field  # 导入 Pydantic 基类和字段约束工具。


class ChatRequest(BaseModel):  # 定义问答接口的请求体结构。
    question: str = Field(min_length=1, max_length=4000)  # 用户输入的问题文本，限制最短和最长长度。
    top_k: int = Field(default=5, ge=1, le=20)  # 检索阶段返回的候选片段数量。


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
    mode: str  # 当前回答模式，例如 placeholder 或 real。
    model: str  # 当前使用的生成模型名称。
    citations: list[Citation]  # 回答中附带的引用片段列表。
