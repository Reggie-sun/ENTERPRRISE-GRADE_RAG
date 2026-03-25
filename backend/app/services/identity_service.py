import json
from functools import lru_cache

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..schemas.auth import IdentityBootstrapData, IdentityBootstrapResponse, UserRecord

DEFAULT_IDENTITY_BOOTSTRAP = {
    "roles": [
        {
            "role_id": "employee",
            "name": "Employee",
            "description": "Can search and view content within the assigned department scope.",
            "data_scope": "department",
            "is_admin": False,
        },
        {
            "role_id": "department_admin",
            "name": "Department Admin",
            "description": "Can manage documents and SOP assets within the assigned department.",
            "data_scope": "department",
            "is_admin": True,
        },
        {
            "role_id": "sys_admin",
            "name": "System Admin",
            "description": "Can access all departments and system management capabilities.",
            "data_scope": "global",
            "is_admin": True,
        },
    ],
    "departments": [
        {
            "department_id": "dept_ops",
            "tenant_id": "wl",
            "department_name": "Operations",
            "parent_department_id": None,
            "is_active": True,
        },
        {
            "department_id": "dept_after_sales",
            "tenant_id": "wl",
            "department_name": "After Sales",
            "parent_department_id": "dept_ops",
            "is_active": True,
        },
        {
            "department_id": "dept_production",
            "tenant_id": "wl",
            "department_name": "Production",
            "parent_department_id": "dept_ops",
            "is_active": True,
        },
    ],
    "users": [
        {
            "user_id": "user_employee_demo",
            "tenant_id": "wl",
            "username": "employee.demo",
            "display_name": "Employee Demo",
            "department_id": "dept_after_sales",
            "role_id": "employee",
            "is_active": True,
        },
        {
            "user_id": "user_department_admin_demo",
            "tenant_id": "wl",
            "username": "department.admin.demo",
            "display_name": "Department Admin Demo",
            "department_id": "dept_after_sales",
            "role_id": "department_admin",
            "is_active": True,
        },
        {
            "user_id": "user_sys_admin_demo",
            "tenant_id": "wl",
            "username": "sys.admin.demo",
            "display_name": "System Admin Demo",
            "department_id": "dept_ops",
            "role_id": "sys_admin",
            "is_active": True,
        },
    ],
}


class IdentityService:  # 身份目录服务，当前仅负责提供 v0.3 登录/权限模块的基础主数据。
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bootstrap = self._load_bootstrap_data()

    def get_bootstrap(self) -> IdentityBootstrapResponse:
        return IdentityBootstrapResponse.model_validate(self.bootstrap.model_dump())

    def list_users(self) -> list[UserRecord]:
        return [item.model_copy(deep=True) for item in self.bootstrap.users]

    def get_user(self, user_id: str) -> UserRecord:
        normalized_user_id = user_id.strip()
        for user in self.bootstrap.users:
            if user.user_id == normalized_user_id:
                return user.model_copy(deep=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found: {user_id}")

    def _load_bootstrap_data(self) -> IdentityBootstrapData:
        path = self.settings.identity_bootstrap_path
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid identity bootstrap JSON: {path}") from exc
            return IdentityBootstrapData.model_validate(payload)
        return IdentityBootstrapData.model_validate(DEFAULT_IDENTITY_BOOTSTRAP)


@lru_cache
def get_identity_service() -> IdentityService:
    return IdentityService()
