from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.sop_service import SopService, get_sop_service
from backend.app.services.sop_version_service import SopVersionService, get_sop_version_service
from backend.tests.test_sop_service import _build_identity_service, _write_sop_bootstrap


def _build_client(tmp_path: Path) -> TestClient:
    identity_service = _build_identity_service(tmp_path)
    sop_bootstrap_path = tmp_path / "sop_bootstrap.json"
    _write_sop_bootstrap(sop_bootstrap_path)
    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        sop_bootstrap_path=sop_bootstrap_path,
        sop_record_dir=tmp_path / "sops",
        sop_version_dir=tmp_path / "sop_versions",
    )
    auth_service = AuthService(identity_service=identity_service)
    sop_service = SopService(settings, identity_service=identity_service)
    sop_version_service = SopVersionService(settings, identity_service=identity_service, sop_service=sop_service)

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_sop_service] = lambda: sop_service
    app.dependency_overrides[get_sop_version_service] = lambda: sop_version_service
    return TestClient(app)


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_save_sop_and_list_versions_endpoints(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        save_response = client.post(
            "/api/v1/sops/save",
            json={
                "title": "数字化部巡检草稿",
                "department_id": "dept_digitalization",
                "process_name": "巡检",
                "scenario_name": "日常维护",
                "content": "步骤一：检查调度服务。",
                "request_mode": "topic",
                "generation_mode": "rag",
                "citations": [
                    {
                        "chunk_id": "chunk_1",
                        "document_id": "doc_1",
                        "document_name": "数字化巡检手册",
                        "snippet": "检查调度服务。",
                        "score": 0.88,
                        "source_path": "/tmp/doc_1.txt",
                    }
                ],
            },
            headers=headers,
        )
        sop_id = save_response.json()["sop_id"]
        versions_response = client.get(f"/api/v1/sops/{sop_id}/versions", headers=headers)
        detail_response = client.get(f"/api/v1/sops/{sop_id}/versions/1", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert save_response.status_code == 200
    assert save_response.json()["version"] == 1
    assert versions_response.status_code == 200
    assert versions_response.json()["current_version"] == 1
    assert versions_response.json()["items"][0]["citations_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["content"] == "步骤一：检查调度服务。"
    assert detail_response.json()["citations"][0]["document_id"] == "doc_1"


def test_save_sop_endpoint_rejects_employee(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        response = client.post(
            "/api/v1/sops/save",
            json={"title": "员工保存", "content": "test"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Current role cannot save SOPs."


def test_list_versions_endpoint_includes_bootstrap_history_after_save(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        save_response = client.post(
            "/api/v1/sops/save",
            json={
                "sop_id": "sop_digitalization_daily_inspection",
                "title": "数字化部系统巡检 SOP",
                "content": "新的 v3 内容",
                "status": "active",
                "generation_mode": "rag",
            },
            headers=headers,
        )
        versions_response = client.get("/api/v1/sops/sop_digitalization_daily_inspection/versions", headers=headers)
        bootstrap_detail = client.get("/api/v1/sops/sop_digitalization_daily_inspection/versions/2", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert save_response.status_code == 200
    assert save_response.json()["version"] == 3
    assert versions_response.status_code == 200
    assert [item["version"] for item in versions_response.json()["items"]] == [3, 2]
    assert bootstrap_detail.status_code == 200
    assert bootstrap_detail.json()["generation_mode"] == "bootstrap"
