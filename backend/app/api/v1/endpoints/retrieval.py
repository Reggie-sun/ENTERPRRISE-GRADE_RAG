from fastapi import APIRouter, Depends  # 导入路由对象和依赖注入工具。

from ....schemas.retrieval import RetrievalRequest, RetrievalResponse  # 导入检索接口的请求和响应模型。
from ....services.retrieval_service import RetrievalService, get_retrieval_service  # 导入检索服务和依赖工厂函数。

router = APIRouter(prefix="/retrieval", tags=["retrieval"])  # 创建 retrieval 路由分组，并统一加上 /retrieval 前缀。


@router.post("/search", response_model=RetrievalResponse)  # 声明 POST /retrieval/search 接口。
def search_documents(  # 定义文档检索接口函数。
    request: RetrievalRequest,  # 从请求体里接收 query 和 top_k。
    retrieval_service: RetrievalService = Depends(get_retrieval_service),  # 通过依赖注入获取检索服务实例。
) -> RetrievalResponse:
    return retrieval_service.search(request)  # 调用服务层执行检索并返回结果。
