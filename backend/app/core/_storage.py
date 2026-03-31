"""存储与基础设施配置：Qdrant、PostgreSQL、文件目录、上传、资产。

本模块定义向量数据库、关系数据库、文件存储路径等基础设施配置。
作为 mixin 被 Settings 多继承组合。
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# 项目路径常量：backend/ 目录和项目根目录
BACKEND_DIR = Path(__file__).resolve().parents[2]   # 指向 backend/ 目录
PROJECT_ROOT = BACKEND_DIR.parent                    # 指向项目根目录


class _StorageSettings(BaseSettings):
    """Storage / infrastructure settings mixin。

    包含：向量数据库(Qdrant)、关系数据库(PostgreSQL)、文件上传限制、资产存储、
    各类数据目录路径、Bootstrap 初始化文件路径。
    """

    # ── 向量数据库（Qdrant）配置 ────────────────────────────────────────────
    qdrant_url: str = "http://127.0.0.1:6333"       # Qdrant 服务地址
    qdrant_collection: str = "enterprise_rag_v1"    # 默认集合名称

    # ── 关系数据库（PostgreSQL）配置 ────────────────────────────────────────
    postgres_metadata_enabled: bool = False          # 是否启用 PostgreSQL 元数据存储
    postgres_metadata_dsn: str | None = None         # PostgreSQL 连接字符串
    database_url: str | None = Field(default=None, alias="DATABASE_URL")  # DATABASE_URL 别名

    # ── 文件上传与资产存储配置 ──────────────────────────────────────────────
    upload_max_file_size_bytes: int = 100 * 1024 * 1024  # 上传文件大小上限（100MB）
    asset_store_backend: str = "filesystem"               # 资产存储后端: filesystem
    data_asset_store_binary_enabled: bool = True           # 是否启用二进制资产存储
    data_asset_binary_max_bytes: int = 1 * 1024 * 1024    # 单个二进制资产大小上限（1MB）

    # ── 数据目录路径配置 ────────────────────────────────────────────────────
    data_dir: Path = Field(default=PROJECT_ROOT / "data")                 # 数据根目录
    upload_dir: Path = Field(default=PROJECT_ROOT / "data" / "uploads")   # 上传文件目录
    parsed_dir: Path = Field(default=PROJECT_ROOT / "data" / "parsed")    # 解析结果目录
    chunk_dir: Path = Field(default=PROJECT_ROOT / "data" / "chunks")     # 文本块目录
    ocr_artifact_dir: Path = Field(default=PROJECT_ROOT / "data" / "ocr_artifacts")  # OCR 产物目录
    document_dir: Path = Field(default=PROJECT_ROOT / "data" / "documents")          # 文档目录
    job_dir: Path = Field(default=PROJECT_ROOT / "data" / "jobs")                    # 异步任务目录
    event_log_dir: Path = Field(default=PROJECT_ROOT / "data" / "event_logs")        # 事件日志目录
    # 以下目录默认为 None，由 Settings.derive_runtime_paths() 在运行时推导
    request_trace_dir: Path | None = Field(default=None)       # 请求追踪目录
    request_snapshot_dir: Path | None = Field(default=None)    # 请求快照目录
    rerank_canary_dir: Path | None = Field(default=None)       # 重排序金丝雀目录
    chat_memory_dir: Path | None = Field(default=None)         # 对话记忆目录
    system_config_path: Path = Field(default=PROJECT_ROOT / "data" / "system_config.json")  # 系统配置文件路径
    # ── SOP 相关目录 ────────────────────────────────────────────────────────
    sop_asset_dir: Path = Field(default=PROJECT_ROOT / "data" / "sop_assets")      # SOP 资产目录
    sop_record_dir: Path = Field(default=PROJECT_ROOT / "data" / "sops")           # SOP 记录目录
    sop_version_dir: Path = Field(default=PROJECT_ROOT / "data" / "sop_versions")  # SOP 版本目录
    # ── Bootstrap 初始化文件路径 ──────────────────────────────────────────────
    identity_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "identity_bootstrap.json")  # 身份数据初始化文件
    sop_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "sop_bootstrap.json")             # SOP 数据初始化文件
