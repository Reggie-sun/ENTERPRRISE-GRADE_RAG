import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.auth_runtime_store import InMemoryAuthRuntimeStore
from backend.app.services.identity_service import IdentityService, get_identity_service


def _build_identity_service(tmp_path) -> IdentityService:
    bootstrap_path = tmp_path / "identity_bootstrap.json"
    bootstrap_path.write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "role_id": "employee",
                        "name": "Employee",
                        "description": "Employee scope",
                        "data_scope": "department",
                        "is_admin": False,
                    },
                    {
                        "role_id": "department_admin",
                        "name": "Department Admin",
                        "description": "Department scope",
                        "data_scope": "department",
                        "is_admin": True,
                    },
                    {
                        "role_id": "sys_admin",
                        "name": "System Admin",
                        "description": "Global scope",
                        "data_scope": "global",
                        "is_admin": True,
                    },
                ],
                "departments": [
                    {
                        "department_id": "dept_demo",
                        "tenant_id": "wl",
                        "department_name": "Demo Department",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                    {
                        "department_id": "dept_secondary",
                        "tenant_id": "wl",
                        "department_name": "Secondary Department",
                        "parent_department_id": "dept_demo",
                        "is_active": True,
                    },
                ],
                "users": [
                    {
                        "user_id": "user_employee_demo",
                        "tenant_id": "wl",
                        "username": "employee.demo",
                        "display_name": "Employee Demo",
                        "department_id": "dept_demo",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password("employee-demo-pass", salt=bytes.fromhex("00112233445566778899aabbccddeeff")),
                    },
                    {
                        "user_id": "user_sys_admin_demo",
                        "tenant_id": "wl",
                        "username": "sys.admin.demo",
                        "display_name": "System Admin Demo",
                        "department_id": "dept_demo",
                        "role_id": "sys_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password("sys-admin-demo-pass", salt=bytes.fromhex("ffeeddccbbaa99887766554433221100")),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return IdentityService(Settings(_env_file=None, identity_bootstrap_path=bootstrap_path))


def _build_auth_service(tmp_path, *, runtime_store: InMemoryAuthRuntimeStore | None = None, **settings_overrides) -> tuple[IdentityService, AuthService]:
    identity_service = _build_identity_service(tmp_path)
    auth_service = AuthService(
        Settings(
            _env_file=None,
            identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
            auth_token_secret="test-auth-secret",
            auth_token_issuer="test-auth-issuer",
            auth_token_expire_minutes=60,
            **settings_overrides,
        ),
        identity_service=identity_service,
        runtime_store=runtime_store,
    )
    return identity_service, auth_service


def test_auth_login_returns_bearer_token_and_profile(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "employee-demo-pass"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["user_id"] == "user_employee_demo"
    assert payload["department"]["department_id"] == "dept_demo"
    assert payload["accessible_department_ids"] == ["dept_demo"]
    assert payload["department_query_isolation_enabled"] is True
    assert isinstance(payload["access_token"], str) and payload["access_token"]


def test_auth_login_rejects_invalid_password(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "wrong-password"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_auth_me_requires_bearer_token(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication credentials were not provided."


def test_auth_logout_revokes_current_token(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "employee-demo-pass"},
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_response = client.get("/api/v1/auth/me", headers=headers)
        logout_response = client.post("/api/v1/auth/logout", headers=headers)
        revoked_response = client.get("/api/v1/auth/me", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert me_response.status_code == 200
    assert logout_response.status_code == 200
    assert logout_response.json()["status"] == "logged_out"
    assert revoked_response.status_code == 401
    assert revoked_response.json()["detail"] == "Token has been revoked."


def test_auth_me_rejects_expired_token(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    expired_token, _ = auth_service.issue_access_token(
        identity_service.get_auth_user("user_employee_demo"),
        expires_in_seconds=-1,
    )

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired."


def test_auth_sys_admin_profile_contains_global_department_scope(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(tmp_path)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "sys.admin.demo", "password": "sys-admin-demo-pass"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["role_id"] == "sys_admin"
    assert payload["accessible_department_ids"] == ["dept_demo", "dept_secondary"]


def test_auth_profile_exposes_query_isolation_toggle(tmp_path) -> None:
    identity_service = _build_identity_service(tmp_path)
    auth_service = AuthService(
        Settings(
            _env_file=None,
            identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
            auth_token_secret="test-auth-secret",
            auth_token_issuer="test-auth-issuer",
            auth_token_expire_minutes=60,
            department_query_isolation_enabled=False,
        ),
        identity_service=identity_service,
    )
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "employee-demo-pass"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["department_query_isolation_enabled"] is False


def test_auth_revoke_is_shared_for_services_using_same_runtime_store(tmp_path) -> None:
    runtime_store = InMemoryAuthRuntimeStore()
    identity_service, auth_service_a = _build_auth_service(tmp_path, runtime_store=runtime_store)
    _, auth_service_b = _build_auth_service(tmp_path, runtime_store=runtime_store)

    user = identity_service.get_auth_user("user_employee_demo")
    token, _ = auth_service_a.issue_access_token(user)
    payload = auth_service_a._decode_token(token)

    auth_service_a.revoke_token(payload.jti, expires_at=datetime.fromtimestamp(payload.exp, tz=UTC))

    with pytest.raises(Exception):
        auth_service_a.build_auth_context(token)
    with pytest.raises(Exception):
        auth_service_b.build_auth_context(token)


def test_auth_login_throttles_repeated_failures(tmp_path) -> None:
    identity_service, auth_service = _build_auth_service(
        tmp_path,
        auth_login_max_attempts=2,
        auth_login_window_seconds=60,
        auth_login_block_seconds=120,
    )
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        first_response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "wrong-password"},
        )
        second_response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "wrong-password"},
        )
        blocked_response = client.post(
            "/api/v1/auth/login",
            json={"username": "employee.demo", "password": "employee-demo-pass"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 401
    assert second_response.status_code == 429
    assert second_response.json()["detail"] == "Too many failed login attempts. Retry later."
    assert second_response.headers["retry-after"] == "120"
    assert blocked_response.status_code == 429
    assert blocked_response.headers["retry-after"] == "120"


def test_auth_token_format_is_base64_hmac(tmp_path) -> None:
    """v0.3 已知行为：token 使用自定义 base64(payload).base64(hmac) 格式。
    V1.1 迁移到标准 JWT 后此测试需更新。"""
    identity_service, auth_service = _build_auth_service(tmp_path)
    user = identity_service.get_auth_user("user_employee_demo")
    token, _ = auth_service.issue_access_token(user)

    parts = token.split(".")
    assert len(parts) == 2, "Token should have exactly two dot-separated parts"

    import base64

    # 第一段应是合法 base64 编码的 JSON
    padding = "=" * (-len(parts[0]) % 4)
    payload_bytes = base64.urlsafe_b64decode(parts[0] + padding)
    payload_json = __import__("json").loads(payload_bytes)
    assert "sub" in payload_json
    assert "jti" in payload_json
    assert "exp" in payload_json

    # 第二段应是合法 base64 编码的签名
    sig_padding = "=" * (-len(parts[1]) % 4)
    base64.urlsafe_b64decode(parts[1] + sig_padding)  # 不抛异常即可


def test_auth_tampered_signature_rejected(tmp_path) -> None:
    """篡改 token 签名应被拒绝。"""
    identity_service, auth_service = _build_auth_service(tmp_path)
    user = identity_service.get_auth_user("user_employee_demo")
    token, _ = auth_service.issue_access_token(user)

    # 篡改签名字节（翻转最后一个 base64 字符）
    payload_part, sig_part = token.split(".", 1)
    tampered_sig = sig_part[:-1] + ("A" if sig_part[-1] != "A" else "B")
    tampered_token = f"{payload_part}.{tampered_sig}"

    import pytest

    with pytest.raises(Exception):  # HTTPException: Token signature is invalid
        auth_service.build_auth_context(tampered_token)
