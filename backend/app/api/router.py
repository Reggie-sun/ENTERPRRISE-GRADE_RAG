"""API 路由聚合层，将 v1 子路由挂载到统一前缀下。"""
from fastapi import APIRouter

from .v1.router import router as v1_router
from ..core.config import get_settings

settings = get_settings()

api_router = APIRouter()
api_router.include_router(v1_router, prefix=settings.api_v1_prefix)
