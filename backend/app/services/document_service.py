import hashlib  # 导入 hashlib，用来计算文件哈希。
import re  # 导入正则库，用来清洗上传文件名。
from datetime import datetime, timezone  # 导入时间工具，用来生成 UTC 时间戳。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from uuid import uuid4  # 导入 uuid4，用来生成文档唯一标识。

from fastapi import HTTPException, UploadFile, status  # 导入 FastAPI 异常、上传文件对象和状态码。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
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

SUPPORTED_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}  # 当前系统支持解析的文件扩展名集合。
SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 当前允许上传的扩展名与可解析扩展名保持一致。


def _sanitize_filename(filename: str) -> str:  # 清洗上传文件名，避免非法字符进入磁盘路径。
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")  # 把不安全字符替换成下划线，再去掉首尾的点和下划线。
    return cleaned or "document"  # 如果清洗后变空，就回退到 document。


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
            file_hash=hashlib.sha256(content).hexdigest(),
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

        self._write_json(self._document_record_path(doc_id), document_record)  # 把 document 元数据落到 documents 目录。
        self._write_json(self._job_record_path(job_id), ingest_job)  # 把 job 元数据落到 jobs 目录。

        return DocumentCreateResponse(doc_id=doc_id, job_id=job_id, status="queued")  # 返回接口需要的最小响应。

    def run_ingest_job(self, job_id: str) -> IngestJobStatusResponse:  # 执行指定 ingest job，并更新文档与任务状态。
        job_record = self._load_job_record(job_id)  # 读取当前任务记录。
        document_record = self._load_document_record(job_record.doc_id)  # 读取关联文档记录。

        if job_record.status == "completed":  # 已完成任务直接返回当前状态，避免重复执行。
            return self._to_ingest_job_status_response(job_record)
        if job_record.status in {"parsing", "chunking", "embedding", "indexing"}:  # 如果任务已经在处理中，直接返回当前状态。
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
            self._update_job_record(  # 把任务标记为失败。
                job_record,
                status="failed",
                stage="failed",
                progress=100,
                error_code="INGEST_VALIDATION_ERROR",
                error_message=str(exc),
                increase_retry=True,
            )
            document_record.status = "failed"  # 文档状态同步标记失败。
            document_record.updated_at = datetime.now(timezone.utc)  # 更新时间戳。
            self._save_document_record(document_record)  # 落盘文档状态。
            return self._to_ingest_job_status_response(job_record)  # 返回失败状态。
        except RuntimeError as exc:  # 捕获依赖错误，例如 embedding/Qdrant 异常。
            self._update_job_record(  # 把任务标记为失败。
                job_record,
                status="failed",
                stage="failed",
                progress=100,
                error_code="INGEST_RUNTIME_ERROR",
                error_message=str(exc),
                increase_retry=True,
            )
            document_record.status = "failed"  # 文档状态同步标记失败。
            document_record.updated_at = datetime.now(timezone.utc)  # 更新时间戳。
            self._save_document_record(document_record)  # 落盘文档状态。
            return self._to_ingest_job_status_response(job_record)  # 返回失败状态。

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
        self.settings.document_dir.mkdir(parents=True, exist_ok=True)  # 确保 documents 元数据目录存在。
        items: list[DocumentSummary] = []  # 初始化文档摘要列表。

        for path in sorted(self.settings.document_dir.glob("*.json")):  # 遍历所有 document 元数据文件。
            if not path.is_file() or path.name.startswith("."):  # 跳过目录和隐藏文件。
                continue

            record = DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析 document 元数据。
            items.append(  # 把当前文件转换成摘要结构并加入列表。
                DocumentSummary(  # 创建单个文档摘要对象。
                    document_id=record.doc_id,  # 填充文档唯一 ID。
                    filename=record.file_name,  # 填充原始文件名。
                    size_bytes=Path(record.storage_path).stat().st_size if Path(record.storage_path).exists() else 0,  # 尝试从原始文件路径读取文件大小。
                    parse_supported=f".{record.source_type.lower()}" in SUPPORTED_PARSE_SUFFIXES,  # 判断该文件类型是否可解析。
                    storage_path=record.storage_path,  # 返回原始文件落盘路径。
                    updated_at=record.updated_at,  # 返回 document 记录里的更新时间。
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

        content = await upload.read()  # 读取上传文件的全部二进制内容。
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
        self._write_json(self._document_record_path(record.doc_id), record)  # 写入 document 元数据文件。

    def _save_job_record(self, record: IngestJobRecord) -> None:  # 持久化 job 记录。
        self._write_json(self._job_record_path(record.job_id), record)  # 写入 job 元数据文件。

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

    @staticmethod
    def _to_ingest_job_status_response(record: IngestJobRecord) -> IngestJobStatusResponse:  # 把 job 记录映射成接口响应模型。
        return IngestJobStatusResponse(  # 返回标准化 job 状态结构。
            job_id=record.job_id,
            doc_id=record.doc_id,
            status=record.status,
            progress=record.progress,
            stage=record.stage,
            retry_count=record.retry_count,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _load_document_record(self, doc_id: str) -> DocumentRecord:  # 读取 document 元数据，不存在则抛 404。
        path = self._document_record_path(doc_id)  # 先拿到目标 JSON 文件路径。
        if not path.exists():  # 如果文件不存在，说明文档 ID 无效。
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document not found: {doc_id}")  # 返回 404。
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析 document JSON。

    def _load_job_record(self, job_id: str) -> IngestJobRecord:  # 读取 ingest job 元数据，不存在则抛 404。
        path = self._job_record_path(job_id)  # 先拿到目标 JSON 文件路径。
        if not path.exists():  # 如果文件不存在，说明 job ID 无效。
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingest job not found: {job_id}")  # 返回 404。
        return IngestJobRecord.model_validate_json(path.read_text(encoding="utf-8"))  # 读取并解析 job JSON。

    @staticmethod  # 这个方法不依赖实例状态，所以声明成静态方法。
    def _decode_storage_name(storage_name: str) -> tuple[str, str]:  # 从磁盘文件名里解析文档 ID 和原始文件名。
        if "__" not in storage_name:  # 如果文件名不符合约定格式。
            return "unknown", storage_name  # 返回兜底值，避免列表接口报错。
        return tuple(storage_name.split("__", 1))  # type: ignore[return-value]  # 按第一个双下划线拆分出文档 ID 和原始文件名。


def get_document_service() -> DocumentService:  # 提供 FastAPI 依赖注入入口。
    return DocumentService()  # 返回一个文档服务实例。
