from fastapi import APIRouter  # 导入 FastAPI 的路由对象，用来声明接口。

from ....core.config import get_settings  # 导入配置读取函数，用来拿到当前系统配置。

router = APIRouter(tags=["health"])  # 创建一个路由分组，并在 Swagger 文档里打上 health 标签。


@router.get("/health")  # 声明一个 GET /health 接口。
def health_check() -> dict[str, object]:  # 定义健康检查函数，返回一个字典结构的状态信息。
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
            "provider": "ollama",  # 当前问答生成阶段默认按 Ollama 风格接口来接。
            "base_url": settings.ollama_base_url,  # 返回 LLM 服务地址。
            "model": settings.ollama_model,  # 返回当前配置的生成模型名称。
        },
        "embedding": {
            "provider": settings.embedding_provider,  # 返回当前 embedding 服务类型，例如 ollama / openai / mock。
            "base_url": settings.embedding_base_url or settings.ollama_base_url,  # 优先返回独立 embedding 地址，没配则复用 LLM 地址。
            "model": settings.embedding_model,  # 返回当前使用的 embedding 模型名称。
        },
    }
