from fastapi import APIRouter, Depends, File, UploadFile, status  # 导入上传接口需要的 FastAPI 组件。

from ....schemas.document import DocumentListResponse, DocumentUploadResponse  # 导入文档相关响应模型。
from ....services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖工厂函数。

router = APIRouter(prefix="/documents", tags=["documents"])  # 创建 documents 路由分组，并统一加上 /documents 前缀。


@router.post(
    "/upload",  # 定义上传接口路径。
    response_model=DocumentUploadResponse,  # 指定成功时返回的响应结构。
    status_code=status.HTTP_201_CREATED,  # 指定成功时返回 201 Created。
    summary="Upload and ingest a document",  # 给 Swagger 页面展示简要标题。
    description="Uploads a PDF/Markdown/TXT document and runs parse, chunk, embedding, and Qdrant upsert synchronously.",  # 给 Swagger 页面展示详细说明。
)
async def upload_document(  # 定义文档上传接口函数。
    file: UploadFile = File(..., description="Supported file types: .pdf, .md, .markdown, .txt"),  # 接收上传文件，并在 Swagger 中注明支持格式。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentUploadResponse:
    return await document_service.save_upload(file)  # 调用服务层保存文件并执行完整入库流程。


@router.get("", response_model=DocumentListResponse)  # 声明 GET /documents 接口，并指定返回模型。
def list_documents(  # 定义文档列表接口函数。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentListResponse:
    return document_service.list_documents()  # 返回当前 uploads 目录中的文档列表。
