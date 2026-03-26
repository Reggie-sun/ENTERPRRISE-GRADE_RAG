import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.schemas.sop import SopRecord
from backend.app.services.auth_service import AuthService
from backend.app.services.identity_service import IdentityService
from backend.app.services.sop_service import SopService


def _write_identity_bootstrap(path: Path) -> None:
    path.write_text(
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
                        "department_id": "dept_digitalization",
                        "tenant_id": "wl",
                        "department_name": "数字化部",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                    {
                        "department_id": "dept_assembly",
                        "tenant_id": "wl",
                        "department_name": "装配部",
                        "parent_department_id": None,
                        "is_active": True,
                    },
                ],
                "users": [
                    {
                        "user_id": "user_digitalization_employee",
                        "tenant_id": "wl",
                        "username": "digitalization.employee",
                        "display_name": "数字化员工",
                        "department_id": "dept_digitalization",
                        "role_id": "employee",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "digitalization-employee-pass",
                            salt=bytes.fromhex("00112233445566778899aabbccddeeff"),
                        ),
                    },
                    {
                        "user_id": "user_sys_admin",
                        "tenant_id": "wl",
                        "username": "sys.admin",
                        "display_name": "系统管理员",
                        "department_id": "dept_digitalization",
                        "role_id": "sys_admin",
                        "is_active": True,
                        "password_hash": AuthService.hash_password(
                            "sys-admin-pass",
                            salt=bytes.fromhex("11223344556677889900aabbccddeeff"),
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_sop_bootstrap(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sops": [
                    {
                        "sop_id": "sop_digitalization_daily_inspection",
                        "tenant_id": "wl",
                        "title": "数字化部系统巡检 SOP",
                        "department_id": "dept_digitalization",
                        "department_ids": ["dept_digitalization"],
                        "process_name": "巡检",
                        "scenario_name": "日常维护",
                        "version": 2,
                        "status": "active",
                        "preview_resource_path": "preview://digitalization/inspection/v2",
                        "preview_resource_type": "text",
                        "preview_text_content": "1. 检查任务调度服务状态。\\n2. 核对数据库与队列连接。\\n3. 记录异常并升级。",
                        "download_docx_resource_path": "asset://digitalization/inspection/v2/docx",
                        "download_pdf_resource_path": "asset://digitalization/inspection/v2/pdf",
                        "tags": ["数字化", "巡检"],
                        "source_document_id": "doc_001",
                        "created_by": "黄前超",
                        "updated_by": "黄前超",
                        "created_at": "2026-03-20T08:00:00Z",
                        "updated_at": "2026-03-25T09:30:00Z"
                    },
                    {
                        "sop_id": "sop_digitalization_handover_draft",
                        "tenant_id": "wl",
                        "title": "数字化部交接草稿",
                        "department_id": "dept_digitalization",
                        "department_ids": ["dept_digitalization"],
                        "process_name": "交接",
                        "scenario_name": "人员轮岗",
                        "version": 1,
                        "status": "draft",
                        "preview_resource_path": None,
                        "preview_resource_type": "text",
                        "preview_text_content": None,
                        "download_docx_resource_path": None,
                        "download_pdf_resource_path": None,
                        "tags": ["交接"],
                        "source_document_id": None,
                        "created_by": "黄梦伟",
                        "updated_by": "黄梦伟",
                        "created_at": "2026-03-21T08:00:00Z",
                        "updated_at": "2026-03-21T08:00:00Z"
                    },
                    {
                        "sop_id": "sop_assembly_alarm",
                        "tenant_id": "wl",
                        "title": "装配部告警处理 SOP",
                        "department_id": "dept_assembly",
                        "department_ids": ["dept_assembly"],
                        "process_name": "异常处理",
                        "scenario_name": "设备报警",
                        "version": 1,
                        "status": "active",
                        "preview_resource_path": "preview://assembly/alarm/v1",
                        "preview_resource_type": "text",
                        "preview_text_content": "1. 确认报警编码。\\n2. 检查急停与气源。\\n3. 按值班表通知责任人。",
                        "download_docx_resource_path": "asset://assembly/alarm/v1/docx",
                        "download_pdf_resource_path": None,
                        "tags": ["装配", "告警"],
                        "source_document_id": "doc_assembly_001",
                        "created_by": "装配管理员",
                        "updated_by": "装配管理员",
                        "created_at": "2026-03-22T08:00:00Z",
                        "updated_at": "2026-03-24T10:15:00Z"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_file_asset_sop_bootstrap(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sops": [
                    {
                        "sop_id": "sop_digitalization_pdf_preview",
                        "tenant_id": "wl",
                        "title": "数字化部 PDF 预览 SOP",
                        "department_id": "dept_digitalization",
                        "department_ids": ["dept_digitalization"],
                        "process_name": "巡检",
                        "scenario_name": "文件预览",
                        "version": 1,
                        "status": "active",
                        "preview_resource_path": "preview/sample-preview.pdf",
                        "preview_resource_type": "pdf",
                        "preview_text_content": "预览文件摘要",
                        "download_docx_resource_path": "asset://digitalization/pdf-preview/docx",
                        "download_pdf_resource_path": "downloads/sample-download.pdf",
                        "tags": ["数字化", "文件"],
                        "source_document_id": None,
                        "created_by": "黄前超",
                        "updated_by": "黄前超",
                        "created_at": "2026-03-20T08:00:00Z",
                        "updated_at": "2026-03-25T09:30:00Z"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _build_identity_service(tmp_path: Path) -> IdentityService:
    identity_bootstrap_path = tmp_path / "identity_bootstrap.json"
    _write_identity_bootstrap(identity_bootstrap_path)
    return IdentityService(Settings(_env_file=None, identity_bootstrap_path=identity_bootstrap_path))


def _build_sop_service(tmp_path: Path, identity_service: IdentityService) -> SopService:
    sop_bootstrap_path = tmp_path / "sop_bootstrap.json"
    _write_sop_bootstrap(sop_bootstrap_path)
    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        sop_bootstrap_path=sop_bootstrap_path,
        sop_record_dir=tmp_path / "managed_sops",
        sop_asset_dir=tmp_path / "sop_assets",
    )
    return SopService(settings, identity_service=identity_service)


def _build_auth_context(identity_service: IdentityService, *, username: str, password: str):
    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        auth_token_secret="test-auth-secret",
        auth_token_issuer="test-auth-issuer",
    )
    auth_service = AuthService(settings, identity_service=identity_service)
    token = auth_service.login(username, password).access_token
    return auth_service.build_auth_context(token)


def test_sop_service_loads_bootstrap_and_filters_by_department_scope(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_service = _build_sop_service(tmp_path, identity_service)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    response = sop_service.list_sops(auth_context=auth_context, page=1, page_size=20)

    assert response.total == 2
    assert [item.sop_id for item in response.items] == [
        "sop_digitalization_daily_inspection",
        "sop_digitalization_handover_draft",
    ]
    assert all(item.department_id == "dept_digitalization" for item in response.items)

    filtered = sop_service.list_sops(
        auth_context=auth_context,
        page=1,
        page_size=20,
        process_name="巡检",
        sop_status="active",
    )
    assert filtered.total == 1
    assert filtered.items[0].downloadable_formats == ["docx", "pdf"]


def test_sop_service_blocks_cross_department_detail_access(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_service = _build_sop_service(tmp_path, identity_service)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    with pytest.raises(HTTPException) as exc_info:
        sop_service.get_sop("sop_assembly_alarm", auth_context=auth_context)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You do not have access to the requested SOP."


def test_sop_service_returns_text_preview_for_accessible_sop(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_service = _build_sop_service(tmp_path, identity_service)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    preview = sop_service.get_sop_preview(
        "sop_digitalization_daily_inspection",
        auth_context=auth_context,
    )

    assert preview.preview_type == "text"
    assert preview.content_type == "text/plain; charset=utf-8"
    assert "检查任务调度服务状态" in (preview.text_content or "")
    assert preview.preview_file_url is None


def test_sop_service_builds_docx_and_pdf_download_payloads(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_service = _build_sop_service(tmp_path, identity_service)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    docx_payload = sop_service.get_sop_download(
        "sop_digitalization_daily_inspection",
        download_format="docx",
        auth_context=auth_context,
    )
    pdf_payload = sop_service.get_sop_download(
        "sop_digitalization_daily_inspection",
        download_format="pdf",
        auth_context=auth_context,
    )

    assert docx_payload.filename == "sop_digitalization_daily_inspection.docx"
    assert docx_payload.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert (docx_payload.content or b"").startswith(b"PK")

    assert pdf_payload.filename == "sop_digitalization_daily_inspection.pdf"
    assert pdf_payload.media_type == "application/pdf"
    assert (pdf_payload.content or b"").startswith(b"%PDF")


def test_sop_service_returns_internal_preview_file_url_and_streams_local_pdf(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_bootstrap_path = tmp_path / "sop_bootstrap.json"
    _write_file_asset_sop_bootstrap(sop_bootstrap_path)
    asset_dir = tmp_path / "sop_assets"
    (asset_dir / "preview").mkdir(parents=True, exist_ok=True)
    (asset_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (asset_dir / "preview" / "sample-preview.pdf").write_bytes(b"%PDF-preview")
    (asset_dir / "downloads" / "sample-download.pdf").write_bytes(b"%PDF-download")
    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        sop_bootstrap_path=sop_bootstrap_path,
        sop_asset_dir=asset_dir,
    )
    sop_service = SopService(settings, identity_service=identity_service)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    preview = sop_service.get_sop_preview("sop_digitalization_pdf_preview", auth_context=auth_context)
    preview_file = sop_service.get_sop_preview_file("sop_digitalization_pdf_preview", auth_context=auth_context)
    download_file = sop_service.get_sop_download(
        "sop_digitalization_pdf_preview",
        download_format="pdf",
        auth_context=auth_context,
    )

    assert preview.preview_file_url == "/api/v1/sops/sop_digitalization_pdf_preview/preview/file"
    assert preview_file.path == asset_dir / "preview" / "sample-preview.pdf"
    assert download_file.path == asset_dir / "downloads" / "sample-download.pdf"


def test_sop_service_rejects_unknown_department_reference(tmp_path: Path) -> None:
    identity_service = _build_identity_service(tmp_path)
    sop_bootstrap_path = tmp_path / "sop_bootstrap.json"
    sop_bootstrap_path.write_text(
        json.dumps(
            {
                "sops": [
                    {
                        "sop_id": "sop_broken",
                        "tenant_id": "wl",
                        "title": "Broken SOP",
                        "department_id": "dept_missing",
                        "department_ids": ["dept_missing"],
                        "process_name": "巡检",
                        "scenario_name": "异常",
                        "version": 1,
                        "status": "active",
                        "preview_resource_path": "preview://broken",
                        "preview_resource_type": "text",
                        "download_docx_resource_path": "asset://broken/docx",
                        "download_pdf_resource_path": None,
                        "tags": [],
                        "source_document_id": None,
                        "created_by": "tester",
                        "updated_by": "tester",
                        "created_at": "2026-03-20T08:00:00Z",
                        "updated_at": "2026-03-20T08:00:00Z"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        _env_file=None,
        identity_bootstrap_path=identity_service.settings.identity_bootstrap_path,
        sop_bootstrap_path=sop_bootstrap_path,
    )
    with pytest.raises(ValueError, match="Unknown department_id for SOP"):
        SopService(settings, identity_service=identity_service)


def test_sop_service_rejects_mixed_preview_and_download_schemes() -> None:
    with pytest.raises(ValueError, match="preview_resource_path must not use asset:// download scheme"):
        SopRecord(
            sop_id="sop_invalid_preview",
            tenant_id="wl",
            title="错误预览路径",
            department_id="dept_digitalization",
            process_name="巡检",
            scenario_name="异常",
            version=1,
            status="active",
            preview_resource_path="asset://digitalization/bad-preview",
            download_docx_resource_path="asset://digitalization/docx",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    with pytest.raises(ValueError, match="download_pdf_resource_path must not use preview:// scheme"):
        SopRecord(
            sop_id="sop_invalid_download",
            tenant_id="wl",
            title="错误下载路径",
            department_id="dept_digitalization",
            process_name="巡检",
            scenario_name="异常",
            version=1,
            status="active",
            preview_resource_path="preview://digitalization/ok",
            download_pdf_resource_path="preview://digitalization/bad-pdf",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_active_sop_requires_preview_and_download_resources() -> None:
    with pytest.raises(ValueError, match="active SOP requires preview_resource_path"):
        SopRecord(
            sop_id="sop_invalid",
            tenant_id="wl",
            title="无预览资源",
            department_id="dept_digitalization",
            process_name="巡检",
            scenario_name="异常",
            version=1,
            status="active",
            preview_resource_path=None,
            download_docx_resource_path="asset://digitalization/docx",
            download_pdf_resource_path=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
