from fastapi import APIRouter  # 导入 FastAPI 路由对象。

from .endpoints import chat, documents, health, retrieval  # 导入 v1 版本下的所有接口模块。

router = APIRouter()  # 创建 v1 版本总路由。
router.include_router(health.router)  # 挂载健康检查接口。
router.include_router(documents.router)  # 挂载文档上传和列表接口。
router.include_router(retrieval.router)  # 挂载检索接口。
router.include_router(chat.router)  # 挂载问答接口。
