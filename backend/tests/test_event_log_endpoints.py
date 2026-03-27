from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.event_log import EventLogActor, EventLogRecord
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.event_log_service import EventLogService, get_event_log_service
from backend.app.services.identity_service import get_identity_service
from backend.tests.test_sop_generation_service import _build_identity_service


def _build_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=data_dir / "parsed",
        chunk_dir=data_dir / "chunks",
        document_dir=data_dir / "documents",
        job_dir=data_dir / "jobs",
        event_log_dir=data_dir / "event_logs",
    )


def _build_client(tmp_path: Path) -> tuple[TestClient, EventLogService]:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    identity_service = _build_identity_service(tmp_path)
    auth_service = AuthService(
        Settings(
            _env_file=None,
            identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
            auth_token_secret="test-auth-secret",
            auth_token_issuer="test-auth-issuer",
        ),
        identity_service=identity_service,
    )
    event_log_service = EventLogService(settings)

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_event_log_service] = lambda: event_log_service
    client = TestClient(app)
    return client, event_log_service


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _append_record(
    event_log_service: EventLogService,
    *,
    event_id: str,
    category: str,
    action: str,
    outcome: str,
    username: str,
    user_id: str,
    role_id: str,
    department_id: str,
    occurred_at: str,
    target_id: str,
) -> None:
    event_log_service.repository.append(
        EventLogRecord(
            event_id=event_id,
            category=category,
            action=action,
            outcome=outcome,
            occurred_at=datetime.fromisoformat(occurred_at).astimezone(timezone.utc),
            actor=EventLogActor(
                tenant_id="wl",
                user_id=user_id,
                username=username,
                role_id=role_id,
                department_id=department_id,
            ),
            target_type="document",
            target_id=target_id,
            mode="fast",
            top_k=5,
            candidate_top_k=10,
            rerank_top_n=3,
            duration_ms=123,
            details={"source": "test"},
        )
    )


def test_log_list_endpoint_filters_to_department_admin_scope(tmp_path: Path) -> None:
    client, event_log_service = _build_client(tmp_path)
    _append_record(
        event_log_service,
        event_id="evt_digitalization_1",
        category="document",
        action="create",
        outcome="success",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-26T08:00:00+00:00",
        target_id="doc_digitalization_1",
    )
    _append_record(
        event_log_service,
        event_id="evt_assembly_1",
        category="chat",
        action="answer",
        outcome="failed",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-26T09:00:00+00:00",
        target_id="doc_assembly_1",
    )

    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        response = client.get("/api/v1/logs?page=1&page_size=20", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["event_id"] == "evt_digitalization_1"
    assert payload["items"][0]["actor"]["department_id"] == "dept_digitalization"


def test_log_list_endpoint_rejects_employee_access(tmp_path: Path) -> None:
    client, event_log_service = _build_client(tmp_path)
    _append_record(
        event_log_service,
        event_id="evt_digitalization_1",
        category="document",
        action="create",
        outcome="success",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-26T08:00:00+00:00",
        target_id="doc_digitalization_1",
    )

    try:
        headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.get("/api/v1/logs?page=1&page_size=20", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to audit logs."


def test_log_list_endpoint_supports_sys_admin_filters(tmp_path: Path) -> None:
    client, event_log_service = _build_client(tmp_path)
    _append_record(
        event_log_service,
        event_id="evt_sys_chat_1",
        category="chat",
        action="answer",
        outcome="success",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:00:00+00:00",
        target_id="chat_001",
    )
    _append_record(
        event_log_service,
        event_id="evt_sys_doc_1",
        category="document",
        action="delete",
        outcome="failed",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-26T01:00:00+00:00",
        target_id="doc_001",
    )

    try:
        headers = _login_headers(
            client,
            username="sys.admin",
            password="sys-admin-pass",
        )
        response = client.get(
            "/api/v1/logs?page=1&page_size=20&category=chat&username=sys.admin&date_from=2026-03-27&date_to=2026-03-27",
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["event_id"] == "evt_sys_chat_1"
    assert payload["items"][0]["category"] == "chat"


def test_log_list_endpoint_rejects_cross_department_query_for_department_admin(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        response = client.get(
            "/api/v1/logs?page=1&page_size=20&department_id=dept_assembly",
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to the requested department."


def test_log_list_endpoint_validates_date_range(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        headers = _login_headers(
            client,
            username="sys.admin",
            password="sys-admin-pass",
        )
        response = client.get(
            "/api/v1/logs?page=1&page_size=20&date_from=2026-03-27&date_to=2026-03-26",
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "date_to must be greater than or equal to date_from."
