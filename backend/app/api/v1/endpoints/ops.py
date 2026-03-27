from fastapi import APIRouter, Depends

from ....schemas.auth import AuthContext
from ....schemas.ops import OpsSummaryResponse
from ....services.auth_service import get_current_auth_context
from ....services.ops_service import OpsService, get_ops_service

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get(
    "/summary",
    response_model=OpsSummaryResponse,
    summary="Get runtime operations summary",
    description="Returns a lightweight runtime summary for workspace operators, including health, queue backlog, recent failures/degrades, and effective model/degrade/retry configuration.",
)
def get_ops_summary(
    auth_context: AuthContext = Depends(get_current_auth_context),
    ops_service: OpsService = Depends(get_ops_service),
) -> OpsSummaryResponse:
    return ops_service.get_summary(auth_context=auth_context)
