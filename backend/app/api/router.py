from fastapi import APIRouter  # 导入 FastAPI 路由对象。

from .v1.router import router as v1_router  # 导入 v1 版本的子路由。
from ..core.config import get_settings  # 导入配置读取函数。

settings = get_settings()  # 读取当前配置，主要为了拿到 API 前缀。

api_router = APIRouter()  # 创建项目级总路由。
api_router.include_router(v1_router, prefix=settings.api_v1_prefix)  # 把 v1 路由挂到统一前缀下。
