"""v1 版本总路由——将各 endpoint 子模块统一挂载到 /api/v1 前缀下。"""
from fastapi import APIRouter  # 导入 FastAPI 路由对象。

from .endpoints import auth, chat, documents, health, ingest, logs, ops, request_snapshots, retrieval, sops, system_config, traces  # 导入 v1 版本下的所有接口模块。

router = APIRouter()  # 创建 v1 版本总路由。
router.include_router(health.router)  # 挂载健康检查接口。
router.include_router(auth.router)  # 挂载身份目录基础接口。
router.include_router(documents.router)  # 挂载文档上传和列表接口。
router.include_router(ingest.router)  # 挂载 ingest 任务状态接口。
router.include_router(retrieval.router)  # 挂载检索接口。
router.include_router(chat.router)  # 挂载问答接口。
router.include_router(sops.router)  # 挂载 SOP 列表接口，v0.4 起和 documents 分开管理。
router.include_router(logs.router)  # 挂载最小事件日志查询接口，v0.6 起给日志页和排障入口复用。
router.include_router(traces.router)  # 挂载最小请求 trace 查询接口，v0.6 起给 ops 页面和后续重放能力复用。
router.include_router(request_snapshots.router)  # 挂载最小请求快照与 replay 接口，v0.6 起给可复现能力复用。
router.include_router(ops.router)  # 挂载运行态汇总接口，v0.6 起给更直观的 workspace 运营页复用。
router.include_router(system_config.router)  # 挂载最小系统配置接口，v0.6 起先承接查询档位配置。
