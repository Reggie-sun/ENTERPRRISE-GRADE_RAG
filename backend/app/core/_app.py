"""应用级别配置：应用名称、环境、调试、CORS、Celery/Ingest。

本模块定义应用运行时的基础配置，包括应用标识、跨域策略、异步任务队列等。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class _AppSettings(BaseSettings):
    """App-level settings mixin — 被 Settings 通过多继承组合。

    包含：应用基本信息、CORS 跨域配置、Celery 异步任务队列配置、文档摄取重试策略、部门查询隔离开关。
    """

    # ── 应用基本信息 ──────────────────────────────────────────────────────
    app_name: str = "Enterprise-grade RAG API"
    app_env: str = "development"                   # 运行环境: development / staging / production
    debug: bool = True                             # 调试模式开关
    api_v1_prefix: str = "/api/v1"                 # API v1 路径前缀
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])  # 允许的跨域来源列表

    # ── Celery 异步任务队列配置 ────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/0"       # 消息代理地址
    celery_result_backend: str = "redis://localhost:6379/1"   # 任务结果存储地址
    celery_ingest_queue: str = "ingest"                       # 文档摄取队列名称
    celery_task_always_eager: bool = False                    # 为 True 时任务同步执行（调试用）
    celery_task_eager_propagates: bool = True                 # 同步模式下异常是否向上传播
    libreoffice_binary: str | None = None                     # 旧版 .doc 解析器显式二进制路径覆写。
    ingest_failure_retry_limit: int = Field(default=3, ge=1)          # 摄取失败最大重试次数
    ingest_retry_delay_seconds: int = Field(default=2, ge=0)          # 重试间隔（秒）
    ingest_inflight_stale_seconds: int = Field(default=30 * 60, ge=1) # 进行中任务超时判定时间（30分钟）

    # ── 部门数据隔离 ──────────────────────────────────────────────────────
    department_query_isolation_enabled: bool = True  # 启用后，查询将按部门隔离数据

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """将逗号分隔的 CORS 字符串拆分为列表。支持环境变量传入 "a,b,c" 格式。"""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
