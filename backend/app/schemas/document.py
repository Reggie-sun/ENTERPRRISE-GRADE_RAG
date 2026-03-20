from datetime import datetime  # 导入 datetime，用于声明时间字段类型。
from typing import Literal  # 导入 Literal，用于限制状态字段可选值。

from pydantic import BaseModel, Field  # 导入 Pydantic 基类和字段约束工具。

Visibility = Literal["public", "department", "role", "private"]  # 定义 ACL 可见性枚举。
Classification = Literal["public", "internal", "confidential", "secret"]  # 定义密级枚举。
DocumentLifecycleStatus = Literal["queued", "uploaded", "active", "failed", "partial_failed"]  # 定义文档生命周期状态。
IngestJobStatus = Literal[
    "pending",
    "uploaded",
    "queued",
    "parsing",
    "ocr_processing",
    "chunking",
    "embedding",
    "indexing",
    "completed",
    "failed",
    "dead_letter",
    "partial_failed",
]  # 定义 ingest job 状态枚举。
IngestErrorCode = Literal[
    "INGEST_DISPATCH_ERROR",
    "INGEST_DISPATCH_ERROR_DEAD_LETTER",
    "INGEST_VALIDATION_ERROR",
    "INGEST_VALIDATION_ERROR_DEAD_LETTER",
    "INGEST_RUNTIME_ERROR",
    "INGEST_RUNTIME_ERROR_DEAD_LETTER",
]  # 定义 ingest job 错误码枚举。


class DocumentCreateResponse(BaseModel):  # 定义 POST /documents 的响应结构。
    doc_id: str  # 新创建文档的唯一标识。
    job_id: str  # 本次入库任务的唯一标识。
    status: Literal["queued"] = "queued"  # 当前创建结果固定为 queued。


class DocumentRecord(BaseModel):  # 定义 document 元数据持久化结构。
    doc_id: str  # 文档唯一标识。
    tenant_id: str  # 文档所属租户。
    file_name: str  # 原始文件名。
    file_hash: str  # 文件内容的 sha256 哈希。
    source_type: str  # 文档来源类型，例如 pdf/txt/md。
    department_ids: list[str] = Field(default_factory=list)  # 文档所属部门范围。
    role_ids: list[str] = Field(default_factory=list)  # 文档所属角色范围。
    owner_id: str | None = None  # 文档 owner。
    visibility: Visibility = "private"  # 可见性策略。
    classification: Classification = "internal"  # 文档密级。
    tags: list[str] = Field(default_factory=list)  # 文档标签。
    source_system: str | None = None  # 文档来源系统。
    status: DocumentLifecycleStatus = "queued"  # 当前文档状态。
    current_version: int = Field(default=1, ge=1)  # 当前文档版本。
    latest_job_id: str  # 最近一次入库任务 ID。
    storage_path: str  # 原始文件落盘路径。
    created_by: str | None = None  # 上传人。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 更新时间。


class DocumentDetailResponse(BaseModel):  # 定义 GET /documents/{doc_id} 的响应结构。
    doc_id: str  # 文档唯一标识。
    file_name: str  # 原始文件名。
    status: DocumentLifecycleStatus  # 当前文档状态。
    current_version: int = Field(ge=1)  # 当前版本。
    latest_job_id: str  # 最近一次入库任务 ID。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 更新时间。


class IngestJobRecord(BaseModel):  # 定义 ingest job 元数据持久化结构。
    job_id: str  # 任务唯一标识。
    doc_id: str  # 关联文档 ID。
    version: int = Field(default=1, ge=1)  # 关联文档版本。
    file_name: str  # 文档文件名。
    status: IngestJobStatus = "queued"  # 当前任务状态。
    stage: str = "queued"  # 当前阶段。
    progress: int = Field(default=0, ge=0, le=100)  # 任务进度百分比。
    retry_count: int = Field(default=0, ge=0)  # 当前重试次数。
    error_code: IngestErrorCode | None = None  # 错误码。
    error_message: str | None = None  # 错误描述。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 更新时间。


class IngestJobStatusResponse(BaseModel):  # 定义 GET /ingest/jobs/{job_id} 的响应结构。
    job_id: str  # 任务唯一标识。
    doc_id: str  # 关联文档 ID。
    status: IngestJobStatus  # 当前状态。
    progress: int = Field(ge=0, le=100)  # 当前进度百分比。
    stage: str  # 当前阶段名。
    retry_count: int = Field(ge=0)  # 重试次数。
    max_retry_limit: int = Field(ge=1)  # 进入 dead_letter 前允许的最大失败次数。
    auto_retry_eligible: bool  # 当前是否还处于自动重试窗口内。
    manual_retry_allowed: bool  # 当前是否允许通过管理接口手动重投递。
    error_code: IngestErrorCode | None = None  # 错误码。
    error_message: str | None = None  # 错误描述。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 更新时间。


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
