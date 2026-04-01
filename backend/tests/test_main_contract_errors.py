from fastapi.testclient import TestClient

from backend.app.main import app
from backend.tests.test_authorization_filters import _create_document, _login_headers, authz_env
from backend.tests.test_sop_endpoints import _build_client as build_sop_asset_client
from backend.tests.test_sop_generation_endpoints import _build_client as build_sop_generation_client


def _assert_error_envelope(payload: dict[str, object], *, code: str, message: str) -> None:
    assert payload["detail"] == message
    assert payload["error"] == {
        "code": code,
        "message": message,
        "status_code": payload["error"]["status_code"],
    }


def test_retrieval_and_chat_reject_cross_department_document_scope(authz_env) -> None:
    client, _document_service, _retrieval_scope_policy = authz_env
    sys_admin_headers = _login_headers(client, "sys.admin.demo", "sys-admin-demo-pass")
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    forbidden_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="assembly_secret.txt",
        content="Alarm E990 assembly-only investigation note.",
        department_id="dept_assembly",
    )

    retrieval_response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "Alarm E990", "top_k": 3, "document_id": forbidden_doc_id},
        headers=employee_headers,
    )
    chat_response = client.post(
        "/api/v1/chat/ask",
        json={"question": "What is Alarm E990?", "top_k": 3, "document_id": forbidden_doc_id},
        headers=employee_headers,
    )

    assert retrieval_response.status_code == 403
    _assert_error_envelope(
        retrieval_response.json(),
        code="forbidden",
        message="You do not have access to the requested document.",
    )
    assert retrieval_response.json()["error"]["status_code"] == 403
    assert chat_response.status_code == 403
    _assert_error_envelope(
        chat_response.json(),
        code="forbidden",
        message="You do not have access to the requested document.",
    )
    assert chat_response.json()["error"]["status_code"] == 403


def test_sop_list_rejects_cross_department_filter_for_employee(tmp_path) -> None:
    client, _auth_service = build_sop_asset_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.get(
            "/api/v1/sops?page=1&page_size=20&department_id=dept_assembly",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    _assert_error_envelope(
        response.json(),
        code="forbidden",
        message="You do not have access to the requested department.",
    )
    assert response.json()["error"]["status_code"] == 403


def test_sop_generate_document_accepts_doc_id_alias(tmp_path) -> None:
    client = build_sop_generation_client(tmp_path)

    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        response = client.post(
            "/api/v1/sops/generate/document",
            json={"doc_id": "doc_digitalization", "top_k": 4},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_mode"] == "document"
    assert payload["department_id"] == "dept_digitalization"
    assert payload["citations"][0]["document_id"] == "doc_digitalization"


def test_sop_generate_topic_requires_authentication(tmp_path) -> None:
    client = build_sop_generation_client(tmp_path)

    try:
        response = client.post(
            "/api/v1/sops/generate/topic",
            json={"topic": "值班交接"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    _assert_error_envelope(
        response.json(),
        code="unauthorized",
        message="Authentication credentials were not provided.",
    )
    assert response.json()["error"]["status_code"] == 401


def test_documents_contract_validation_error_uses_structured_envelope(tmp_path) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents",
        data={"created_by": "u001"},
        files={"file": ("manual.txt", b"Alarm E102 handling guide.", "text/plain")},
    )

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload["detail"], list)
    assert payload["error"] == {
        "code": "validation_error",
        "message": "Request validation failed.",
        "status_code": 422,
    }
    assert any(item["loc"][-1] == "tenant_id" for item in payload["detail"])
