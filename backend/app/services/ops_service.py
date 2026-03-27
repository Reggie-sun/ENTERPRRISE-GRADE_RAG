from datetime import UTC, datetime
from functools import lru_cache
from math import ceil
from typing import Callable
from urllib.parse import urlparse

from fastapi import HTTPException, status
from redis import Redis

from ..core.config import Settings, get_settings
from ..schemas.auth import AuthContext
from ..schemas.event_log import EventLogCategory, EventLogRecord
from ..schemas.ops import (
    OpsCategorySummary,
    OpsQueueSummary,
    OpsRecentWindowSummary,
    OpsSummaryResponse,
)
from .event_log_service import EventLogService
from .health_service import HealthService
from .system_config_service import SystemConfigService


class OpsService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        health_service: HealthService | None = None,
        event_log_service: EventLogService | None = None,
        system_config_service: SystemConfigService | None = None,
        queue_probe: Callable[[], OpsQueueSummary] | None = None,
        recent_window_size: int = 200,
    ) -> None:
        self.settings = settings or get_settings()
        self.health_service = health_service or HealthService(self.settings)
        self.event_log_service = event_log_service or EventLogService(self.settings)
        self.system_config_service = system_config_service or SystemConfigService(self.settings)
        self.queue_probe = queue_probe or self._probe_queue
        self.recent_window_size = recent_window_size

    def get_summary(self, *, auth_context: AuthContext) -> OpsSummaryResponse:
        self._ensure_workspace_access(auth_context)
        records = self._filter_records_by_scope(
            records=self.event_log_service.list_recent(limit=self.recent_window_size),
            auth_context=auth_context,
        )
        return OpsSummaryResponse(
            checked_at=datetime.now(UTC),
            health=self.health_service.get_snapshot(),
            queue=self.queue_probe(),
            recent_window=self._build_recent_window(records),
            categories=self._build_category_summaries(records),
            recent_failures=[record for record in records if record.outcome == "failed"][:5],
            recent_degraded=[record for record in records if record.downgraded_from][:5],
            config=self.system_config_service.get_effective_config(),
        )

    @staticmethod
    def _ensure_workspace_access(auth_context: AuthContext) -> None:
        if auth_context.user.role_id == "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to runtime operations.",
            )

    @staticmethod
    def _filter_records_by_scope(
        *,
        records: list[EventLogRecord],
        auth_context: AuthContext,
    ) -> list[EventLogRecord]:
        if auth_context.role.data_scope == "global":
            return records
        allowed_departments = set(auth_context.accessible_department_ids)
        return [record for record in records if record.actor.department_id in allowed_departments]

    def _probe_queue(self) -> OpsQueueSummary:
        broker_url = self.settings.celery_broker_url
        parsed = urlparse(broker_url)
        if parsed.scheme not in {"redis", "rediss"}:
            return OpsQueueSummary(
                available=False,
                ingest_queue=self.settings.celery_ingest_queue,
                error="Only redis-backed queue backlog probing is supported.",
            )

        try:
            client = Redis.from_url(
                broker_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
            )
            client.ping()
            backlog = int(client.llen(self.settings.celery_ingest_queue))
            return OpsQueueSummary(
                available=True,
                ingest_queue=self.settings.celery_ingest_queue,
                backlog=backlog,
            )
        except Exception as exc:
            return OpsQueueSummary(
                available=False,
                ingest_queue=self.settings.celery_ingest_queue,
                error=str(exc),
            )

    @staticmethod
    def _build_recent_window(records: list[EventLogRecord]) -> OpsRecentWindowSummary:
        durations = sorted(record.duration_ms for record in records if record.duration_ms is not None)
        return OpsRecentWindowSummary(
            sample_size=len(records),
            failed_count=sum(1 for record in records if record.outcome == "failed"),
            timeout_count=sum(1 for record in records if record.timeout_flag),
            downgraded_count=sum(1 for record in records if record.downgraded_from),
            duration_count=len(durations),
            duration_p50_ms=OpsService._percentile(durations, 50),
            duration_p95_ms=OpsService._percentile(durations, 95),
            duration_p99_ms=OpsService._percentile(durations, 99),
        )

    @staticmethod
    def _build_category_summaries(records: list[EventLogRecord]) -> list[OpsCategorySummary]:
        categories: tuple[EventLogCategory, ...] = ("chat", "document", "sop_generation")
        summaries: list[OpsCategorySummary] = []
        for category in categories:
            category_records = [record for record in records if record.category == category]
            failed_records = [record for record in category_records if record.outcome == "failed"]
            summaries.append(
                OpsCategorySummary(
                    category=category,
                    total=len(category_records),
                    failed_count=len(failed_records),
                    timeout_count=sum(1 for record in category_records if record.timeout_flag),
                    downgraded_count=sum(1 for record in category_records if record.downgraded_from),
                    last_event_at=category_records[0].occurred_at if category_records else None,
                    last_failed_at=failed_records[0].occurred_at if failed_records else None,
                )
            )
        return summaries

    @staticmethod
    def _percentile(values: list[int], percentile: int) -> int | None:
        if not values:
            return None
        rank = max(0, ceil((percentile / 100) * len(values)) - 1)
        return values[min(rank, len(values) - 1)]


@lru_cache
def get_ops_service() -> OpsService:
    return OpsService()
