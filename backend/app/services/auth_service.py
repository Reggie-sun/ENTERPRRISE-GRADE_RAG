"""认证服务模块。

提供用户密码校验、自定义 HMAC Token 签发/验证/吊销、权限上下文构造等功能。
v0.3 使用 base64+HMAC 格式（非标准 JWT），V1.1 将迁移到标准 JWT (HS256)。

核心类:
    AuthService — 最小鉴权服务，负责密码校验、Token 签发和权限上下文构造。

核心函数:
    get_current_auth_context — FastAPI 依赖注入：强制要求 Bearer Token
    get_optional_auth_context — FastAPI 依赖注入：Token 可选（兼容未登录场景）
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from functools import lru_cache
from secrets import token_bytes
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from ..core.config import Settings, get_settings
from ..schemas.auth import (
    AuthContext,
    AuthProfileResponse,
    AuthTokenPayload,
    IdentityUserRecord,
    LoginResponse,
)
from ..services.identity_service import IdentityService, get_identity_service
from .auth_runtime_store import AuthRuntimeStore

bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:  # v0.3 最小鉴权服务，负责密码校验、token 签发和权限上下文构造。
    """认证服务核心类。

    职责：
    - 密码哈希（PBKDF2-SHA256）与校验
    - 自定义 HMAC Token 签发、解码、吊销（v0.3 格式，V1.1 迁移到 JWT）
    - 构建权限上下文（AuthContext），供 API 层依赖注入使用
    - 查询用户档案（角色、部门、可访问部门范围）
    """
    def __init__(
        self,
        settings: Settings | None = None,
        identity_service: IdentityService | None = None,
        runtime_store: AuthRuntimeStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.identity_service = identity_service or get_identity_service()
        self.runtime_store = runtime_store or AuthRuntimeStore.from_settings(self.settings)

    @staticmethod
    def hash_password(
        password: str,
        *,
        iterations: int = 200_000,
        salt: bytes | None = None,
    ) -> str:
        resolved_salt = salt or token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), resolved_salt, iterations)
        return f"pbkdf2_sha256${iterations}${resolved_salt.hex()}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        try:
            algorithm, iteration_text, salt_hex, expected_digest_hex = stored_hash.split("$", 3)
        except ValueError:
            return False
        if algorithm != "pbkdf2_sha256" or not iteration_text.isdigit():
            return False

        derived_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iteration_text),
        )
        return hmac.compare_digest(derived_digest.hex(), expected_digest_hex)

    def login(self, username: str, password: str, *, client_ip: str | None = None) -> LoginResponse:
        normalized_username = username.strip()
        if not normalized_username or not password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        blocked_retry_after = self.runtime_store.get_login_block_retry_after(
            username=normalized_username,
            client_ip=client_ip,
        )
        if blocked_retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Retry later.",
                headers={"Retry-After": str(blocked_retry_after)},
            )

        try:
            user = self.identity_service.get_auth_user_by_username(normalized_username)
        except HTTPException as exc:
            self._register_failed_login(normalized_username, client_ip=client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Inactive user: {user.user_id}")
        if not self.verify_password(password, user.password_hash):
            self._register_failed_login(normalized_username, client_ip=client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        self.runtime_store.clear_login_failures(username=normalized_username, client_ip=client_ip)
        token, expires_in_seconds = self.issue_access_token(user)
        profile = self.build_profile(user)
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in_seconds=expires_in_seconds,
            user=profile.user,
            role=profile.role,
            department=profile.department,
            accessible_department_ids=profile.accessible_department_ids,
            department_query_isolation_enabled=profile.department_query_isolation_enabled,
        )

    def issue_access_token(self, user: IdentityUserRecord, *, expires_in_seconds: int | None = None) -> tuple[str, int]:
        now = int(datetime.now(UTC).timestamp())
        resolved_expires_in_seconds = expires_in_seconds or self.settings.auth_token_expire_minutes * 60
        payload = AuthTokenPayload(
            sub=user.user_id,
            tenant_id=user.tenant_id,
            department_id=user.department_id,
            role_id=user.role_id,
            iss=self.settings.auth_token_issuer,
            jti=uuid4().hex,
            iat=now,
            exp=now + resolved_expires_in_seconds,
        )
        return self._encode_token(payload), resolved_expires_in_seconds

    def build_auth_context(self, token: str) -> AuthContext:
        payload = self._decode_token(token)
        if self.runtime_store.is_token_revoked(payload.jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        current_timestamp = int(datetime.now(UTC).timestamp())
        if payload.iss != self.settings.auth_token_issuer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token issuer is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if payload.exp <= current_timestamp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = self.identity_service.get_auth_user(payload.sub)
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Inactive user: {user.user_id}")

        profile = self.build_profile(user)
        return AuthContext(
            token_id=payload.jti,
            issued_at=datetime.fromtimestamp(payload.iat, tz=UTC),
            expires_at=datetime.fromtimestamp(payload.exp, tz=UTC),
            user=profile.user,
            role=profile.role,
            department=profile.department,
            accessible_department_ids=profile.accessible_department_ids,
        )

    def revoke_token(self, token_id: str, *, expires_at: datetime) -> None:
        self.runtime_store.revoke_token(token_id, expires_at=expires_at)

    def build_profile(self, user: IdentityUserRecord) -> AuthProfileResponse:
        role = self.identity_service.get_role(user.role_id)
        department = self.identity_service.get_department(user.department_id)
        accessible_department_ids = (
            [item.department_id for item in self.identity_service.get_bootstrap().departments if item.is_active]
            if role.data_scope == "global"
            else [department.department_id]
        )
        return AuthProfileResponse(
            user=user.to_public_record(),
            role=role,
            department=department,
            accessible_department_ids=accessible_department_ids,
            department_query_isolation_enabled=self.settings.department_query_isolation_enabled,
        )

    def _encode_token(self, payload: AuthTokenPayload) -> str:
        # NOTE(v0.3): 自定义 base64+HMAC 格式，非标准 JWT。
        # V1.1 将迁移到标准 JWT (HS256)。详见 docs/AUTH_EVOLUTION.md。
        serialized = json.dumps(payload.model_dump(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.new(
            self.settings.auth_token_secret.encode("utf-8"),
            serialized,
            hashlib.sha256,
        ).digest()
        return f"{self._b64encode(serialized)}.{self._b64encode(signature)}"

    def _decode_token(self, token: str) -> AuthTokenPayload:
        parts = token.split(".", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token format is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        encoded_payload, encoded_signature = parts
        try:
            payload_bytes = self._b64decode(encoded_payload)
            provided_signature = self._b64decode(encoded_signature)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token encoding is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        expected_signature = hmac.new(
            self.settings.auth_token_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signature is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        try:
            return AuthTokenPayload.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is invalid.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def _register_failed_login(self, username: str, *, client_ip: str | None) -> None:
        blocked, retry_after = self.runtime_store.register_failed_login(
            username=username,
            client_ip=client_ip,
            max_attempts=self.settings.auth_login_max_attempts,
            window_seconds=self.settings.auth_login_window_seconds,
            block_seconds=self.settings.auth_login_block_seconds,
        )
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Retry later.",
                headers={"Retry-After": str(retry_after or self.settings.auth_login_block_seconds)},
            )

    @staticmethod
    def _b64encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    @staticmethod
    def _b64decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()


def get_current_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_service.build_auth_context(credentials.credentials)


def get_optional_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthContext | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_service.build_auth_context(credentials.credentials)
