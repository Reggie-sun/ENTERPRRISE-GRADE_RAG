"""认证运行时共享存储。

负责：
- token 吊销状态共享
- 登录失败计数与限流锁

优先复用 Redis；本地/测试环境下在非 Redis broker 时回退到进程内内存实现。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from threading import Lock
from urllib.parse import urlparse

from redis import Redis

from ..core.config import Settings


class AuthRuntimeStore:
    def is_token_revoked(self, token_id: str) -> bool:
        raise NotImplementedError

    def revoke_token(self, token_id: str, *, expires_at: datetime) -> None:
        raise NotImplementedError

    def get_login_block_retry_after(self, *, username: str, client_ip: str | None) -> int | None:
        raise NotImplementedError

    def register_failed_login(
        self,
        *,
        username: str,
        client_ip: str | None,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int,
    ) -> tuple[bool, int | None]:
        raise NotImplementedError

    def clear_login_failures(self, *, username: str, client_ip: str | None) -> None:
        raise NotImplementedError

    @staticmethod
    def from_settings(settings: Settings) -> AuthRuntimeStore:
        runtime_store_url = (settings.auth_runtime_store_url or settings.celery_broker_url or "").strip()
        if urlparse(runtime_store_url).scheme in {"redis", "rediss"}:
            return RedisBackedAuthRuntimeStore(runtime_store_url)
        return InMemoryAuthRuntimeStore()


class InMemoryAuthRuntimeStore(AuthRuntimeStore):
    def __init__(self) -> None:
        self._lock = Lock()
        self._revoked_tokens: dict[str, datetime] = {}
        self._login_failures: dict[str, tuple[int, datetime]] = {}
        self._login_blocks: dict[str, datetime] = {}

    def is_token_revoked(self, token_id: str) -> bool:
        now = datetime.now(UTC)
        with self._lock:
            self._purge_expired(now)
            return token_id in self._revoked_tokens

    def revoke_token(self, token_id: str, *, expires_at: datetime) -> None:
        normalized_token_id = token_id.strip()
        if not normalized_token_id:
            return
        resolved_expiry = _normalize_expiry(expires_at)
        now = datetime.now(UTC)
        if resolved_expiry <= now:
            return
        with self._lock:
            self._purge_expired(now)
            self._revoked_tokens[normalized_token_id] = resolved_expiry

    def get_login_block_retry_after(self, *, username: str, client_ip: str | None) -> int | None:
        now = datetime.now(UTC)
        key = _login_scope_key(username=username, client_ip=client_ip)
        with self._lock:
            self._purge_expired(now)
            expires_at = self._login_blocks.get(key)
            if expires_at is None:
                return None
            return max(1, int((expires_at - now).total_seconds()))

    def register_failed_login(
        self,
        *,
        username: str,
        client_ip: str | None,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int,
    ) -> tuple[bool, int | None]:
        now = datetime.now(UTC)
        key = _login_scope_key(username=username, client_ip=client_ip)
        with self._lock:
            self._purge_expired(now)
            blocked_until = self._login_blocks.get(key)
            if blocked_until is not None:
                return True, max(1, int((blocked_until - now).total_seconds()))

            failure_count, expires_at = self._login_failures.get(key, (0, now))
            if expires_at <= now:
                failure_count = 0
            failure_count += 1
            self._login_failures[key] = (failure_count, now + _seconds(window_seconds))
            if failure_count >= max_attempts:
                blocked_until = now + _seconds(block_seconds)
                self._login_blocks[key] = blocked_until
                self._login_failures.pop(key, None)
                return True, block_seconds
            return False, None

    def clear_login_failures(self, *, username: str, client_ip: str | None) -> None:
        key = _login_scope_key(username=username, client_ip=client_ip)
        with self._lock:
            self._login_failures.pop(key, None)
            self._login_blocks.pop(key, None)

    def _purge_expired(self, now: datetime) -> None:
        self._revoked_tokens = {
            key: expires_at
            for key, expires_at in self._revoked_tokens.items()
            if expires_at > now
        }
        self._login_failures = {
            key: (count, expires_at)
            for key, (count, expires_at) in self._login_failures.items()
            if expires_at > now
        }
        self._login_blocks = {
            key: expires_at
            for key, expires_at in self._login_blocks.items()
            if expires_at > now
        }


class RedisBackedAuthRuntimeStore(AuthRuntimeStore):
    def __init__(self, redis_url: str) -> None:
        self._client = Redis.from_url(
            redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            retry_on_timeout=False,
            decode_responses=True,
        )
        self._fallback = InMemoryAuthRuntimeStore()

    def is_token_revoked(self, token_id: str) -> bool:
        normalized_token_id = token_id.strip()
        if not normalized_token_id:
            return False
        try:
            return bool(self._client.exists(_revoked_token_key(normalized_token_id)))
        except Exception:
            return self._fallback.is_token_revoked(normalized_token_id)

    def revoke_token(self, token_id: str, *, expires_at: datetime) -> None:
        normalized_token_id = token_id.strip()
        if not normalized_token_id:
            return
        resolved_expiry = _normalize_expiry(expires_at)
        ttl_seconds = max(0, int((resolved_expiry - datetime.now(UTC)).total_seconds()))
        if ttl_seconds <= 0:
            return
        try:
            self._client.set(_revoked_token_key(normalized_token_id), "1", ex=ttl_seconds)
        except Exception:
            self._fallback.revoke_token(normalized_token_id, expires_at=resolved_expiry)

    def get_login_block_retry_after(self, *, username: str, client_ip: str | None) -> int | None:
        block_key = _login_block_key(username=username, client_ip=client_ip)
        try:
            ttl = self._client.ttl(block_key)
        except Exception:
            return self._fallback.get_login_block_retry_after(username=username, client_ip=client_ip)
        if ttl is None or ttl < 0:
            return None
        return max(1, int(ttl))

    def register_failed_login(
        self,
        *,
        username: str,
        client_ip: str | None,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int,
    ) -> tuple[bool, int | None]:
        failure_key = _login_failure_key(username=username, client_ip=client_ip)
        block_key = _login_block_key(username=username, client_ip=client_ip)
        try:
            ttl = self._client.ttl(block_key)
            if ttl is not None and ttl > 0:
                return True, max(1, int(ttl))

            failure_count = int(self._client.incr(failure_key))
            if failure_count == 1:
                self._client.expire(failure_key, window_seconds)
            if failure_count >= max_attempts:
                self._client.set(block_key, "1", ex=block_seconds)
                self._client.delete(failure_key)
                return True, block_seconds
            return False, None
        except Exception:
            return self._fallback.register_failed_login(
                username=username,
                client_ip=client_ip,
                max_attempts=max_attempts,
                window_seconds=window_seconds,
                block_seconds=block_seconds,
            )

    def clear_login_failures(self, *, username: str, client_ip: str | None) -> None:
        failure_key = _login_failure_key(username=username, client_ip=client_ip)
        block_key = _login_block_key(username=username, client_ip=client_ip)
        try:
            self._client.delete(failure_key, block_key)
        except Exception:
            self._fallback.clear_login_failures(username=username, client_ip=client_ip)


def _revoked_token_key(token_id: str) -> str:
    return f"auth:revoked:{token_id}"


def _login_failure_key(*, username: str, client_ip: str | None) -> str:
    return f"auth:login:fail:{_login_scope_key(username=username, client_ip=client_ip)}"


def _login_block_key(*, username: str, client_ip: str | None) -> str:
    return f"auth:login:block:{_login_scope_key(username=username, client_ip=client_ip)}"


def _login_scope_key(*, username: str, client_ip: str | None) -> str:
    normalized_username = username.strip().lower()
    normalized_ip = (client_ip or "unknown").strip() or "unknown"
    digest = hashlib.sha256(f"{normalized_username}|{normalized_ip}".encode("utf-8")).hexdigest()
    return digest


def _normalize_expiry(expires_at: datetime) -> datetime:
    return expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)


def _seconds(value: int) -> timedelta:
    return timedelta(seconds=value)
