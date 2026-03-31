"""健康检查接口模块。提供 /health 紻性探针，用于监控系统判断服务是否正常运行。"""

from fastapi import APIRouter, Depends  # 导入 FastAPI 的路由对象，用来声明接口。

from ....schemas.health import HealthResponse  # 导入健康检查响应模型，固定接口合同字段。
from ....services.health_service import HealthService, get_health_service

router = APIRouter(tags=["health"])  # 创建一个路由分组，并在 Swagger 文档里打上 health 标签。


@router.get("/health", response_model=HealthResponse)  # 声明 GET /health 接口并固定响应结构。
def health_check(
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:  # 定义健康检查函数，返回结构化健康状态。
    return health_service.get_snapshot()
