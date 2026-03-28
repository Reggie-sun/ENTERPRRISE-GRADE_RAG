from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..db.event_log_repository import EventLogRepository, FilesystemEventLogRepository
from ..schemas.auth import AuthContext
from ..schemas.event_log import (
    EventLogActor,
    EventLogCategory,
    EventLogListResponse,
    EventLogOutcome,
    EventLogQueryFilters,
    EventLogRecord,
)


class EventLogService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: EventLogRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or FilesystemEventLogRepository(self.settings.event_log_dir)

    def record(
        self,
        *,
        category: EventLogCategory,
        action: str,
        outcome: EventLogOutcome,
        auth_context: AuthContext | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        mode: str | None = None,
        top_k: int | None = None,
        candidate_top_k: int | None = None,
        rerank_top_n: int | None = None,
        rerank_strategy: str | None = None,
        rerank_provider: str | None = None,
        rerank_model: str | None = None,
        duration_ms: int | None = None,
        timeout_flag: bool = False,
        downgraded_from: str | None = None,
        details: dict[str, object] | None = None,
    ) -> EventLogRecord:
        record = EventLogRecord(
            event_id=f"evt_{uuid4().hex[:16]}",
            category=category,
            action=action,
            outcome=outcome,
            occurred_at=datetime.now(timezone.utc),
            actor=self._build_actor(auth_context),
            target_type=target_type,
            target_id=target_id,
            mode=mode,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            rerank_top_n=rerank_top_n,
            rerank_strategy=rerank_strategy,
            rerank_provider=rerank_provider,
            rerank_model=rerank_model,
            duration_ms=duration_ms,
            timeout_flag=timeout_flag,
            downgraded_from=downgraded_from,
            details=details or {},
        )
        try:
            self.repository.append(record)
        except Exception:
            return record
        return record

    def list_recent(
        self,
        *,
        category: EventLogCategory | None = None,
        limit: int = 100,
    ) -> list[EventLogRecord]:
        return self.repository.list_records(category=category, limit=limit)

    def list_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: EventLogQueryFilters | None = None,
        auth_context: AuthContext,
    ) -> EventLogListResponse:
        resolved_filters = filters or EventLogQueryFilters()
        self._validate_log_access(auth_context=auth_context, department_id=resolved_filters.department_id)
        if (
            resolved_filters.date_from is not None
            and resolved_filters.date_to is not None
            and resolved_filters.date_to < resolved_filters.date_from
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_to must be greater than or equal to date_from.",
            )

        records = self.repository.list_records(
            category=resolved_filters.category,
            action=resolved_filters.action,
            outcome=resolved_filters.outcome,
            username=resolved_filters.username,
            user_id=resolved_filters.user_id,
            department_id=resolved_filters.department_id,
            target_id=resolved_filters.target_id,
            rerank_strategy=resolved_filters.rerank_strategy,
            rerank_provider=resolved_filters.rerank_provider,
            date_from=resolved_filters.date_from,
            date_to=resolved_filters.date_to,
            limit=None,
        )
        scoped_records = self._filter_records_by_scope(records=records, auth_context=auth_context)
        start = (page - 1) * page_size
        end = start + page_size
        return EventLogListResponse(
            items=scoped_records[start:end],
            total=len(scoped_records),
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _build_actor(auth_context: AuthContext | None) -> EventLogActor:
        user = getattr(auth_context, "user", None)
        if auth_context is None or user is None:
            return EventLogActor()
        return EventLogActor(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            username=user.username,
            role_id=user.role_id,
            department_id=user.department_id,
        )

    @staticmethod
    def _validate_log_access(*, auth_context: AuthContext, department_id: str | None) -> None:
        if auth_context.user.role_id == "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to audit logs.",
            )
        if department_id is not None and department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested department.",
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


@lru_cache
def get_event_log_service() -> EventLogService:
    return EventLogService()
