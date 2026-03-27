from fastapi import APIRouter, Depends, Query

from ....schemas.auth import AuthContext
from ....schemas.request_trace import RequestTraceListResponse, RequestTraceQueryFilters
from ....services.auth_service import get_current_auth_context
from ....services.request_trace_service import RequestTraceService, get_request_trace_service

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get(
    "",
    response_model=RequestTraceListResponse,
    summary="List request traces",
    description="Returns lightweight request traces for chat and future RAG stages. Employees are denied; department admins are scoped to their departments.",
)
def list_request_traces(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    action: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    username: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    auth_context: AuthContext = Depends(get_current_auth_context),
    request_trace_service: RequestTraceService = Depends(get_request_trace_service),
) -> RequestTraceListResponse:
    filters = RequestTraceQueryFilters.model_validate(
        {
            "category": category,
            "action": action,
            "outcome": outcome,
            "username": username,
            "user_id": user_id,
            "department_id": department_id,
            "trace_id": trace_id,
            "request_id": request_id,
            "target_id": target_id,
            "date_from": date_from,
            "date_to": date_to,
        }
    )
    return request_trace_service.list_traces(
        page=page,
        page_size=page_size,
        filters=filters,
        auth_context=auth_context,
    )
