import json

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import IdentityService, get_identity_service
from backend.tests.test_sop_generation_service import _build_identity_service as _build_auth_identity_service


def _build_auth_client(tmp_path, *, public_bootstrap: bool = False) -> TestClient:
    identity_service = _build_auth_identity_service(tmp_path)
    auth_service = AuthService(
        Settings(
            _env_file=None,
            identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
            auth_token_secret="test-auth-secret",
            auth_token_issuer="test-auth-issuer",
            auth_identity_bootstrap_public_enabled=public_bootstrap,
        ),
        identity_service=identity_service,
    )
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    return TestClient(app)


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_identity_service_exposes_frozen_roles_and_department_relation() -> None:
    service = IdentityService()

    bootstrap = service.get_bootstrap()

    assert [item.role_id for item in bootstrap.roles] == ["employee", "department_admin", "sys_admin"]
    departments = {item.department_id: item for item in bootstrap.departments}
    assert departments["dept_digitalization"].department_name == "数字化部"
    assert departments["dept_general_manager_office"].department_name == "总经办"
    assert service.get_user("user_department_admin_demo").department_id == "dept_digitalization"
    assert service.get_user("user_digitalization_real_01").display_name == "黄前超"
    assert service.get_user("user_digitalization_real_01").role_id == "department_admin"
    assert service.get_user("user_digitalization_real_22").display_name == "应旭冲"
    assert service.get_user("user_sys_admin_demo").role_id == "sys_admin"


def test_identity_service_accepts_custom_bootstrap_file(tmp_path) -> None:
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
                        "department_id": "dept_custom",
                        "tenant_id": "wl",
                        "department_name": "Custom",
                        "parent_department_id": None,
                        "is_active": True,
                    }
                ],
                "users": [
                    {
                        "user_id": "user_custom",
                        "tenant_id": "wl",
                        "username": "custom.user",
                        "display_name": "Custom User",
                        "department_id": "dept_custom",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "custom-user-pass",
                            salt=bytes.fromhex("1234567890abcdef1234567890abcdef"),
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    service = IdentityService(Settings(_env_file=None, identity_bootstrap_path=bootstrap_path))

    bootstrap = service.get_bootstrap()
    assert len(bootstrap.departments) == 1
    assert bootstrap.users[0].user_id == "user_custom"


def test_identity_service_rejects_unknown_department_reference(tmp_path) -> None:
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
                "departments": [],
                "users": [
                    {
                        "user_id": "user_broken",
                        "tenant_id": "wl",
                        "username": "broken.user",
                        "display_name": "Broken User",
                        "department_id": "dept_missing",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "broken-user-pass",
                            salt=bytes.fromhex("abcdef1234567890abcdef1234567890"),
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown department_id"):
        IdentityService(Settings(_env_file=None, identity_bootstrap_path=bootstrap_path))


def test_auth_bootstrap_endpoint_returns_identity_directory_for_sys_admin(tmp_path) -> None:
    client = _build_auth_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/auth/bootstrap", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [item["role_id"] for item in payload["roles"]] == ["employee", "department_admin", "sys_admin"]
    assert any(item["department_id"] == "dept_digitalization" for item in payload["departments"])
    assert any(item["department_name"] == "装配部" for item in payload["departments"])
    assert any(item["user_id"] == "user_digitalization_employee" for item in payload["users"])


def test_auth_bootstrap_endpoint_can_be_public_when_enabled(tmp_path) -> None:
    client = _build_auth_client(tmp_path, public_bootstrap=True)

    try:
        response = client.get("/api/v1/auth/bootstrap")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert any(item["user_id"] == "user_sys_admin" for item in response.json()["users"])


def test_auth_user_endpoint_returns_404_for_unknown_user(tmp_path) -> None:
    client = _build_auth_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/auth/users/user_missing", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found: user_missing"


def test_auth_user_endpoint_allows_self_but_blocks_other_user(tmp_path) -> None:
    client = _build_auth_client(tmp_path)

    try:
        employee_headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        own_response = client.get("/api/v1/auth/users/user_digitalization_employee", headers=employee_headers)
        other_response = client.get("/api/v1/auth/users/user_sys_admin", headers=employee_headers)
    finally:
        app.dependency_overrides.clear()

    assert own_response.status_code == 200
    assert own_response.json()["user_id"] == "user_digitalization_employee"
    assert other_response.status_code == 403
    assert other_response.json()["detail"] == "You do not have access to this user record."
