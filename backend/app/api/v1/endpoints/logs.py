"""事件日志查询接口模块。提供日志列表和筛选能力，用于审计和排障。"""

from datetime import date

from fastapi import APIRouter, Depends, Query

from ....schemas.auth import AuthContext
from ....schemas.event_log import EventLogCategory, EventLogListResponse, EventLogOutcome, EventLogQueryFilters
from ....services.auth_service import get_current_auth_context
from ....services.event_log_service import EventLogService, get_event_log_service

router = APIRouter(prefix="/logs", tags=["logs"])  # v0.6 起提供最小事件日志查询接口，给日志页与排障入口复用。


@router.get(
    "",
    response_model=EventLogListResponse,
    summary="List event logs",
    description="Returns paginated event logs with date/user/action filters and department-scope permission enforcement.",
)
def list_event_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: EventLogCategory | None = Query(default=None),
    action: str | None = Query(default=None),
    outcome: EventLogOutcome | None = Query(default=None),
    username: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    rerank_strategy: str | None = Query(default=None),
    rerank_provider: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_context: AuthContext = Depends(get_current_auth_context),
    event_log_service: EventLogService = Depends(get_event_log_service),
) -> EventLogListResponse:
    return event_log_service.list_logs(
        page=page,
        page_size=page_size,
        filters=EventLogQueryFilters(
            category=category,
            action=action,
            outcome=outcome,
            username=username,
            user_id=user_id,
            department_id=department_id,
            target_id=target_id,
            rerank_strategy=rerank_strategy,
            rerank_provider=rerank_provider,
            date_from=date_from,
            date_to=date_to,
        ),
        auth_context=auth_context,
    )
