from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.rerank_canary_service import get_rerank_canary_service
from backend.tests.test_ops_endpoints import _append_canary, _build_client, _login_headers


def test_rerank_canary_endpoint_returns_recent_samples_for_sys_admin(tmp_path) -> None:
    client, _event_log_service, _request_trace_service, _request_snapshot_service, rerank_canary_service = _build_client(tmp_path)

    _append_canary(
        rerank_canary_service,
        sample_id="rcs_recent_1",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-28T08:00:00+00:00",
        decision="eligible",
        should_switch_default_strategy=True,
        message="provider candidate looks healthy",
    )
    _append_canary(
        rerank_canary_service,
        sample_id="rcs_recent_2",
        username="dept.admin",
        user_id="user_department_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-28T09:00:00+00:00",
        decision="hold",
        message="keep heuristic for now",
    )

    try:
        app.dependency_overrides[get_rerank_canary_service] = lambda: rerank_canary_service
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/retrieval/rerank-canary?limit=2", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 2
    assert [item["sample_id"] for item in payload["items"]] == ["rcs_recent_2", "rcs_recent_1"]
    assert payload["items"][0]["recommendation"]["decision"] == "hold"
    assert payload["items"][1]["recommendation"]["decision"] == "eligible"


def test_rerank_canary_endpoint_filters_samples_by_department_scope(tmp_path) -> None:
    client, _event_log_service, _request_trace_service, _request_snapshot_service, rerank_canary_service = _build_client(tmp_path)

    _append_canary(
        rerank_canary_service,
        sample_id="rcs_visible",
        username="dept.admin",
        user_id="user_department_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-28T08:00:00+00:00",
        decision="eligible",
    )
    _append_canary(
        rerank_canary_service,
        sample_id="rcs_hidden",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-28T09:00:00+00:00",
        decision="hold",
    )

    try:
        app.dependency_overrides[get_rerank_canary_service] = lambda: rerank_canary_service
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/retrieval/rerank-canary?limit=10", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [item["sample_id"] for item in payload["items"]] == ["rcs_visible"]


def test_rerank_canary_endpoint_filters_samples_by_decision(tmp_path) -> None:
    client, _event_log_service, _request_trace_service, _request_snapshot_service, rerank_canary_service = _build_client(tmp_path)

    _append_canary(
        rerank_canary_service,
        sample_id="rcs_eligible_1",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-28T08:00:00+00:00",
        decision="eligible",
        should_switch_default_strategy=True,
    )
    _append_canary(
        rerank_canary_service,
        sample_id="rcs_hold_1",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-28T09:00:00+00:00",
        decision="hold",
    )

    try:
        app.dependency_overrides[get_rerank_canary_service] = lambda: rerank_canary_service
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/retrieval/rerank-canary?limit=10&decision=eligible", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [item["sample_id"] for item in payload["items"]] == ["rcs_eligible_1"]
    assert payload["items"][0]["recommendation"]["decision"] == "eligible"


def test_rerank_canary_endpoint_rejects_non_admin_users(tmp_path) -> None:
    client, _event_log_service, _request_trace_service, _request_snapshot_service, rerank_canary_service = _build_client(tmp_path)

    _append_canary(
        rerank_canary_service,
        sample_id="rcs_any",
        username="employee.demo",
        user_id="user_employee",
        role_id="employee",
        department_id="dept_digitalization",
        occurred_at="2026-03-28T08:00:00+00:00",
        decision="hold",
    )

    try:
        app.dependency_overrides[get_rerank_canary_service] = lambda: rerank_canary_service
        headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        response = client.get("/api/v1/retrieval/rerank-canary?limit=5", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    payload = response.json()
    assert payload["detail"] == "You do not have access to rerank canary diagnostics."
    assert payload["error"]["code"] == "forbidden"
