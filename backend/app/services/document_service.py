"""文档管理服务模块。

提供文档全生命周期管理：上传、创建、预览、下载、删除、向量重建。
支持重复文件检测、异步入库任务调度、部门数据隔离和 RBAC 权限控制。
同时兼容文件系统（JSON）和 PostgreSQL 两种元数据存储后端。

核心类:
    DocumentService — 文档服务，管理文档 CRUD、入库调度和权限校验。
"""

import hashlib
import importlib.util
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4
from zipfile import is_zipfile

from fastapi import HTTPException, UploadFile, status

from ..core.config import Settings, get_postgres_metadata_dsn, get_settings  # 导入配置对象和配置获取函数。
from ..db.postgres_metadata_store import PostgresMetadataStore  # 导入 PostgreSQL 元数据存储后端。
from ..schemas.auth import AuthContext  # 导入统一鉴权上下文。
from ..schemas.document import (
    Classification,  # 文档分类级别：internal / confidential / restricted 等。
    DocumentBatchCreateResponse,  # 批量创建响应。
    DocumentBatchItemResponse,  # 批量创建中单条结果。
    DocumentCreateResponse,  # 单文档创建响应。
    DocumentDeleteResponse,  # 文档删除响应。
    DocumentDetailResponse,  # 文档详情响应。
    DocumentLifecycleStatus,  # 文档生命周期状态类型。
    DocumentListResponse,  # 文档列表响应。
    DocumentPreviewResponse,  # 文档预览响应。
    DocumentRebuildResponse,  # 文档向量重建响应。
    DocumentRecord,  # 文档元数据记录（内部持久化结构）。
    DocumentSummary,  # 文档摘要（列表项）。
    DocumentUploadResponse,  # 同步上传响应。
    IngestJobRecord,  # 入库任务记录。
    IngestJobStatusResponse,  # 入库任务状态响应。
    Visibility,  # 文档可见性：private / department / public / role。
)
from ..schemas.ops import OpsStuckIngestJobSummary  # 运维接口：卡住的入库任务摘要。
from .asset_store import AssetStore  # 文件资产存储（本地文件系统管理）。
from .event_log_service import EventLogService, get_event_log_service  # 事件日志服务。
from .ingestion_service import DocumentIngestionService  # 文档入库服务（解析/OCR/切块/向量化）。
from .retrieval_scope_policy import (  # noqa: F401 — 向后兼容重新导出
    DepartmentPriorityRetrievalScope,
    RetrievalScopePolicy,
)
from ..rag.parsers.document_parser import SUPPORTED_PARSE_SUFFIXES, find_libreoffice_binary  # 导入解析器支持的扩展名和 LibreOffice 检测。
from ..worker.celery_app import dispatch_ingest_job  # 导入 Celery 任务调度函数。

# ===== 文件类型与状态常量 =====

SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 允许上传的扩展名 = 可解析的扩展名，保持一致
TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown"}  # 纯文本类：直接读取原文预览
PARSED_TEXT_PREVIEW_SUFFIXES = {".doc", ".docx", ".csv", ".html", ".json", ".xlsx", ".pptx", ".xls"}  # Office 类：读取解析后的文本预览
PDF_PREVIEW_SUFFIXES = {".pdf"}  # PDF 类：通过 file streaming 预览
SUPPORTED_PREVIEW_SUFFIXES = TEXT_PREVIEW_SUFFIXES | PARSED_TEXT_PREVIEW_SUFFIXES | PDF_PREVIEW_SUFFIXES  # 所有支持预览的类型汇总
TEXT_PREVIEW_MAX_CHARS = 12_000  # 文本预览最大字符数
TEXT_PREVIEW_CONTENT_TYPE_BY_SUFFIX = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".doc": "text/plain; charset=utf-8",
    ".docx": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8",
    ".html": "text/plain; charset=utf-8",
    ".json": "text/plain; charset=utf-8",
    ".xlsx": "text/plain; charset=utf-8",
    ".pptx": "text/plain; charset=utf-8",
    ".xls": "text/plain; charset=utf-8",
}
DOCUMENT_CONTENT_TYPE_BY_SUFFIX = {  # 下载时使用的 MIME 类型映射
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
}
PROCESSING_JOB_STATUSES = {"parsing", "ocr_processing", "chunking", "embedding", "indexing"}  # 入库任务进行中的各阶段状态
IN_FLIGHT_JOB_STATUSES = {"pending", "uploaded", "queued"} | PROCESSING_JOB_STATUSES  # 所有未完成的状态（含待处理 + 进行中）
TERMINAL_JOB_STATUSES = {"completed", "dead_letter", "partial_failed"}  # 终态；partial_failed 表示有可用结果但存在 OCR 告警
IngestBaseErrorCode = Literal["INGEST_DISPATCH_ERROR", "INGEST_VALIDATION_ERROR", "INGEST_RUNTIME_ERROR"]  # 入库错误码基础类型
UPLOAD_READ_CHUNK_SIZE_BYTES = 1 * 1024 * 1024  # 上传文件读取分块大小：1MB
INGEST_ERROR_CODE_DISPATCH: IngestBaseErrorCode = "INGEST_DISPATCH_ERROR"  # 任务调度失败错误码
INGEST_ERROR_CODE_VALIDATION: IngestBaseErrorCode = "INGEST_VALIDATION_ERROR"  # 参数校验失败错误码
INGEST_ERROR_CODE_RUNTIME: IngestBaseErrorCode = "INGEST_RUNTIME_ERROR"  # 运行时错误码
DEAD_LETTER_ERROR_SUFFIX = "_DEAD_LETTER"  # 超过重试上限后追加的后缀，标记为死信
PDF_MAGIC_PREFIX = b"%PDF-"  # PDF 文件头魔数，用于校验上传文件确实是 PDF
ZIP_OFFICE_UPLOAD_LABELS = {  # Office 格式必须以 ZIP 容器包裹，用于上传时校验容器完整性
    ".docx": "DOCX",
    ".pptx": "PPTX",
    ".xlsx": "XLSX",
}


@dataclass(frozen=True)
class DocumentFilePayload:
    """文件下载/预览的返回载荷。

    根据存储方式不同，优先返回 path（直接文件路径，供静态文件服务），
    回退到 content（内存字节，适用于对象存储或远程存储）。
    """
    media_type: str  # MIME 类型，如 "application/pdf"
    filename: str  # 原始文件名
    path: Path | None = None  # 本地文件路径（优先使用）
    content: bytes | None = None  # 文件字节内容（path 不可用时回退）


def _dead_letter_error_code(base_error_code: IngestBaseErrorCode) -> str:
    """将基础错误码转为死信错误码，追加 _DEAD_LETTER 后缀。"""
    return f"{base_error_code}{DEAD_LETTER_ERROR_SUFFIX}"


def _sanitize_filename(filename: str) -> str:
    """清理文件名，移除特殊字符，保留字母/数字/点/下划线/短横线。

    优先保留原始扩展名；如果清理后基础名为空，回退到 'document'。
    """
    safe_name = Path(filename or "document").name
    suffix = Path(safe_name).suffix.lower()
    base_name = safe_name[: -len(suffix)] if suffix else safe_name

    cleaned_base = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name).strip("._-")  # 非法字符替换为下划线
    if not cleaned_base:
        cleaned_base = "document"  # 基础名为空时兜底

    cleaned_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix.lstrip("."))  # 扩展名也清理
    if cleaned_suffix:
        return f"{cleaned_base}.{cleaned_suffix}"

    # 扩展名为空时，整体再清理一次作为兜底
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name).strip("._")
    return fallback or "document"


def _normalize_optional_str(value: str | None) -> str | None:
    """标准化可选字符串：None 或去除首尾空白后的空字符串返回 None。"""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_list(values: list[str] | None) -> list[str]:
    """标准化可选列表：None 或空列表返回空列表，否则去除每个元素的空白并过滤空值。"""
    if not values:
        return []
    return [item.strip() for item in values if item and item.strip()]


class DocumentService:
    """文档管理服务核心类。

    负责：
    1. 文档 CRUD（创建、读取、预览、下载、删除）
    2. 入库任务调度（Celery 异步）和同步执行
    3. 部门数据隔离与 RBAC 权限控制
    4. 重复文件检测与智能复用
    5. 向量重建
    6. 部门优先检索作用域构建
    """
    def __init__(self, settings: Settings | None = None, *, event_log_service: EventLogService | None = None) -> None:
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置
        self.asset_store = AssetStore(self.settings)  # 文件资产存储（本地文件管理）
        self.ingestion_service = DocumentIngestionService(self.settings)  # 入库服务（解析/OCR/切块/向量化）
        self.event_log_service = event_log_service or get_event_log_service()  # 事件日志服务
        self.metadata_store: PostgresMetadataStore | None = None
        if self.settings.postgres_metadata_enabled:  # PostgreSQL 模式下初始化数据库连接
            dsn = get_postgres_metadata_dsn(self.settings)
            if not dsn:  # 启用 PostgreSQL 但未配置 DSN 时直接报错，避免静默失败
                raise RuntimeError("PostgreSQL metadata storage enabled but no DSN configured.")
            store = PostgresMetadataStore(dsn)
            store.ping()  # 连接探活
            store.ensure_required_tables()  # 确保所需表结构存在
            self.metadata_store = store

    # ===== 文档创建与上传 =====

    async def create_document(
        self,
        *,
        upload: UploadFile,
        tenant_id: str,
        department_id: str | None = None,
        department_ids: list[str] | None = None,
        retrieval_department_ids: list[str] | None = None,
        category_id: str | None = None,
        role_ids: list[str] | None = None,
        owner_id: str | None = None,
        visibility: Visibility = "private",
        classification: Classification = "internal",
        tags: list[str] | None = None,
        source_system: str | None = None,
        uploaded_by: str | None = None,
        created_by: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> DocumentCreateResponse:
        """创建文档（主入口）。

        流程：
        1. 读取上传内容，校验文件类型和大小
        2. 标准化参数，执行权限校验
        3. 计算文件哈希，检测同租户重复
        4. 有重复 → 智能复用已有文档/任务
        5. 无重复 → 创建新 DocumentRecord + IngestJobRecord
        6. 保存元数据，调度入库任务
        7. 记录事件日志

        返回：DocumentCreateResponse（包含 doc_id, job_id, status）
        """
        started_at = perf_counter()
        # --- 1. 读取上传内容 ---
        filename, suffix, content = await self._read_upload_content(upload)

        # --- 2. 标准化参数 ---
        normalized_tenant_id = _normalize_optional_str(tenant_id)
        if normalized_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must not be blank.")
        normalized_department_id = _normalize_optional_str(department_id)
        normalized_department_ids = _normalize_optional_list(department_ids)
        if normalized_department_id and normalized_department_id not in normalized_department_ids:
            normalized_department_ids = [normalized_department_id, *normalized_department_ids]  # 主部门必须在列表中
        if normalized_department_id is None and normalized_department_ids:
            normalized_department_id = normalized_department_ids[0]  # 取列表第一个作为主部门
        normalized_retrieval_department_ids = _normalize_optional_list(retrieval_department_ids)
        normalized_category_id = _normalize_optional_str(category_id)
        normalized_role_ids = _normalize_optional_list(role_ids)
        normalized_tags = _normalize_optional_list(tags)
        normalized_owner_id = _normalize_optional_str(owner_id)
        normalized_source_system = _normalize_optional_str(source_system)
        normalized_uploaded_by = _normalize_optional_str(uploaded_by)
        normalized_created_by = _normalize_optional_str(created_by)
        effective_uploaded_by = normalized_uploaded_by or normalized_created_by  # 上传人兜底
        effective_created_by = normalized_created_by or normalized_uploaded_by  # 创建人兜底

        # --- 3. 权限校验 ---
        (
            normalized_tenant_id,
            normalized_department_id,
            normalized_department_ids,
            effective_uploaded_by,
            effective_created_by,
        ) = self._enforce_document_create_scope(
            auth_context,
            tenant_id=normalized_tenant_id,
            department_id=normalized_department_id,
            department_ids=normalized_department_ids,
            uploaded_by=effective_uploaded_by,
            created_by=effective_created_by,
        )

        # --- 4. 重复文件检测 ---
        file_hash = hashlib.sha256(content).hexdigest()
        duplicate_record = self._find_document_record_by_file_hash(file_hash, tenant_id=normalized_tenant_id)  # 同租户下命中相同内容时直接复用已有文档
        if duplicate_record is not None and duplicate_record.status == "deleted":
            duplicate_record = None  # 已删除的文档不算重复

        if duplicate_record is not None:
            # --- 4a. 有重复：智能复用 ---
            latest_job_record = self._load_latest_job_record(duplicate_record.latest_job_id)
            self._refresh_duplicate_document_source(
                duplicate_record,
                content=content,
                filename=filename,
                source_type=suffix.lstrip(".") or "unknown",
                uploaded_by=effective_uploaded_by,
                created_by=effective_created_by,
            )  # 重复上传默认按"覆盖旧文档"处理：更新文件名、来源类型、上传人等

            # 情况 A：旧任务还在进行中，但解析产物已存在 → 直接标记为已完成
            if latest_job_record is not None and latest_job_record.status in IN_FLIGHT_JOB_STATUSES and self._has_materialized_ingest_artifacts(duplicate_record.doc_id):
                self._update_job_record(
                    latest_job_record,
                    status="completed",
                    stage="completed",
                    progress=100,
                )
                duplicate_record.status = "active"
                self._save_document_record(duplicate_record)
                self._record_document_event(
                    action="create",
                    outcome="success",
                    auth_context=auth_context,
                    doc_id=duplicate_record.doc_id,
                    job_id=duplicate_record.latest_job_id,
                    duration_ms=self._elapsed_ms(started_at),
                    details={
                        "file_name": filename,
                        "duplicate": True,
                        "reused_job": True,
                        "reused_completed": True,
                        "repaired_stuck_job": True,
                    },
                )
                return DocumentCreateResponse(doc_id=duplicate_record.doc_id, job_id=duplicate_record.latest_job_id, status="completed")

            # 情况 B：旧任务已完成，检查产物是否存在
            if latest_job_record is not None and latest_job_record.status == "completed":
                if not self._has_materialized_ingest_artifacts(duplicate_record.doc_id):
                    # 产物丢失 → 创建 follow-up 任务重新入库
                    followup_job = self._create_followup_ingest_job(duplicate_record)
                    self._record_document_event(
                        action="create",
                        outcome="success",
                        auth_context=auth_context,
                        doc_id=duplicate_record.doc_id,
                        job_id=followup_job.job_id,
                        duration_ms=self._elapsed_ms(started_at),
                        details={"file_name": filename, "duplicate": True, "reused_job": False, "recompleted": True},
                    )
                    return DocumentCreateResponse(doc_id=duplicate_record.doc_id, job_id=followup_job.job_id, status="queued")
                # 产物存在 → 直接复用
                self._save_document_record(duplicate_record)
                self._record_document_event(
                    action="create",
                    outcome="success",
                    auth_context=auth_context,
                    doc_id=duplicate_record.doc_id,
                    job_id=duplicate_record.latest_job_id,
                    duration_ms=self._elapsed_ms(started_at),
                    details={"file_name": filename, "duplicate": True, "reused_job": True, "reused_completed": True},
                )
                return DocumentCreateResponse(doc_id=duplicate_record.doc_id, job_id=duplicate_record.latest_job_id, status="completed")

            # 情况 C：旧任务仍在活跃进行中 → 复用（避免重复入库）
            if self._should_reuse_inflight_job(latest_job_record):
                self._save_document_record(duplicate_record)
                self._record_document_event(
                    action="create",
                    outcome="success",
                    auth_context=auth_context,
                    doc_id=duplicate_record.doc_id,
                    job_id=duplicate_record.latest_job_id,
                    duration_ms=self._elapsed_ms(started_at),
                    details={"file_name": filename, "duplicate": True, "reused_job": True},
                )
                return DocumentCreateResponse(doc_id=duplicate_record.doc_id, job_id=duplicate_record.latest_job_id, status="queued")

            # 情况 D：旧任务已终止（failed/dead_letter）→ 创建 follow-up 任务
            followup_job = self._create_followup_ingest_job(duplicate_record)
            self._record_document_event(
                action="create",
                outcome="success",
                auth_context=auth_context,
                doc_id=duplicate_record.doc_id,
                job_id=followup_job.job_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"file_name": filename, "duplicate": True, "reused_job": False},
            )
            return DocumentCreateResponse(doc_id=duplicate_record.doc_id, job_id=followup_job.job_id, status="queued")

        # --- 5. 无重复：创建新文档和新入库任务 ---
        now = datetime.now(timezone.utc)
        doc_id = self._generate_entity_id("doc")  # 生成文档 ID：doc_20260331120000_abc12345
        job_id = self._generate_entity_id("job")  # 生成任务 ID：job_20260331120000_def67890
        target_name = f"{doc_id}__{_sanitize_filename(filename)}"  # 存储文件名：doc_xxx__原始文件名.txt
        storage_path = self.asset_store.save_upload(
            doc_id=doc_id,
            target_name=target_name,
            file_name=filename,
            content=content,
            mime_type=upload.content_type,
            job_id=job_id,
        )

        document_record = DocumentRecord(
            doc_id=doc_id,
            tenant_id=normalized_tenant_id,
            file_name=filename,
            file_hash=file_hash,
            source_type=suffix.lstrip(".") or "unknown",  # 去掉点号，如 "pdf" / "docx"
            department_id=normalized_department_id,
            department_ids=normalized_department_ids,
            retrieval_department_ids=normalized_retrieval_department_ids,
            category_id=normalized_category_id,
            role_ids=normalized_role_ids,
            owner_id=normalized_owner_id,
            visibility=visibility,
            classification=classification,
            tags=normalized_tags,
            source_system=normalized_source_system,
            status="queued",  # 初始状态：待处理
            current_version=1,
            latest_job_id=job_id,
            storage_path=storage_path,
            uploaded_by=effective_uploaded_by,
            created_by=effective_created_by,
            created_at=now,
            updated_at=now,
        )
        ingest_job = IngestJobRecord(
            job_id=job_id,
            doc_id=doc_id,
            version=1,
            file_name=filename,
            status="queued",
            stage="queued",
            progress=0,
            retry_count=0,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )

        # --- 6. 持久化并调度 ---
        self._save_document_record(document_record)
        self._save_job_record(ingest_job)
        self._dispatch_job_or_fail(ingest_job, document_record)  # 投递到 Celery 异步执行

        # --- 7. 记录事件 ---
        self._record_document_event(
            action="create",
            outcome="success",
            auth_context=auth_context,
            doc_id=doc_id,
            job_id=job_id,
            duration_ms=self._elapsed_ms(started_at),
            details={"file_name": filename, "duplicate": False},
        )

        return DocumentCreateResponse(doc_id=doc_id, job_id=job_id, status="queued")

    async def create_documents_batch(
        self,
        *,
        uploads: list[UploadFile],
        tenant_id: str,
        department_id: str | None = None,
        department_ids: list[str] | None = None,
        retrieval_department_ids: list[str] | None = None,
        category_id: str | None = None,
        role_ids: list[str] | None = None,
        owner_id: str | None = None,
        visibility: Visibility = "private",
        classification: Classification = "internal",
        tags: list[str] | None = None,
        source_system: str | None = None,
        uploaded_by: str | None = None,
        created_by: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> DocumentBatchCreateResponse:
        """批量创建文档。

        逐个调用 create_document，单个失败不影响其他。
        返回每条的上传结果（queued / failed + 错误信息）。
        """
        started_at = perf_counter()
        if not uploads:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files must not be empty.")

        items: list[DocumentBatchItemResponse] = []
        for upload in uploads:
            file_name = upload.filename or "document"
            try:
                created = await self.create_document(
                    upload=upload,
                    tenant_id=tenant_id,
                    department_id=department_id,
                    department_ids=department_ids,
                    retrieval_department_ids=retrieval_department_ids,
                    category_id=category_id,
                    role_ids=role_ids,
                    owner_id=owner_id,
                    visibility=visibility,
                    classification=classification,
                    tags=tags,
                    source_system=source_system,
                    uploaded_by=uploaded_by,
                    created_by=created_by,
                    auth_context=auth_context,
                )
            except HTTPException as exc:
                error_code, error_message = self._extract_batch_error_detail(exc.detail)
                items.append(
                    DocumentBatchItemResponse(
                        file_name=file_name,
                        status="failed",
                        http_status=exc.status_code,
                        error_code=error_code,
                        error_message=error_message,
                    )
                )
                continue

            items.append(
                DocumentBatchItemResponse(
                    file_name=file_name,
                    status="queued",
                    doc_id=created.doc_id,
                    job_id=created.job_id,
                )
            )

        queued_count = sum(1 for item in items if item.status == "queued")
        response = DocumentBatchCreateResponse(
            total=len(items),
            queued=queued_count,
            failed=len(items) - queued_count,
            items=items,
        )
        self._record_document_event(
            action="batch_create",
            outcome="success",
            auth_context=auth_context,
            duration_ms=self._elapsed_ms(started_at),
            details={"total": response.total, "queued": response.queued, "failed": response.failed},
        )
        return response

    # ===== 入库任务管理 =====

    def queue_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
        """重新排队一个入库任务。

        如果任务已在处理中或已完成，直接返回当前状态。
        否则重置为 queued 并重新调度。
        eager 模式下任务在当前进程直接执行，所以需要重新读取以拿到最新状态。
        """
        job_record = self._load_job_record(job_id)
        document_record = self._load_document_record(job_record.doc_id)

        if job_record.status in PROCESSING_JOB_STATUSES:
            return self._to_ingest_job_status_response(job_record)
        if job_record.status == "completed":
            return self._to_ingest_job_status_response(job_record)

        document_record.status = "queued"
        document_record.updated_at = datetime.now(timezone.utc)
        self._save_document_record(document_record)
        self._update_job_record(
            job_record,
            status="queued",
            stage="queued",
            progress=0,
            error_code=None,
            error_message=None,
        )
        self._dispatch_job_or_fail(job_record, document_record)
        latest_job_record = self._load_job_record(job_id)  # eager 模式下任务可能已执行完毕
        return self._to_ingest_job_status_response(latest_job_record)

    def run_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
        """同步执行入库任务（用于 eager 模式和测试）。

        流程：uploaded → parsing → ocr_processing → chunking → embedding → indexing → completed
        如果入库结果有 OCR 告警，标记为 partial_failed。
        """
        job_record = self._load_job_record(job_id)
        document_record = self._load_document_record(job_record.doc_id)

        if job_record.status in TERMINAL_JOB_STATUSES:
            return self._to_ingest_job_status_response(job_record)  # 终态任务不重复执行
        if job_record.status in PROCESSING_JOB_STATUSES:
            return self._to_ingest_job_status_response(job_record)  # 进行中的任务不重复执行

        document_record.status = "uploaded"
        document_record.updated_at = datetime.now(timezone.utc)
        self._save_document_record(document_record)

        self._update_job_record(
            job_record,
            status="parsing",
            stage="parsing",
            progress=5,
            error_code=None,
            error_message=None,
        )

        # 定义阶段回调：入库过程中每完成一个阶段就更新 job 状态
        def on_stage(stage: str, progress: int) -> None:
            self._update_job_record(job_record, status=stage, stage=stage, progress=progress)

        try:
            # 物化文件（如从对象存储下载到本地临时目录）
            with self.asset_store.materialize_for_processing(
                document_record.storage_path,
                file_name=document_record.file_name,
            ) as materialized_asset:
                if materialized_asset.normalized_storage_path != document_record.storage_path:
                    document_record.storage_path = materialized_asset.normalized_storage_path
                    document_record.updated_at = datetime.now(timezone.utc)
                    self._save_document_record(document_record)

                # 执行入库：解析 → OCR → 切块 → 向量化
                ingestion_result = self.ingestion_service.ingest_document(
                    document_id=document_record.doc_id,
                    filename=document_record.file_name,
                    source_path=materialized_asset.local_path,
                    on_stage=on_stage,
                )
        except ValueError as exc:
            return self._mark_ingest_failure(
                job_record=job_record,
                document_record=document_record,
                error_code=INGEST_ERROR_CODE_VALIDATION,
                error_message=str(exc),
            )
        except (RuntimeError, OSError) as exc:
            return self._mark_ingest_failure(
                job_record=job_record,
                document_record=document_record,
                error_code=INGEST_ERROR_CODE_RUNTIME,
                error_message=str(exc),
            )

        # 根据入库结果更新最终状态
        if ingestion_result.final_status == "partial_failed":
            self._update_job_record(
                job_record,
                status="partial_failed",
                stage="partial_failed",
                progress=100,
                error_code=None,
                error_message=ingestion_result.warning_message,
            )
            document_record.status = "partial_failed"
        else:
            self._update_job_record(
                job_record,
                status="completed",
                stage="completed",
                progress=100,
                error_code=None,
                error_message=None,
            )
            document_record.status = "active"
        document_record.updated_at = datetime.now(timezone.utc)
        self._save_document_record(document_record)
        return self._to_ingest_job_status_response(job_record)

    # ===== 旧版同步上传接口（向后兼容） =====

    async def save_upload(self, upload: UploadFile) -> DocumentUploadResponse:
        """同步上传入口（旧版兼容）。

        直接在当前进程完成入库，返回完整的解析结果。
        不创建 DocumentRecord 元数据记录，仅返回入库产物信息。
        """
        filename, _, content = await self._read_upload_content(upload)
        document_id = uuid4().hex
        target_name = f"{document_id}__{_sanitize_filename(filename)}"
        storage_path = self.asset_store.save_upload(
            doc_id=document_id,
            target_name=target_name,
            file_name=filename,
            content=content,
            mime_type=upload.content_type,
        )

        try:
            with self.asset_store.materialize_for_processing(storage_path, file_name=filename) as materialized_asset:
                ingestion_result = self.ingestion_service.ingest_document(
                    document_id=document_id,
                    filename=filename,
                    source_path=materialized_asset.local_path,
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        return DocumentUploadResponse(
            document_id=document_id,
            filename=filename,
            content_type=upload.content_type,
            size_bytes=len(content),
            status="partial_failed" if ingestion_result.final_status == "partial_failed" else "ingested",
            parse_supported=True,
            storage_path=storage_path,
            parsed_path=ingestion_result.parsed_path,
            chunk_path=ingestion_result.chunk_path,
            ocr_artifact_path=ingestion_result.ocr_artifact_path,
            collection_name=ingestion_result.collection_name,
            parser_name=ingestion_result.parser_name,
            chunk_count=ingestion_result.chunk_count,
            vector_count=ingestion_result.vector_count,
            warning_message=ingestion_result.warning_message,
            created_at=datetime.now(timezone.utc),
        )

    # ===== 文档读取与预览 =====

    def get_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDetailResponse:
        """获取文档详情。需通过 _can_read_document 权限校验。"""
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)
        latest_ingest_status = self._get_latest_ingest_status(record.latest_job_id)
        return DocumentDetailResponse(
            doc_id=record.doc_id,
            file_name=record.file_name,
            status=record.status,
            ingest_status=latest_ingest_status,
            department_id=record.department_id,
            category_id=record.category_id,
            uploaded_by=record.uploaded_by,
            current_version=record.current_version,
            latest_job_id=record.latest_job_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def get_document_preview(
        self,
        doc_id: str,
        *,
        max_chars: int = TEXT_PREVIEW_MAX_CHARS,
        auth_context: AuthContext | None = None,
    ) -> DocumentPreviewResponse:
        """获取文档预览。

        根据文件类型选择预览方式：
        - 纯文本/Markdown：直接读取原文
        - Office（doc/docx/xlsx 等）：读取解析后的文本
        - PDF：返回文本摘要 + 文件流 URL
        """
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)
        suffix = self._normalize_source_suffix(record.source_type)
        if suffix not in SUPPORTED_PREVIEW_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_PREVIEW_SUFFIXES))
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Preview is not supported for file type: {suffix or 'unknown'}. Supported types: {supported}",
            )

        if suffix in TEXT_PREVIEW_SUFFIXES | PARSED_TEXT_PREVIEW_SUFFIXES:
            text_content, text_truncated = self._load_text_preview_content(
                record,
                suffix=suffix,
                max_chars=max_chars,
            )
            return DocumentPreviewResponse(
                doc_id=record.doc_id,
                file_name=record.file_name,
                preview_type="text",
                content_type=TEXT_PREVIEW_CONTENT_TYPE_BY_SUFFIX[suffix],
                text_content=text_content,
                text_truncated=text_truncated,
                preview_file_url=None,
                updated_at=record.updated_at,
            )

        # PDF 预览：尝试读取解析后的文本，否则返回空文本 + 文件流 URL
        parsed_path = self.settings.parsed_dir / f"{record.doc_id}.txt"
        parsed_text, text_truncated = (
            self._read_text_preview_bytes(parsed_path.read_bytes(), max_chars=max_chars) if parsed_path.exists() else ("", False)
        )
        return DocumentPreviewResponse(
            doc_id=record.doc_id,
            file_name=record.file_name,
            preview_type="pdf",
            content_type=DOCUMENT_CONTENT_TYPE_BY_SUFFIX[suffix],
            text_content=parsed_text or None,
            text_truncated=text_truncated,
            preview_file_url=f"/api/v1/documents/{record.doc_id}/preview/file",
            updated_at=record.updated_at,
        )

    def get_document_preview_file(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentFilePayload:
        """获取 PDF 文件预览流（仅支持 PDF 类型）。"""
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)
        suffix = self._normalize_source_suffix(record.source_type)
        if suffix not in PDF_PREVIEW_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only PDF documents support preview file streaming.",
            )

        if not self.asset_store.exists(record.storage_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preview source file not found for document: {doc_id}",
            )
        if self.asset_store.can_serve_local_path(record.storage_path):
            return DocumentFilePayload(
                path=self.asset_store.resolve_local_path(record.storage_path),
                media_type=DOCUMENT_CONTENT_TYPE_BY_SUFFIX[suffix],
                filename=record.file_name,
            )
        return DocumentFilePayload(
            content=self.asset_store.read_bytes(record.storage_path),
            media_type=DOCUMENT_CONTENT_TYPE_BY_SUFFIX[suffix],
            filename=record.file_name,
        )

    def get_document_file(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentFilePayload:
        """获取原始文件（下载）。返回文件路径或字节内容。"""
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)
        suffix = self._normalize_source_suffix(record.source_type)
        if not self.asset_store.exists(record.storage_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source file not found for document: {doc_id}",
            )

        media_type = DOCUMENT_CONTENT_TYPE_BY_SUFFIX.get(suffix, "application/octet-stream")
        if self.asset_store.can_serve_local_path(record.storage_path):
            return DocumentFilePayload(
                path=self.asset_store.resolve_local_path(record.storage_path),
                media_type=media_type,
                filename=record.file_name,
            )
        return DocumentFilePayload(
            content=self.asset_store.read_bytes(record.storage_path),
            media_type=media_type,
            filename=record.file_name,
        )

    # ===== 文档删除与向量重建 =====

    def delete_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDeleteResponse:
        """软删除文档：标记 status='deleted' + 清理 Qdrant 向量点。

        需通过 _can_manage_document 管理权限校验。
        """
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)
            self._ensure_can_manage_document(record, auth_context)
            now = datetime.now(timezone.utc)
            if record.status != "deleted":
                record.status = "deleted"
                record.updated_at = now
                self._save_document_record(record)  # 先改主数据

            try:
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)  # 再删向量副本
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to clean vector replica for document {doc_id}: {exc}",
                ) from exc

            response = DocumentDeleteResponse(doc_id=record.doc_id, status="deleted", vector_points_removed=removed)
            self._record_document_event(
                action="delete",
                outcome="success",
                auth_context=auth_context,
                doc_id=record.doc_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"vector_points_removed": removed},
            )
            return response
        except Exception as exc:
            self._record_document_event(
                action="delete",
                outcome="failed",
                auth_context=auth_context,
                doc_id=doc_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"error_message": str(exc)},
            )
            raise

    def rebuild_document_vectors(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentRebuildResponse:
        """重建文档向量：删除旧向量 + 调度新入库任务。

        前置检查：
        - 需要管理权限
        - 文档不能已删除
        - 不能有正在进行的入库任务
        """
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)
            self._ensure_can_manage_document(record, auth_context)
            if record.status == "deleted":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deleted document cannot rebuild vectors: {doc_id}")

            # 检查是否有正在进行的入库任务
            if record.latest_job_id:
                try:
                    latest_job = self._load_job_record(record.latest_job_id)
                    if self._should_reuse_inflight_job(latest_job):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Document ingest job is still running: {record.latest_job_id}",
                        )
                except HTTPException as exc:
                    if exc.status_code != status.HTTP_404_NOT_FOUND:
                        raise

            # 删除旧向量
            try:
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to clean vector replica before rebuild for document {doc_id}: {exc}",
                ) from exc

            # 创建 follow-up 入库任务
            followup_job = self._create_followup_ingest_job(record)
            response = DocumentRebuildResponse(
                doc_id=record.doc_id,
                job_id=followup_job.job_id,
                status="queued",
                previous_vector_points_removed=removed,
            )
            self._record_document_event(
                action="rebuild",
                outcome="success",
                auth_context=auth_context,
                doc_id=record.doc_id,
                job_id=followup_job.job_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"previous_vector_points_removed": removed},
            )
            return response
        except Exception as exc:
            self._record_document_event(
                action="rebuild",
                outcome="failed",
                auth_context=auth_context,
                doc_id=record.doc_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"error_message": str(exc)},
            )
            raise

    def get_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
        """查询入库任务状态。"""
        record = self._load_job_record(job_id)
        return self._to_ingest_job_status_response(record)

    def _get_latest_ingest_status(self, latest_job_id: str | None) -> str | None:
        """获取文档最新入库任务的状态，任务不存在时返回 None。"""
        latest_job = self._load_latest_job_record(latest_job_id)
        if latest_job is None:
            return None
        return latest_job.status

    # ===== 文档列表查询 =====

    def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        department_id: str | None = None,
        category_id: str | None = None,
        document_status: DocumentLifecycleStatus | None = None,
        auth_context: AuthContext | None = None,
    ) -> DocumentListResponse:
        """分页列出文档。

        支持按关键字、部门、分类、状态过滤。
        先从元数据存储读取，如果无结果则回退到上传目录扫描（兼容旧数据）。
        """
        safe_page = max(1, page)
        safe_page_size = min(max(1, page_size), 200)  # 上限 200 条/页
        normalized_keyword = _normalize_optional_str(keyword)
        normalized_department_id = _normalize_optional_str(department_id)
        normalized_category_id = _normalize_optional_str(category_id)
        self._ensure_department_filter_allowed(normalized_department_id, auth_context)  # 部门过滤权限检查
        items: list[DocumentSummary] = []
        records = self._list_document_records()

        # PostgreSQL 模式批量读取 latest job 状态，避免 N+1 查询
        latest_ingest_statuses: dict[str, str] = (
            self.metadata_store.load_job_statuses([record.latest_job_id for record in records]) if self.metadata_store is not None else {}
        )

        for record in records:
            if not self._can_read_document(record, auth_context):
                continue  # 权限过滤：用户不可见的文档不返回
            latest_ingest_status = (
                latest_ingest_statuses.get(record.latest_job_id)
                if self.metadata_store is not None
                else self._get_latest_ingest_status(record.latest_job_id)
            )
            items.append(
                DocumentSummary(
                    document_id=record.doc_id,
                    filename=record.file_name,
                    size_bytes=self.asset_store.size_bytes(record.storage_path),
                    parse_supported=f".{record.source_type.lower()}" in SUPPORTED_PARSE_SUFFIXES,
                    storage_path=record.storage_path,
                    status=record.status,
                    ingest_status=latest_ingest_status,
                    latest_job_id=record.latest_job_id,
                    department_id=record.department_id,
                    category_id=record.category_id,
                    uploaded_by=record.uploaded_by,
                    updated_at=record.updated_at,
                )
            )

        # 回退：扫描上传目录，兼容没有元数据记录的旧文件
        if not items:
            self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.settings.upload_dir.iterdir()):
                if not path.is_file() or path.name.startswith("."):
                    continue

                document_id, filename = self._decode_storage_name(path.name)
                items.append(
                    DocumentSummary(
                        document_id=document_id,
                        filename=filename,
                        size_bytes=path.stat().st_size,
                        parse_supported=path.suffix.lower() in SUPPORTED_PARSE_SUFFIXES,
                        storage_path=str(path),
                        status="uploaded",  # 无元数据时统一标记为 uploaded
                        ingest_status=None,
                        latest_job_id=None,
                        department_id=None,
                        category_id=None,
                        uploaded_by=None,
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                    )
                )

        items.sort(key=lambda item: item.updated_at, reverse=True)  # 按更新时间降序排列
        filtered_items = [
            item
            for item in items
            if self._matches_document_filters(
                item,
                keyword=normalized_keyword,
                department_id=normalized_department_id,
                category_id=normalized_category_id,
                document_status=document_status,
            )
        ]
        total = len(filtered_items)
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        paged_items = filtered_items[start:end]

        return DocumentListResponse(total=total, page=safe_page, page_size=safe_page_size, items=paged_items)

    def list_stuck_ingest_jobs(
        self,
        *,
        auth_context: AuthContext | None = None,
        limit: int = 5,
    ) -> list[OpsStuckIngestJobSummary]:
        """列出卡住的入库任务（运维接口）。

        检测条件：
        - 任务状态处于 in-flight（pending/queued/processing 等）
        - 并且满足以下任一条件：
          a) 解析和切块产物已经存在（说明任务实际已完成但状态未更新）
          b) 任务超时未更新（stale）
        按优先级排序：产物已存在 > 超时时间最长
        """
        safe_limit = min(max(1, limit), 20)
        now = datetime.now(timezone.utc)
        candidates: list[OpsStuckIngestJobSummary] = []
        for record in self._list_document_records():
            if not self._can_read_document(record, auth_context):
                continue
            latest_job = self._load_latest_job_record(record.latest_job_id)
            if latest_job is None or latest_job.status not in IN_FLIGHT_JOB_STATUSES:
                continue
            has_artifacts = self._has_materialized_ingest_artifacts(record.doc_id)
            is_stale = self._is_job_stale(latest_job)
            if not has_artifacts and not is_stale:
                continue  # 既没产物也没超时，不算卡住
            updated_at = latest_job.updated_at if latest_job.updated_at.tzinfo is not None else latest_job.updated_at.replace(tzinfo=timezone.utc)
            candidates.append(
                OpsStuckIngestJobSummary(
                    doc_id=record.doc_id,
                    job_id=latest_job.job_id,
                    file_name=record.file_name,
                    document_status=record.status,
                    job_status=latest_job.status,
                    stage=latest_job.stage,
                    progress=latest_job.progress,
                    updated_at=updated_at,
                    stale_seconds=max(0, int((now - updated_at).total_seconds())),
                    has_materialized_artifacts=has_artifacts,
                    reason="artifacts_ready_but_inflight" if has_artifacts else "stale_inflight",
                )
            )
        candidates.sort(
            key=lambda item: (
                1 if item.reason == "artifacts_ready_but_inflight" else 0,  # 产物已存在的优先级更高
                item.stale_seconds,  # 超时越久越优先
                item.updated_at.timestamp(),
            ),
            reverse=True,
        )
        return candidates[:safe_limit]

    # ===== 检索作用域与权限 =====

    @staticmethod
    def _matches_document_filters(
        item: DocumentSummary,
        *,
        keyword: str | None,
        department_id: str | None,
        category_id: str | None,
        document_status: DocumentLifecycleStatus | None,
    ) -> bool:
        """文档列表过滤匹配：关键字（文件名或文档 ID 模糊匹配）、部门、分类、状态。"""
        if keyword is not None:
            lowered_keyword = keyword.lower()
            if lowered_keyword not in item.filename.lower() and lowered_keyword not in item.document_id.lower():
                return False
        if department_id is not None and item.department_id != department_id:
            return False
        if category_id is not None and item.category_id != category_id:
            return False
        if document_status is not None and item.status != document_status:
            return False
        return True

    def is_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> bool:
        """单文档直接访问可读性检查（对应详情/预览/下载的权限）。"""
        try:
            record = self._load_document_record(doc_id)
        except HTTPException:
            return False
        return self._can_read_document(record, auth_context)

    def get_document_readability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
        """批量直接访问可读性检查。PostgreSQL 模式下走批量查询优化。"""
        normalized_doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()]
        if not normalized_doc_ids:
            return {}
        if auth_context is None:
            return {doc_id: True for doc_id in normalized_doc_ids}

        if self.metadata_store is not None:
            records = self.metadata_store.load_documents(normalized_doc_ids)
            return {
                doc_id: self._can_read_document(record, auth_context)
                for doc_id, record in records.items()
            }

        readability: dict[str, bool] = {}
        for doc_id in normalized_doc_ids:
            try:
                record = self._load_document_record(doc_id)
            except HTTPException:
                readability[doc_id] = False
                continue
            readability[doc_id] = self._can_read_document(record, auth_context)
        return readability

    def ensure_document_readable(self, doc_id: str, auth_context: AuthContext | None = None) -> None:
        """断言文档可读，不可读时抛 403。"""
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)

    # ===== 部门范围与权限辅助 =====

    @staticmethod
    def _normalize_department_scope(values: list[str] | None, primary_department_id: str | None) -> list[str]:
        """标准化部门范围：将 primary_department_id 放首位，去重。

        例如：("dept_a", None, ["dept_b", "dept_a"]) → ["dept_a", "dept_b"]
        """
        normalized: list[str] = []
        if primary_department_id and primary_department_id not in normalized:
            normalized.append(primary_department_id)  # 主部门放首位
        for item in values or []:
            if item and item not in normalized:
                normalized.append(item)  # 去重后追加
        return normalized

    def _enforce_document_create_scope(
        self,
        auth_context: AuthContext | None,
        *,
        tenant_id: str,
        department_id: str | None,
        department_ids: list[str],
        uploaded_by: str | None,
        created_by: str | None,
    ) -> tuple[str, str | None, list[str], str | None, str | None]:
        """执行文档创建的权限校验。

        规则：
        1. auth_context 为空时跳过（兼容开发工作台）
        2. 不允许跨租户创建
        3. employee 只能在自己所属部门创建
        4. department_admin 只能在自己管理的部门创建
        5. 未指定部门时自动设为当前用户所属部门
        6. 强制 uploaded_by / created_by 为当前用户 ID
        """
        if auth_context is None:
            return tenant_id, department_id, department_ids, uploaded_by, created_by

        if tenant_id != auth_context.user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create documents outside your tenant.")

        effective_department_id = department_id
        effective_department_ids = self._normalize_department_scope(department_ids, department_id)

        # 普通员工：只能在自己可访问的部门内创建
        if auth_context.user.role_id == "employee":
            allowed_departments = set(auth_context.accessible_department_ids)
            if effective_department_ids and not set(effective_department_ids).issubset(allowed_departments):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Employees can only create documents in their accessible departments.",
                )
            if effective_department_id is None:
                effective_department_id = auth_context.department.department_id
                effective_department_ids = self._normalize_department_scope(effective_department_ids, effective_department_id)

        # 部门管理员：只能在自己管理的部门内创建
        if auth_context.user.role_id == "department_admin":
            allowed_departments = set(auth_context.accessible_department_ids)
            if effective_department_ids and not set(effective_department_ids).issubset(allowed_departments):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Department admins can only manage documents in their accessible departments.",
                )
            if effective_department_id is None:
                effective_department_id = auth_context.department.department_id
                effective_department_ids = self._normalize_department_scope(effective_department_ids, effective_department_id)

        effective_uploaded_by = auth_context.user.user_id  # 强制覆盖为当前用户
        effective_created_by = auth_context.user.user_id
        return tenant_id, effective_department_id, effective_department_ids, effective_uploaded_by, effective_created_by

    def _ensure_department_filter_allowed(self, department_id: str | None, auth_context: AuthContext | None) -> None:
        """检查用户是否有权按部门过滤文档列表。"""
        if auth_context is None or department_id is None:
            return
        if not self.settings.department_query_isolation_enabled:
            return
        if auth_context.role.data_scope == "global":
            return
        if department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot query documents outside your accessible departments.",
            )

    def _ensure_can_read_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> None:
        """断言文档可读。不可读时抛 403。"""
        if self._can_read_document(record, auth_context):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this document.")

    def _ensure_can_manage_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> None:
        """断言文档可管理。不可管理时抛 403。"""
        if self._can_manage_document(record, auth_context):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage this document.")

    def _can_read_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> bool:
        """直接访问权限检查（用于详情/预览下载）。

        检查优先级：
        1. 无鉴权上下文 → 允许
        2. 租户不匹配 → 拒绝
        3. 全局角色 → 允许
        4. role visibility 限制 → 检查用户角色是否在文档的 role_ids 中
        5. public 可见性 → 允许
        6. 部门隔离关闭 → 允许
        7. 文档部门与用户可访问部门有交集 → 允许
        8. 无部门信息的旧数据 → 允许
        """
        if auth_context is None:
            return True
        if record.tenant_id != auth_context.user.tenant_id:
            return False
        if auth_context.role.data_scope == "global":
            return True
        if record.visibility == "role" and record.role_ids and auth_context.user.role_id not in record.role_ids:
            return False
        if record.visibility == "public":
            return True
        if not self.settings.department_query_isolation_enabled:
            return True
        record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
        if not record_departments:  # 兼容旧数据：没有部门字段时默认当前租户内可读
            return True
        return bool(set(record_departments) & set(auth_context.accessible_department_ids))

    def _can_manage_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> bool:
        """管理权限检查（用于删除/重建）。

        只有 sys_admin 或文档所属部门的 department_admin 可以管理。
        """
        if auth_context is None:
            return True
        if record.tenant_id != auth_context.user.tenant_id:
            return False
        if auth_context.user.role_id == "sys_admin":
            return True
        if auth_context.user.role_id != "department_admin":
            return False  # 非 department_admin 无管理权限
        record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
        if not record_departments:
            return False
        return set(record_departments).issubset(set(auth_context.accessible_department_ids))

    # ===== 上传内容读取与校验 =====

    async def _read_upload_content(self, upload: UploadFile) -> tuple[str, str, bytes]:
        """读取上传文件内容，校验文件类型和大小。返回 (文件名, 扩展名, 字节内容)。"""
        filename = upload.filename or "document"
        suffix = Path(filename).suffix.lower()

        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {suffix or 'unknown'}. Supported types: {supported}",
            )

        content_buffer = bytearray()
        while True:
            chunk = await upload.read(UPLOAD_READ_CHUNK_SIZE_BYTES)  # 分块读取，每块 1MB
            if not chunk:
                break
            content_buffer.extend(chunk)
            if len(content_buffer) > self.settings.upload_max_file_size_bytes:  # 超过大小限制
                max_size_mb = self.settings.upload_max_file_size_bytes // (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"File too large: {len(content_buffer)} bytes. "
                        f"Maximum allowed size is {self.settings.upload_max_file_size_bytes} bytes ({max_size_mb}MB)."
                    ),
                )

        content = bytes(content_buffer)
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        self._validate_upload_parse_prerequisites(filename=filename, suffix=suffix, content=content)
        return filename, suffix, content

    @staticmethod
    def _validate_upload_parse_prerequisites(*, filename: str, suffix: str, content: bytes) -> None:
        """上传前的前置校验：PDF 文件头、Office 容器格式、依赖检查。"""
        # PDF：校验文件头魔数
        if suffix == ".pdf" and not content.lstrip().startswith(PDF_MAGIC_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid PDF content for '{filename}': missing PDF file signature (%PDF-); "
                    "source file may be mislabeled, encrypted, or corrupted."
                ),
            )

        # Office 格式：校验 ZIP 容器
        office_label = ZIP_OFFICE_UPLOAD_LABELS.get(suffix)
        if office_label is not None and not is_zipfile(BytesIO(content)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {office_label} container for '{filename}'.",
            )

        # .doc 格式：检查 LibreOffice 是否可用
        if suffix == ".doc" and find_libreoffice_binary() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Legacy DOC parsing requires a resolvable LibreOffice binary in the current API runtime.",
            )

        # .xls 格式：检查 xlrd 是否安装
        if suffix == ".xls" and importlib.util.find_spec("xlrd") is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parsing .xls files requires xlrd to be installed on the API/worker runtime.",
            )

    # ===== 元数据持久化（JSON 文件 / PostgreSQL 双模式） =====

    @staticmethod
    def _generate_entity_id(prefix: str) -> str:
        """生成实体 ID：{prefix}_{时间戳}_{uuid8}，如 doc_20260331120000_abc12345。"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"

    def _document_record_path(self, doc_id: str) -> Path:
        """文档元数据记录的 JSON 文件路径。"""
        return self.settings.document_dir / f"{doc_id}.json"

    def _job_record_path(self, job_id: str) -> Path:
        """入库任务记录的 JSON 文件路径。"""
        return self.settings.job_dir / f"{job_id}.json"

    @staticmethod
    def _write_json(path: Path, model: DocumentRecord | IngestJobRecord) -> None:
        """将 Pydantic 模型序列化为 JSON 并写入文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def _save_document_record(self, record: DocumentRecord) -> None:
        """保存文档记录（PostgreSQL 或 JSON 文件）。"""
        if self.metadata_store is not None:
            self.metadata_store.save_document(record)
            return
        self._write_json(self._document_record_path(record.doc_id), record)

    def _save_job_record(self, record: IngestJobRecord) -> None:
        """保存入库任务记录（PostgreSQL 或 JSON 文件）。"""
        if self.metadata_store is not None:
            self.metadata_store.save_job(record)
            return
        self._write_json(self._job_record_path(record.job_id), record)

    def list_document_records(self) -> list[DocumentRecord]:
        """稳定的文档记录读取接口，供检索等只读协作者复用。"""
        return self._list_document_records()

    def _list_document_records(self) -> list[DocumentRecord]:
        """列出所有文档记录。PostgreSQL 模式走批量查询，JSON 模式遍历目录。"""
        if self.metadata_store is not None:
            return self.metadata_store.list_documents()
        self.settings.document_dir.mkdir(parents=True, exist_ok=True)
        records: list[DocumentRecord] = []
        for path in sorted(self.settings.document_dir.glob("*.json")):
            if not path.is_file() or path.name.startswith("."):
                continue
            records.append(DocumentRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    def _update_job_record(
        self,
        record: IngestJobRecord,
        *,
        status: str,
        stage: str,
        progress: int,
        error_code: str | None = None,
        error_message: str | None = None,
        increase_retry: bool = False,
    ) -> None:
        """更新入库任务记录的部分字段。"""
        record.status = status
        record.stage = stage
        record.progress = max(0, min(100, progress))  # 进度限制在 0-100
        record.error_code = error_code
        record.error_message = error_message
        if increase_retry:
            record.retry_count += 1
        record.updated_at = datetime.now(timezone.utc)
        self._save_job_record(record)

    def _to_ingest_job_status_response(self, record: IngestJobRecord) -> IngestJobStatusResponse:
        """将内部 IngestJobRecord 转为对外 API 响应。"""
        auto_retry_eligible = record.status == "failed" and record.retry_count < self.settings.ingest_failure_retry_limit
        manual_retry_allowed = record.status not in PROCESSING_JOB_STATUSES and record.status != "completed"
        return IngestJobStatusResponse(
            job_id=record.job_id,
            doc_id=record.doc_id,
            status=record.status,
            progress=record.progress,
            stage=record.stage,
            retry_count=record.retry_count,
            max_retry_limit=self.settings.ingest_failure_retry_limit,
            auto_retry_eligible=auto_retry_eligible,
            manual_retry_allowed=manual_retry_allowed,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _load_document_record(self, doc_id: str) -> DocumentRecord:
        """按 ID 加载文档记录，不存在时抛 404。"""
        if self.metadata_store is not None:
            record = self.metadata_store.load_document(doc_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")
            return record
        path = self._document_record_path(doc_id)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_document_record(self, doc_id: str) -> DocumentRecord:
        """稳定的单文档记录读取接口，供检索等只读协作者复用。"""
        return self._load_document_record(doc_id)

    def _load_job_record(self, job_id: str) -> IngestJobRecord:
        """按 ID 加载入库任务记录，不存在时抛 404。"""
        if self.metadata_store is not None:
            record = self.metadata_store.load_job(job_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingest job not found: {job_id}")
            return record
        path = self._job_record_path(job_id)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingest job not found: {job_id}")
        return IngestJobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_latest_job_record(self, latest_job_id: str | None) -> IngestJobRecord | None:
        """加载文档的最新入库任务记录。任务不存在时返回 None。"""
        if not latest_job_id:
            return None
        try:
            return self._load_job_record(latest_job_id)
        except HTTPException:
            return None

    # ===== 任务状态判断辅助 =====

    def _is_job_stale(self, job_record: IngestJobRecord) -> bool:
        """判断任务是否超时卡住（超过配置的超时时间未更新）。"""
        updated_at = job_record.updated_at
        if updated_at.tzinfo is None:  # 兼容旧 JSON 里没有显式时区的时间戳
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        stale_after = timedelta(seconds=self.settings.ingest_inflight_stale_seconds)
        return datetime.now(timezone.utc) - updated_at > stale_after

    def _should_reuse_inflight_job(self, job_record: IngestJobRecord | None) -> bool:
        """判断是否应该复用正在进行的入库任务。

        复用条件：任务存在、状态为 in-flight、且未超时。
        超时任务不复用，避免把当前上传也带挂。
        """
        if job_record is None:
            return False
        if job_record.status not in IN_FLIGHT_JOB_STATUSES:
            return False
        return not self._is_job_stale(job_record)

    def _has_materialized_ingest_artifacts(self, doc_id: str) -> bool:
        """检查文档是否有已物化的入库产物（解析文本文件或切块文件）。"""
        parsed_path = self.settings.parsed_dir / f"{doc_id}.txt"
        if parsed_path.exists() and parsed_path.stat().st_size > 0:
            return True
        chunk_path = self.settings.chunk_dir / f"{doc_id}.json"
        return chunk_path.exists() and chunk_path.stat().st_size > 0

    # ===== 重复检测与后续任务 =====

    def _find_document_record_by_file_hash(self, file_hash: str, *, tenant_id: str | None = None) -> DocumentRecord | None:
        """通过 SHA256 文件哈希查找同租户的重复文档记录。"""
        if self.metadata_store is not None:
            return self.metadata_store.find_document_by_file_hash(file_hash, tenant_id=tenant_id)
        self.settings.document_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.settings.document_dir.glob("*.json")):
            if not path.is_file() or path.name.startswith("."):
                continue
            record = DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if tenant_id is not None and record.tenant_id != tenant_id:
                continue
            if record.file_hash == file_hash:
                return record
        return None

    def _create_followup_ingest_job(self, document_record: DocumentRecord) -> IngestJobRecord:
        """为已有文档创建后续入库任务（用于重复上传/向量重建场景）。

        创建新任务记录，更新文档的 latest_job_id，重新调度执行。
        """
        now = datetime.now(timezone.utc)
        followup_job = IngestJobRecord(
            job_id=self._generate_entity_id("job"),
            doc_id=document_record.doc_id,
            version=document_record.current_version,
            file_name=document_record.file_name,
            status="queued",
            stage="queued",
            progress=0,
            retry_count=0,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        document_record.status = "queued"
        document_record.latest_job_id = followup_job.job_id
        document_record.updated_at = now
        self._save_document_record(document_record)
        self._save_job_record(followup_job)
        self._dispatch_job_or_fail(followup_job, document_record)
        return followup_job

    def _refresh_duplicate_document_source(
        self,
        document_record: DocumentRecord,
        *,
        content: bytes,
        filename: str,
        source_type: str,
        uploaded_by: str | None,
        created_by: str | None = None,
    ) -> None:
        """更新重复文档的源文件信息（文件名、来源类型、上传人）。

        如果源文件不存在或扩展名变了，重新保存文件内容。
        """
        document_record.file_name = filename
        document_record.source_type = source_type
        if uploaded_by is not None:
            document_record.uploaded_by = uploaded_by
        if created_by is not None:
            document_record.created_by = created_by

        storage_path_suffix = Path(document_record.storage_path).suffix.lower()
        source_exists = self.asset_store.exists(document_record.storage_path)
        should_rewrite_source = (not source_exists) or (storage_path_suffix != f".{source_type.lower()}" if source_type else False)

        if should_rewrite_source:
            target_name = f"{document_record.doc_id}__{_sanitize_filename(document_record.file_name)}"
            document_record.storage_path = self.asset_store.save_upload(
                doc_id=document_record.doc_id,
                target_name=target_name,
                file_name=document_record.file_name,
                content=content,
                job_id=document_record.latest_job_id,
            )
        document_record.updated_at = datetime.now(timezone.utc)

    def _dispatch_job_or_fail(self, job_record: IngestJobRecord, document_record: DocumentRecord) -> None:
        """调度入库任务到 Celery。调度失败时标记任务状态并抛 502。"""
        try:
            dispatch_ingest_job(job_record.job_id, self.settings)
        except Exception as exc:
            next_retry_count = job_record.retry_count + 1
            moved_to_dead_letter = next_retry_count >= self.settings.ingest_failure_retry_limit
            error_code = _dead_letter_error_code(INGEST_ERROR_CODE_DISPATCH) if moved_to_dead_letter else INGEST_ERROR_CODE_DISPATCH
            error_message = str(exc)
            if moved_to_dead_letter:
                error_message = (
                    f"{error_message} (retry_count={next_retry_count}/{self.settings.ingest_failure_retry_limit}; moved to dead_letter)"
                )
            self._update_job_record(
                job_record,
                status="dead_letter" if moved_to_dead_letter else "failed",
                stage="dead_letter" if moved_to_dead_letter else "failed",
                progress=100,
                error_code=error_code,
                error_message=error_message,
                increase_retry=True,
            )
            document_record.status = "failed"
            document_record.updated_at = datetime.now(timezone.utc)
            self._save_document_record(document_record)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to enqueue ingest job: {exc}",
            ) from exc

    def _mark_ingest_failure(
        self,
        *,
        job_record: IngestJobRecord,
        document_record: DocumentRecord,
        error_code: IngestBaseErrorCode,
        error_message: str,
    ) -> IngestJobStatusResponse:
        """标记入库任务失败。超过重试上限时进入 dead_letter。"""
        next_retry_count = job_record.retry_count + 1
        moved_to_dead_letter = next_retry_count >= self.settings.ingest_failure_retry_limit
        final_error_code = _dead_letter_error_code(error_code) if moved_to_dead_letter else error_code
        final_error_message = error_message
        if moved_to_dead_letter:
            final_error_message = (
                f"{error_message} (retry_count={next_retry_count}/{self.settings.ingest_failure_retry_limit}; moved to dead_letter)"
            )

        self._update_job_record(
            job_record,
            status="dead_letter" if moved_to_dead_letter else "failed",
            stage="dead_letter" if moved_to_dead_letter else "failed",
            progress=100,
            error_code=final_error_code,
            error_message=final_error_message,
            increase_retry=True,
        )
        document_record.status = "failed"
        document_record.updated_at = datetime.now(timezone.utc)
        self._save_document_record(document_record)
        return self._to_ingest_job_status_response(job_record)

    # ===== 文本预览辅助 =====

    @staticmethod
    def _decode_storage_name(storage_name: str) -> tuple[str, str]:
        """从存储文件名解析出文档 ID 和原始文件名。

        存储格式：{doc_id}__{原始文件名}
        例如："doc_abc123__manual.txt" → ("doc_abc123", "manual.txt")
        """
        if "__" not in storage_name:
            return "unknown", storage_name
        return tuple(storage_name.split("__", 1))

    @staticmethod
    def _normalize_source_suffix(source_type: str) -> str:
        """将 source_type 规范化为带点号的扩展名。例如 "pdf" → ".pdf"。"""
        normalized = source_type.strip().lower().lstrip(".")
        return f".{normalized}" if normalized else ""

    def _load_text_preview_content(
        self,
        record: DocumentRecord,
        *,
        suffix: str,
        max_chars: int,
    ) -> tuple[str, bool]:
        """加载文档的文本预览内容。

        优先级：
        1. 纯文本文件：直接读取原文
        2. Office 文件：读取已解析的文本文件
        3. 回退：实时解析原始文件
        返回 (文本内容, 是否被截断)
        """
        if suffix in TEXT_PREVIEW_SUFFIXES:
            if not self.asset_store.exists(record.storage_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Preview source file not found for document: {record.doc_id}",
                )
            return self._read_text_preview_bytes(
                self.asset_store.read_bytes(record.storage_path),
                max_chars=max_chars,
            )

        parsed_path = self.settings.parsed_dir / f"{record.doc_id}.txt"
        if parsed_path.exists():
            return self._read_text_preview_bytes(parsed_path.read_bytes(), max_chars=max_chars)

        if not self.asset_store.exists(record.storage_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preview source file not found for document: {record.doc_id}",
            )

        # 实时解析原始文件
        with self.asset_store.materialize_for_processing(record.storage_path, file_name=record.file_name) as materialized_asset:
            parsed_document = self.ingestion_service.parser.parse(
                source_path=materialized_asset.path,
                document_id=record.doc_id,
                filename=record.file_name,
            )
        return self._read_text_preview_bytes(parsed_document.text.encode("utf-8"), max_chars=max_chars)

    @staticmethod
    def _read_text_preview_bytes(content: bytes, *, max_chars: int) -> tuple[str, bool]:
        """将字节内容截断到指定字符数。返回 (截断后文本, 是否被截断)。"""
        raw_text = content.decode("utf-8", errors="ignore")  # ignore 兼容脏字符
        safe_limit = max(1, max_chars)
        if len(raw_text) <= safe_limit:
            return raw_text, False
        return raw_text[:safe_limit], True

    # ===== 事件日志 =====

    def _record_document_event(
        self,
        *,
        action: str,
        outcome: str,
        auth_context: AuthContext | None,
        duration_ms: int,
        doc_id: str | None = None,
        job_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """记录文档操作事件到事件日志服务。"""
        payload = dict(details or {})
        if job_id is not None:
            payload["job_id"] = job_id
        self.event_log_service.record(
            category="document",
            action=action,
            outcome="success" if outcome == "success" else "failed",
            auth_context=auth_context,
            target_type="document" if doc_id else None,
            target_id=doc_id,
            duration_ms=duration_ms,
            details=payload,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        """计算从 started_at 到现在的毫秒数。"""
        return max(0, int((perf_counter() - started_at) * 1000))

    @staticmethod
    def _extract_batch_error_detail(detail: object) -> tuple[str | None, str]:
        """从批量创建的错误详情中提取 (error_code, error_message)。

        支持三种格式：
        1. 纯字符串 → (None, 字符串)
        2. 字典（含 code/message/detail）→ 提取结构化错误信息
        3. 其他 → (None, str(对象))
        """
        if isinstance(detail, str):
            return None, detail

        if isinstance(detail, dict):
            raw_code = detail.get("code")
            error_code = raw_code if isinstance(raw_code, str) else None

            if isinstance(detail.get("message"), str):
                return error_code, detail["message"]
            if isinstance(detail.get("detail"), str):
                return error_code, detail["detail"]
            return error_code, str(detail)

        return None, str(detail)


@lru_cache
def get_document_service() -> DocumentService:
    """获取文档服务单例（带 LRU 缓存，避免重复创建）。"""
    return DocumentService()
