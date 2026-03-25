from fastapi import APIRouter  # 导入 FastAPI 的路由对象，用来声明接口。

from ....core.config import get_llm_base_url, get_llm_model, get_postgres_metadata_dsn, get_settings  # 导入配置读取函数和统一配置解析函数。
from ....schemas.health import HealthResponse  # 导入健康检查响应模型，固定接口合同字段。

router = APIRouter(tags=["health"])  # 创建一个路由分组，并在 Swagger 文档里打上 health 标签。


@router.get("/health", response_model=HealthResponse)  # 声明 GET /health 接口并固定响应结构。
def health_check() -> HealthResponse:  # 定义健康检查函数，返回结构化健康状态。
    settings = get_settings()  # 读取当前项目配置，例如应用名、Qdrant 地址、模型地址等。
    return {
        "status": "ok",  # 表示服务本身当前可用。
        "app_name": settings.app_name,  # 返回应用名称，便于确认当前服务实例。
        "environment": settings.app_env,  # 返回当前运行环境，例如 development / test / production。
        "vector_store": {
            "provider": "qdrant",  # 当前向量库提供方固定为 Qdrant。
            "url": settings.qdrant_url,  # 返回 Qdrant 的连接地址。
            "collection": settings.qdrant_collection,  # 返回当前使用的 collection 名称。
        },
        "llm": {
            "provider": settings.llm_provider,  # 返回当前 LLM provider。
            "base_url": get_llm_base_url(settings) if settings.llm_provider.lower().strip() != "mock" else "",  # 非 mock 模式返回当前生效的服务地址。
            "model": "mock" if settings.llm_provider.lower().strip() == "mock" else get_llm_model(settings),  # mock 模式显式返回 mock，避免误导联调判断。
        },
        "embedding": {
            "provider": settings.embedding_provider,  # 返回当前 embedding 服务类型，例如 ollama / openai / mock。
            "base_url": settings.embedding_base_url or settings.ollama_base_url,  # 优先返回独立 embedding 地址，没配则复用 LLM 地址。
            "model": settings.embedding_model,  # 返回当前使用的 embedding 模型名称。
        },
        "queue": {
            "provider": "celery",  # 当前异步任务框架固定为 Celery。
            "broker_url": settings.celery_broker_url,  # 返回 Celery broker 地址。
            "result_backend": settings.celery_result_backend,  # 返回 Celery 结果后端地址。
            "ingest_queue": settings.celery_ingest_queue,  # 返回入库任务默认队列名。
        },
        "metadata_store": {
            "provider": "postgres" if settings.postgres_metadata_enabled else "local_json",  # 当前 document/job 元数据后端。
            "postgres_enabled": settings.postgres_metadata_enabled,  # 是否启用了 PostgreSQL 元数据真源。
            "dsn_configured": bool(get_postgres_metadata_dsn(settings)),  # 是否检测到可用 DSN，避免把敏感连接串暴露给前端。
        },
    }
