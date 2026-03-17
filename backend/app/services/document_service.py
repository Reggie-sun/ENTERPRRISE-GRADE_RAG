import re  # 导入正则库，用来清洗上传文件名。
from datetime import datetime, timezone  # 导入时间工具，用来生成 UTC 时间戳。
from pathlib import Path  # 导入 Path，方便处理文件路径。
from uuid import uuid4  # 导入 uuid4，用来生成文档唯一标识。

from fastapi import HTTPException, UploadFile, status  # 导入 FastAPI 异常、上传文件对象和状态码。

from ..core.config import Settings, get_settings  # 导入配置对象和配置获取函数。
from ..schemas.document import DocumentListResponse, DocumentSummary, DocumentUploadResponse  # 导入文档相关响应模型。
from .ingestion_service import DocumentIngestionService  # 导入文档入库服务。

SUPPORTED_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}  # 当前系统支持解析的文件扩展名集合。
SUPPORTED_UPLOAD_SUFFIXES = SUPPORTED_PARSE_SUFFIXES  # 当前允许上传的扩展名与可解析扩展名保持一致。


def _sanitize_filename(filename: str) -> str:  # 清洗上传文件名，避免非法字符进入磁盘路径。
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")  # 把不安全字符替换成下划线，再去掉首尾的点和下划线。
    return cleaned or "document"  # 如果清洗后变空，就回退到 document。


class DocumentService:  # 封装文档上传、列表和入库的业务逻辑。
    def __init__(self, settings: Settings | None = None) -> None:  # 初始化文档服务。
        self.settings = settings or get_settings()  # 优先使用传入配置，否则读取全局配置。
        self.ingestion_service = DocumentIngestionService(self.settings)  # 创建入库服务实例。

    async def save_upload(self, upload: UploadFile) -> DocumentUploadResponse:  # 保存上传文件并执行完整入库。
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

    def list_documents(self) -> DocumentListResponse:  # 列出当前已经上传过的文档。
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)  # 确保 uploads 目录存在。
        items: list[DocumentSummary] = []  # 初始化文档摘要列表。

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

    @staticmethod  # 这个方法不依赖实例状态，所以声明成静态方法。
    def _decode_storage_name(storage_name: str) -> tuple[str, str]:  # 从磁盘文件名里解析文档 ID 和原始文件名。
        if "__" not in storage_name:  # 如果文件名不符合约定格式。
            return "unknown", storage_name  # 返回兜底值，避免列表接口报错。
        return tuple(storage_name.split("__", 1))  # type: ignore[return-value]  # 按第一个双下划线拆分出文档 ID 和原始文件名。


def get_document_service() -> DocumentService:  # 提供 FastAPI 依赖注入入口。
    return DocumentService()  # 返回一个文档服务实例。
