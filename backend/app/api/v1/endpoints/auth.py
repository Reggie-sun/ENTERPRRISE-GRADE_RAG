from fastapi import APIRouter, Depends

from ....schemas.auth import IdentityBootstrapResponse, UserRecord
from ....services.identity_service import IdentityService, get_identity_service

router = APIRouter(prefix="/auth", tags=["auth"])  # 当前只暴露基础身份目录，为后续登录与权限上下文提供只读入口。


@router.get("/bootstrap", response_model=IdentityBootstrapResponse)  # 返回最小用户/部门/角色目录，便于后续登录页和权限开发联调。
def get_auth_bootstrap(
    identity_service: IdentityService = Depends(get_identity_service),
) -> IdentityBootstrapResponse:
    return identity_service.get_bootstrap()


@router.get("/users/{user_id}", response_model=UserRecord)  # 读取单个用户基础信息，后续登录成功后的“当前用户信息”接口可直接复用。
def get_user(
    user_id: str,
    identity_service: IdentityService = Depends(get_identity_service),
) -> UserRecord:
    return identity_service.get_user(user_id)
