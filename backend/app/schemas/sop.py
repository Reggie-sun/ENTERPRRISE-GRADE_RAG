from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SopStatus = Literal["draft", "active", "archived"]  # v0.4 先冻结最小 SOP 生命周期集合，避免过早引入审批流状态。
SopPreviewType = Literal["text", "html", "pdf"]  # 预览资源类型和下载资源分离，避免后续互相耦合。
SopDownloadFormat = Literal["docx", "pdf"]  # 当前下载格式先冻结为 Word/PDF。
_PREVIEW_URI_PREFIX = "preview://"
_DOWNLOAD_URI_PREFIX = "asset://"


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_str_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    deduped: list[str] = []
    for item in values:
        normalized = _normalize_optional_str(item)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


class SopRecord(BaseModel):  # SOP 主数据对象：独立于文档主对象，为列表/详情/下载提供稳定主键。
    sop_id: str
    tenant_id: str
    title: str = Field(min_length=1)
    department_id: str
    department_ids: list[str] = Field(default_factory=list)
    process_name: str | None = None
    scenario_name: str | None = None
    version: int = Field(default=1, ge=1)
    status: SopStatus = "active"
    preview_resource_path: str | None = None
    preview_resource_type: SopPreviewType = "text"
    preview_text_content: str | None = None
    download_docx_resource_path: str | None = None
    download_pdf_resource_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_document_id: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def normalize_scope_and_resources(self) -> "SopRecord":
        normalized_department_id = _normalize_optional_str(self.department_id)
        if normalized_department_id is None:
            raise ValueError("department_id must not be blank.")
        self.department_id = normalized_department_id

        normalized_department_ids = _normalize_str_list(self.department_ids)
        if not normalized_department_ids:
            normalized_department_ids = [normalized_department_id]
        elif normalized_department_id not in normalized_department_ids:
            normalized_department_ids = [normalized_department_id, *normalized_department_ids]
        self.department_ids = normalized_department_ids

        self.title = self.title.strip()
        self.process_name = _normalize_optional_str(self.process_name)
        self.scenario_name = _normalize_optional_str(self.scenario_name)
        self.preview_resource_path = _normalize_optional_str(self.preview_resource_path)
        self.preview_text_content = _normalize_optional_str(self.preview_text_content)
        self.download_docx_resource_path = _normalize_optional_str(self.download_docx_resource_path)
        self.download_pdf_resource_path = _normalize_optional_str(self.download_pdf_resource_path)
        self.tags = _normalize_str_list(self.tags)
        self.source_document_id = _normalize_optional_str(self.source_document_id)
        self.created_by = _normalize_optional_str(self.created_by)
        self.updated_by = _normalize_optional_str(self.updated_by)

        self._validate_preview_resource_path()
        self._validate_download_resource_path(self.download_docx_resource_path, "docx")
        self._validate_download_resource_path(self.download_pdf_resource_path, "pdf")

        if self.status == "active":
            if self.preview_resource_path is None:
                raise ValueError("active SOP requires preview_resource_path.")
            if self.download_docx_resource_path is None and self.download_pdf_resource_path is None:
                raise ValueError("active SOP requires at least one download resource path.")

        return self

    def _validate_preview_resource_path(self) -> None:
        if self.preview_resource_path is None:
            return
        if self.preview_resource_path.startswith(_DOWNLOAD_URI_PREFIX):
            raise ValueError("preview_resource_path must not use asset:// download scheme.")

    @staticmethod
    def _validate_download_resource_path(resource_path: str | None, download_format: str) -> None:
        if resource_path is None:
            return
        if resource_path.startswith(_PREVIEW_URI_PREFIX):
            raise ValueError(f"download_{download_format}_resource_path must not use preview:// scheme.")


class SopSummary(BaseModel):  # 列表摘要结构，给 SOP 列表页和门户卡片直接复用。
    sop_id: str
    title: str
    department_id: str
    department_name: str
    process_name: str | None = None
    scenario_name: str | None = None
    version: int = Field(ge=1)
    status: SopStatus
    preview_available: bool
    downloadable_formats: list[SopDownloadFormat] = Field(default_factory=list)
    updated_at: datetime


class SopDetailResponse(BaseModel):  # 详情模型先冻结好，后续 issue 只补接口不再改主字段语义。
    sop_id: str
    title: str
    tenant_id: str
    department_id: str
    department_name: str
    process_name: str | None = None
    scenario_name: str | None = None
    version: int = Field(ge=1)
    status: SopStatus
    preview_resource_path: str | None = None
    preview_resource_type: SopPreviewType
    download_docx_available: bool = False
    download_pdf_available: bool = False
    tags: list[str] = Field(default_factory=list)
    source_document_id: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class SopPreviewResponse(BaseModel):  # SOP 预览响应，和详情解耦，便于后续支持 PDF/HTML 文件流。
    sop_id: str
    title: str
    preview_type: SopPreviewType
    content_type: str
    text_content: str | None = None
    preview_file_url: str | None = None
    updated_at: datetime


class SopListResponse(BaseModel):  # SOP 列表响应结构，下一步接口层直接复用。
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    items: list[SopSummary]


class SopBootstrapData(BaseModel):  # 当前 v0.4 先用 bootstrap 文件承接已有 SOP 资产主数据。
    sops: list[SopRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_sop_id(self) -> "SopBootstrapData":
        sop_ids = [item.sop_id for item in self.sops]
        if len(set(sop_ids)) != len(sop_ids):
            raise ValueError("sop_id must be unique.")
        return self
