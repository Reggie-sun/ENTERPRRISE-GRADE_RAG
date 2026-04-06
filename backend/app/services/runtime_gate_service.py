"""运行时并发门控服务模块。基于通道和用户粒度限制并发请求数量。"""
from dataclasses import dataclass
from functools import lru_cache
from threading import Condition
from time import monotonic
from typing import Literal

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..schemas.system_config import ConcurrencyControlsConfig
from .system_config_service import SystemConfigService, get_system_config_service

RuntimeGateChannel = Literal["chat_fast", "chat_accurate", "sop_generation"]
RuntimeGateBusyReason = Literal["channel_limit", "user_limit"]


@dataclass(frozen=True)
class RuntimeGateChannelState:
    channel: RuntimeGateChannel
    inflight: int
    limit: int
    available_slots: int


@dataclass(frozen=True)
class RuntimeGateSnapshot:
    acquire_timeout_ms: int
    busy_retry_after_seconds: int
    per_user_online_max_inflight: int
    active_users: int
    max_user_inflight: int
    channels: list[RuntimeGateChannelState]


class RuntimeGateLease:
    def __init__(self, service: "RuntimeGateService", channel: RuntimeGateChannel, owner_key: str | None = None) -> None:
        self._service = service
        self.channel: RuntimeGateChannel = channel
        self.owner_key = owner_key
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._service.release(self.channel, owner_key=self.owner_key)


class RuntimeGateBusyError(RuntimeError):
    def __init__(
        self,
        *,
        detail: str,
        channel: RuntimeGateChannel,
        reason: RuntimeGateBusyReason,
        retry_after_seconds: int,
        requested_mode: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.channel = channel
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        self.requested_mode = requested_mode

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=self.detail,
            headers={"Retry-After": str(self.retry_after_seconds)},
        )


class RuntimeGateService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        system_config_service: SystemConfigService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.system_config_service = system_config_service or get_system_config_service()
        self._condition = Condition()
        self._inflight: dict[RuntimeGateChannel, int] = {
            "chat_fast": 0,
            "chat_accurate": 0,
            "sop_generation": 0,
        }
        self._user_inflight: dict[str, int] = {}

    def acquire(self, channel: RuntimeGateChannel, *, timeout_ms: int | None = None) -> RuntimeGateLease | None:
        lease, _ = self.acquire_with_reason(channel, timeout_ms=timeout_ms)
        return lease

    def acquire_with_reason(
        self,
        channel: RuntimeGateChannel,
        *,
        timeout_ms: int | None = None,
        owner_key: str | None = None,
    ) -> tuple[RuntimeGateLease | None, RuntimeGateBusyReason | None]:
        deadline = None if timeout_ms is None else monotonic() + max(0, timeout_ms) / 1000
        with self._condition:
            while True:
                reject_reason = self._current_reject_reason(channel, owner_key=owner_key)
                if reject_reason is None:
                    self._inflight[channel] += 1
                    if owner_key is not None:
                        self._user_inflight[owner_key] = self._user_inflight.get(owner_key, 0) + 1
                    return RuntimeGateLease(self, channel, owner_key=owner_key), None
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None, reject_reason
                self._condition.wait(timeout=remaining)

    def release(self, channel: RuntimeGateChannel, *, owner_key: str | None = None) -> None:
        with self._condition:
            if self._inflight[channel] > 0:
                self._inflight[channel] -= 1
            if owner_key is not None and owner_key in self._user_inflight:
                current = self._user_inflight[owner_key] - 1
                if current > 0:
                    self._user_inflight[owner_key] = current
                else:
                    self._user_inflight.pop(owner_key, None)
            self._condition.notify_all()

    def get_snapshot(self) -> RuntimeGateSnapshot:
        controls = self.system_config_service.get_concurrency_controls()
        with self._condition:
            channels = [
                RuntimeGateChannelState(
                    channel=channel,
                    inflight=self._inflight[channel],
                    limit=self._limit_for(channel, controls=controls),
                    available_slots=max(0, self._limit_for(channel, controls=controls) - self._inflight[channel]),
                )
                for channel in ("chat_fast", "chat_accurate", "sop_generation")
            ]
        return RuntimeGateSnapshot(
            acquire_timeout_ms=controls.acquire_timeout_ms,
            busy_retry_after_seconds=controls.busy_retry_after_seconds,
            per_user_online_max_inflight=controls.per_user_online_max_inflight,
            active_users=len(self._user_inflight),
            max_user_inflight=max(self._user_inflight.values(), default=0),
            channels=channels,
        )

    def _current_reject_reason(
        self,
        channel: RuntimeGateChannel,
        *,
        owner_key: str | None = None,
    ) -> RuntimeGateBusyReason | None:
        if self._inflight[channel] >= self._limit_for(channel):
            return "channel_limit"
        if owner_key is not None and self._user_inflight.get(owner_key, 0) >= self._per_user_limit():
            return "user_limit"
        return None

    def _limit_for(
        self,
        channel: RuntimeGateChannel,
        *,
        controls: ConcurrencyControlsConfig | None = None,
    ) -> int:
        current_controls = controls or self.system_config_service.get_concurrency_controls()
        if channel == "chat_fast":
            return current_controls.fast_max_inflight
        if channel == "chat_accurate":
            return current_controls.accurate_max_inflight
        return current_controls.sop_generation_max_inflight

    def _per_user_limit(self, *, controls: ConcurrencyControlsConfig | None = None) -> int:
        current_controls = controls or self.system_config_service.get_concurrency_controls()
        return current_controls.per_user_online_max_inflight


@lru_cache
def get_runtime_gate_service() -> RuntimeGateService:
    return RuntimeGateService()
