from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.event_log import EventLogActor
from backend.app.schemas.request_trace import RequestTraceRecord, RequestTraceStage
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.request_trace_service import RequestTraceService, get_request_trace_service
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
        request_trace_dir=data_dir / "request_traces",
    )


def _build_client(tmp_path: Path) -> tuple[TestClient, RequestTraceService]:
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
    request_trace_service = RequestTraceService(settings)

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_request_trace_service] = lambda: request_trace_service
    return TestClient(app), request_trace_service


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _append_trace(
    request_trace_service: RequestTraceService,
    *,
    trace_id: str,
    request_id: str,
    username: str,
    user_id: str,
    role_id: str,
    department_id: str,
    occurred_at: str,
    outcome: str,
) -> None:
    request_trace_service.repository.append(
        RequestTraceRecord(
            trace_id=trace_id,
            request_id=request_id,
            category="chat",
            action="answer",
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
            target_id="doc_001",
            mode="accurate",
            top_k=8,
            candidate_top_k=16,
            rerank_top_n=5,
            total_duration_ms=120,
            response_mode="rag",
            stages=[
                RequestTraceStage(stage="retrieval", status="success", duration_ms=40, input_size=12, output_size=5),
                RequestTraceStage(stage="llm", status="success", duration_ms=80, input_size=5, output_size=220),
            ],
            details={"source": "test"},
        )
    )


def test_trace_list_endpoint_filters_department_admin_scope(tmp_path: Path) -> None:
    client, request_trace_service = _build_client(tmp_path)
    _append_trace(
        request_trace_service,
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T08:00:00+00:00",
        outcome="success",
    )
    _append_trace(
        request_trace_service,
        trace_id="trc_assembly_1",
        request_id="req_assembly_1",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-27T09:00:00+00:00",
        outcome="failed",
    )

    try:
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/traces?page=1&page_size=20", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["trace_id"] == "trc_digitalization_1"


def test_trace_list_endpoint_rejects_employee_access(tmp_path: Path) -> None:
    client, request_trace_service = _build_client(tmp_path)
    _append_trace(
        request_trace_service,
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T08:00:00+00:00",
        outcome="success",
    )

    try:
        headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        response = client.get("/api/v1/traces?page=1&page_size=20", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to request traces."
