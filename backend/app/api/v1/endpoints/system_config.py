from fastapi import APIRouter, Depends

from ....schemas.auth import AuthContext
from ....schemas.system_config import SystemConfigResponse, SystemConfigUpdateRequest
from ....services.auth_service import get_current_auth_context
from ....services.system_config_service import SystemConfigService, get_system_config_service

router = APIRouter(
    prefix="/system-config",
    tags=["system-config"],
)  # v0.6 起提供最小系统配置接口，先承接 fast/accurate 查询档位。


@router.get(
    "",
    response_model=SystemConfigResponse,
    summary="Get system configuration",
    description="Returns the effective query profile, model routing, degrade, and retry configuration for sys_admin users.",
)
def get_system_config(
    auth_context: AuthContext = Depends(get_current_auth_context),
    system_config_service: SystemConfigService = Depends(get_system_config_service),
) -> SystemConfigResponse:
    return system_config_service.get_config(auth_context=auth_context)


@router.put(
    "",
    response_model=SystemConfigResponse,
    summary="Update system configuration",
    description="Updates the effective query profile, model routing, degrade, and retry configuration for sys_admin users.",
)
def update_system_config(
    payload: SystemConfigUpdateRequest,
    auth_context: AuthContext = Depends(get_current_auth_context),
    system_config_service: SystemConfigService = Depends(get_system_config_service),
) -> SystemConfigResponse:
    return system_config_service.update_config(payload, auth_context=auth_context)
