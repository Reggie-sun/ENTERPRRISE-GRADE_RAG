from datetime import datetime  # 导入 datetime，用于声明时间字段类型。
from typing import Literal  # 导入 Literal，用于限制状态字段可选值。

from pydantic import BaseModel, Field  # 导入 Pydantic 基类和字段约束工具。


class DocumentUploadResponse(BaseModel):  # 定义上传接口成功后的响应结构。
    document_id: str  # 上传文档的唯一标识。
    filename: str  # 原始文件名。
    content_type: str | None = None  # 文件 MIME 类型，可为空。
    size_bytes: int = Field(ge=0)  # 文件大小，单位是字节。
    status: Literal["ingested"] = "ingested"  # 当前上传状态，固定表示已完成入库。
    parse_supported: bool  # 当前文件类型是否属于系统支持解析的范围。
    storage_path: str  # 原始文件的落盘路径。
    parsed_path: str  # 解析后纯文本文件的路径。
    chunk_path: str  # chunk 结果 JSON 文件的路径。
    collection_name: str  # 向量写入的 Qdrant collection 名称。
    parser_name: str  # 本次使用的解析器名称。
    chunk_count: int = Field(ge=0)  # 本次生成的 chunk 数量。
    vector_count: int = Field(ge=0)  # 本次写入的向量数量。
    created_at: datetime  # 本次上传完成的时间。


class DocumentSummary(BaseModel):  # 定义文档列表里单个文档的摘要结构。
    document_id: str  # 文档唯一标识。
    filename: str  # 文档文件名。
    size_bytes: int = Field(ge=0)  # 文件大小。
    parse_supported: bool  # 该文件类型是否支持解析。
    storage_path: str  # 文件落盘路径。
    updated_at: datetime  # 文件最近更新时间。


class DocumentListResponse(BaseModel):  # 定义文档列表接口的响应结构。
    total: int = Field(ge=0)  # 文档总数。
    items: list[DocumentSummary]  # 文档摘要列表。
