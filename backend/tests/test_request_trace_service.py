from types import SimpleNamespace

from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.schemas.request_trace import RequestTraceStage
from backend.app.services.request_trace_service import RequestTraceService


def _build_auth_context(*, role_id: str, department_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(
            tenant_id="wl",
            user_id=f"user_{role_id}",
            username=f"{role_id}.demo",
            role_id=role_id,
            department_id=department_ids[0],
        ),
        role=SimpleNamespace(data_scope="global" if role_id == "sys_admin" else "department"),
        accessible_department_ids=department_ids,
    )


def test_request_trace_service_records_and_filters_by_scope(tmp_path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    service = RequestTraceService(settings)
    service.record(
        trace_id="trc_1",
        request_id="req_1",
        category="chat",
        action="answer",
        outcome="success",
        auth_context=_build_auth_context(role_id="department_admin", department_ids=["dept_digitalization"]),
        target_type="document",
        target_id="doc_001",
        mode="accurate",
        top_k=8,
        candidate_top_k=16,
        rerank_top_n=5,
        total_duration_ms=120,
        response_mode="rag",
        stages=[RequestTraceStage(stage="retrieval", status="success", duration_ms=30, input_size=10, output_size=4)],
        details={"source": "test"},
    )
    service.record(
        trace_id="trc_2",
        request_id="req_2",
        category="chat",
        action="answer",
        outcome="failed",
        auth_context=_build_auth_context(role_id="department_admin", department_ids=["dept_assembly"]),
        target_type="document",
        target_id="doc_002",
        mode="fast",
        top_k=5,
        candidate_top_k=10,
        rerank_top_n=3,
        total_duration_ms=80,
        response_mode="failed",
        error_message="boom",
        stages=[RequestTraceStage(stage="retrieval", status="failed", duration_ms=10, input_size=8, output_size=0)],
        details={"source": "test"},
    )

    traces = service.list_recent(
        auth_context=_build_auth_context(role_id="department_admin", department_ids=["dept_digitalization"]),
        limit=10,
    )
    assert len(traces) == 1
    assert traces[0].trace_id == "trc_1"


def test_request_trace_service_rejects_employee_access(tmp_path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    service = RequestTraceService(settings)

    try:
        service.list_traces(
            auth_context=_build_auth_context(role_id="employee", department_ids=["dept_digitalization"]),
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "You do not have access to request traces."
    else:
        raise AssertionError("Expected employee trace query to be rejected.")
