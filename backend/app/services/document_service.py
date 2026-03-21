import hashlib  # 导入 hashlib，用来计算文件哈希。
import re  # 导入正则库，用来清洗上传文件名。
from datetime import datetime, timezone  # 导入时间工具，用来生成 UTC 时间戳。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from typing import Literal  # 导入 Literal，用于约束 ingest 错误码基类。
from uuid import uuid4  # 导入 uuid4，用来生成文档唯一标识。

from fastapi import HTTPException, UploadFile, status  # 导入 FastAPI 异常、上传文件对象和状态码。

from ..core.config import Settings, get_postgres_metadata_dsn, get_settings  # 导入配置对象和配置获取函数。
from ..db.postgres_metadata_store import PostgresMetadataStore  # 导入 PostgreSQL 元数据存储实现。
from ..schemas.document import (  # 导入文档相关响应模型和持久化结构。
    Classification,
    DocumentCreateResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentRecord,
    DocumentSummary,
    DocumentUploadResponse,
    IngestJobRecord,
    IngestJobStatusResponse,
    Visibility,
)
from .ingestion_service import DocumentIngestionService  # 导入文档入库服务。
from ..worker.celery_app import dispatch_ingest_job  # 导入 Celery 投递函数，用于异步触发 ingest job。

SUPPORTED_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}  # 当前系统支持解析的文件扩展名集合。
SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 当前允许上传的扩展名与可解析扩展名保持一致。
PROCESSING_JOB_STATUSES = {"parsing", "ocr_processing", "chunking", "embedding", "indexing"}  # ingest job 处理中状态集合。
TERMINAL_JOB_STATUSES = {"completed", "dead_letter"}  # ingest job 终态集合。
IngestBaseErrorCode = Literal["INGEST_DISPATCH_ERROR", "INGEST_VALIDATION_ERROR", "INGEST_RUNTIME_ERROR"]  # ingest 基础错误码集合。
UPLOAD_READ_CHUNK_SIZE_BYTES = 1 * 1024 * 1024  # 上传文件分块读取大小，避免一次 read() 拉满内存。
INGEST_ERROR_CODE_DISPATCH: IngestBaseErrorCode = "INGEST_DISPATCH_ERROR"  # 调度失败基础错误码。
INGEST_ERROR_CODE_VALIDATION: IngestBaseErrorCode = "INGEST_VALIDATION_ERROR"  # 业务校验失败基础错误码。
INGEST_ERROR_CODE_RUNTIME: IngestBaseErrorCode = "INGEST_RUNTIME_ERROR"  # 运行期依赖失败基础错误码。
DEAD_LETTER_ERROR_SUFFIX = "_DEAD_LETTER"  # dead_letter 错误码后缀。


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
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化文档服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.ingestion_service = DocumentIngestionService(self.settings)  # 创建入库服务实例。
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
        department_ids: list[str] | None = None,
        role_ids: list[str] | None = None,
        owner_id: str | None = None,
        visibility: Visibility = "private",
        classification: Classification = "internal",
        tags: list[str] | None = None,
        source_system: str | None = None,
        created_by: str | None = None,
    ) -> DocumentCreateResponse:
        filename, suffix, content = await self._read_upload_content(upload)  # 先统一校验并读取上传文件内容。
        normalized_tenant_id = _normalize_optional_str(tenant_id)  # 对租户 ID 做空白归一化。
        if normalized_tenant_id is None:  # tenant_id 是必填字段，清洗后为空也应拒绝。
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must not be blank.")
        normalized_department_ids = _normalize_optional_list(department_ids)  # 清洗部门列表，去掉空字符串。
        normalized_role_ids = _normalize_optional_list(role_ids)  # 清洗角色列表，去掉空字符串。
        normalized_tags = _normalize_optional_list(tags)  # 清洗标签列表，去掉空字符串。
        normalized_owner_id = _normalize_optional_str(owner_id)  # 清洗 owner_id。
        normalized_source_system = _normalize_optional_str(source_system)  # 清洗 source_system。
        normalized_created_by = _normalize_optional_str(created_by)  # 清洗 created_by。
        file_hash = hashlib.sha256(content).hexdigest()  # 对上传内容计算稳定哈希，用于内容级去重。
        duplicate_record = self._find_document_record_by_file_hash(file_hash, tenant_id=normalized_tenant_id)  # 同租户下命中相同内容时直接复用已有文档。
        if duplicate_record is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DOCUMENT_ALREADY_EXISTS",
                    "doc_id": duplicate_record.doc_id,
                    "latest_job_id": duplicate_record.latest_job_id,
                    "file_name": duplicate_record.file_name,
                    "file_hash": duplicate_record.file_hash,
                },
            )
        now = datetime.now(timezone.utc)  # 记录本次创建的统一时间戳。
        doc_id = self._generate_entity_id("doc")  # 生成文档 ID。
        job_id = self._generate_entity_id("job")  # 生成任务 ID。
        target_name = f"{doc_id}__{_sanitize_filename(filename)}"  # 生成安全的磁盘文件名。
        target_path = self.settings.upload_dir / target_name  # 计算原始文件落盘路径。
        target_path.parent.mkdir(parents=True, exist_ok=True)  # 确保上传目录存在。
        target_path.write_bytes(content)  # 把原始文件内容写到 uploads 目录。

        document_record = DocumentRecord(  # 组装 document 元数据记录。
            doc_id=doc_id,
            tenant_id=normalized_tenant_id,
            file_name=filename,
            file_hash=file_hash,
            source_type=suffix.lstrip(".") or "unknown",
            department_ids=normalized_department_ids,
            role_ids=normalized_role_ids,
            owner_id=normalized_owner_id,
            visibility=visibility,
            classification=classification,
            tags=normalized_tags,
            source_system=normalized_source_system,
            status="queued",
            current_version=1,
            latest_job_id=job_id,
            storage_path=str(target_path),
            created_by=normalized_created_by,
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

        return DocumentCreateResponse(doc_id=doc_id, job_id=job_id, status="queued")  # 返回接口需要的最小响应。

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
            self.ingestion_service.ingest_document(  # 调用入库服务执行解析、切块、向量化和写库。
                document_id=document_record.doc_id,  # 传入文档 ID。
                filename=document_record.file_name,  # 传入原始文件名。
                source_path=Path(document_record.storage_path),  # 传入原始文件路径。
                on_stage=on_stage,  # 传入阶段回调，用于进度更新。
            )
        except ValueError as exc:  # 捕获业务可预期错误，例如切块失败。
            return self._mark_ingest_failure(  # 按失败重试上限统一处理失败/死信状态。
                job_record=job_record,
                document_record=document_record,
                error_code=INGEST_ERROR_CODE_VALIDATION,
                error_message=str(exc),
            )
        except RuntimeError as exc:  # 捕获依赖错误，例如 embedding/Qdrant 异常。
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
        target_path = self.settings.upload_dir / target_name  # 计算最终落盘路径。
        target_path.parent.mkdir(parents=True, exist_ok=True)  # 确保上传目录存在。
        target_path.write_bytes(content)  # 把原始文件内容写到磁盘。

        try:  # 尝试执行完整的文档入库流程。
            ingestion_result = self.ingestion_service.ingest_document(  # 调用入库服务执行解析、切分、向量化和写库。
                document_id=document_id,  # 传入文档唯一 ID。
                filename=filename,  # 传入原始文件名。
                source_path=target_path,  # 传入刚刚落盘的原始文件路径。
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
            storage_path=str(target_path),  # 返回原始文件路径。
            parsed_path=ingestion_result.parsed_path,  # 返回解析文本路径。
            chunk_path=ingestion_result.chunk_path,  # 返回 chunk 文件路径。
            collection_name=ingestion_result.collection_name,  # 返回写入的 Qdrant collection。
            parser_name=ingestion_result.parser_name,  # 返回本次使用的解析器名称。
            chunk_count=ingestion_result.chunk_count,  # 返回生成的 chunk 数量。
            vector_count=ingestion_result.vector_count,  # 返回写入的向量数量。
            created_at=datetime.now(timezone.utc),  # 返回当前 UTC 时间。
        )

    def get_document(self, doc_id: str) -> DocumentDetailResponse:  # 按 doc_id 读取文档元信息。
        record = self._load_document_record(doc_id)  # 从本地元数据目录读取 document 记录。
        return DocumentDetailResponse(  # 把完整记录映射成对外的详情响应。
            doc_id=record.doc_id,
            file_name=record.file_name,
            status=record.status,
            current_version=record.current_version,
            latest_job_id=record.latest_job_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def get_ingest_job(self, job_id: str) -> IngestJobStatusResponse:  # 按 job_id 读取 ingest job 状态。
        record = self._load_job_record(job_id)  # 从本地元数据目录读取 job 记录。
        return self._to_ingest_job_status_response(record)  # 返回接口需要的任务状态字段。

    def list_documents(self) -> DocumentListResponse:  # 列出当前已经上传过的文档。
        items: list[DocumentSummary] = []  # 初始化文档摘要列表。
        if self.metadata_store is not None:  # PostgreSQL 模式优先从数据库读取文档列表。
            records = self.metadata_store.list_documents()  # 读取数据库中的 document 记录。
        else:  # 未启用 PostgreSQL 时，继续沿用本地 JSON 元数据目录。
            self.settings.document_dir.mkdir(parents=True, exist_ok=True)  # 确保 documents 元数据目录存在。
            records = []  # 先初始化空列表，再从 JSON 文件反序列化。
            for path in sorted(self.settings.document_dir.glob("*.json")):  # 遍历所有 document 元数据文件。
                if not path.is_file() or path.name.startswith("."):  # 跳过目录和隐藏文件。
                    continue
                records.append(DocumentRecord.model_validate_json(path.read_text(encoding="utf-8")))  # 读取并解析 document 元数据。

        for record in records:  # 把 document 记录转换成对外的摘要结构。
            items.append(
                DocumentSummary(
                    document_id=record.doc_id,
                    filename=record.file_name,
                    size_bytes=Path(record.storage_path).stat().st_size if Path(record.storage_path).exists() else 0,
                    parse_supported=f".{record.source_type.lower()}" in SUPPORTED_PARSE_SUFFIXES,
                    storage_path=record.storage_path,
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
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),  # 填充最后修改时间。
                    )
                )

        return DocumentListResponse(total=len(items), items=items)  # 返回最终的文档列表响应。

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


def get_document_service() -> DocumentService:  # 提供 FastAPI 依赖注入入口。
    return DocumentService()  # 返回一个文档服务实例。
