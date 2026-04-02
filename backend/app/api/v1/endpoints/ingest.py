"""Ingest 任务接口模块——提供按 job_id 查询摄取状态与手动触发执行的端点。"""
from fastapi import APIRouter, Depends  # 导入路由对象和依赖注入工具。

from ....schemas.auth import AuthContext
from ....schemas.document import IngestJobStatusResponse  # 导入 ingest job 状态响应模型。
from ....services.auth_service import get_current_auth_context
from ....services.document_service import DocumentService, get_document_service  # 导入文档服务和依赖工厂函数。

router = APIRouter(prefix="/ingest/jobs", tags=["ingest"])  # 创建 ingest 路由分组，并统一加上 /ingest/jobs 前缀。


@router.get(
    "/{job_id}",  # 定义按 job_id 查询 ingest 状态的路径。
    response_model=IngestJobStatusResponse,  # 指定成功时返回的响应结构。
    summary="Get ingest job status",  # 给 Swagger 页面展示简要标题。
)
def get_ingest_job_status(  # 定义 ingest job 状态查询接口函数。
    job_id: str,  # 接收路径中的任务 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> IngestJobStatusResponse:
    return document_service.get_ingest_job(job_id, auth_context=auth_context)  # 返回指定任务的状态信息。


@router.post(
    "/{job_id}/run",  # 定义按 job_id 触发执行 ingest 任务的路径。
    response_model=IngestJobStatusResponse,  # 指定成功时返回的响应结构。
    summary="Enqueue ingest job now",  # 给 Swagger 页面展示简要标题。
)
def run_ingest_job(  # 定义 ingest job 手动重投递接口函数。
    job_id: str,  # 接收路径中的任务 ID。
    auth_context: AuthContext = Depends(get_current_auth_context),
    document_service: DocumentService = Depends(get_document_service),  # 通过依赖注入获取文档服务实例。
) -> IngestJobStatusResponse:
    return document_service.queue_ingest_job(job_id, auth_context=auth_context)  # 把指定任务重新投递到异步队列并返回最新状态。
