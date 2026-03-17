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

    qdrant_url: str = "http://qdrant:6333"  # Qdrant 服务地址。
    qdrant_collection: str = "enterprise_rag_v1"  # 默认使用的 Qdrant collection 名称。

    ollama_base_url: str = "http://ollama:11434"  # LLM 服务地址，默认按 Ollama 风格接口处理。
    ollama_model: str = "qwen2.5:7b"  # 默认生成模型名称。
    embedding_provider: str = "ollama"  # 当前 embedding 提供方类型。
    embedding_base_url: str | None = None  # 独立 embedding 服务地址，可为空。
    embedding_api_key: str | None = None  # OpenAI 兼容 embedding 服务的鉴权密钥。
    embedding_model: str = "BAAI/bge-m3"  # 默认 embedding 模型名称。
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # 默认 reranker 模型名称。
    embedding_timeout_seconds: float = 120.0  # embedding 请求超时时间。
    embedding_batch_size: int = 16  # embedding 批量请求大小。
    embedding_mock_vector_size: int = 32  # mock embedding 模式下生成的向量维度。

    chunk_size_chars: int = 800  # 每个 chunk 的目标字符长度。
    chunk_overlap_chars: int = 120  # 相邻 chunk 的重叠字符长度。
    chunk_min_chars: int = 200  # chunk 切分时允许的最小字符阈值。

    top_k_default: int = 5  # 默认检索返回数量。
    rerank_top_n: int = 3  # 默认 rerank 后保留的数量。

    data_dir: Path = Field(default=PROJECT_ROOT / "data")  # 项目数据根目录。
    upload_dir: Path = Field(default=PROJECT_ROOT / "data" / "uploads")  # 原始上传文件目录。
    parsed_dir: Path = Field(default=PROJECT_ROOT / "data" / "parsed")  # 解析后纯文本目录。
    chunk_dir: Path = Field(default=PROJECT_ROOT / "data" / "chunks")  # chunk 结果目录。

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
    for path in (settings.data_dir, settings.upload_dir, settings.parsed_dir, settings.chunk_dir):  # 依次遍历所有关键目录。
        path.mkdir(parents=True, exist_ok=True)  # 不存在就递归创建，存在则跳过。
