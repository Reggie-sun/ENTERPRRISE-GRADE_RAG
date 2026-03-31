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

from ..core.config import Settings, get_postgres_metadata_dsn, get_settings
from ..db.postgres_metadata_store import PostgresMetadataStore
from ..schemas.auth import AuthContext
from ..schemas.document import (
    Classification,
    DocumentBatchCreateResponse,
    DocumentBatchItemResponse,
    DocumentCreateResponse,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentLifecycleStatus,
    DocumentListResponse,
    DocumentPreviewResponse,
    DocumentRebuildResponse,
    DocumentRecord,
    DocumentSummary,
    DocumentUploadResponse,
    IngestJobRecord,
    IngestJobStatusResponse,
    Visibility,
)
from ..schemas.ops import OpsStuckIngestJobSummary
from .asset_store import AssetStore
from .event_log_service import EventLogService, get_event_log_service
from .ingestion_service import DocumentIngestionService
from ..rag.parsers.document_parser import SUPPORTED_PARSE_SUFFIXES, find_libreoffice_binary
from ..worker.celery_app import dispatch_ingest_job

SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 当前允许上传的扩展名与可解析扩展名保持一致
TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown"}
PARSED_TEXT_PREVIEW_SUFFIXES = {".doc", ".docx", ".csv", ".html", ".json", ".xlsx", ".pptx", ".xls"}
PDF_PREVIEW_SUFFIXES = {".pdf"}
SUPPORTED_PREVIEW_SUFFIXES = TEXT_PREVIEW_SUFFIXES | PARSED_TEXT_PREVIEW_SUFFIXES | PDF_PREVIEW_SUFFIXES
TEXT_PREVIEW_MAX_CHARS = 12_000
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
DOCUMENT_CONTENT_TYPE_BY_SUFFIX = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
}
PROCESSING_JOB_STATUSES = {"parsing", "ocr_processing", "chunking", "embedding", "indexing"}
IN_FLIGHT_JOB_STATUSES = {"pending", "uploaded", "queued"} | PROCESSING_JOB_STATUSES
TERMINAL_JOB_STATUSES = {"completed", "dead_letter", "partial_failed"}  # partial_failed 代表有可用结果但存在 OCR 告警
IngestBaseErrorCode = Literal["INGEST_DISPATCH_ERROR", "INGEST_VALIDATION_ERROR", "INGEST_RUNTIME_ERROR"]
UPLOAD_READ_CHUNK_SIZE_BYTES = 1 * 1024 * 1024
INGEST_ERROR_CODE_DISPATCH: IngestBaseErrorCode = "INGEST_DISPATCH_ERROR"
INGEST_ERROR_CODE_VALIDATION: IngestBaseErrorCode = "INGEST_VALIDATION_ERROR"
INGEST_ERROR_CODE_RUNTIME: IngestBaseErrorCode = "INGEST_RUNTIME_ERROR"
DEAD_LETTER_ERROR_SUFFIX = "_DEAD_LETTER"
PDF_MAGIC_PREFIX = b"%PDF-"
ZIP_OFFICE_UPLOAD_LABELS = {
    ".docx": "DOCX",
    ".pptx": "PPTX",
    ".xlsx": "XLSX",
}


@dataclass(frozen=True)
class DocumentFilePayload:
    media_type: str
    filename: str
    path: Path | None = None
    content: bytes | None = None


@dataclass(frozen=True)
class DepartmentPriorityRetrievalScope:
    department_document_ids: list[str]
    global_document_ids: list[str]


def _dead_letter_error_code(base_error_code: IngestBaseErrorCode) -> str:
    return f"{base_error_code}{DEAD_LETTER_ERROR_SUFFIX}"


def _sanitize_filename(filename: str) -> str:
    safe_name = Path(filename or "document").name
    suffix = Path(safe_name).suffix.lower()
    base_name = safe_name[: -len(suffix)] if suffix else safe_name

    cleaned_base = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name).strip("._-")
    if not cleaned_base:
        cleaned_base = "document"

    cleaned_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix.lstrip("."))
    if cleaned_suffix:
        return f"{cleaned_base}.{cleaned_suffix}"

    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name).strip("._")
    return fallback or "document"


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [item.strip() for item in values if item and item.strip()]


class DocumentService:
    def __init__(self, settings: Settings | None = None, *, event_log_service: EventLogService | None = None) -> None:
        self.settings = settings or get_settings()
        self.asset_store = AssetStore(self.settings)
        self.ingestion_service = DocumentIngestionService(self.settings)
        self.event_log_service = event_log_service or get_event_log_service()
        self.metadata_store: PostgresMetadataStore | None = None
        if self.settings.postgres_metadata_enabled:
            dsn = get_postgres_metadata_dsn(self.settings)
            if not dsn:  # avoid silent success when DSN is missing
                raise RuntimeError("PostgreSQL metadata storage enabled but no DSN configured.")
            store = PostgresMetadataStore(dsn)
            store.ping()
            store.ensure_required_tables()
            self.metadata_store = store

    async def create_document(
        self,
        *,
        upload: UploadFile,
        tenant_id: str,
        department_id: str | None = None,
        department_ids: list[str] | None = None,
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
        started_at = perf_counter()
        filename, suffix, content = await self._read_upload_content(upload)
        normalized_tenant_id = _normalize_optional_str(tenant_id)
        if normalized_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must not be blank.")
        normalized_department_id = _normalize_optional_str(department_id)
        normalized_department_ids = _normalize_optional_list(department_ids)
        if normalized_department_id and normalized_department_id not in normalized_department_ids:
            normalized_department_ids = [normalized_department_id, *normalized_department_ids]
        if normalized_department_id is None and normalized_department_ids:
            normalized_department_id = normalized_department_ids[0]
        normalized_category_id = _normalize_optional_str(category_id)
        normalized_role_ids = _normalize_optional_list(role_ids)
        normalized_tags = _normalize_optional_list(tags)
        normalized_owner_id = _normalize_optional_str(owner_id)
        normalized_source_system = _normalize_optional_str(source_system)
        normalized_uploaded_by = _normalize_optional_str(uploaded_by)
        normalized_created_by = _normalize_optional_str(created_by)
        effective_uploaded_by = normalized_uploaded_by or normalized_created_by
        effective_created_by = normalized_created_by or normalized_uploaded_by
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
        file_hash = hashlib.sha256(content).hexdigest()
        duplicate_record = self._find_document_record_by_file_hash(file_hash, tenant_id=normalized_tenant_id)  # 同租户下命中相同内容时直接复用已有文档
        if duplicate_record is not None and duplicate_record.status == "deleted":
            duplicate_record = None
        if duplicate_record is not None:
            latest_job_record = self._load_latest_job_record(duplicate_record.latest_job_id)
            self._refresh_duplicate_document_source(
                duplicate_record,
                content=content,
                filename=filename,
                source_type=suffix.lstrip(".") or "unknown",
                uploaded_by=effective_uploaded_by,
                created_by=effective_created_by,
            )  # 重复上传默认按"覆盖旧文档"处理
            if latest_job_record is not None and latest_job_record.status in IN_FLIGHT_JOB_STATUSES and self._has_materialized_ingest_artifacts(duplicate_record.doc_id):
                self._update_job_record(
                    latest_job_record,
                    status="completed",
                    stage="completed",
                    progress=100,
                )  # 若旧的 follow-up job 卡在 queued/processing，但同 doc_id 的解析和切块产物已存在，直接把这次重复上传修正为已完成可用态
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
            if latest_job_record is not None and latest_job_record.status == "completed":
                if not self._has_materialized_ingest_artifacts(duplicate_record.doc_id):
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
            if self._should_reuse_inflight_job(latest_job_record):
                # 仅复用"仍在持续刷新"的 in-flight job，避免历史卡死任务把当前重复上传也带挂
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
        now = datetime.now(timezone.utc)
        doc_id = self._generate_entity_id("doc")
        job_id = self._generate_entity_id("job")
        target_name = f"{doc_id}__{_sanitize_filename(filename)}"
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
            source_type=suffix.lstrip(".") or "unknown",
            department_id=normalized_department_id,
            department_ids=normalized_department_ids,
            category_id=normalized_category_id,
            role_ids=normalized_role_ids,
            owner_id=normalized_owner_id,
            visibility=visibility,
            classification=classification,
            tags=normalized_tags,
            source_system=normalized_source_system,
            status="queued",
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

        self._save_document_record(document_record)
        self._save_job_record(ingest_job)
        self._dispatch_job_or_fail(ingest_job, document_record)
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
        started_at = perf_counter()
        if not uploads:  # 避免返回无意义的批处理结果
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

    def queue_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
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
        # eager 模式下任务在当前进程直接执行，重新读取以拿到最新状态
        latest_job_record = self._load_job_record(job_id)
        return self._to_ingest_job_status_response(latest_job_record)

    def run_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
        job_record = self._load_job_record(job_id)
        document_record = self._load_document_record(job_record.doc_id)

        if job_record.status in TERMINAL_JOB_STATUSES:
            return self._to_ingest_job_status_response(job_record)
        if job_record.status in PROCESSING_JOB_STATUSES:
            return self._to_ingest_job_status_response(job_record)

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

        def on_stage(stage: str, progress: int) -> None:
            self._update_job_record(job_record, status=stage, stage=stage, progress=progress)

        try:
            with self.asset_store.materialize_for_processing(
                document_record.storage_path,
                file_name=document_record.file_name,
            ) as materialized_asset:
                if materialized_asset.normalized_storage_path != document_record.storage_path:
                    document_record.storage_path = materialized_asset.normalized_storage_path
                    document_record.updated_at = datetime.now(timezone.utc)
                    self._save_document_record(document_record)

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

    async def save_upload(self, upload: UploadFile) -> DocumentUploadResponse:
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

    def get_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDetailResponse:
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

    def delete_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDeleteResponse:
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)
            self._ensure_can_manage_document(record, auth_context)
            now = datetime.now(timezone.utc)
            # 先改主数据，再删副本
            if record.status != "deleted":
                record.status = "deleted"
                record.updated_at = now
                self._save_document_record(record)

            try:
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)
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
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)
            self._ensure_can_manage_document(record, auth_context)
            if record.status == "deleted":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deleted document cannot rebuild vectors: {doc_id}")

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

            try:
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to clean vector replica before rebuild for document {doc_id}: {exc}",
                ) from exc

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
                doc_id=doc_id,
                duration_ms=self._elapsed_ms(started_at),
                details={"error_message": str(exc)},
            )
            raise

    def get_ingest_job(self, job_id: str) -> IngestJobStatusResponse:
        record = self._load_job_record(job_id)
        return self._to_ingest_job_status_response(record)

    def _get_latest_ingest_status(self, latest_job_id: str | None) -> str | None:
        latest_job = self._load_latest_job_record(latest_job_id)
        if latest_job is None:
            return None
        return latest_job.status

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
        safe_page = max(1, page)
        safe_page_size = min(max(1, page_size), 200)
        normalized_keyword = _normalize_optional_str(keyword)
        normalized_department_id = _normalize_optional_str(department_id)
        normalized_category_id = _normalize_optional_str(category_id)
        self._ensure_department_filter_allowed(normalized_department_id, auth_context)
        items: list[DocumentSummary] = []
        records = self._list_document_records()
        # PostgreSQL 模式批量读取 latest job 状态，避免 N+1 查询
        latest_ingest_statuses: dict[str, str] = (
            self.metadata_store.load_job_statuses([record.latest_job_id for record in records]) if self.metadata_store is not None else {}
        )

        for record in records:
            if not self._can_read_document(record, auth_context):
                continue
            # PostgreSQL 模式统一走批量结果，避免列表查询退回到逐条 job 读取
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
                        status="uploaded",  # uploads 回退场景没有 metadata，统一标记为 uploaded
                        ingest_status=None,
                        latest_job_id=None,
                        department_id=None,
                        category_id=None,
                        uploaded_by=None,
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                    )
                )

        items.sort(key=lambda item: item.updated_at, reverse=True)
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
                continue
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
                1 if item.reason == "artifacts_ready_but_inflight" else 0,
                item.stale_seconds,
                item.updated_at.timestamp(),
            ),
            reverse=True,
        )
        return candidates[:safe_limit]

    @staticmethod
    def _matches_document_filters(
        item: DocumentSummary,
        *,
        keyword: str | None,
        department_id: str | None,
        category_id: str | None,
        document_status: DocumentLifecycleStatus | None,
    ) -> bool:
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
        try:
            record = self._load_document_record(doc_id)
        except HTTPException:
            return False
        return self._can_read_document(record, auth_context)

    def get_document_readability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
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

    def is_document_retrievable(self, doc_id: str, auth_context: AuthContext | None) -> bool:
        """Retrieval-specific readability check.

        Unlike ``_can_read_document`` (which gates direct access to documents,
        previews, downloads), this method only enforces tenant boundary and
        role-level visibility.  It does *not* reject cross-department documents
        so that the retrieval supplemental pool can include same-tenant documents
        from other departments.
        """
        if auth_context is None:
            return True
        try:
            record = self._load_document_record(doc_id)
        except HTTPException:
            return False
        return self._can_retrieve_document(record, auth_context)

    def get_document_retrievability_map(self, doc_ids: list[str], auth_context: AuthContext | None) -> dict[str, bool]:
        """Batch retrieval-specific readability check.

        See ``is_document_retrievable`` for the semantic difference from
        ``get_document_readability_map``.
        """
        normalized_doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()]
        if not normalized_doc_ids:
            return {}
        if auth_context is None:
            return {doc_id: True for doc_id in normalized_doc_ids}

        if self.metadata_store is not None:
            records = self.metadata_store.load_documents(normalized_doc_ids)
            return {
                doc_id: self._can_retrieve_document(record, auth_context)
                for doc_id, record in records.items()
            }

        retrievability: dict[str, bool] = {}
        for doc_id in normalized_doc_ids:
            try:
                record = self._load_document_record(doc_id)
            except HTTPException:
                retrievability[doc_id] = False
                continue
            retrievability[doc_id] = self._can_retrieve_document(record, auth_context)
        return retrievability

    def build_department_priority_retrieval_scope(
        self,
        auth_context: AuthContext | None,
    ) -> DepartmentPriorityRetrievalScope | None:
        if auth_context is None:
            return None
        if auth_context.role.data_scope == "global":
            return None

        current_department_id = auth_context.department.department_id
        department_document_ids: list[str] = []
        global_document_ids: list[str] = []

        for record in self._list_document_records():
            if record.status == "deleted":
                continue
            # Use retrieval-scoped readability which does NOT reject cross-department docs
            if not self._can_retrieve_document(record, auth_context):
                continue

            record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
            is_department_match = current_department_id in record_departments if record_departments else False

            if is_department_match:
                department_document_ids.append(record.doc_id)
            else:
                # Supplemental pool: same-tenant documents not in the user's department.
                # Only documents with public visibility belong in the supplemental pool.
                if record.visibility == "public":
                    global_document_ids.append(record.doc_id)

        return DepartmentPriorityRetrievalScope(
            department_document_ids=department_document_ids,
            global_document_ids=global_document_ids,
        )

    def ensure_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> None:
        record = self._load_document_record(doc_id)
        self._ensure_can_read_document(record, auth_context)

    @staticmethod
    def _normalize_department_scope(values: list[str] | None, primary_department_id: str | None) -> list[str]:
        normalized: list[str] = []
        if primary_department_id and primary_department_id not in normalized:
            normalized.append(primary_department_id)
        for item in values or []:
            if item and item not in normalized:
                normalized.append(item)
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
        if auth_context is None:  # 前端登录接入前先兼容当前开发工作台。
            return tenant_id, department_id, department_ids, uploaded_by, created_by

        if tenant_id != auth_context.user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create documents outside your tenant.")

        effective_department_id = department_id
        effective_department_ids = self._normalize_department_scope(department_ids, department_id)
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

        effective_uploaded_by = auth_context.user.user_id
        effective_created_by = auth_context.user.user_id
        return tenant_id, effective_department_id, effective_department_ids, effective_uploaded_by, effective_created_by

    def _ensure_department_filter_allowed(self, department_id: str | None, auth_context: AuthContext | None) -> None:
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
        if self._can_read_document(record, auth_context):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this document.")

    def _ensure_can_manage_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> None:
        if self._can_manage_document(record, auth_context):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage this document.")

    def _can_read_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> bool:
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
        if not record_departments:  # 兼容旧数据：没有部门字段时默认当前租户内可读。
            return True
        return bool(set(record_departments) & set(auth_context.accessible_department_ids))

    def _can_retrieve_document(self, record: DocumentRecord, auth_context: AuthContext) -> bool:
        """Retrieval-scoped readability: enforces tenant + role visibility only.

        This intentionally does *not* check department isolation, so that
        same-tenant cross-department documents can enter the retrieval
        supplemental pool.  Direct-access interfaces (detail, download,
        preview) continue to use ``_can_read_document`` which enforces
        department isolation.
        """
        if record.tenant_id != auth_context.user.tenant_id:
            return False
        if auth_context.role.data_scope == "global":
            return True
        if record.visibility == "role" and record.role_ids and auth_context.user.role_id not in record.role_ids:
            return False
        return True

    def _can_manage_document(self, record: DocumentRecord, auth_context: AuthContext | None) -> bool:
        if auth_context is None:
            return True
        if record.tenant_id != auth_context.user.tenant_id:
            return False
        if auth_context.user.role_id == "sys_admin":
            return True
        if auth_context.user.role_id != "department_admin":
            return False
        record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
        if not record_departments:
            return False
        return set(record_departments).issubset(set(auth_context.accessible_department_ids))

    async def _read_upload_content(self, upload: UploadFile) -> tuple[str, str, bytes]:
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
            chunk = await upload.read(UPLOAD_READ_CHUNK_SIZE_BYTES)
            if not chunk:
                break
            content_buffer.extend(chunk)
            if len(content_buffer) > self.settings.upload_max_file_size_bytes:
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
        if suffix == ".pdf" and not content.lstrip().startswith(PDF_MAGIC_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid PDF content for '{filename}': missing PDF file signature (%PDF-); "
                    "source file may be mislabeled, encrypted, or corrupted."
                ),
            )

        office_label = ZIP_OFFICE_UPLOAD_LABELS.get(suffix)
        if office_label is not None and not is_zipfile(BytesIO(content)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {office_label} container for '{filename}'.",
            )

        if suffix == ".doc" and find_libreoffice_binary() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Legacy DOC parsing requires a resolvable LibreOffice binary in the current API runtime.",
            )

        if suffix == ".xls" and importlib.util.find_spec("xlrd") is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parsing .xls files requires xlrd to be installed on the API/worker runtime.",
            )

    @staticmethod
    def _generate_entity_id(prefix: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"

    def _document_record_path(self, doc_id: str) -> Path:
        return self.settings.document_dir / f"{doc_id}.json"

    def _job_record_path(self, job_id: str) -> Path:
        return self.settings.job_dir / f"{job_id}.json"

    @staticmethod
    def _write_json(path: Path, model: DocumentRecord | IngestJobRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def _save_document_record(self, record: DocumentRecord) -> None:
        if self.metadata_store is not None:
            self.metadata_store.save_document(record)
            return
        self._write_json(self._document_record_path(record.doc_id), record)

    def _save_job_record(self, record: IngestJobRecord) -> None:
        if self.metadata_store is not None:
            self.metadata_store.save_job(record)
            return
        self._write_json(self._job_record_path(record.job_id), record)

    def _list_document_records(self) -> list[DocumentRecord]:
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
        record.status = status
        record.stage = stage
        record.progress = max(0, min(100, progress))
        record.error_code = error_code
        record.error_message = error_message
        if increase_retry:
            record.retry_count += 1
        record.updated_at = datetime.now(timezone.utc)
        self._save_job_record(record)

    def _to_ingest_job_status_response(self, record: IngestJobRecord) -> IngestJobStatusResponse:
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
        if self.metadata_store is not None:
            record = self.metadata_store.load_document(doc_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")
            return record
        path = self._document_record_path(doc_id)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_job_record(self, job_id: str) -> IngestJobRecord:
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
        if not latest_job_id:
            return None
        try:
            return self._load_job_record(latest_job_id)
        except HTTPException:
            return None

    def _is_job_stale(self, job_record: IngestJobRecord) -> bool:
        updated_at = job_record.updated_at
        if updated_at.tzinfo is None:  # 兼容旧 JSON 里没有显式时区的时间戳
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        stale_after = timedelta(seconds=self.settings.ingest_inflight_stale_seconds)
        return datetime.now(timezone.utc) - updated_at > stale_after

    def _should_reuse_inflight_job(self, job_record: IngestJobRecord | None) -> bool:
        if job_record is None:
            return False
        if job_record.status not in IN_FLIGHT_JOB_STATUSES:
            return False
        return not self._is_job_stale(job_record)

    def _has_materialized_ingest_artifacts(self, doc_id: str) -> bool:
        parsed_path = self.settings.parsed_dir / f"{doc_id}.txt"
        if parsed_path.exists() and parsed_path.stat().st_size > 0:
            return True
        chunk_path = self.settings.chunk_dir / f"{doc_id}.json"
        return chunk_path.exists() and chunk_path.stat().st_size > 0

    def _find_document_record_by_file_hash(self, file_hash: str, *, tenant_id: str | None = None) -> DocumentRecord | None:
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
        created_by: str | None,
    ) -> None:
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
            # avoid silent success when dispatch fails
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

    @staticmethod  # 这个方法不依赖实例状态，所以声明成静态方法
    def _decode_storage_name(storage_name: str) -> tuple[str, str]:
        if "__" not in storage_name:
            return "unknown", storage_name
        return tuple(storage_name.split("__", 1))  # type: ignore[return-value]

    @staticmethod
    def _normalize_source_suffix(source_type: str) -> str:
        normalized = source_type.strip().lower().lstrip(".")
        return f".{normalized}" if normalized else ""

    def _load_text_preview_content(
        self,
        record: DocumentRecord,
        *,
        suffix: str,
        max_chars: int,
    ) -> tuple[str, bool]:
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

        with self.asset_store.materialize_for_processing(record.storage_path, file_name=record.file_name) as materialized_asset:
            parsed_document = self.ingestion_service.parser.parse(
                source_path=materialized_asset.path,
                document_id=record.doc_id,
                filename=record.file_name,
            )
        return self._read_text_preview_bytes(parsed_document.text.encode("utf-8"), max_chars=max_chars)

    @staticmethod
    def _read_text_preview_bytes(content: bytes, *, max_chars: int) -> tuple[str, bool]:
        raw_text = content.decode("utf-8", errors="ignore")  # 用 ignore 兼容脏字符，避免单文件编码问题打断页面
        safe_limit = max(1, max_chars)
        if len(raw_text) <= safe_limit:
            return raw_text, False
        return raw_text[:safe_limit], True

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
        return max(0, int((perf_counter() - started_at) * 1000))

    @staticmethod
    def _extract_batch_error_detail(detail: object) -> tuple[str | None, str]:
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
    return DocumentService()
