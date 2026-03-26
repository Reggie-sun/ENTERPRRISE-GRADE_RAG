import os  # 导入 os，用于兼容读取标准 DATABASE_URL 环境变量。
from functools import lru_cache  # 导入缓存装饰器，避免重复创建 Settings 对象。
from pathlib import Path  # 导入 Path，方便跨平台处理目录路径。

from pydantic import Field, field_validator  # 导入字段定义和字段校验工具。
from pydantic_settings import BaseSettings, SettingsConfigDict  # 导入基于环境变量的配置基类。

BACKEND_DIR = Path(__file__).resolve().parents[2]  # 计算 backend 目录的绝对路径。
PROJECT_ROOT = BACKEND_DIR.parent  # 再往上一层拿到项目根目录。


class Settings(BaseSettings):  # 定义项目统一配置对象，所有配置都从这里读取。
    app_name: str = "Enterprise-grade RAG API"  # 应用名称，用于文档和接口返回。
    app_env: str = "development"  # 当前运行环境，例如 development / test / production。
    debug: bool = True  # 是否开启调试模式。
    api_v1_prefix: str = "/api/v1"  # API v1 的统一前缀。
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])  # 允许跨域的来源列表。

    qdrant_url: str = "http://127.0.0.1:6333"  # Qdrant 服务地址，默认走本机端口以匹配本地开发基线。
    qdrant_collection: str = "enterprise_rag_v1"  # 默认使用的 Qdrant collection 名称。
    postgres_metadata_enabled: bool = False  # 是否启用 PostgreSQL 作为 document/job 元数据存储真源。
    postgres_metadata_dsn: str | None = None  # PostgreSQL 连接串，未配置时可回退读取 DATABASE_URL。
    database_url: str | None = Field(default=None, alias="DATABASE_URL")  # 兼容读取 Prisma 常用的 DATABASE_URL（无 RAG_ 前缀）。

    celery_broker_url: str = "redis://localhost:6379/0"  # Celery broker 地址，开发环境默认走本机 Redis。
    celery_result_backend: str = "redis://localhost:6379/1"  # Celery 结果后端地址，默认单独占一个 Redis DB。
    celery_ingest_queue: str = "ingest"  # 文档入库任务默认进入 ingest 队列。
    celery_task_always_eager: bool = False  # 测试环境可打开 eager，让任务在当前进程内直接执行。
    celery_task_eager_propagates: bool = True  # eager 模式下把任务异常直接抛出，便于测试排查。
    ingest_failure_retry_limit: int = Field(default=3, ge=1)  # 单个 ingest job 在进入 dead_letter 前允许的最大失败次数。
    ingest_retry_delay_seconds: int = Field(default=2, ge=0)  # Celery 自动重试的退避秒数。
    ingest_inflight_stale_seconds: int = Field(default=30 * 60, ge=1)  # queued/processing 任务超过该时长未刷新时视为卡死，允许重复上传补发新 job。

    llm_provider: str = "mock"  # 当前 LLM provider，支持 mock / ollama / openai。
    llm_base_url: str | None = None  # OpenAI 兼容或通用 LLM 服务地址，未配置时回退到 ollama_base_url。
    llm_api_key: str | None = None  # OpenAI 兼容 LLM 的鉴权密钥，本地 vLLM 可留空。
    llm_model: str | None = None  # 通用 LLM 模型名称，未配置时回退到 ollama_model。
    ollama_base_url: str = "http://127.0.0.1:11434"  # Ollama 服务地址，默认走本机端口，避免容器域名缺失导致连不上。
    ollama_model: str = "qwen2.5:7b"  # 兼容旧配置的默认生成模型名称。
    llm_timeout_seconds: float = 180.0  # LLM 生成请求超时时间。
    llm_temperature: float = 0.1  # LLM 默认采样温度。
    embedding_provider: str = "mock"  # 当前 embedding 提供方类型，默认 mock 便于零依赖启动。
    embedding_base_url: str | None = None  # 独立 embedding 服务地址，可为空。
    embedding_api_key: str | None = None  # OpenAI 兼容 embedding 服务的鉴权密钥。
    embedding_model: str = "BAAI/bge-m3"  # 默认 embedding 模型名称。
    reranker_provider: str = "heuristic"  # 当前 reranker provider，V1 默认启发式重排。
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # 默认 reranker 模型名称。
    embedding_timeout_seconds: float = 120.0  # embedding 请求超时时间。
    embedding_batch_size: int = 16  # embedding 批量请求大小。
    embedding_mock_vector_size: int = 32  # mock embedding 模式下生成的向量维度。

    chunk_size_chars: int = 800  # 每个 chunk 的目标字符长度。
    chunk_overlap_chars: int = 120  # 相邻 chunk 的重叠字符长度。
    chunk_min_chars: int = 200  # chunk 切分时允许的最小字符阈值。

    top_k_default: int = 5  # 默认检索返回数量。
    rerank_top_n: int = 3  # 默认 rerank 后保留的数量。
    upload_max_file_size_bytes: int = 100 * 1024 * 1024  # 上传文件大小上限，默认 100MB。
    asset_store_backend: str = "filesystem"  # 上传原文件存储后端，默认仍走本地文件系统，可切到 postgres。
    data_asset_store_binary_enabled: bool = True  # data 资产是否写入 binaryContent（二进制落库开关）。
    data_asset_binary_max_bytes: int = 1 * 1024 * 1024  # 允许写入 binaryContent 的最大文件大小（默认 1MB）。

    data_dir: Path = Field(default=PROJECT_ROOT / "data")  # 项目数据根目录。
    upload_dir: Path = Field(default=PROJECT_ROOT / "data" / "uploads")  # 原始上传文件目录。
    parsed_dir: Path = Field(default=PROJECT_ROOT / "data" / "parsed")  # 解析后纯文本目录。
    chunk_dir: Path = Field(default=PROJECT_ROOT / "data" / "chunks")  # chunk 结果目录。
    document_dir: Path = Field(default=PROJECT_ROOT / "data" / "documents")  # document 元数据目录。
    job_dir: Path = Field(default=PROJECT_ROOT / "data" / "jobs")  # ingest job 元数据目录。
    sop_asset_dir: Path = Field(default=PROJECT_ROOT / "data" / "sop_assets")  # SOP 本地预览/下载资源目录，独立于文档解析产物目录。
    identity_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "identity_bootstrap.json")  # 身份目录 bootstrap 文件路径，供 v0.3 登录/权限模块复用。
    sop_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "sop_bootstrap.json")  # SOP 主数据 bootstrap 文件路径，供 v0.4 列表/详情接口复用。
    auth_token_secret: str = "local-dev-enterprise-rag-auth-secret"  # 本地开发用 token 签名密钥，生产环境必须通过环境变量覆盖。
    auth_token_issuer: str = "enterprise-rag-api"  # 最小 token 发行者标识，便于后续切换到标准 JWT 时保持语义稳定。
    auth_token_expire_minutes: int = Field(default=60, ge=1)  # access token 默认有效期（分钟）。

    model_config = SettingsConfigDict(  # 定义 Pydantic Settings 的加载规则。
        env_file=str(PROJECT_ROOT / ".env"),  # 默认从项目根目录的 .env 读取环境变量。
        env_file_encoding="utf-8",  # 指定 .env 文件编码。
        case_sensitive=False,  # 环境变量名大小写不敏感。
        extra="ignore",  # 忽略没有定义在 Settings 里的多余环境变量。
        env_prefix="RAG_",  # 所有项目环境变量统一使用 RAG_ 前缀。
    )

    @field_validator("cors_origins", mode="before")  # 在字段赋值前先执行这个校验函数。
    @classmethod  # 把校验函数定义成类方法。
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:  # 兼容字符串和列表两种输入格式。
        if isinstance(value, str):  # 如果环境变量传进来的是字符串。
            return [item.strip() for item in value.split(",") if item.strip()]  # 按逗号拆分并清理空白项。
        return value  # 如果本来就是列表，则直接原样返回。


@lru_cache  # 缓存 Settings 实例，避免每次调用都重复读取环境变量。
def get_settings() -> Settings:  # 提供全局统一的配置获取入口。
    return Settings()  # 创建并返回 Settings 对象。


def ensure_data_directories(settings: Settings) -> None:  # 确保项目需要的数据目录都已经存在。
    for path in (  # 依次遍历所有关键目录。
        settings.data_dir,
        settings.upload_dir,
        settings.parsed_dir,
        settings.chunk_dir,
        settings.document_dir,
        settings.job_dir,
        settings.sop_asset_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)  # 不存在就递归创建，存在则跳过。


def get_llm_base_url(settings: Settings) -> str:  # 统一解析当前生效的 LLM 服务地址。
    return (settings.llm_base_url or settings.ollama_base_url).rstrip("/")  # 优先走通用地址，兼容旧配置再回退到 Ollama。


def get_llm_model(settings: Settings) -> str:  # 统一解析当前生效的 LLM 模型名称。
    return (settings.llm_model or settings.ollama_model).strip()  # 优先走通用模型名，兼容旧配置再回退到 Ollama。


def get_postgres_metadata_dsn(settings: Settings) -> str | None:  # 统一解析元数据 PostgreSQL 连接串。
    configured_dsn = (settings.postgres_metadata_dsn or "").strip()  # 优先读取 RAG_POSTGRES_METADATA_DSN 配置。
    if configured_dsn:  # 如果显式配置了 DSN，直接使用。
        return configured_dsn
    aliased_dsn = (settings.database_url or "").strip()  # 再尝试读取 Settings 中 alias 到 DATABASE_URL 的值。
    if aliased_dsn:  # 如果通过 .env 或环境变量加载到了 DATABASE_URL，就直接使用。
        return aliased_dsn
    fallback_dsn = os.getenv("DATABASE_URL", "").strip()  # 回退兼容 Prisma 常用的 DATABASE_URL。
    return fallback_dsn or None  # 为空时返回 None，交由调用方决定是否启用。
