"""请求快照接口模块。提供请求快照查询和回放能力。"""
from fastapi import APIRouter, Depends, Path, Query

from ....schemas.auth import AuthContext
from ....schemas.request_snapshot import (
    RequestSnapshotListResponse,
    RequestSnapshotQueryFilters,
    RequestSnapshotRecord,
    RequestSnapshotReplayRequest,
    RequestSnapshotReplayResponse,
)
from ....services.auth_service import get_current_auth_context
from ....services.chat_service import ChatService, get_chat_service
from ....services.request_snapshot_service import RequestSnapshotService, get_request_snapshot_service
from ....services.retrieval_service import RetrievalService, get_retrieval_service
from ....services.sop_generation_service import SopGenerationService, get_sop_generation_service

router = APIRouter(prefix="/request-snapshots", tags=["request-snapshots"])


@router.get(
    "",
    response_model=RequestSnapshotListResponse,
    summary="List request snapshots",
    description="Returns replayable request snapshots for chat and SOP generation. Employees are denied; department admins are scoped to their departments.",
)
def list_request_snapshots(
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
    snapshot_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    auth_context: AuthContext = Depends(get_current_auth_context),
    request_snapshot_service: RequestSnapshotService = Depends(get_request_snapshot_service),
) -> RequestSnapshotListResponse:
    filters = RequestSnapshotQueryFilters.model_validate(
        {
            "category": category,
            "action": action,
            "outcome": outcome,
            "username": username,
            "user_id": user_id,
            "department_id": department_id,
            "trace_id": trace_id,
            "request_id": request_id,
            "snapshot_id": snapshot_id,
            "target_id": target_id,
            "date_from": date_from,
            "date_to": date_to,
        }
    )
    return request_snapshot_service.list_snapshots(
        page=page,
        page_size=page_size,
        filters=filters,
        auth_context=auth_context,
    )


@router.get(
    "/{snapshot_id}",
    response_model=RequestSnapshotRecord,
    summary="Get request snapshot detail",
    description="Returns the persisted request snapshot payload for replay and diagnosis.",
)
def get_request_snapshot(
    snapshot_id: str = Path(min_length=1, max_length=64),
    auth_context: AuthContext = Depends(get_current_auth_context),
    request_snapshot_service: RequestSnapshotService = Depends(get_request_snapshot_service),
) -> RequestSnapshotRecord:
    return request_snapshot_service.get_snapshot(snapshot_id, auth_context=auth_context)


@router.post(
    "/{snapshot_id}/replay",
    response_model=RequestSnapshotReplayResponse,
    summary="Replay request snapshot",
    description="Replays a chat or SOP-generation snapshot either with original effective parameters or current request defaults/configuration.",
)
def replay_request_snapshot(
    payload: RequestSnapshotReplayRequest,
    snapshot_id: str = Path(min_length=1, max_length=64),
    auth_context: AuthContext = Depends(get_current_auth_context),
    request_snapshot_service: RequestSnapshotService = Depends(get_request_snapshot_service),
    chat_service: ChatService = Depends(get_chat_service),
    sop_generation_service: SopGenerationService = Depends(get_sop_generation_service),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
) -> RequestSnapshotReplayResponse:
    return request_snapshot_service.replay_snapshot(
        snapshot_id=snapshot_id,
        replay_mode=payload.replay_mode,
        auth_context=auth_context,
        chat_service=chat_service,
        sop_generation_service=sop_generation_service,
        retrieval_service=retrieval_service,
    )
