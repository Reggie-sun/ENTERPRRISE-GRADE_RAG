import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.chat_service import ChatService, get_chat_service
from backend.app.services.document_service import DocumentService, get_document_service
from backend.app.services.identity_service import IdentityService, get_identity_service
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service


def _build_identity_service(tmp_path: Path) -> IdentityService:
    bootstrap_path = tmp_path / "identity_bootstrap.json"
    bootstrap_path.write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "role_id": "employee",
                        "name": "Employee",
                        "description": "Department reader",
                        "data_scope": "department",
                        "is_admin": False,
                    },
                    {
                        "role_id": "department_admin",
                        "name": "Department Admin",
                        "description": "Department manager",
                        "data_scope": "department",
                        "is_admin": True,
                    },
                    {
                        "role_id": "sys_admin",
                        "name": "System Admin",
                        "description": "Global manager",
                        "data_scope": "global",
                        "is_admin": True,
                    },
                ],
                "departments": [
                    {
                        "department_id": "dept_after_sales",
                        "tenant_id": "wl",
                        "department_name": "After Sales",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                    {
                        "department_id": "dept_assembly",
                        "tenant_id": "wl",
                        "department_name": "Assembly",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                ],
                "users": [
                    {
                        "user_id": "user_employee_demo",
                        "tenant_id": "wl",
                        "username": "employee.demo",
                        "display_name": "Employee Demo",
                        "department_id": "dept_after_sales",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "employee-demo-pass",
                            salt=bytes.fromhex("00112233445566778899aabbccddeeff"),
                        ),
                    },
                    {
                        "user_id": "user_department_admin_demo",
                        "tenant_id": "wl",
                        "username": "department.admin.demo",
                        "display_name": "Department Admin Demo",
                        "department_id": "dept_after_sales",
                        "role_id": "department_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "department-admin-demo-pass",
                            salt=bytes.fromhex("11223344556677889900aabbccddeeff"),
                        ),
                    },
                    {
                        "user_id": "user_sys_admin_demo",
                        "tenant_id": "wl",
                        "username": "sys.admin.demo",
                        "display_name": "System Admin Demo",
                        "department_id": "dept_after_sales",
                        "role_id": "sys_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "sys-admin-demo-pass",
                            salt=bytes.fromhex("ffeeddccbbaa99887766554433221100"),
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return IdentityService(Settings(_env_file=None, identity_bootstrap_path=bootstrap_path))


def _build_settings(
    tmp_path: Path,
    identity_service: IdentityService,
    *,
    department_query_isolation_enabled: bool = True,
) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        auth_token_secret="test-auth-secret",
        auth_token_issuer="test-auth-issuer",
        auth_token_expire_minutes=60,
        qdrant_url=str(tmp_path / "qdrant_db"),
        qdrant_collection="enterprise_rag_authz_test",
        postgres_metadata_enabled=False,
        postgres_metadata_dsn=None,
        database_url=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        celery_task_always_eager=True,
        celery_task_eager_propagates=True,
        llm_provider="mock",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Qwen2.5-7B-Instruct",
        reranker_provider="heuristic",
        embedding_provider="mock",
        embedding_base_url="http://embedding.test",
        embedding_model="BAAI/bge-m3",
        ollama_base_url="http://embedding.test",
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=data_dir / "parsed",
        chunk_dir=data_dir / "chunks",
        document_dir=data_dir / "documents",
        job_dir=data_dir / "jobs",
        department_query_isolation_enabled=department_query_isolation_enabled,
    )


@pytest.fixture()
def authz_env(tmp_path: Path):
    identity_service = _build_identity_service(tmp_path)
    settings = _build_settings(tmp_path, identity_service)
    ensure_data_directories(settings)

    auth_service = AuthService(settings, identity_service=identity_service)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings, document_service=document_service)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = retrieval_service

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    client = TestClient(app)

    try:
        yield client, document_service
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def authz_env_no_query_isolation(tmp_path: Path):
    identity_service = _build_identity_service(tmp_path)
    settings = _build_settings(
        tmp_path,
        identity_service,
        department_query_isolation_enabled=False,
    )
    ensure_data_directories(settings)

    auth_service = AuthService(settings, identity_service=identity_service)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings, document_service=document_service)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = retrieval_service

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    client = TestClient(app)

    try:
        yield client, document_service
    finally:
        app.dependency_overrides.clear()


def _login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_document(
    client: TestClient,
    *,
    headers: dict[str, str],
    filename: str,
    content: str,
    department_id: str | None,
    visibility: str = "department",
) -> str:
    data: dict[str, object] = {"tenant_id": "wl", "visibility": visibility}
    if department_id is not None:
        data["department_id"] = department_id
    response = client.post(
        "/api/v1/documents",
        data=data,
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201
    return str(response.json()["doc_id"])


def test_document_list_filters_by_department_for_employee(authz_env) -> None:
    client, _ = authz_env
    sys_admin_headers = _login_headers(client, "sys.admin.demo", "sys-admin-demo-pass")
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    visible_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="after_sales_manual.txt",
        content="Alarm E700 after-sales repair guide.",
        department_id="dept_after_sales",
    )
    _create_document(
        client,
        headers=sys_admin_headers,
        filename="assembly_manual.txt",
        content="Alarm E700 assembly line calibration guide.",
        department_id="dept_assembly",
    )

    response = client.get("/api/v1/documents?page=1&page_size=20", headers=employee_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["document_id"] for item in payload["items"]] == [visible_doc_id]


def test_retrieval_filters_results_to_accessible_departments(authz_env) -> None:
    """Employee retrieval should return own-department results first, with cross-department results as supplemental."""
    client, _ = authz_env
    sys_admin_headers = _login_headers(client, "sys.admin.demo", "sys-admin-demo-pass")
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    visible_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="after_sales_alarm.txt",
        content="Alarm E205 after-sales handling process and spare-parts checklist.",
        department_id="dept_after_sales",
    )
    other_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="assembly_alarm.txt",
        content="Alarm E205 assembly station torque inspection and fixture reset process.",
        department_id="dept_assembly",
    )

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "Alarm E205 process", "top_k": 5},
        headers=employee_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    result_doc_ids = {item["document_id"] for item in payload["results"]}
    # Own-department result must always be present
    assert visible_doc_id in result_doc_ids
    # Cross-department result should now be available as supplemental
    assert other_doc_id in result_doc_ids
    # Own-department result should rank first
    assert payload["results"][0]["document_id"] == visible_doc_id


def test_cross_department_document_id_is_rejected_for_retrieval_and_chat(authz_env) -> None:
    client, _ = authz_env
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
    assert retrieval_response.json()["detail"] == "You do not have access to the requested document."
    assert chat_response.status_code == 403
    assert chat_response.json()["detail"] == "You do not have access to the requested document."


def test_management_boundaries_are_enforced_by_role(authz_env) -> None:
    client, _ = authz_env
    sys_admin_headers = _login_headers(client, "sys.admin.demo", "sys-admin-demo-pass")
    department_admin_headers = _login_headers(client, "department.admin.demo", "department-admin-demo-pass")
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    own_department_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="after_sales_manage.txt",
        content="After-sales managed document.",
        department_id="dept_after_sales",
    )
    other_department_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="assembly_manage.txt",
        content="Assembly managed document.",
        department_id="dept_assembly",
    )

    employee_delete = client.delete(f"/api/v1/documents/{own_department_doc_id}", headers=employee_headers)
    cross_department_delete = client.delete(f"/api/v1/documents/{other_department_doc_id}", headers=department_admin_headers)
    own_department_delete = client.delete(f"/api/v1/documents/{own_department_doc_id}", headers=department_admin_headers)

    assert employee_delete.status_code == 403
    assert employee_delete.json()["detail"] == "You do not have permission to manage this document."
    assert cross_department_delete.status_code == 403
    assert cross_department_delete.json()["detail"] == "You do not have permission to manage this document."
    assert own_department_delete.status_code == 200
    assert own_department_delete.json()["status"] == "deleted"


def test_department_admin_create_defaults_to_own_department_and_rejects_other_departments(authz_env) -> None:
    client, document_service = authz_env
    department_admin_headers = _login_headers(client, "department.admin.demo", "department-admin-demo-pass")

    default_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl"},
        files={"file": ("default_scope.txt", "Department-admin scoped upload.".encode("utf-8"), "text/plain")},
        headers=department_admin_headers,
    )
    forbidden_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl", "department_id": "dept_assembly"},
        files={"file": ("forbidden_scope.txt", "Wrong department upload.".encode("utf-8"), "text/plain")},
        headers=department_admin_headers,
    )

    assert default_department_response.status_code == 201
    created_doc_id = str(default_department_response.json()["doc_id"])
    created_record = document_service._load_document_record(created_doc_id)
    assert created_record.department_id == "dept_after_sales"
    assert created_record.uploaded_by == "user_department_admin_demo"

    assert forbidden_department_response.status_code == 403
    assert forbidden_department_response.json()["detail"] == "Department admins can only manage documents in their accessible departments."


def test_employee_create_defaults_to_own_department_and_rejects_other_departments(authz_env) -> None:
    client, document_service = authz_env
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    default_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl"},
        files={"file": ("employee_scope.txt", "Employee scoped upload.".encode("utf-8"), "text/plain")},
        headers=employee_headers,
    )
    forbidden_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl", "department_id": "dept_assembly"},
        files={"file": ("employee_forbidden_scope.txt", "Wrong department upload.".encode("utf-8"), "text/plain")},
        headers=employee_headers,
    )

    assert default_department_response.status_code == 201
    created_doc_id = str(default_department_response.json()["doc_id"])
    created_record = document_service._load_document_record(created_doc_id)
    assert created_record.department_id == "dept_after_sales"
    assert created_record.uploaded_by == "user_employee_demo"

    assert forbidden_department_response.status_code == 403
    assert forbidden_department_response.json()["detail"] == "Employees can only create documents in their accessible departments."


def test_query_scope_can_read_cross_department_documents_when_query_isolation_disabled(authz_env_no_query_isolation) -> None:
    client, _ = authz_env_no_query_isolation
    sys_admin_headers = _login_headers(client, "sys.admin.demo", "sys-admin-demo-pass")
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    own_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="after_sales_shared.txt",
        content="After-sales troubleshooting guide.",
        department_id="dept_after_sales",
    )
    other_doc_id = _create_document(
        client,
        headers=sys_admin_headers,
        filename="assembly_shared.txt",
        content="Assembly torque checklist.",
        department_id="dept_assembly",
    )

    list_response = client.get("/api/v1/documents?page=1&page_size=20", headers=employee_headers)
    retrieval_response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "guide checklist", "top_k": 5},
        headers=employee_headers,
    )
    detail_response = client.get(f"/api/v1/documents/{other_doc_id}", headers=employee_headers)
    chat_response = client.post(
        "/api/v1/chat/ask",
        json={"question": "What is in the assembly checklist?", "document_id": other_doc_id, "top_k": 3},
        headers=employee_headers,
    )

    assert list_response.status_code == 200
    assert {item["document_id"] for item in list_response.json()["items"]} == {own_doc_id, other_doc_id}

    assert retrieval_response.status_code == 200
    assert {item["document_id"] for item in retrieval_response.json()["results"]} == {own_doc_id, other_doc_id}

    assert detail_response.status_code == 200
    assert detail_response.json()["document_id"] == other_doc_id

    assert chat_response.status_code == 200
    assert {item["document_id"] for item in chat_response.json()["citations"]} == {other_doc_id}


def test_query_scope_disable_does_not_widen_write_boundaries(authz_env_no_query_isolation) -> None:
    client, document_service = authz_env_no_query_isolation
    employee_headers = _login_headers(client, "employee.demo", "employee-demo-pass")

    default_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl"},
        files={"file": ("employee_scope.txt", "Employee scoped upload.".encode("utf-8"), "text/plain")},
        headers=employee_headers,
    )
    forbidden_department_response = client.post(
        "/api/v1/documents",
        data={"tenant_id": "wl", "department_id": "dept_assembly"},
        files={"file": ("employee_forbidden_scope.txt", "Wrong department upload.".encode("utf-8"), "text/plain")},
        headers=employee_headers,
    )

    assert default_department_response.status_code == 201
    created_doc_id = str(default_department_response.json()["doc_id"])
    created_record = document_service._load_document_record(created_doc_id)
    assert created_record.department_id == "dept_after_sales"

    assert forbidden_department_response.status_code == 403
    assert forbidden_department_response.json()["detail"] == "Employees can only create documents in their accessible departments."
