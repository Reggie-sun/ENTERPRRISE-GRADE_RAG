from fastapi import APIRouter, Depends

from ....schemas.auth import (
    AuthContext,
    AuthProfileResponse,
    IdentityBootstrapResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserRecord,
)
from ....services.auth_service import AuthService, get_auth_service, get_current_auth_context
from ....services.identity_service import IdentityService, get_identity_service

router = APIRouter(prefix="/auth", tags=["auth"])  # 当前只暴露基础身份目录，为后续登录与权限上下文提供只读入口。


@router.post("/login", response_model=LoginResponse)  # 最小用户名密码登录接口，返回 bearer token 和权限上下文。
def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    return auth_service.login(payload.username, payload.password)


@router.post("/logout", response_model=LogoutResponse)  # 注销当前 token，后续权限上下文解析会拒绝该 token。
def logout(
    auth_context: AuthContext = Depends(get_current_auth_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    auth_service.revoke_token(auth_context.token_id)
    return LogoutResponse()


@router.get("/me", response_model=AuthProfileResponse)  # 返回当前登录用户的最小权限上下文。
def get_current_user(
    auth_context: AuthContext = Depends(get_current_auth_context),
) -> AuthProfileResponse:
    return AuthProfileResponse(
        user=auth_context.user,
        role=auth_context.role,
        department=auth_context.department,
        accessible_department_ids=auth_context.accessible_department_ids,
        department_query_isolation_enabled=auth_context.department_query_isolation_enabled,
    )


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
