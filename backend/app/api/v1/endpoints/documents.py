"""文档管理接口模块——提供文档上传、列表、详情、预览、下载、删除及向量重建等 CRUD 端点。"""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status  # 导入上传接口需要的 FastAPI 组件。
from fastapi.responses import FileResponse, Response  # 导入文件流响应和字节响应，兼容本地路径与数据库二进制存储。

from ._response_headers import build_content_disposition
from ....schemas.auth import AuthContext  # 导入统一鉴权上下文，让文档接口复用同一份权限边界。
from ....schemas.document import (  # 导入文档相关响应模型。
    Classification,
    DocumentBatchCreateResponse,
    DocumentBatchDeleteResponse,
    DocumentBatchRebuildResponse,
    DocumentBatchRestoreResponse,
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
from ....services.auth_service import get_current_auth_context
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
    file: UploadFile = File(..., description="Supported file types: .pdf, .md, .markdown, .txt, .doc, .docx, .csv, .html, .json, .xlsx, .pptx, .xls, .png, .jpg, .jpeg, .webp, .bmp"),  # 接收上传文件。
    tenant_id: str = Form(..., description="Tenant identifier"),  # 接收租户 ID。
    department_id: str | None = Form(default=None),  # 接收主部门（v0.2 新增字段）。
    department_ids: list[str] | None = Form(default=None),  # 接收部门范围。
    retrieval_department_ids: list[str] | None = Form(default=None),  # 接收检索补充授权部门范围。
    category_id: str | None = Form(default=None),  # 接收二级分类（v0.2 新增字段）。
    role_ids: list[str] | None = Form(default=None),  # 接收角色范围。
    owner_id: str | None = Form(default=None),  # 接收 owner。
    visibility: Visibility = Form(default="private"),  # 接收可见性策略。
    classification: Classification = Form(default="internal"),  # 接收文档密级。
    tags: list[str] | None = Form(default=None),  # 接收标签列表。
    source_system: str | None = Form(default=None),  # 接收来源系统。
    uploaded_by: str | None = Form(default=None),  # 接收上传人（v0.2 新命名）。
    created_by: str | None = Form(default=None),  # 接收上传人。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 试点环境下文档管理接口默认要求登录，避免匿名越过部门边界。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentCreateResponse:
    return await document_service.create_document(  # 调用服务层创建文档和 ingest job。
        upload=file,
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


@router.post(
    "/batch",  # 定义批量创建接口路径。
    response_model=DocumentBatchCreateResponse,  # 指定批量上传响应结构。
    status_code=status.HTTP_201_CREATED,  # 批量创建接口保持 201 语义。
    summary="Batch create documents and queue ingestion",  # 给 Swagger 页面展示简要标题。
    description="Uploads multiple documents and queues one ingest job per file; returns per-file queued/failed result.",  # 给 Swagger 页面展示详细说明。
)
async def create_documents_batch(  # 定义批量文档创建接口函数。
    files: list[UploadFile] = File(..., description="Supported file types: .pdf, .md, .markdown, .txt, .doc, .docx, .csv, .html, .json, .xlsx, .pptx, .xls, .png, .jpg, .jpeg, .webp, .bmp"),  # 接收多个上传文件。
    tenant_id: str = Form(..., description="Tenant identifier"),  # 接收租户 ID。
    department_id: str | None = Form(default=None),  # 接收主部门（v0.2 新增字段）。
    department_ids: list[str] | None = Form(default=None),  # 接收部门范围。
    retrieval_department_ids: list[str] | None = Form(default=None),  # 接收检索补充授权部门范围。
    category_id: str | None = Form(default=None),  # 接收二级分类（v0.2 新增字段）。
    role_ids: list[str] | None = Form(default=None),  # 接收角色范围。
    owner_id: str | None = Form(default=None),  # 接收 owner。
    visibility: Visibility = Form(default="private"),  # 接收可见性策略。
    classification: Classification = Form(default="internal"),  # 接收文档密级。
    tags: list[str] | None = Form(default=None),  # 接收标签列表。
    source_system: str | None = Form(default=None),  # 接收来源系统。
    uploaded_by: str | None = Form(default=None),  # 接收上传人（v0.2 新命名）。
    created_by: str | None = Form(default=None),  # 接收上传人。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 批量上传同样走受保护的管理边界。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentBatchCreateResponse:
    return await document_service.create_documents_batch(  # 逐文件复用 create_document 逻辑并汇总结果。
        uploads=files,
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


@router.post(
    "/upload",  # 定义上传接口路径。
    response_model=DocumentUploadResponse,  # 指定成功时返回的响应结构。
    status_code=status.HTTP_201_CREATED,  # 指定成功时返回 201 Created。
    summary="Upload and ingest a document",  # 给 Swagger 页面展示简要标题。
    description="Uploads a document and runs native parse or OCR, chunk, embedding, and Qdrant upsert synchronously.",  # 给 Swagger 页面展示详细说明。
)
async def upload_document(  # 定义文档上传接口函数。
    file: UploadFile = File(..., description="Supported file types: .pdf, .md, .markdown, .txt, .doc, .docx, .csv, .html, .json, .xlsx, .pptx, .xls, .png, .jpg, .jpeg, .webp, .bmp"),  # 接收上传文件，并在 Swagger 中注明支持格式。
    auth_context: AuthContext = Depends(get_current_auth_context),
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentUploadResponse:
    return await document_service.save_upload(file, auth_context=auth_context)  # 调用服务层保存文件并执行完整入库流程。


@router.get("", response_model=DocumentListResponse)  # 声明 GET /documents 接口，并指定返回模型。
def list_documents(  # 定义文档列表接口函数。
    page: int = Query(default=1, ge=1),  # 当前页码，从 1 开始。
    page_size: int = Query(default=20, ge=1, le=200),  # 每页大小，限制上限避免一次拉取过大。
    keyword: str | None = Query(default=None),  # 文件名关键字筛选。
    department_id: str | None = Query(default=None),  # 主部门筛选。
    category_id: str | None = Query(default=None),  # 分类筛选。
    document_status: DocumentLifecycleStatus | None = Query(default=None, alias="status"),  # 文档生命周期状态筛选。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 文档列表默认 fail-closed，避免匿名探测资料范围。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentListResponse:
    return document_service.list_documents(
        page=page,
        page_size=page_size,
        keyword=keyword,
        department_id=department_id,
        category_id=category_id,
        document_status=document_status,
        auth_context=auth_context,
    )  # 返回分页+筛选后的文档列表。


@router.get("/{doc_id}", response_model=DocumentDetailResponse)  # 声明 GET /documents/{doc_id} 接口，并指定返回模型。
def get_document(  # 定义文档详情接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 文档详情默认要求登录并按部门权限过滤。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentDetailResponse:
    return document_service.get_document(doc_id, auth_context=auth_context)  # 返回指定文档的元信息。


@router.get("/{doc_id}/preview", response_model=DocumentPreviewResponse)  # 声明 GET /documents/{doc_id}/preview 接口，返回在线预览内容。
def preview_document(  # 定义文档预览接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    max_chars: int = Query(default=12_000, ge=1, le=100_000),  # 文本预览最大字符数，限制区间防止一次读取过大。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 预览接口同样受保护。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentPreviewResponse:
    return document_service.get_document_preview(doc_id, max_chars=max_chars, auth_context=auth_context)  # 返回文本预览或 PDF 预览元信息。


@router.get("/{doc_id}/preview/file")  # 声明 GET /documents/{doc_id}/preview/file 接口，返回 PDF 文件流。
def preview_document_file(  # 定义文档预览文件流接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),  # PDF 文件流和预览文本共享权限边界。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> Response:
    payload = document_service.get_document_preview_file(doc_id, auth_context=auth_context)  # 读取预览文件信息。
    if payload.path is not None:
        return FileResponse(  # 返回 inline 文件流，供前端 iframe 在线预览。
            path=payload.path,
            media_type=payload.media_type,
            filename=payload.filename,
            headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="inline")},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="inline")},
    )


@router.get("/{doc_id}/file")  # 声明 GET /documents/{doc_id}/file 接口，返回原始文件下载流。
def download_document_file(  # 定义文档原始文件下载接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 下载接口同样走统一读权限。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> Response:
    payload = document_service.get_document_file(doc_id, auth_context=auth_context)  # 读取原始文件信息。
    if payload.path is not None:
        return FileResponse(  # 返回 attachment 文件流，供前端下载。
            path=payload.path,
            media_type=payload.media_type,
            filename=payload.filename,
            headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="attachment")},
        )
    return Response(
        content=payload.content or b"",
        media_type=payload.media_type,
        headers={"Content-Disposition": build_content_disposition(payload.filename, disposition_type="attachment")},
    )


@router.delete("/{doc_id}", response_model=DocumentDeleteResponse)  # 声明 DELETE /documents/{doc_id} 接口，删除文档并清理向量副本。
def delete_document(  # 定义文档删除接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 删除接口默认要求登录，角色限制由服务层继续执行。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentDeleteResponse:
    return document_service.delete_document(doc_id, auth_context=auth_context)  # 先改主数据状态，再清理向量副本并返回结果。


@router.delete("", response_model=DocumentBatchDeleteResponse)  # 声明 DELETE /documents 接口，批量删除当前用户上传的文档。
def delete_my_documents(  # 定义批量删除接口函数。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 批量删除必须登录，只删当前用户上传的。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentBatchDeleteResponse:
    return document_service.delete_my_documents(auth_context=auth_context)  # 查找当前用户上传的所有文档并逐个删除。


@router.post(
    "/restore",
    response_model=DocumentBatchRestoreResponse,
    status_code=status.HTTP_202_ACCEPTED,
)  # 声明 POST /documents/restore 接口，批量恢复当前用户已删除的文档。
def restore_my_documents(  # 定义批量恢复接口函数。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 批量恢复必须登录，只恢复当前用户上传的文档。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentBatchRestoreResponse:
    return document_service.restore_my_documents(auth_context=auth_context)  # 筛选当前用户已删除文档，恢复状态并重新入库。


@router.post(
    "/rebuild",
    response_model=DocumentBatchRebuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)  # 声明 POST /documents/rebuild 接口，批量重建当前用户文档的向量。
def rebuild_my_documents(  # 定义批量重建向量接口函数。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 批量重建必须登录，只处理当前用户上传的文档。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentBatchRebuildResponse:
    return document_service.rebuild_my_documents(auth_context=auth_context)  # 筛选当前用户文档并用最新 chunk 配置重建向量。


@router.post(
    "/{doc_id}/rebuild",
    response_model=DocumentRebuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
)  # 声明 POST /documents/{doc_id}/rebuild 接口，异步触发重建向量。
def rebuild_document_vectors(  # 定义文档重建向量接口函数。
    doc_id: str,  # 接收路径里的文档 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),  # 重建接口默认要求登录，角色限制由服务层继续执行。
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> DocumentRebuildResponse:
    return document_service.rebuild_document_vectors(doc_id, auth_context=auth_context)  # 清理旧向量并复用 ingest job 机制触发重建。
