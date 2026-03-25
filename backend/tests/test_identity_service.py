import json

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.services.auth_service import AuthService
from backend.app.services.identity_service import IdentityService, get_identity_service


def test_identity_service_exposes_frozen_roles_and_department_relation() -> None:
    service = IdentityService()

    bootstrap = service.get_bootstrap()

    assert [item.role_id for item in bootstrap.roles] == ["employee", "department_admin", "sys_admin"]
    departments = {item.department_id: item for item in bootstrap.departments}
    assert departments["dept_after_sales"].parent_department_id == "dept_ops"
    assert service.get_user("user_department_admin_demo").department_id == "dept_after_sales"
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


def test_auth_bootstrap_endpoint_returns_identity_directory() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert [item["role_id"] for item in payload["roles"]] == ["employee", "department_admin", "sys_admin"]
    assert any(item["department_id"] == "dept_after_sales" for item in payload["departments"])
    assert any(item["user_id"] == "user_employee_demo" for item in payload["users"])


def test_auth_user_endpoint_returns_404_for_unknown_user() -> None:
    app.dependency_overrides[get_identity_service] = lambda: IdentityService()
    client = TestClient(app)

    try:
        response = client.get("/api/v1/auth/users/user_missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found: user_missing"
