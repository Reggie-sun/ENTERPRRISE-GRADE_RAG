from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status  # 导入上传接口需要的 FastAPI 组件。
from fastapi.responses import FileResponse  # 导入文件流响应类型，用于在线预览 PDF。

from ....schemas.document import (  # 导入文档相关响应模型。
    Classification,
    DocumentBatchCreateResponse,
    DocumentLifecycleStatus,
    DocumentCreateResponse,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentPreviewResponse,
    DocumentRebuildResponse,
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
    department_id: str | None = Form(default=None),  # 接收主部门（v0.2 新增字段）。
    department_ids: list[str] | None = Form(default=None),  # 接收部门范围。
    category_id: str | None = Form(default=None),  # 接收二级分类（v0.2 新增字段）。
    role_ids: list[str] | None = Form(default=None),  # 接收角色范围。
    owner_id: str | None = Form(default=None),  # 接收 owner。
    visibility: Visibility = Form(default="private"),  # 接收可见性策略。
    classification: Classification = Form(default="internal"),  # 接收文档密级。
    tags: list[str] | None = Form(default=None),  # 接收标签列表。
    source_system: str | None = Form(default=None),  # 接收来源系统。
    uploaded_by: str | None = Form(default=None),  # 接收上传人（v0.2 新命名）。
    created_by: str | None = Form(default=None),  # 接收上传人。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentCreateResponse:
    return await document_service.create_document(  # 调用服务层创建文档和 ingest job。
        upload=file,
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
    )


@router.post(
    "/batch",  # 定义批量创建接口路径。
    response_model=DocumentBatchCreateResponse,  # 指定批量上传响应结构。
    status_code=status.HTTP_201_CREATED,  # 批量创建接口保持 201 语义。
    summary="Batch create documents and queue ingestion",  # 给 Swagger 页面展示简要标题。
    description="Uploads multiple documents and queues one ingest job per file; returns per-file queued/failed result.",  # 给 Swagger 页面展示详细说明。
)
async def create_documents_batch(  # 定义批量文档创建接口函数。
    files: list[UploadFile] = File(..., description="Supported file types: .pdf, .md, .markdown, .txt"),  # 接收多个上传文件。
    tenant_id: str = Form(..., description="Tenant identifier"),  # 接收租户 ID。
    department_id: str | None = Form(default=None),  # 接收主部门（v0.2 新增字段）。
    department_ids: list[str] | None = Form(default=None),  # 接收部门范围。
    category_id: str | None = Form(default=None),  # 接收二级分类（v0.2 新增字段）。
    role_ids: list[str] | None = Form(default=None),  # 接收角色范围。
    owner_id: str | None = Form(default=None),  # 接收 owner。
    visibility: Visibility = Form(default="private"),  # 接收可见性策略。
    classification: Classification = Form(default="internal"),  # 接收文档密级。
    tags: list[str] | None = Form(default=None),  # 接收标签列表。
    source_system: str | None = Form(default=None),  # 接收来源系统。
    uploaded_by: str | None = Form(default=None),  # 接收上传人（v0.2 新命名）。
    created_by: str | None = Form(default=None),  # 接收上传人。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentBatchCreateResponse:
    return await document_service.create_documents_batch(  # 逐文件复用 create_document 逻辑并汇总结果。
        uploads=files,
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
    page: int = Query(default=1, ge=1),  # 当前页码，从 1 开始。
    page_size: int = Query(default=20, ge=1, le=200),  # 每页大小，限制上限避免一次拉取过大。
    keyword: str | None = Query(default=None),  # 文件名关键字筛选。
    department_id: str | None = Query(default=None),  # 主部门筛选。
    category_id: str | None = Query(default=None),  # 分类筛选。
    document_status: DocumentLifecycleStatus | None = Query(default=None, alias="status"),  # 文档生命周期状态筛选。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentListResponse:
    return document_service.list_documents(
        page=page,
        page_size=page_size,
        keyword=keyword,
        department_id=department_id,
        category_id=category_id,
        document_status=document_status,
    )  # 返回分页+筛选后的文档列表。


@router.get("/{doc_id}", response_model=DocumentDetailResponse)  # 声明 GET /documents/{doc_id} 接口，并指定返回模型。
def get_document(  # 定义文档详情接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentDetailResponse:
    return document_service.get_document(doc_id)  # 返回指定文档的元信息。


@router.get("/{doc_id}/preview", response_model=DocumentPreviewResponse)  # 声明 GET /documents/{doc_id}/preview 接口，返回在线预览内容。
def preview_document(  # 定义文档预览接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    max_chars: int = Query(default=12_000, ge=1, le=100_000),  # 文本预览最大字符数，限制区间防止一次读取过大。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentPreviewResponse:
    return document_service.get_document_preview(doc_id, max_chars=max_chars)  # 返回文本预览或 PDF 预览元信息。


@router.get("/{doc_id}/preview/file")  # 声明 GET /documents/{doc_id}/preview/file 接口，返回 PDF 文件流。
def preview_document_file(  # 定义文档预览文件流接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> FileResponse:
    path, media_type, filename = document_service.get_document_preview_file(doc_id)  # 读取预览文件信息。
    return FileResponse(  # 返回 inline 文件流，供前端 iframe 在线预览。
        path=path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/{doc_id}", response_model=DocumentDeleteResponse)  # 声明 DELETE /documents/{doc_id} 接口，删除文档并清理向量副本。
def delete_document(  # 定义文档删除接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentDeleteResponse:
    return document_service.delete_document(doc_id)  # 先改主数据状态，再清理向量副本并返回结果。


@router.post(
    "/{doc_id}/rebuild",
    response_model=DocumentRebuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)  # 声明 POST /documents/{doc_id}/rebuild 接口，异步触发重建向量。
def rebuild_document_vectors(  # 定义文档重建向量接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentRebuildResponse:
    return document_service.rebuild_document_vectors(doc_id)  # 清理旧向量并复用 ingest job 机制触发重建。
