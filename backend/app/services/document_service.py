import hashlib  # 导入 hashlib，用来计算文件哈希。
import re  # 导入正则库，用来清洗上传文件名。
from dataclasses import dataclass  # 导入 dataclass，封装文件下载/预览的统一返回载荷。
from datetime import datetime, timedelta, timezone  # 导入时间工具，用来生成 UTC 时间戳并判断任务是否过期。
from functools import lru_cache  # 导入缓存装饰器，避免重复创建重量级服务实例。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from time import perf_counter
from typing import Literal  # 导入 Literal，用于约束 ingest 错误码基类。
from uuid import uuid4  # 导入 uuid4，用来生成文档唯一标识。

from fastapi import HTTPException, UploadFile, status  # 导入 FastAPI 异常、上传文件对象和状态码。

from ..core.config import Settings, get_postgres_metadata_dsn, get_settings  # 导入配置对象和配置获取函数。
from ..db.postgres_metadata_store import PostgresMetadataStore  # 导入 PostgreSQL 元数据存储实现。
from ..schemas.auth import AuthContext  # 导入统一鉴权上下文，供文档读写过滤复用。
from ..schemas.document import (  # 导入文档相关响应模型和持久化结构。
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
from .asset_store import AssetStore  # 导入统一资产存储抽象，解耦上传文件与 worker 所在机器。
from .event_log_service import EventLogService, get_event_log_service
from .ingestion_service import DocumentIngestionService  # 导入文档入库服务。
from ..worker.celery_app import dispatch_ingest_job  # 导入 Celery 投递函数，用于异步触发 ingest job。

SUPPORTED_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".docx"}  # 当前系统支持解析的文件扩展名集合。
SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 当前允许上传的扩展名与可解析扩展名保持一致。
TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown"}  # 支持直接读取原始文本预览的扩展名集合。
PARSED_TEXT_PREVIEW_SUFFIXES = {".docx"}  # 需要先解析成纯文本再做预览的扩展名集合。
PDF_PREVIEW_SUFFIXES = {".pdf"}  # 支持在线 PDF 预览的扩展名集合。
SUPPORTED_PREVIEW_SUFFIXES = TEXT_PREVIEW_SUFFIXES | PARSED_TEXT_PREVIEW_SUFFIXES | PDF_PREVIEW_SUFFIXES  # 统一预览支持集合。
TEXT_PREVIEW_MAX_CHARS = 12_000  # 文本预览最大字符数，避免一次返回过大响应。
TEXT_PREVIEW_CONTENT_TYPE_BY_SUFFIX = {  # 文本预览接口的内容类型映射。
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".docx": "text/plain; charset=utf-8",
}
DOCUMENT_CONTENT_TYPE_BY_SUFFIX = {  # 原始文件下载与 PDF 文件流预览的内容类型映射。
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
PROCESSING_JOB_STATUSES = {"parsing", "ocr_processing", "chunking", "embedding", "indexing"}  # ingest job 处理中状态集合。
IN_FLIGHT_JOB_STATUSES = {"pending", "uploaded", "queued"} | PROCESSING_JOB_STATUSES  # ingest job 进行中状态集合，重复上传时优先复用当前任务。
TERMINAL_JOB_STATUSES = {"completed", "dead_letter"}  # ingest job 终态集合。
IngestBaseErrorCode = Literal["INGEST_DISPATCH_ERROR", "INGEST_VALIDATION_ERROR", "INGEST_RUNTIME_ERROR"]  # ingest 基础错误码集合。
UPLOAD_READ_CHUNK_SIZE_BYTES = 1 * 1024 * 1024  # 上传文件分块读取大小，避免一次 read() 拉满内存。
INGEST_ERROR_CODE_DISPATCH: IngestBaseErrorCode = "INGEST_DISPATCH_ERROR"  # 调度失败基础错误码。
INGEST_ERROR_CODE_VALIDATION: IngestBaseErrorCode = "INGEST_VALIDATION_ERROR"  # 业务校验失败基础错误码。
INGEST_ERROR_CODE_RUNTIME: IngestBaseErrorCode = "INGEST_RUNTIME_ERROR"  # 运行期依赖失败基础错误码。
DEAD_LETTER_ERROR_SUFFIX = "_DEAD_LETTER"  # dead_letter 错误码后缀。


@dataclass(frozen=True)
class DocumentFilePayload:
    media_type: str
    filename: str
    path: Path | None = None
    content: bytes | None = None


def _dead_letter_error_code(base_error_code: IngestBaseErrorCode) -> str:  # 给基础错误码统一追加 dead_letter 后缀。
    return f"{base_error_code}{DEAD_LETTER_ERROR_SUFFIX}"  # 返回标准化 dead_letter 错误码。


def _sanitize_filename(filename: str) -> str:  # 清洗上传文件名，避免非法字符进入磁盘路径。
    safe_name = Path(filename or "document").name  # 只保留文件名本体，避免路径穿越。
    suffix = Path(safe_name).suffix.lower()  # 先拿到原始扩展名，后续单独保留，避免清洗过程把扩展名吞掉。
    base_name = safe_name[: -len(suffix)] if suffix else safe_name  # 把主名和扩展名拆开处理。

    cleaned_base = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name).strip("._-")  # 清洗主文件名，不动扩展名。
    if not cleaned_base:  # 主文件名完全被清空时回退兜底值。
        cleaned_base = "document"

    cleaned_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix.lstrip("."))  # 扩展名仅保留字母数字，避免异常字符。
    if cleaned_suffix:
        return f"{cleaned_base}.{cleaned_suffix}"  # 有合法扩展名时拼回去，保证后续解析器能识别文件类型。

    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name).strip("._")  # 没有合法扩展名时回退到旧逻辑行为。
    return fallback or "document"  # 如果仍为空，统一回退 document。


def _normalize_optional_str(value: str | None) -> str | None:  # 统一清洗可选字符串，空白值视为未传。
    if value is None:  # 没传值时直接返回 None。
        return None
    normalized = value.strip()  # 去掉首尾空白，避免把空格当有效值存库。
    return normalized or None  # 清洗后为空字符串时，统一转成 None。


def _normalize_optional_list(values: list[str] | None) -> list[str]:  # 统一清洗数组字段，去掉空白和空字符串。
    if not values:  # 没传值或空列表时直接返回空列表。
        return []
    return [item.strip() for item in values if item and item.strip()]  # 只保留有意义的字符串项。


class DocumentService:  # 封装文档上传、列表和入库的业务逻辑。
    def __init__(self, settings: Settings | None = None, *, event_log_service: EventLogService | None = None) -> None:  # 初始化文档服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.asset_store = AssetStore(self.settings)  # 初始化统一资产存储，上传/worker/下载都通过这一层解耦。
        self.ingestion_service = DocumentIngestionService(self.settings)  # 创建入库服务实例。
        self.event_log_service = event_log_service or get_event_log_service()  # 文档操作日志统一写这里，后续查询接口复用。
        self.metadata_store: PostgresMetadataStore | None = None  # 默认不启用 PostgreSQL 元数据存储。
        if self.settings.postgres_metadata_enabled:  # 显式启用后，切换 document/job 元数据到 PostgreSQL 真源。
            dsn = get_postgres_metadata_dsn(self.settings)  # 读取 PostgreSQL 连接串，兼容 DATABASE_URL。
            if not dsn:  # 启用开关但没有 DSN 时，直接失败，避免“看起来成功但数据没落库”。
                raise RuntimeError("PostgreSQL metadata storage enabled but no DSN configured.")
            store = PostgresMetadataStore(dsn)  # 创建 PostgreSQL 元数据存储实例。
            store.ping()  # 启动阶段先做一次连通性校验，失败尽早暴露。
            store.ensure_required_tables()  # 校验目标表是否存在，避免运行期才发现元数据无法写入。
            self.metadata_store = store  # 元数据操作统一切到 PostgreSQL。

    async def create_document(  # 创建文档记录和 ingest job，并立即返回 queued。
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
        filename, suffix, content = await self._read_upload_content(upload)  # 先统一校验并读取上传文件内容。
        normalized_tenant_id = _normalize_optional_str(tenant_id)  # 对租户 ID 做空白归一化。
        if normalized_tenant_id is None:  # tenant_id 是必填字段，清洗后为空也应拒绝。
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must not be blank.")
        normalized_department_id = _normalize_optional_str(department_id)  # 清洗主部门字段。
        normalized_department_ids = _normalize_optional_list(department_ids)  # 清洗部门列表，去掉空字符串。
        if normalized_department_id and normalized_department_id not in normalized_department_ids:  # 只传主部门时也补齐部门范围。
            normalized_department_ids = [normalized_department_id, *normalized_department_ids]
        if normalized_department_id is None and normalized_department_ids:  # 老数据只有部门列表时，主部门默认取第一项。
            normalized_department_id = normalized_department_ids[0]
        normalized_category_id = _normalize_optional_str(category_id)  # 清洗分类字段。
        normalized_role_ids = _normalize_optional_list(role_ids)  # 清洗角色列表，去掉空字符串。
        normalized_tags = _normalize_optional_list(tags)  # 清洗标签列表，去掉空字符串。
        normalized_owner_id = _normalize_optional_str(owner_id)  # 清洗 owner_id。
        normalized_source_system = _normalize_optional_str(source_system)  # 清洗 source_system。
        normalized_uploaded_by = _normalize_optional_str(uploaded_by)  # 清洗上传人（新字段）。
        normalized_created_by = _normalize_optional_str(created_by)  # 清洗 created_by。
        effective_uploaded_by = normalized_uploaded_by or normalized_created_by  # 新旧命名统一收敛。
        effective_created_by = normalized_created_by or normalized_uploaded_by  # 旧字段保持兼容。
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
        file_hash = hashlib.sha256(content).hexdigest()  # 对上传内容计算稳定哈希，用于内容级去重。
        duplicate_record = self._find_document_record_by_file_hash(file_hash, tenant_id=normalized_tenant_id)  # 同租户下命中相同内容时直接复用已有文档。
        if duplicate_record is not None and duplicate_record.status == "deleted":  # 已删除文档不参与去重，可按同内容重新创建新文档。
            duplicate_record = None
        if duplicate_record is not None:
            latest_job_record = self._load_latest_job_record(duplicate_record.latest_job_id)  # 读取最近一次任务记录，判断是否仍值得复用。
            self._refresh_duplicate_document_source(
                duplicate_record,
                content=content,
                filename=filename,
                source_type=suffix.lstrip(".") or "unknown",
                uploaded_by=effective_uploaded_by,
                created_by=effective_created_by,
            )  # 重复上传默认按“覆盖旧文档”处理，先用新文件刷新元数据和存储路径。
            if self._should_reuse_inflight_job(latest_job_record):
                # 仅复用“仍在持续刷新”的 in-flight job，避免历史卡死任务把当前重复上传也带挂。
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
            followup_job = self._create_followup_ingest_job(duplicate_record)  # 旧任务已终止或缺失时，补发一个新 job 覆盖旧结果。
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
        now = datetime.now(timezone.utc)  # 记录本次创建的统一时间戳。
        doc_id = self._generate_entity_id("doc")  # 生成文档 ID。
        job_id = self._generate_entity_id("job")  # 生成任务 ID。
        target_name = f"{doc_id}__{_sanitize_filename(filename)}"  # 生成安全的磁盘文件名。
        storage_path = self.asset_store.save_upload(
            doc_id=doc_id,
            target_name=target_name,
            file_name=filename,
            content=content,
            mime_type=upload.content_type,
            job_id=job_id,
        )  # 把原始文件写入当前配置的资产后端。

        document_record = DocumentRecord(  # 组装 document 元数据记录。
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
        ingest_job = IngestJobRecord(  # 组装 ingest job 元数据记录。
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

        self._save_document_record(document_record)  # 按当前存储策略持久化 document 元数据。
        self._save_job_record(ingest_job)  # 按当前存储策略持久化 ingest job 元数据。
        self._dispatch_job_or_fail(ingest_job, document_record)  # 把新建的 job 投递到 Celery 队列，失败时立即返回错误。
        self._record_document_event(
            action="create",
            outcome="success",
            auth_context=auth_context,
            doc_id=doc_id,
            job_id=job_id,
            duration_ms=self._elapsed_ms(started_at),
            details={"file_name": filename, "duplicate": False},
        )

        return DocumentCreateResponse(doc_id=doc_id, job_id=job_id, status="queued")  # 返回接口需要的最小响应。

    async def create_documents_batch(  # 批量创建文档任务：每个文件仍复用单文档创建链路。
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
        if not uploads:  # 空文件列表直接拒绝，避免返回无意义的批处理结果。
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files must not be empty.")

        items: list[DocumentBatchItemResponse] = []  # 逐文件收集处理结果，失败不打断后续文件。
        for upload in uploads:
            file_name = upload.filename or "document"
            try:  # 单文件创建直接复用现有 create_document，保持行为一致。
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
            except HTTPException as exc:  # 单文件失败时记录错误，继续处理剩余文件。
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

    def queue_ingest_job(self, job_id: str) -> IngestJobStatusResponse:  # 把指定 ingest job 重新投递到异步队列。
        job_record = self._load_job_record(job_id)  # 读取当前任务记录。
        document_record = self._load_document_record(job_record.doc_id)  # 读取关联文档记录。

        if job_record.status in PROCESSING_JOB_STATUSES:  # 处理中任务不重复投递，直接返回当前状态。
            return self._to_ingest_job_status_response(job_record)
        if job_record.status == "completed":  # 已完成任务不做重复重跑，保持当前状态。
            return self._to_ingest_job_status_response(job_record)

        document_record.status = "queued"  # 重新投递前把文档状态切回 queued。
        document_record.updated_at = datetime.now(timezone.utc)  # 刷新文档更新时间。
        self._save_document_record(document_record)  # 落盘文档状态。
        self._update_job_record(  # 重置任务状态，等待 worker 异步消费。
            job_record,
            status="queued",
            stage="queued",
            progress=0,
            error_code=None,
            error_message=None,
        )
        self._dispatch_job_or_fail(job_record, document_record)  # 正式投递到 Celery 队列。
        latest_job_record = self._load_job_record(job_id)  # 重新读取最新任务状态，兼容 eager 模式下任务已同步执行完成。
        return self._to_ingest_job_status_response(latest_job_record)  # 返回最新的任务状态。

    def run_ingest_job(self, job_id: str) -> IngestJobStatusResponse:  # 执行指定 ingest job，并更新文档与任务状态。
        job_record = self._load_job_record(job_id)  # 读取当前任务记录。
        document_record = self._load_document_record(job_record.doc_id)  # 读取关联文档记录。

        if job_record.status in TERMINAL_JOB_STATUSES:  # 已完成或死信任务直接返回当前状态，避免重复执行。
            return self._to_ingest_job_status_response(job_record)
        if job_record.status in PROCESSING_JOB_STATUSES:  # 如果任务已经在处理中，直接返回当前状态。
            return self._to_ingest_job_status_response(job_record)

        document_record.status = "uploaded"  # 任务开始前先把文档标记为 uploaded。
        document_record.updated_at = datetime.now(timezone.utc)  # 更新文档更新时间。
        self._save_document_record(document_record)  # 落盘更新后的文档状态。

        self._update_job_record(  # 把任务状态改成 parsing，开始执行入库。
            job_record,
            status="parsing",
            stage="parsing",
            progress=5,
            error_code=None,
            error_message=None,
        )

        def on_stage(stage: str, progress: int) -> None:  # 定义阶段回调，给 ingest 流程实时更新状态。
            self._update_job_record(job_record, status=stage, stage=stage, progress=progress)  # 同步写入当前阶段和进度。

        try:  # 尝试执行完整入库流程。
            with self.asset_store.materialize_for_processing(
                document_record.storage_path,
                file_name=document_record.file_name,
            ) as materialized_asset:
                if materialized_asset.normalized_storage_path != document_record.storage_path:  # 命中本地 fallback 时，同步回写当前可访问路径。
                    document_record.storage_path = materialized_asset.normalized_storage_path
                    document_record.updated_at = datetime.now(timezone.utc)
                    self._save_document_record(document_record)

                self.ingestion_service.ingest_document(  # 调用入库服务执行解析、切块、向量化和写库。
                    document_id=document_record.doc_id,  # 传入文档 ID。
                    filename=document_record.file_name,  # 传入原始文件名。
                    source_path=materialized_asset.local_path,  # 传入当前运行环境可访问的原始文件路径。
                    on_stage=on_stage,  # 传入阶段回调，用于进度更新。
                )
        except ValueError as exc:  # 捕获业务可预期错误，例如切块失败。
            return self._mark_ingest_failure(  # 按失败重试上限统一处理失败/死信状态。
                job_record=job_record,
                document_record=document_record,
                error_code=INGEST_ERROR_CODE_VALIDATION,
                error_message=str(exc),
            )
        except (RuntimeError, OSError) as exc:  # 捕获依赖错误和底层文件 IO 错误，例如 embedding/Qdrant/历史路径失效。
            return self._mark_ingest_failure(  # 按失败重试上限统一处理失败/死信状态。
                job_record=job_record,
                document_record=document_record,
                error_code=INGEST_ERROR_CODE_RUNTIME,
                error_message=str(exc),
            )

        self._update_job_record(  # 入库成功后把任务标记成 completed。
            job_record,
            status="completed",
            stage="completed",
            progress=100,
            error_code=None,
            error_message=None,
        )
        document_record.status = "active"  # 文档状态切成 active，表示可检索。
        document_record.updated_at = datetime.now(timezone.utc)  # 更新时间戳。
        self._save_document_record(document_record)  # 落盘文档状态。
        return self._to_ingest_job_status_response(job_record)  # 返回最新任务状态。

    async def save_upload(self, upload: UploadFile) -> DocumentUploadResponse:  # 保存上传文件并执行完整入库。
        filename, _, content = await self._read_upload_content(upload)  # 复用统一上传校验逻辑。
        document_id = uuid4().hex  # 为当前文档生成唯一 ID。
        target_name = f"{document_id}__{_sanitize_filename(filename)}"  # 把文档 ID 和清洗后的文件名拼成磁盘文件名。
        storage_path = self.asset_store.save_upload(
            doc_id=document_id,
            target_name=target_name,
            file_name=filename,
            content=content,
            mime_type=upload.content_type,
        )  # 把原始文件写入当前配置的资产后端。

        try:  # 尝试执行完整的文档入库流程。
            with self.asset_store.materialize_for_processing(storage_path, file_name=filename) as materialized_asset:
                ingestion_result = self.ingestion_service.ingest_document(  # 调用入库服务执行解析、切分、向量化和写库。
                    document_id=document_id,  # 传入文档唯一 ID。
                    filename=filename,  # 传入原始文件名。
                    source_path=materialized_asset.local_path,  # 传入当前可访问的原始文件路径。
                )
        except ValueError as exc:  # 捕获业务层可预期的解析或切分错误。
            raise HTTPException(  # 把业务错误转换成 HTTP 422。
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,  # 使用 422，表示文件能上传但内容无法处理。
                detail=str(exc),  # 返回具体错误文本。
            ) from exc
        except RuntimeError as exc:  # 捕获外部依赖失败，例如 embedding 或 Qdrant 错误。
            raise HTTPException(  # 把依赖错误转换成 HTTP 502。
                status_code=status.HTTP_502_BAD_GATEWAY,  # 使用 502，表示后端依赖异常。
                detail=str(exc),  # 返回具体错误文本。
            ) from exc

        return DocumentUploadResponse(  # 把入库结果组装成接口响应。
            document_id=document_id,  # 返回文档唯一 ID。
            filename=filename,  # 返回原始文件名。
            content_type=upload.content_type,  # 返回文件 MIME 类型。
            size_bytes=len(content),  # 返回文件大小。
            parse_supported=True,  # 当前能走到这里说明文件类型可解析。
            storage_path=storage_path,  # 返回原始文件存储引用。
            parsed_path=ingestion_result.parsed_path,  # 返回解析文本路径。
            chunk_path=ingestion_result.chunk_path,  # 返回 chunk 文件路径。
            collection_name=ingestion_result.collection_name,  # 返回写入的 Qdrant collection。
            parser_name=ingestion_result.parser_name,  # 返回本次使用的解析器名称。
            chunk_count=ingestion_result.chunk_count,  # 返回生成的 chunk 数量。
            vector_count=ingestion_result.vector_count,  # 返回写入的向量数量。
            created_at=datetime.now(timezone.utc),  # 返回当前 UTC 时间。
        )

    def get_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDetailResponse:  # 按 doc_id 读取文档元信息。
        record = self._load_document_record(doc_id)  # 从本地元数据目录读取 document 记录。
        self._ensure_can_read_document(record, auth_context)  # 已登录场景按部门/角色上下文校验读权限。
        latest_ingest_status = self._get_latest_ingest_status(record.latest_job_id)  # 最近一次 ingest 状态与文档状态分离展示。
        return DocumentDetailResponse(  # 把完整记录映射成对外的详情响应。
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
    ) -> DocumentPreviewResponse:  # 按 doc_id 读取在线预览内容。
        record = self._load_document_record(doc_id)  # 先读取文档元数据。
        self._ensure_can_read_document(record, auth_context)  # 文档预览复用统一读权限判断。
        suffix = self._normalize_source_suffix(record.source_type)  # 统一计算文档扩展名。
        if suffix not in SUPPORTED_PREVIEW_SUFFIXES:  # 对不支持预览的文件类型直接返回 422。
            supported = ", ".join(sorted(SUPPORTED_PREVIEW_SUFFIXES))
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Preview is not supported for file type: {suffix or 'unknown'}. Supported types: {supported}",
            )

        if suffix in TEXT_PREVIEW_SUFFIXES | PARSED_TEXT_PREVIEW_SUFFIXES:  # 文本类文档返回文本预览，DOCX 走解析文本。
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

        parsed_path = self.settings.parsed_dir / f"{record.doc_id}.txt"  # PDF 预览时可选返回解析文本片段，便于快速浏览。
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

    def get_document_preview_file(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentFilePayload:  # 返回文档在线预览文件流所需信息。
        record = self._load_document_record(doc_id)  # 读取文档元数据。
        self._ensure_can_read_document(record, auth_context)  # PDF 文件流预览也走同一份读权限。
        suffix = self._normalize_source_suffix(record.source_type)  # 统一计算扩展名。
        if suffix not in PDF_PREVIEW_SUFFIXES:  # 当前仅允许 PDF 走文件流预览。
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

    def get_document_file(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentFilePayload:  # 返回原始文件下载流所需信息。
        record = self._load_document_record(doc_id)  # 读取文档元数据。
        self._ensure_can_read_document(record, auth_context)  # 下载接口同样受部门范围控制。
        suffix = self._normalize_source_suffix(record.source_type)  # 统一计算扩展名，回填 content-type。
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

    def delete_document(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentDeleteResponse:  # 删除文档：先更新主数据状态，再清理向量副本。
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)  # 读取文档元数据，不存在会抛 404。
            self._ensure_can_manage_document(record, auth_context)  # 删除属于管理操作，普通员工无权限。
            now = datetime.now(timezone.utc)
            if record.status != "deleted":  # 首次删除时先落盘主数据状态，满足“先改主数据，再删副本”顺序。
                record.status = "deleted"
                record.updated_at = now
                self._save_document_record(record)

            try:  # 主数据状态落盘后，再执行向量副本删除。
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)
            except RuntimeError as exc:  # 清理向量副本失败时返回 502，便于前端重试。
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

    def rebuild_document_vectors(self, doc_id: str, *, auth_context: AuthContext | None = None) -> DocumentRebuildResponse:  # 重建文档向量：先清理旧向量，再复用 ingest job 机制重建。
        started_at = perf_counter()
        try:
            record = self._load_document_record(doc_id)  # 先读取文档元数据。
            self._ensure_can_manage_document(record, auth_context)  # 重建也属于管理动作，边界与删除保持一致。
            if record.status == "deleted":  # 已删除文档不允许重建，避免“删除后复活”语义混乱。
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deleted document cannot rebuild vectors: {doc_id}")

            if record.latest_job_id:  # 已有任务时，先检查是否存在进行中的任务，避免重复并发重建。
                try:
                    latest_job = self._load_job_record(record.latest_job_id)
                    if self._should_reuse_inflight_job(latest_job):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Document ingest job is still running: {record.latest_job_id}",
                        )
                except HTTPException as exc:
                    if exc.status_code != status.HTTP_404_NOT_FOUND:  # 仅忽略“旧 job 不存在”的场景，其余错误继续抛出。
                        raise

            try:  # 先清理旧向量副本，避免重建后残留历史脏点位。
                removed = self.ingestion_service.vector_store.delete_document_points(record.doc_id)
            except RuntimeError as exc:  # 向量库操作失败时返回 502，便于前端提示依赖异常。
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to clean vector replica before rebuild for document {doc_id}: {exc}",
                ) from exc

            followup_job = self._create_followup_ingest_job(record)  # 复用现有 ingest job 创建+投递逻辑。
            response = DocumentRebuildResponse(  # 返回重建任务信息，前端可据此轮询状态。
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

    def get_ingest_job(self, job_id: str) -> IngestJobStatusResponse:  # 按 job_id 读取 ingest job 状态。
        record = self._load_job_record(job_id)  # 从本地元数据目录读取 job 记录。
        return self._to_ingest_job_status_response(record)  # 返回接口需要的任务状态字段。

    def _get_latest_ingest_status(self, latest_job_id: str | None) -> str | None:  # 读取最近一次 ingest 状态，缺失或异常时返回 None。
        latest_job = self._load_latest_job_record(latest_job_id)  # 先安全读取 latest job，避免列表接口被缺失记录打断。
        if latest_job is None:
            return None
        return latest_job.status

    def list_documents(  # 列出当前已经上传过的文档，并支持分页与筛选。
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
        safe_page = max(1, page)  # 兜底页码最小值，避免直接调用服务层时传入非法页码。
        safe_page_size = min(max(1, page_size), 200)  # 兜底分页大小，和接口层上限保持一致。
        normalized_keyword = _normalize_optional_str(keyword)  # 关键字筛选参数去空白。
        normalized_department_id = _normalize_optional_str(department_id)  # 部门筛选参数去空白。
        normalized_category_id = _normalize_optional_str(category_id)  # 分类筛选参数去空白。
        self._ensure_department_filter_allowed(normalized_department_id, auth_context)  # 已登录场景拒绝越权查其他部门。
        items: list[DocumentSummary] = []  # 初始化文档摘要列表。
        latest_ingest_statuses: dict[str, str] = {}  # PostgreSQL 模式下批量缓存 latest job 状态，避免 N+1 查询。
        if self.metadata_store is not None:  # PostgreSQL 模式优先从数据库读取文档列表。
            records = self.metadata_store.list_documents()  # 读取数据库中的 document 记录。
            latest_ingest_statuses = self.metadata_store.load_job_statuses(
                [record.latest_job_id for record in records]
            )  # 批量读取 latest job 状态，避免每条 document 再单独查一次 job。
        else:  # 未启用 PostgreSQL 时，继续沿用本地 JSON 元数据目录。
            self.settings.document_dir.mkdir(parents=True, exist_ok=True)  # 确保 documents 元数据目录存在。
            records = []  # 先初始化空列表，再从 JSON 文件反序列化。
            for path in sorted(self.settings.document_dir.glob("*.json")):  # 遍历所有 document 元数据文件。
                if not path.is_file() or path.name.startswith("."):  # 跳过目录和隐藏文件。
                    continue
                records.append(DocumentRecord.model_validate_json(path.read_text(encoding="utf-8")))  # 读取并解析 document 元数据。

        for record in records:  # 把 document 记录转换成对外的摘要结构。
            if not self._can_read_document(record, auth_context):  # 权限范围外的文档不进入列表结果。
                continue
            latest_ingest_status = (
                latest_ingest_statuses.get(record.latest_job_id)
                if self.metadata_store is not None
                else self._get_latest_ingest_status(record.latest_job_id)
            )  # PostgreSQL 模式统一走批量结果，避免列表查询退回到逐条 job 读取。
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

        if not items:  # 如果还没有新的 document 元数据记录，就回退到旧的 uploads 目录扫描逻辑。
            self.settings.upload_dir.mkdir(parents=True, exist_ok=True)  # 确保 uploads 目录存在。
            for path in sorted(self.settings.upload_dir.iterdir()):  # 遍历 uploads 目录下的所有条目。
                if not path.is_file() or path.name.startswith("."):  # 跳过目录和隐藏文件。
                    continue

                document_id, filename = self._decode_storage_name(path.name)  # 从磁盘文件名中反解出文档 ID 和原始文件名。
                items.append(  # 把当前文件转换成摘要结构并加入列表。
                    DocumentSummary(  # 创建单个文档摘要对象。
                        document_id=document_id,  # 填充文档唯一 ID。
                        filename=filename,  # 填充原始文件名。
                        size_bytes=path.stat().st_size,  # 填充文件大小。
                        parse_supported=path.suffix.lower() in SUPPORTED_PARSE_SUFFIXES,  # 判断该文件类型是否可解析。
                        storage_path=str(path),  # 填充落盘路径。
                        status="uploaded",  # uploads 回退场景没有 metadata，统一标记为 uploaded。
                        ingest_status=None,  # uploads 回退场景无 job 记录。
                        latest_job_id=None,  # uploads 回退场景无 latest_job_id。
                        department_id=None,  # uploads 回退场景无部门字段。
                        category_id=None,  # uploads 回退场景无分类字段。
                        uploaded_by=None,  # uploads 回退场景无上传人字段。
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),  # 填充最后修改时间。
                    )
                )

        items.sort(key=lambda item: item.updated_at, reverse=True)  # 统一按更新时间倒序，保证分页稳定。
        filtered_items = [  # 应用筛选条件，过滤出最终候选集。
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
        total = len(filtered_items)  # 统计筛选后总量，供前端分页器使用。
        start = (safe_page - 1) * safe_page_size  # 计算当前页起始下标。
        end = start + safe_page_size  # 计算当前页结束下标。
        paged_items = filtered_items[start:end]  # 切出当前页数据。

        return DocumentListResponse(total=total, page=safe_page, page_size=safe_page_size, items=paged_items)  # 返回最终分页结果。

    @staticmethod
    def _matches_document_filters(  # 判断单条文档是否命中筛选条件。
        item: DocumentSummary,
        *,
        keyword: str | None,
        department_id: str | None,
        category_id: str | None,
        document_status: DocumentLifecycleStatus | None,
    ) -> bool:
        if keyword is not None:  # 关键字支持按文档名和文档 ID 模糊匹配。
            lowered_keyword = keyword.lower()
            if lowered_keyword not in item.filename.lower() and lowered_keyword not in item.document_id.lower():
                return False
        if department_id is not None and item.department_id != department_id:  # 主部门精确匹配。
            return False
        if category_id is not None and item.category_id != category_id:  # 分类精确匹配。
            return False
        if document_status is not None and item.status != document_status:  # 文档状态精确匹配。
            return False
        return True

    def is_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> bool:  # 给检索/问答复用的轻量读权限判断。
        try:
            record = self._load_document_record(doc_id)
        except HTTPException:
            return False
        return self._can_read_document(record, auth_context)

    def ensure_document_readable(self, doc_id: str, auth_context: AuthContext | None) -> None:  # 按 doc_id 统一抛出读权限错误。
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
        record_departments = self._normalize_department_scope(record.department_ids, record.department_id)
        if not record_departments:  # 兼容旧数据：没有部门字段时默认当前租户内可读。
            return True
        return bool(set(record_departments) & set(auth_context.accessible_department_ids))

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

    async def _read_upload_content(self, upload: UploadFile) -> tuple[str, str, bytes]:  # 统一读取并校验上传文件内容。
        filename = upload.filename or "document"  # 优先使用客户端传来的文件名，没有则回退到 document。
        suffix = Path(filename).suffix.lower()  # 提取并标准化文件扩展名。

        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:  # 如果扩展名不在支持范围内，直接拒绝。
            supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))  # 拼出可读的支持格式列表。
            raise HTTPException(  # 抛出 400 错误，表示请求参数不合法。
                status_code=status.HTTP_400_BAD_REQUEST,  # 使用 400 Bad Request。
                detail=f"Unsupported file type: {suffix or 'unknown'}. Supported types: {supported}",  # 返回明确的错误说明。
            )

        content_buffer = bytearray()  # 分块读取上传内容，避免一次性 read() 把超大文件全部搬进内存。
        while True:  # 循环读取直到文件结束或超限。
            chunk = await upload.read(UPLOAD_READ_CHUNK_SIZE_BYTES)  # 每次读取固定大小，便于提前触发超限判断。
            if not chunk:  # 没有更多内容时结束读取。
                break
            content_buffer.extend(chunk)  # 累积已读取内容。
            if len(content_buffer) > self.settings.upload_max_file_size_bytes:  # 一旦超过上限立即失败，避免继续读完大文件。
                max_size_mb = self.settings.upload_max_file_size_bytes // (1024 * 1024)  # 用 MB 展示上限，便于前端和调用方理解。
                raise HTTPException(  # 抛出 413，明确表示请求实体过大。
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"File too large: {len(content_buffer)} bytes. "
                        f"Maximum allowed size is {self.settings.upload_max_file_size_bytes} bytes ({max_size_mb}MB)."
                    ),
                )

        content = bytes(content_buffer)  # 读取完成后转换成 bytes，兼容后续落盘和哈希流程。
        if len(content) > self.settings.upload_max_file_size_bytes:  # 保留最终兜底校验，防止极端场景漏判。
            max_size_mb = self.settings.upload_max_file_size_bytes // (1024 * 1024)  # 用 MB 展示上限，便于前端和调用方理解。
            raise HTTPException(  # 抛出 413，明确表示请求实体过大。
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File too large: {len(content)} bytes. "
                    f"Maximum allowed size is {self.settings.upload_max_file_size_bytes} bytes ({max_size_mb}MB)."
                ),
            )
        if not content:  # 如果文件内容为空，拒绝继续入库。
            raise HTTPException(  # 抛出 400 错误。
                status_code=status.HTTP_400_BAD_REQUEST,  # 使用 400 Bad Request。
                detail="Uploaded file is empty.",  # 返回明确的错误信息。
            )

        return filename, suffix, content  # 返回校验通过后的文件名、扩展名和文件内容。

    @staticmethod
    def _generate_entity_id(prefix: str) -> str:  # 生成类似 doc_xxx / job_xxx 的业务 ID。
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")  # 先拼一个 UTC 时间戳，便于排查和排序。
        return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"  # 拼上短 UUID，避免高并发下冲突。

    def _document_record_path(self, doc_id: str) -> Path:  # 计算单个 document 元数据文件路径。
        return self.settings.document_dir / f"{doc_id}.json"  # documents 目录下按 doc_id 命名。

    def _job_record_path(self, job_id: str) -> Path:  # 计算单个 ingest job 元数据文件路径。
        return self.settings.job_dir / f"{job_id}.json"  # jobs 目录下按 job_id 命名。

    @staticmethod
    def _write_json(path: Path, model: DocumentRecord | IngestJobRecord) -> None:  # 把 Pydantic 模型稳定写成 JSON 文件。
        path.parent.mkdir(parents=True, exist_ok=True)  # 先确保目标目录存在。
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")  # 直接落盘，方便后续调试和状态查询。

    def _save_document_record(self, record: DocumentRecord) -> None:  # 持久化 document 记录。
        if self.metadata_store is not None:  # 启用 PostgreSQL 元数据模式时优先写库。
            self.metadata_store.save_document(record)  # 写入 rag_source_documents。
            return
        self._write_json(self._document_record_path(record.doc_id), record)  # 回退写入本地 document 元数据文件。

    def _save_job_record(self, record: IngestJobRecord) -> None:  # 持久化 job 记录。
        if self.metadata_store is not None:  # 启用 PostgreSQL 元数据模式时优先写库。
            self.metadata_store.save_job(record)  # 写入 rag_ingest_jobs。
            return
        self._write_json(self._job_record_path(record.job_id), record)  # 回退写入本地 job 元数据文件。

    def _update_job_record(  # 统一更新并落盘任务状态。
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
        record.status = status  # 更新任务状态。
        record.stage = stage  # 更新阶段名。
        record.progress = max(0, min(100, progress))  # 约束进度范围在 0~100。
        record.error_code = error_code  # 更新错误码。
        record.error_message = error_message  # 更新错误信息。
        if increase_retry:  # 如果是失败重试路径，就累加重试计数。
            record.retry_count += 1
        record.updated_at = datetime.now(timezone.utc)  # 刷新更新时间。
        self._save_job_record(record)  # 落盘当前任务记录。

    def _to_ingest_job_status_response(self, record: IngestJobRecord) -> IngestJobStatusResponse:  # 把 job 记录映射成接口响应模型。
        auto_retry_eligible = record.status == "failed" and record.retry_count < self.settings.ingest_failure_retry_limit  # failed 且未到上限时可自动重试。
        manual_retry_allowed = record.status not in PROCESSING_JOB_STATUSES and record.status != "completed"  # 非处理中且非 completed 状态允许手动重投递。
        return IngestJobStatusResponse(  # 返回标准化 job 状态结构。
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

    def _load_document_record(self, doc_id: str) -> DocumentRecord:  # 读取 document 元数据，不存在则抛 404。
        if self.metadata_store is not None:  # PostgreSQL 模式优先从数据库读取。
            record = self.metadata_store.load_document(doc_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")
            return record
        path = self._document_record_path(doc_id)  # 先拿到目标 JSON 文件路径。
        if not path.exists():  # 如果文件不存在，说明文档 ID 无效。
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")  # 返回 404。
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析 document JSON。

    def _load_job_record(self, job_id: str) -> IngestJobRecord:  # 读取 ingest job 元数据，不存在则抛 404。
        if self.metadata_store is not None:  # PostgreSQL 模式优先从数据库读取。
            record = self.metadata_store.load_job(job_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingest job not found: {job_id}")
            return record
        path = self._job_record_path(job_id)  # 先拿到目标 JSON 文件路径。
        if not path.exists():  # 如果文件不存在，说明 job ID 无效。
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingest job not found: {job_id}")  # 返回 404。
        return IngestJobRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析 job JSON。

    def _load_latest_job_record(self, latest_job_id: str | None) -> IngestJobRecord | None:  # 安全读取 latest job，缺失时返回 None。
        if not latest_job_id:
            return None
        try:
            return self._load_job_record(latest_job_id)
        except HTTPException:
            return None

    def _is_job_stale(self, job_record: IngestJobRecord) -> bool:  # 超过配置阈值仍未刷新状态的 in-flight job 视为卡死。
        updated_at = job_record.updated_at
        if updated_at.tzinfo is None:  # 兼容旧 JSON 里没有显式时区的时间戳。
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        stale_after = timedelta(seconds=self.settings.ingest_inflight_stale_seconds)
        return datetime.now(timezone.utc) - updated_at > stale_after

    def _should_reuse_inflight_job(self, job_record: IngestJobRecord | None) -> bool:  # 只有新鲜的 in-flight job 才值得复用。
        if job_record is None:
            return False
        if job_record.status not in IN_FLIGHT_JOB_STATUSES:
            return False
        return not self._is_job_stale(job_record)

    def _find_document_record_by_file_hash(self, file_hash: str, *, tenant_id: str | None = None) -> DocumentRecord | None:  # 按文件内容哈希查找已存在文档，避免重复入库。
        if self.metadata_store is not None:  # PostgreSQL 模式优先从数据库查重。
            return self.metadata_store.find_document_by_file_hash(file_hash, tenant_id=tenant_id)
        self.settings.document_dir.mkdir(parents=True, exist_ok=True)  # 确保 document 元数据目录存在。
        for path in sorted(self.settings.document_dir.glob("*.json")):  # 遍历所有 document 元数据记录。
            if not path.is_file() or path.name.startswith("."):  # 跳过目录和隐藏文件。
                continue
            record = DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析单条 document 记录。
            if tenant_id is not None and record.tenant_id != tenant_id:  # 指定租户时只在当前租户范围内去重。
                continue
            if record.file_hash == file_hash:  # 命中相同内容时直接返回已有记录。
                return record
        return None  # 没找到则返回 None，允许继续创建新文档。

    def _create_followup_ingest_job(self, document_record: DocumentRecord) -> IngestJobRecord:  # 为已有文档补发一个新的 ingest job。
        now = datetime.now(timezone.utc)  # 统一记录这次补发任务的时间戳。
        followup_job = IngestJobRecord(  # 复用原文档，创建一个新的 job 记录。
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
        document_record.status = "queued"  # 补发任务时把文档重新标记为等待处理。
        document_record.latest_job_id = followup_job.job_id  # latest_job_id 指向这次新的补发任务。
        document_record.updated_at = now
        self._save_document_record(document_record)  # 先更新文档元数据，避免前端继续拿到旧 job。
        self._save_job_record(followup_job)  # 落盘新的 job 记录。
        self._dispatch_job_or_fail(followup_job, document_record)  # 正式投递到 Celery 队列。
        return followup_job

    def _refresh_duplicate_document_source(  # 用本次重新上传的内容刷新重复文档的源文件和元数据，确保补发任务读取的是最新可解析文件。
        self,
        document_record: DocumentRecord,
        *,
        content: bytes,
        filename: str,
        source_type: str,
        uploaded_by: str | None,
        created_by: str | None,
    ) -> None:
        document_record.file_name = filename  # 重复上传时同步覆盖文件名，避免历史脏扩展名继续污染解析流程。
        document_record.source_type = source_type  # 同步覆盖 source_type，保证预览和解析分支一致。
        if uploaded_by is not None:  # 传入上传人时刷新文档上传人，便于排查最近一次补发来源。
            document_record.uploaded_by = uploaded_by
        if created_by is not None:  # 兼容旧字段 created_by。
            document_record.created_by = created_by

        target_name = f"{document_record.doc_id}__{_sanitize_filename(document_record.file_name)}"  # 重复文档继续沿用 doc_id 作为磁盘文件名前缀，避免打散既有元数据关系。
        document_record.storage_path = self.asset_store.save_upload(
            doc_id=document_record.doc_id,
            target_name=target_name,
            file_name=document_record.file_name,
            content=content,
            job_id=document_record.latest_job_id,
        )  # 后续 worker 统一通过资产存储读取最新源文件。
        document_record.updated_at = datetime.now(timezone.utc)  # 刷新更新时间，反映这次源文件修复。

    def _dispatch_job_or_fail(self, job_record: IngestJobRecord, document_record: DocumentRecord) -> None:  # 统一处理 Celery 投递失败路径。
        try:  # 尝试把当前任务投递给 Celery worker。
            dispatch_ingest_job(job_record.job_id, self.settings)  # 用当前服务配置把任务发到 broker。
        except Exception as exc:  # broker 不可用或 Celery 配置异常时，统一标记失败并返回 502。
            next_retry_count = job_record.retry_count + 1  # 预估本次失败后会落到的重试次数。
            moved_to_dead_letter = next_retry_count >= self.settings.ingest_failure_retry_limit  # 判断是否触发死信阈值。
            error_code = _dead_letter_error_code(INGEST_ERROR_CODE_DISPATCH) if moved_to_dead_letter else INGEST_ERROR_CODE_DISPATCH  # 统一错误码语义。
            error_message = str(exc)  # 先保留原始异常文本。
            if moved_to_dead_letter:  # 进入死信时追加语义说明，便于排查。
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
            document_record.status = "failed"  # 调度失败说明任务没有真正入队，文档状态也标为 failed。
            document_record.updated_at = datetime.now(timezone.utc)  # 刷新文档更新时间。
            self._save_document_record(document_record)  # 落盘失败状态。
            raise HTTPException(  # 向接口返回 502，避免“显示 queued 但实际上没入队”的假成功。
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to enqueue ingest job: {exc}",
            ) from exc

    def _mark_ingest_failure(  # 统一处理 ingest 执行阶段失败后的状态流转。
        self,
        *,
        job_record: IngestJobRecord,
        document_record: DocumentRecord,
        error_code: IngestBaseErrorCode,
        error_message: str,
    ) -> IngestJobStatusResponse:
        next_retry_count = job_record.retry_count + 1  # 预估本次失败后的重试次数。
        moved_to_dead_letter = next_retry_count >= self.settings.ingest_failure_retry_limit  # 判断是否触发死信阈值。
        final_error_code = _dead_letter_error_code(error_code) if moved_to_dead_letter else error_code  # 统一死信错误码命名。
        final_error_message = error_message  # 默认保留原始异常文本。
        if moved_to_dead_letter:  # 进入死信时补充重试信息，方便接口直接定位问题。
            final_error_message = (
                f"{error_message} (retry_count={next_retry_count}/{self.settings.ingest_failure_retry_limit}; moved to dead_letter)"
            )

        self._update_job_record(  # 先更新任务状态。
            job_record,
            status="dead_letter" if moved_to_dead_letter else "failed",
            stage="dead_letter" if moved_to_dead_letter else "failed",
            progress=100,
            error_code=final_error_code,
            error_message=final_error_message,
            increase_retry=True,
        )
        document_record.status = "failed"  # 文档状态统一标记失败，避免错误文档进入 active。
        document_record.updated_at = datetime.now(timezone.utc)  # 刷新文档更新时间。
        self._save_document_record(document_record)  # 落盘文档状态。
        return self._to_ingest_job_status_response(job_record)  # 返回最新任务状态。

    @staticmethod  # 这个方法不依赖实例状态，所以声明成静态方法。
    def _decode_storage_name(storage_name: str) -> tuple[str, str]:  # 从磁盘文件名里解析文档 ID 和原始文件名。
        if "__" not in storage_name:  # 如果文件名不符合约定格式。
            return "unknown", storage_name  # 返回兜底值，避免列表接口报错。
        return tuple(storage_name.split("__", 1))  # type: ignore[return-value]  # 按第一个双下划线拆分出文档 ID 和原始文件名。

    @staticmethod
    def _normalize_source_suffix(source_type: str) -> str:  # 统一把 source_type 转成带点前缀的小写扩展名。
        normalized = source_type.strip().lower().lstrip(".")
        return f".{normalized}" if normalized else ""

    def _load_text_preview_content(
        self,
        record: DocumentRecord,
        *,
        suffix: str,
        max_chars: int,
    ) -> tuple[str, bool]:  # 统一加载文本预览内容，普通文本走原文件，DOCX 走解析文本。
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
    def _read_text_preview_bytes(content: bytes, *, max_chars: int) -> tuple[str, bool]:  # 从字节内容生成文本预览并按最大长度截断。
        raw_text = content.decode("utf-8", errors="ignore")  # 用 ignore 兼容脏字符，避免单文件编码问题打断页面。
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
    def _extract_batch_error_detail(detail: object) -> tuple[str | None, str]:  # 把单文件 HTTP 错误细节规整成批量响应可用格式。
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
def get_document_service() -> DocumentService:  # 提供 FastAPI 依赖注入入口。
    return DocumentService()  # 返回一个文档服务实例。
