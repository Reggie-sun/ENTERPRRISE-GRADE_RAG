import json
from functools import lru_cache

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..schemas.auth import DepartmentRecord, IdentityBootstrapData, IdentityBootstrapResponse, IdentityUserRecord, RoleDefinition, UserRecord

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
            "password_hash": "pbkdf2_sha256$200000$85bad70aa22bd1bc01e53fda2e678bab$58c892a3862943b5ad5e2edbc7516d799eef5aca3f098a769543f86936ffbda6",
        },
        {
            "user_id": "user_department_admin_demo",
            "tenant_id": "wl",
            "username": "department.admin.demo",
            "display_name": "Department Admin Demo",
            "department_id": "dept_after_sales",
            "role_id": "department_admin",
            "is_active": True,
            "password_hash": "pbkdf2_sha256$200000$a6ee3dcbdb3f47ba59b109f63714d64c$47639ecd42275e0461303fb926c894cbf51aa2fdbe857a687c5e4f3674bcff27",
        },
        {
            "user_id": "user_sys_admin_demo",
            "tenant_id": "wl",
            "username": "sys.admin.demo",
            "display_name": "System Admin Demo",
            "department_id": "dept_ops",
            "role_id": "sys_admin",
            "is_active": True,
            "password_hash": "pbkdf2_sha256$200000$7d8321838373579773f161fbc045e423$f1794f670a4a4f33020e77384fddb9a534f8442b56a3e3de9a17876950150f73",
        },
    ],
}


class IdentityService:  # 身份目录服务，当前仅负责提供 v0.3 登录/权限模块的基础主数据。
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bootstrap = self._load_bootstrap_data()

    def get_bootstrap(self) -> IdentityBootstrapResponse:
        return IdentityBootstrapResponse(
            roles=[item.model_copy(deep=True) for item in self.bootstrap.roles],
            departments=[item.model_copy(deep=True) for item in self.bootstrap.departments],
            users=[item.to_public_record() for item in self.bootstrap.users],
        )

    def list_users(self) -> list[UserRecord]:
        return [item.to_public_record() for item in self.bootstrap.users]

    def get_user(self, user_id: str) -> UserRecord:
        return self.get_auth_user(user_id).to_public_record()

    def get_auth_user(self, user_id: str) -> IdentityUserRecord:
        normalized_user_id = user_id.strip()
        for user in self.bootstrap.users:
            if user.user_id == normalized_user_id:
                return user.model_copy(deep=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found: {user_id}")

    def get_auth_user_by_username(self, username: str) -> IdentityUserRecord:
        normalized_username = username.strip().lower()
        for user in self.bootstrap.users:
            if user.username.lower() == normalized_username:
                return user.model_copy(deep=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found for username: {username}")

    def get_role(self, role_id: str) -> RoleDefinition:
        normalized_role_id = role_id.strip()
        for role in self.bootstrap.roles:
            if role.role_id == normalized_role_id:
                return role.model_copy(deep=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Role not found: {role_id}")

    def get_department(self, department_id: str) -> DepartmentRecord:
        normalized_department_id = department_id.strip()
        for department in self.bootstrap.departments:
            if department.department_id == normalized_department_id:
                return department.model_copy(deep=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Department not found: {department_id}")

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
