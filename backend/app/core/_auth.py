"""认证配置：JWT Token 签发与校验。

本模块定义 Token 签名密钥、签发者标识和过期时间等认证相关参数。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class _AuthSettings(BaseSettings):
    """Auth settings mixin — 被 Settings 通过多继承组合。

    包含：Token 签名密钥、签发者名称、Token 默认过期时间。
    """

    auth_token_secret: str = "local-dev-enterprise-rag-auth-secret"  # JWT 签名密钥（生产环境应替换）
    auth_token_issuer: str = "enterprise-rag-api"                    # Token 签发者标识
    auth_token_expire_minutes: int = Field(default=60, ge=1)         # Token 过期时间（分钟）
