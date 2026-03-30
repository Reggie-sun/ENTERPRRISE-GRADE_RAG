from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

UserRole = Literal["employee", "department_admin", "sys_admin"]  # v0.3 冻结最小角色集合，后续鉴权仅在此集合上扩展。
RoleDataScope = Literal["department", "global"]  # 当前权限范围只区分部门级和全局级，避免过早引入复杂 ACL。


class RoleDefinition(BaseModel):  # 角色定义对象，描述角色语义而不是登录态。
    role_id: UserRole
    name: str
    description: str
    data_scope: RoleDataScope
    is_admin: bool = False


class DepartmentRecord(BaseModel):  # 部门基础模型，后续文档/SOP/权限都以 department_id 关联。
    department_id: str
    tenant_id: str
    department_name: str
    parent_department_id: str | None = None
    is_active: bool = True


class UserRecord(BaseModel):  # 用户基础模型，当前仅表达归属关系和最小角色，不引入密码等登录字段。
    user_id: str
    tenant_id: str
    username: str
    display_name: str
    department_id: str
    role_id: UserRole
    is_active: bool = True


class IdentityUserRecord(UserRecord):  # 身份目录内部用户模型，额外持有密码哈希，不对外暴露。
    password_hash: str

    @model_validator(mode="after")
    def validate_password_hash(self) -> "IdentityUserRecord":
        parts = self.password_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            raise ValueError(f"Unsupported password hash format for user {self.user_id}.")
        iterations = parts[1]
        if not iterations.isdigit() or int(iterations) <= 0:
            raise ValueError(f"Invalid password hash iteration count for user {self.user_id}.")
        if not parts[2] or not parts[3]:
            raise ValueError(f"Password hash salt/digest is empty for user {self.user_id}.")
        return self

    def to_public_record(self) -> UserRecord:
        return UserRecord.model_validate(self.model_dump(exclude={"password_hash"}))


class IdentityBootstrapData(BaseModel):  # 身份目录 bootstrap 配置，供服务启动时一次性读取。
    roles: list[RoleDefinition] = Field(default_factory=list)
    departments: list[DepartmentRecord] = Field(default_factory=list)
    users: list[IdentityUserRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "IdentityBootstrapData":
        role_ids = [item.role_id for item in self.roles]
        if set(role_ids) != {"employee", "department_admin", "sys_admin"}:
            raise ValueError("roles must contain exactly employee, department_admin, sys_admin.")
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("role_id must be unique.")

        department_ids = [item.department_id for item in self.departments]
        if len(set(department_ids)) != len(department_ids):
            raise ValueError("department_id must be unique.")

        user_ids = [item.user_id for item in self.users]
        if len(set(user_ids)) != len(user_ids):
            raise ValueError("user_id must be unique.")

        known_departments = {item.department_id: item for item in self.departments}
        for department in self.departments:
            if department.parent_department_id is not None and department.parent_department_id not in known_departments:
                raise ValueError(f"Unknown parent_department_id: {department.parent_department_id}")

        known_roles = {item.role_id for item in self.roles}
        for user in self.users:
            department = known_departments.get(user.department_id)
            if department is None:
                raise ValueError(f"Unknown department_id for user {user.user_id}: {user.department_id}")
            if user.role_id not in known_roles:
                raise ValueError(f"Unknown role_id for user {user.user_id}: {user.role_id}")
            if user.tenant_id != department.tenant_id:
                raise ValueError(
                    f"User {user.user_id} tenant_id {user.tenant_id} does not match department tenant_id {department.tenant_id}."
                )

        return self


class IdentityBootstrapResponse(BaseModel):  # 只读 bootstrap 响应，便于后续登录页或管理页复用。
    roles: list[RoleDefinition]
    departments: list[DepartmentRecord]
    users: list[UserRecord]


class LoginRequest(BaseModel):  # 登录请求体，当前采用最小用户名+密码模式。
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AuthProfileResponse(BaseModel):  # 当前用户的最小权限上下文。
    user: UserRecord
    role: RoleDefinition
    department: DepartmentRecord
    accessible_department_ids: list[str] = Field(default_factory=list)
    department_query_isolation_enabled: bool = True  # 读链路是否仍按部门隔离；前端据此调整门户范围文案，不改变稳定字段骨架。


class LoginResponse(AuthProfileResponse):  # 登录成功响应。
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int = Field(ge=1)


class LogoutResponse(BaseModel):  # 登出响应。
    status: Literal["logged_out"] = "logged_out"


class AuthTokenPayload(BaseModel):  # token 内部载荷，当前不直接暴露给外部调用方。
    sub: str
    tenant_id: str
    department_id: str
    role_id: UserRole
    iss: str
    jti: str
    iat: int = Field(ge=0)
    exp: int = Field(ge=0)


class AuthContext(AuthProfileResponse):  # 鉴权依赖解析出的完整上下文。
    token_id: str
    issued_at: datetime
    expires_at: datetime
