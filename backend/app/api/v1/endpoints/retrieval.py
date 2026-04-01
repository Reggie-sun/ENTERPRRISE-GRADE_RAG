"""检索接口模块——提供文档向量检索、rerank 对比及 rerank 金丝雀诊断端点。"""
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status  # 导入路由对象和依赖注入工具。

from ....schemas.auth import AuthContext  # 导入统一鉴权上下文，让检索与文档列表共用部门范围。
from ....schemas.query_profile import QueryProfile
from ....schemas.rerank_canary import RerankCanaryListResponse
from ....schemas.retrieval import RetrievalRerankCompareResponse, RetrievalRequest, RetrievalResponse  # 导入检索接口的请求和响应模型。
from ....services.auth_service import get_current_auth_context, get_optional_auth_context  # 导入可选鉴权依赖，兼容当前开发工作台。
from ....services.event_log_service import EventLogService, get_event_log_service
from ....services.query_profile_service import QueryProfileService
from ....services.request_snapshot_service import RequestSnapshotService, get_request_snapshot_service
from ....services.request_trace_service import RequestTraceService, get_request_trace_service
from ....services.rerank_canary_service import RerankCanaryService, get_rerank_canary_service
from ....services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖工厂函数。

router = APIRouter(prefix="/retrieval", tags=["retrieval"])  # 创建 retrieval 路由分组，并统一加上 /retrieval 前缀。


@router.post("/search", response_model=RetrievalResponse)  # 声明 POST /retrieval/search 接口。
def search_documents(  # 定义文档检索接口函数。
    request: RetrievalRequest,  # 从请求体里接收 query 和 top_k。
    auth_context: AuthContext | None = Depends(get_optional_auth_context),  # 已登录时按部门过滤检索结果。
    retrieval_service: RetrievalService = Depends(get_retrieval_service),  # 通过依赖注入获取检索服务实例。
    event_log_service: EventLogService = Depends(get_event_log_service),
    request_snapshot_service: RequestSnapshotService = Depends(get_request_snapshot_service),
    trace_service: RequestTraceService = Depends(get_request_trace_service),
) -> RetrievalResponse:
    trace_id = f"trc_retrieval_{uuid4().hex[:16]}"
    request_id = f"req_retrieval_{uuid4().hex[:16]}"
    normalized_document_id = request.document_id.strip() if request.document_id else None
    start_time = time.monotonic()
    response = retrieval_service.search(request, auth_context=auth_context)
    duration_ms = int((time.monotonic() - start_time) * 1000)
    try:
        profile = QueryProfile.model_validate(
            retrieval_service.query_profile_service.resolve(
                purpose="retrieval",
                requested_mode=request.mode,
                requested_top_k=request.top_k,
            )
        )
    except Exception:
        profile = QueryProfileService().resolve(
            purpose="retrieval",
            requested_mode=request.mode,
            requested_top_k=request.top_k,
        )
    diagnostic_details = {}
    if response.diagnostic is not None:
        diagnostic_details = response.diagnostic.model_dump()

    # Record telemetry best-effort, never block the response.
    try:
        event_log_service.record(
            category="retrieval",
            action="search",
            outcome="success",
            auth_context=auth_context,
            target_type="document" if normalized_document_id else None,
            target_id=normalized_document_id,
            mode=profile.mode,
            top_k=profile.top_k,
            candidate_top_k=profile.candidate_top_k,
            rerank_top_n=profile.rerank_top_n,
            duration_ms=duration_ms,
            details=diagnostic_details,
        )
    except Exception:
        pass

    try:
        trace_service.record(
            trace_id=trace_id,
            request_id=request_id,
            category="retrieval",
            action="search",
            outcome="success",
            auth_context=auth_context,
            target_type="document" if normalized_document_id else None,
            target_id=normalized_document_id,
            mode=profile.mode,
            top_k=profile.top_k,
            candidate_top_k=profile.candidate_top_k,
            rerank_top_n=profile.rerank_top_n,
            total_duration_ms=duration_ms,
            details=diagnostic_details,
        )
    except Exception:
        pass

    try:
        request_snapshot_service.record_retrieval_snapshot(
            trace_id=trace_id,
            request_id=request_id,
            action="search",
            outcome="success",
            request=request,
            profile=profile,
            auth_context=auth_context,
            response=response,
            details=diagnostic_details,
        )
    except Exception:
        pass

    return response


@router.post("/rerank-compare", response_model=RetrievalRerankCompareResponse)  # 声明 POST /retrieval/rerank-compare 接口。
def compare_rerank_routes(  # 对同一批检索候选执行当前默认 rerank 路由与 heuristic 基线对比。
    request: RetrievalRequest,
    auth_context: AuthContext | None = Depends(get_optional_auth_context),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
) -> RetrievalRerankCompareResponse:
    return retrieval_service.compare_rerank(request, auth_context=auth_context)


@router.get("/rerank-canary", response_model=RerankCanaryListResponse)
def list_recent_rerank_canary_samples(
    limit: int = Query(default=8, ge=1, le=50),
    decision: str | None = Query(default=None, min_length=1, max_length=64),
    auth_context: AuthContext = Depends(get_current_auth_context),
    rerank_canary_service: RerankCanaryService = Depends(get_rerank_canary_service),
) -> RerankCanaryListResponse:
    if not auth_context.role.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to rerank canary diagnostics.",
        )
    return RerankCanaryListResponse(
        limit=limit,
        items=rerank_canary_service.list_recent(auth_context=auth_context, limit=limit, decision=decision),
    )
