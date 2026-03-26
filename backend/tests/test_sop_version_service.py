from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.schemas.sop_generation import SopGenerationCitation
from backend.app.schemas.sop_version import SopSaveRequest
from backend.app.services.identity_service import IdentityService
from backend.app.services.sop_service import SopService
from backend.app.services.sop_version_service import SopVersionService
from backend.tests.test_sop_service import _build_auth_context, _build_identity_service, _write_sop_bootstrap


def _build_services(tmp_path: Path) -> tuple[IdentityService, SopService, SopVersionService]:
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
    sop_service = SopService(settings, identity_service=identity_service)
    sop_version_service = SopVersionService(settings, identity_service=identity_service, sop_service=sop_service)
    return identity_service, sop_service, sop_version_service


def test_sop_version_service_saves_new_sop_and_lists_versions(tmp_path: Path) -> None:
    identity_service, sop_service, sop_version_service = _build_services(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="sys.admin",
        password="sys-admin-pass",
    )

    response = sop_version_service.save_sop(
        SopSaveRequest(
            title="数字化部巡检草稿",
            department_id="dept_digitalization",
            process_name="巡检",
            scenario_name="日常维护",
            content="步骤一：检查调度服务。步骤二：核对数据库连接。",
            request_mode="topic",
            generation_mode="rag",
            citations=[
                SopGenerationCitation(
                    chunk_id="chunk_1",
                    document_id="doc_1",
                    document_name="数字化巡检手册",
                    snippet="检查调度服务与数据库连接。",
                    score=0.91,
                    source_path="/tmp/doc_1.txt",
                )
            ],
        ),
        auth_context=auth_context,
    )

    saved_detail = sop_service.get_sop(response.sop_id, auth_context=auth_context)
    versions = sop_version_service.list_versions(response.sop_id, auth_context=auth_context)
    version_detail = sop_version_service.get_version_detail(response.sop_id, 1, auth_context=auth_context)

    assert response.version == 1
    assert saved_detail.title == "数字化部巡检草稿"
    assert saved_detail.version == 1
    assert versions.current_version == 1
    assert [item.version for item in versions.items] == [1]
    assert versions.items[0].citations_count == 1
    assert version_detail.content.startswith("步骤一")
    assert version_detail.citations[0].document_id == "doc_1"


def test_sop_version_service_increments_version_and_keeps_bootstrap_history(tmp_path: Path) -> None:
    identity_service, _, sop_version_service = _build_services(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="sys.admin",
        password="sys-admin-pass",
    )

    response = sop_version_service.save_sop(
        SopSaveRequest(
            sop_id="sop_digitalization_daily_inspection",
            title="数字化部系统巡检 SOP",
            content="新的 v3 内容",
            status="active",
            request_mode="scenario",
            generation_mode="rag",
        ),
        auth_context=auth_context,
    )

    versions = sop_version_service.list_versions("sop_digitalization_daily_inspection", auth_context=auth_context)
    bootstrap_detail = sop_version_service.get_version_detail("sop_digitalization_daily_inspection", 2, auth_context=auth_context)
    saved_detail = sop_version_service.get_version_detail("sop_digitalization_daily_inspection", 3, auth_context=auth_context)

    assert response.version == 3
    assert [item.version for item in versions.items] == [3, 2]
    assert versions.items[0].is_current is True
    assert bootstrap_detail.generation_mode == "bootstrap"
    assert "检查任务调度服务状态" in bootstrap_detail.content
    assert saved_detail.content == "新的 v3 内容"


def test_sop_version_service_blocks_employee_save(tmp_path: Path) -> None:
    identity_service, _, sop_version_service = _build_services(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="digitalization.employee",
        password="digitalization-employee-pass",
    )

    with pytest.raises(HTTPException) as exc_info:
        sop_version_service.save_sop(
            SopSaveRequest(title="员工不允许保存", content="test"),
            auth_context=auth_context,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Current role cannot save SOPs."


def test_sop_version_service_blocks_department_change_on_existing_sop(tmp_path: Path) -> None:
    identity_service, _, sop_version_service = _build_services(tmp_path)
    auth_context = _build_auth_context(
        identity_service,
        username="sys.admin",
        password="sys-admin-pass",
    )

    with pytest.raises(HTTPException) as exc_info:
        sop_version_service.save_sop(
            SopSaveRequest(
                sop_id="sop_digitalization_daily_inspection",
                title="跨部门变更",
                content="test",
                department_id="dept_assembly",
            ),
            auth_context=auth_context,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "department_id cannot be changed when saving a new version of an existing SOP."
