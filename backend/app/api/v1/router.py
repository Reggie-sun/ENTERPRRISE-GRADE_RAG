from fastapi import APIRouter  # 导入 FastAPI 路由对象。

from .endpoints import auth, chat, documents, health, ingest, retrieval, sops  # 导入 v1 版本下的所有接口模块。

router = APIRouter()  # 创建 v1 版本总路由。
router.include_router(health.router)  # 挂载健康检查接口。
router.include_router(auth.router)  # 挂载身份目录基础接口。
router.include_router(documents.router)  # 挂载文档上传和列表接口。
router.include_router(ingest.router)  # 挂载 ingest 任务状态接口。
router.include_router(retrieval.router)  # 挂载检索接口。
router.include_router(chat.router)  # 挂载问答接口。
router.include_router(sops.router)  # 挂载 SOP 列表接口，v0.4 起和 documents 分开管理。
