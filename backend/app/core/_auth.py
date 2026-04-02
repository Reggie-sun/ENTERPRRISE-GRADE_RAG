"""认证配置：JWT Token 签发与校验。

本模块定义 Token 签名密钥、签发者标识和过期时间等认证相关参数。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field
from pydantic_settings import BaseSettings

DEFAULT_AUTH_TOKEN_SECRET = "local-dev-enterprise-rag-auth-secret"


class _AuthSettings(BaseSettings):
    """Auth settings mixin — 被 Settings 通过多继承组合。

    包含：Token 签名密钥、签发者名称、Token 默认过期时间。
    """

    auth_token_secret: str = DEFAULT_AUTH_TOKEN_SECRET              # JWT 签名密钥（生产环境应替换）
    auth_token_issuer: str = "enterprise-rag-api"                    # Token 签发者标识
    auth_token_expire_minutes: int = Field(default=60, ge=1)         # Token 过期时间（分钟）
    auth_runtime_store_url: str | None = None                        # 认证运行时共享存储；为空时优先复用 Redis broker。
    auth_login_max_attempts: int = Field(default=5, ge=1, le=20)     # 登录失败达到该次数后进入限流锁定。
    auth_login_window_seconds: int = Field(default=300, ge=30)       # 登录失败计数窗口（秒）。
    auth_login_block_seconds: int = Field(default=300, ge=30)        # 登录锁定时长（秒）。
    auth_identity_bootstrap_public_enabled: bool = False             # 是否允许匿名读取身份 bootstrap；生产默认关闭。
