from fastapi import APIRouter, Depends, File, Form, UploadFile, status  # 导入上传接口需要的 FastAPI 组件。

from ....schemas.document import (  # 导入文档相关响应模型。
    Classification,
    DocumentCreateResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    Visibility,
)
from ....services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖工厂函数。

router = APIRouter(prefix="/documents", tags=["documents"])  # 创建 documents 路由分组，并统一加上 /documents 前缀。


@router.post(
    "",  # 定义文档创建接口路径。
    response_model=DocumentCreateResponse,  # 指定成功时返回的响应结构。
    status_code=status.HTTP_201_CREATED,  # 指定成功时返回 201 Created。
    summary="Create a document and queue ingestion",  # 给 Swagger 页面展示简要标题。
    description="Uploads a document, persists the document/job metadata, enqueues a Celery ingest job, and returns immediately with queued status.",  # 给 Swagger 页面展示详细说明。
)
async def create_document(  # 定义文档创建接口函数。
    file: UploadFile = File(..., description="Supported file types: .pdf, .md, .markdown, .txt"),  # 接收上传文件。
    tenant_id: str = Form(..., description="Tenant identifier"),  # 接收租户 ID。
    department_ids: list[str] | None = Form(default=None),  # 接收部门范围。
    role_ids: list[str] | None = Form(default=None),  # 接收角色范围。
    owner_id: str | None = Form(default=None),  # 接收 owner。
    visibility: Visibility = Form(default="private"),  # 接收可见性策略。
    classification: Classification = Form(default="internal"),  # 接收文档密级。
    tags: list[str] | None = Form(default=None),  # 接收标签列表。
    source_system: str | None = Form(default=None),  # 接收来源系统。
    created_by: str | None = Form(default=None),  # 接收上传人。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentCreateResponse:
    return await document_service.create_document(  # 调用服务层创建文档和 ingest job。
        upload=file,
        tenant_id=tenant_id,
        department_ids=department_ids,
        role_ids=role_ids,
        owner_id=owner_id,
        visibility=visibility,
        classification=classification,
        tags=tags,
        source_system=source_system,
        created_by=created_by,
    )


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


@router.get("/{doc_id}", response_model=DocumentDetailResponse)  # 声明 GET /documents/{doc_id} 接口，并指定返回模型。
def get_document(  # 定义文档详情接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentDetailResponse:
    return document_service.get_document(doc_id)  # 返回指定文档的元信息。
