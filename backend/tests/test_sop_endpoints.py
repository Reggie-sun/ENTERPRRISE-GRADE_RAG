from pathlib import Path
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import get_identity_service
from backend.app.core.config import Settings
from backend.app.services.sop_service import SopService, get_sop_service
from backend.tests.test_sop_service import (
    _build_identity_service,
    _build_sop_service,
    _write_file_asset_sop_bootstrap,
)


def _build_client(tmp_path: Path) -> tuple[TestClient, AuthService]:
    identity_service = _build_identity_service(tmp_path)
    sop_service = _build_sop_service(tmp_path, identity_service)
    auth_service = AuthService(
        identity_service=identity_service,
    )

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_sop_service] = lambda: sop_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)
    return client, auth_service


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_sop_list_endpoint_requires_authentication(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        response = client.get("/api/v1/sops?page=1&page_size=20")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication credentials were not provided."


def test_sop_list_endpoint_filters_to_accessible_department(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.get("/api/v1/sops?page=1&page_size=20", headers=employee_headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["sop_id"] for item in payload["items"]] == [
        "sop_digitalization_daily_inspection",
        "sop_digitalization_handover_draft",
    ]
    assert all(item["department_id"] == "dept_digitalization" for item in payload["items"])


def test_sop_list_endpoint_supports_process_and_status_filters(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.get(
            "/api/v1/sops?page=1&page_size=20&process_name=%E5%B7%A1%E6%A3%80&status=active",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["sop_id"] == "sop_digitalization_daily_inspection"
    assert payload["items"][0]["downloadable_formats"] == ["docx", "pdf"]


def test_sop_list_endpoint_rejects_cross_department_query_for_employee(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

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
    assert response.json()["detail"] == "You do not have access to the requested department."


def test_sop_list_endpoint_allows_sys_admin_global_scope(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        sys_admin_headers = _login_headers(
            client,
            username="sys.admin",
            password="sys-admin-pass",
        )
        response = client.get(
            "/api/v1/sops?page=1&page_size=20&department_id=dept_assembly",
            headers=sys_admin_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["sop_id"] == "sop_assembly_alarm"


def test_sop_detail_and_preview_endpoints_return_text_preview(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        detail_response = client.get(
            "/api/v1/sops/sop_digitalization_daily_inspection",
            headers=employee_headers,
        )
        preview_response = client.get(
            "/api/v1/sops/sop_digitalization_daily_inspection/preview",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert detail_response.status_code == 200
    assert detail_response.json()["department_id"] == "dept_digitalization"
    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["preview_type"] == "text"
    assert "检查任务调度服务状态" in payload["text_content"]


def test_sop_preview_endpoint_rejects_cross_department_access(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.get(
            "/api/v1/sops/sop_assembly_alarm/preview",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to the requested SOP."


def test_sop_download_endpoint_returns_docx_and_pdf_files(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        docx_response = client.get(
            "/api/v1/sops/sop_digitalization_daily_inspection/download?format=docx",
            headers=employee_headers,
        )
        pdf_response = client.get(
            "/api/v1/sops/sop_digitalization_daily_inspection/download?format=pdf",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert docx_response.status_code == 200
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "sop_digitalization_daily_inspection.docx" in docx_response.headers["content-disposition"]
    assert docx_response.content.startswith(b"PK")

    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert "sop_digitalization_daily_inspection.pdf" in pdf_response.headers["content-disposition"]
    assert pdf_response.content.startswith(b"%PDF")


def test_sop_download_endpoint_handles_missing_resource_and_scope(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        missing_response = client.get(
            "/api/v1/sops/sop_digitalization_handover_draft/download?format=pdf",
            headers=employee_headers,
        )
        forbidden_response = client.get(
            "/api/v1/sops/sop_assembly_alarm/download?format=docx",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "SOP download resource not found: sop_digitalization_handover_draft (pdf)"
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["detail"] == "You do not have access to the requested SOP."


def test_sop_export_endpoint_returns_docx_and_pdf_for_unsaved_draft(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        payload = {
            "title": "Digitalization Daily Inspection Draft",
            "content": "## 目的\n规范日常巡检。\n\n## 步骤\n1. 查看监控。\n2. 记录异常。",
            "department_id": "dept_digitalization",
            "process_name": "巡检",
            "scenario_name": "日常运维",
            "source_document_id": "doc_digitalization_source",
        }
        docx_response = client.post(
            "/api/v1/sops/export",
            headers=employee_headers,
            json={**payload, "format": "docx"},
        )
        pdf_response = client.post(
            "/api/v1/sops/export",
            headers=employee_headers,
            json={**payload, "format": "pdf"},
        )
    finally:
        app.dependency_overrides.clear()

    assert docx_response.status_code == 200
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "Digitalization_Daily_Inspection_Draft.docx" in docx_response.headers["content-disposition"]
    assert docx_response.content.startswith(b"PK")

    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert "Digitalization_Daily_Inspection_Draft.pdf" in pdf_response.headers["content-disposition"]
    assert pdf_response.content.startswith(b"%PDF")


def test_sop_export_endpoint_supports_non_ascii_filename_in_content_disposition(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.post(
            "/api/v1/sops/export",
            headers=employee_headers,
            json={
                "title": "数字化部巡检 SOP 草稿",
                "content": "## 目的\n规范日常巡检。",
                "format": "docx",
                "department_id": "dept_digitalization",
                "source_document_id": "doc_digitalization_source",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="SOP.docx"' in disposition
    assert "filename*=UTF-8''" in disposition
    assert "%E6%95%B0%E5%AD%97%E5%8C%96%E9%83%A8%E5%B7%A1%E6%A3%80_SOP_%E8%8D%89%E7%A8%BF.docx" in disposition
    assert response.content.startswith(b"PK")


def test_sop_export_endpoint_pdf_preserves_chinese_text(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.post(
            "/api/v1/sops/export",
            headers=employee_headers,
            json={
                "title": "数字化部巡检 SOP 草稿",
                "content": "## 目的\n规范日常巡检。\n\n## 步骤\n1. 检查数据库连接。\n2. 记录异常。",
                "format": "pdf",
                "department_id": "dept_digitalization",
                "source_document_id": "doc_digitalization_source",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")

    extracted_text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
    assert "数字化部巡检 SOP 草稿" in extracted_text
    assert "检查数据库连接" in extracted_text


def test_sop_export_endpoint_rejects_cross_department_request_for_employee(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        response = client.post(
            "/api/v1/sops/export",
            headers=employee_headers,
            json={
                "title": "Assembly Draft",
                "content": "## 步骤\n1. 处理告警。",
                "format": "docx",
                "department_id": "dept_assembly",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to the requested department."


def test_sop_preview_file_endpoint_streams_local_pdf_asset(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_bootstrap_path = tmp_path / "sop_bootstrap.json"
    _write_file_asset_sop_bootstrap(sop_bootstrap_path)
    asset_dir = tmp_path / "sop_assets"
    (asset_dir / "preview").mkdir(parents=True, exist_ok=True)
    (asset_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (asset_dir / "preview" / "sample-preview.pdf").write_bytes(b"%PDF-preview")
    (asset_dir / "downloads" / "sample-download.pdf").write_bytes(b"%PDF-download")
    sop_service = SopService(
        Settings(
            _env_file=None,
            identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
            sop_bootstrap_path=sop_bootstrap_path,
            sop_asset_dir=asset_dir,
        ),
        identity_service=identity_service,
    )

    auth_service = AuthService(identity_service=identity_service)
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_sop_service] = lambda: sop_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    client = TestClient(app)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        preview_response = client.get(
            "/api/v1/sops/sop_digitalization_pdf_preview/preview",
            headers=employee_headers,
        )
        preview_file_response = client.get(
            "/api/v1/sops/sop_digitalization_pdf_preview/preview/file",
            headers=employee_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert preview_response.status_code == 200
    assert preview_response.json()["preview_file_url"] == "/api/v1/sops/sop_digitalization_pdf_preview/preview/file"
    assert preview_file_response.status_code == 200
    assert preview_file_response.headers["content-type"].startswith("application/pdf")
    assert preview_file_response.content.startswith(b"%PDF-preview")
