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

bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:  # v0.3 最小鉴权服务，负责密码校验、token 签发和权限上下文构造。
    def __init__(
        self,
        settings: Settings | None = None,
        identity_service: IdentityService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.identity_service = identity_service or get_identity_service()
        self.revoked_token_ids: set[str] = set()

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

    def login(self, username: str, password: str) -> LoginResponse:
        normalized_username = username.strip()
        if not normalized_username or not password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            user = self.identity_service.get_auth_user_by_username(normalized_username)
        except HTTPException as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Inactive user: {user.user_id}")
        if not self.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

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
        if payload.jti in self.revoked_token_ids:
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

    def revoke_token(self, token_id: str) -> None:
        self.revoked_token_ids.add(token_id.strip())

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
        )

    def _encode_token(self, payload: AuthTokenPayload) -> str:
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
