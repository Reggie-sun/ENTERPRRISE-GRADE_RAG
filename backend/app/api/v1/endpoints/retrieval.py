"""检索接口模块——提供文档向量检索、rerank 对比及 rerank 金丝雀诊断端点。"""
from fastapi import APIRouter, Depends, HTTPException, Query, status  # 导入路由对象和依赖注入工具。

from ....schemas.auth import AuthContext  # 导入统一鉴权上下文，让检索与文档列表共用部门范围。
from ....schemas.rerank_canary import RerankCanaryListResponse
from ....schemas.retrieval import RetrievalRerankCompareResponse, RetrievalRequest, RetrievalResponse  # 导入检索接口的请求和响应模型。
from ....services.auth_service import get_current_auth_context, get_optional_auth_context  # 导入可选鉴权依赖，兼容当前开发工作台。
from ....services.rerank_canary_service import RerankCanaryService, get_rerank_canary_service
from ....services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖工厂函数。

router = APIRouter(prefix="/retrieval", tags=["retrieval"])  # 创建 retrieval 路由分组，并统一加上 /retrieval 前缀。


@router.post("/search", response_model=RetrievalResponse)  # 声明 POST /retrieval/search 接口。
def search_documents(  # 定义文档检索接口函数。
    request: RetrievalRequest,  # 从请求体里接收 query 和 top_k。
    auth_context: AuthContext | None = Depends(get_optional_auth_context),  # 已登录时按部门过滤检索结果。
    retrieval_service: RetrievalService = Depends(get_retrieval_service),  # 通过依赖注入获取检索服务实例。
) -> RetrievalResponse:
    return retrieval_service.search(request, auth_context=auth_context)  # 调用服务层执行检索并返回结果。


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
