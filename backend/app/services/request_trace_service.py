from datetime import datetime, timezone
from functools import lru_cache

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..db.request_trace_repository import FilesystemRequestTraceRepository, RequestTraceRepository
from ..schemas.auth import AuthContext
from ..schemas.event_log import EventLogActor, EventLogCategory, EventLogOutcome
from ..schemas.request_trace import (
    RequestTraceListResponse,
    RequestTraceQueryFilters,
    RequestTraceRecord,
    RequestTraceStage,
)


class RequestTraceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: RequestTraceRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or FilesystemRequestTraceRepository(self.settings.request_trace_dir)

    def record(
        self,
        *,
        trace_id: str,
        request_id: str,
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
        total_duration_ms: int | None = None,
        timeout_flag: bool = False,
        downgraded_from: str | None = None,
        response_mode: str | None = None,
        error_message: str | None = None,
        stages: list[RequestTraceStage] | None = None,
        details: dict[str, object] | None = None,
    ) -> RequestTraceRecord:
        record = RequestTraceRecord(
            trace_id=trace_id,
            request_id=request_id,
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
            total_duration_ms=total_duration_ms,
            timeout_flag=timeout_flag,
            downgraded_from=downgraded_from,
            response_mode=response_mode,
            error_message=error_message,
            stages=stages or [],
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
        auth_context: AuthContext,
        category: EventLogCategory | None = None,
        limit: int = 20,
    ) -> list[RequestTraceRecord]:
        records = self.repository.list_records(category=category, limit=limit)
        return self._filter_records_by_scope(records=records, auth_context=auth_context)

    def list_traces(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: RequestTraceQueryFilters | None = None,
        auth_context: AuthContext,
    ) -> RequestTraceListResponse:
        resolved_filters = filters or RequestTraceQueryFilters()
        self._validate_trace_access(auth_context=auth_context, department_id=resolved_filters.department_id)
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
            trace_id=resolved_filters.trace_id,
            request_id=resolved_filters.request_id,
            target_id=resolved_filters.target_id,
            date_from=resolved_filters.date_from,
            date_to=resolved_filters.date_to,
            limit=None,
        )
        scoped_records = self._filter_records_by_scope(records=records, auth_context=auth_context)
        start = (page - 1) * page_size
        end = start + page_size
        return RequestTraceListResponse(
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
    def _validate_trace_access(*, auth_context: AuthContext, department_id: str | None) -> None:
        if auth_context.user.role_id == "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to request traces.",
            )
        if department_id is not None and department_id not in auth_context.accessible_department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested department.",
            )

    @staticmethod
    def _filter_records_by_scope(
        *,
        records: list[RequestTraceRecord],
        auth_context: AuthContext,
    ) -> list[RequestTraceRecord]:
        if auth_context.role.data_scope == "global":
            return records
        allowed_departments = set(auth_context.accessible_department_ids)
        return [record for record in records if record.actor.department_id in allowed_departments]


@lru_cache
def get_request_trace_service() -> RequestTraceService:
    return RequestTraceService()
