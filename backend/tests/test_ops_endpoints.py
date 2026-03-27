from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.event_log import EventLogActor, EventLogRecord
from backend.app.schemas.ops import OpsQueueSummary
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.event_log_service import EventLogService
from backend.app.services.identity_service import get_identity_service
from backend.app.services.ops_service import OpsService, get_ops_service
from backend.app.services.system_config_service import SystemConfigService
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
        system_config_path=data_dir / "system_config.json",
        llm_provider="openai",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Test-7B",
        embedding_provider="openai",
        embedding_base_url="http://embedding.test/v1",
        embedding_model="bge-m3",
    )


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
    duration_ms: int,
    timeout_flag: bool = False,
    downgraded_from: str | None = None,
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
            mode="accurate",
            top_k=8,
            candidate_top_k=16,
            rerank_top_n=5,
            duration_ms=duration_ms,
            timeout_flag=timeout_flag,
            downgraded_from=downgraded_from,
            details={"source": "test"},
        )
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
    system_config_service = SystemConfigService(settings)
    ops_service = OpsService(
        settings,
        event_log_service=event_log_service,
        system_config_service=system_config_service,
        queue_probe=lambda: OpsQueueSummary(
            available=True,
            ingest_queue=settings.celery_ingest_queue,
            backlog=3,
        ),
    )

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_ops_service] = lambda: ops_service
    return TestClient(app), event_log_service


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_ops_summary_returns_runtime_snapshot_for_sys_admin(tmp_path: Path) -> None:
    client, event_log_service = _build_client(tmp_path)
    _append_record(
        event_log_service,
        event_id="evt_chat_1",
        category="chat",
        action="answer",
        outcome="success",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:00:00+00:00",
        target_id="chat_001",
        duration_ms=120,
    )
    _append_record(
        event_log_service,
        event_id="evt_chat_2",
        category="chat",
        action="answer",
        outcome="failed",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:01:00+00:00",
        target_id="chat_002",
        duration_ms=240,
        timeout_flag=True,
        downgraded_from="accurate",
    )

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/ops/summary", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["health"]["status"] == "ok"
    assert payload["queue"]["available"] is True
    assert payload["queue"]["backlog"] == 3
    assert payload["recent_window"]["sample_size"] == 2
    assert payload["recent_window"]["failed_count"] == 1
    assert payload["recent_window"]["timeout_count"] == 1
    assert payload["recent_window"]["downgraded_count"] == 1
    assert payload["recent_window"]["duration_p95_ms"] == 240
    assert payload["config"]["model_routing"]["fast_model"] == "Qwen/Test-7B"
    assert payload["recent_failures"][0]["event_id"] == "evt_chat_2"
    assert payload["recent_degraded"][0]["event_id"] == "evt_chat_2"


def test_ops_summary_scopes_logs_for_department_admin(tmp_path: Path) -> None:
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
        occurred_at="2026-03-27T01:00:00+00:00",
        target_id="doc_001",
        duration_ms=80,
    )
    _append_record(
        event_log_service,
        event_id="evt_other_1",
        category="document",
        action="delete",
        outcome="failed",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-27T01:01:00+00:00",
        target_id="doc_002",
        duration_ms=140,
    )

    try:
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/ops/summary", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_window"]["sample_size"] == 1
    assert payload["categories"][1]["category"] == "document"
    assert payload["categories"][1]["total"] == 1
    assert payload["recent_failures"] == []


def test_ops_summary_rejects_employee_access(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        response = client.get("/api/v1/ops/summary", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to runtime operations."
