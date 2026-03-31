"""项目统一配置 — 薄聚合层。

字段定义已按职责拆分到 _app / _storage / _model / _retrieval / _auth 五个子模块，
Settings 通过多继承将它们组合在一起，对外保持完全平坦的属性访问方式不变。
"""

# ── 配置聚合模块 ──────────────────────────────────────────────────────────
# 各维度配置定义在子模块中，此处仅做组合与暴露公共辅助函数。
# 子模块: _app(应用级) / _storage(存储) / _model(模型) / _retrieval(检索) / _auth(认证) / _ocr(OCR)

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from ._app import _AppSettings
from ._auth import _AuthSettings
from ._model import _ModelSettings
from ._ocr import _OCRSettings
from ._retrieval import _RetrievalSettings
from ._storage import BACKEND_DIR, PROJECT_ROOT, _StorageSettings

# 对外暴露的公共 API 列表
__all__ = [
    "BACKEND_DIR",
    "PROJECT_ROOT",
    "Settings",
    "get_settings",
    "ensure_data_directories",
    "get_llm_base_url",
    "get_llm_model",
    "get_reranker_base_url",
    "get_postgres_metadata_dsn",
]


class Settings(_AppSettings, _StorageSettings, _ModelSettings, _RetrievalSettings, _OCRSettings, _AuthSettings):
    """项目统一配置对象 — 多继承组合各维度子配置，对外接口不变。

    所有环境变量均以 RAG_ 为前缀（如 RAG_APP_NAME），从 .env 文件加载。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),       # 从项目根目录的 .env 文件加载配置
        env_file_encoding="utf-8",
        case_sensitive=False,                       # 环境变量名不区分大小写
        extra="ignore",                             # 忽略未定义的环境变量
        env_prefix="RAG_",                          # 环境变量统一前缀
    )

    @model_validator(mode="after")
    def derive_runtime_paths(self) -> "Settings":
        """在所有字段加载完毕后，为未显式配置的路径字段推导默认值。"""
        if self.request_trace_dir is None:
            self.request_trace_dir = self.data_dir / "request_traces"
        if self.request_snapshot_dir is None:
            self.request_snapshot_dir = self.data_dir / "request_snapshots"
        if self.rerank_canary_dir is None:
            self.rerank_canary_dir = self.data_dir / "rerank_canary"
        if self.chat_memory_dir is None:
            self.chat_memory_dir = self.data_dir / "chat_memory"
        return self


# 缓存单例：整个进程生命周期内只创建一次 Settings 实例
@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（带缓存）。"""
    return Settings()


def ensure_data_directories(settings: Settings) -> None:
    """确保所有数据目录存在，不存在则自动创建（含父目录）。"""
    for path in (
        settings.data_dir,
        settings.upload_dir,
        settings.parsed_dir,
        settings.chunk_dir,
        settings.ocr_artifact_dir,
        settings.document_dir,
        settings.job_dir,
        settings.event_log_dir,
        settings.request_trace_dir,
        settings.request_snapshot_dir,
        settings.rerank_canary_dir,
        settings.chat_memory_dir,
        settings.sop_asset_dir,
        settings.sop_record_dir,
        settings.sop_version_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def get_llm_base_url(settings: Settings) -> str:
    """获取 LLM 基础 URL，优先使用 llm_base_url，回退到 ollama_base_url。"""
    return (settings.llm_base_url or settings.ollama_base_url).rstrip("/")


def get_llm_model(settings: Settings) -> str:
    """获取 LLM 模型名称，优先使用 llm_model，回退到 ollama_model。"""
    return (settings.llm_model or settings.ollama_model).strip()


def get_reranker_base_url(settings: Settings) -> str:
    """获取 Reranker 基础 URL，按优先级依次尝试 reranker / embedding / llm / ollama 的 URL。

    Raises:
        RuntimeError: 所有候选 URL 均未配置时抛出。
    """
    for value in (
        settings.reranker_base_url,
        settings.embedding_base_url,
        settings.llm_base_url,
        settings.ollama_base_url,
    ):
        normalized = (value or "").strip()
        if normalized:
            return normalized.rstrip("/")
    raise RuntimeError(
        "Reranker base URL is not configured. Set RAG_RERANKER_BASE_URL or reuse embedding/llm base URL."
    )


def get_postgres_metadata_dsn(settings: Settings) -> str | None:
    """获取 PostgreSQL 元数据连接字符串，按优先级依次尝试：
    1. postgres_metadata_dsn（显式配置）
    2. database_url（别名，对应环境变量 DATABASE_URL）
    3. 系统环境变量 DATABASE_URL
    """
    configured_dsn = (settings.postgres_metadata_dsn or "").strip()
    if configured_dsn:
        return configured_dsn
    aliased_dsn = (settings.database_url or "").strip()
    if aliased_dsn:
        return aliased_dsn
    fallback_dsn = os.getenv("DATABASE_URL", "").strip()
    return fallback_dsn or None
