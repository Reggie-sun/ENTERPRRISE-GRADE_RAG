from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.event_log import EventLogActor, EventLogRecord
from backend.app.schemas.document import DocumentRecord, IngestJobRecord
from backend.app.schemas.ops import OpsQueueSummary
from backend.app.schemas.request_snapshot import (
    RequestSnapshotComponentVersions,
    RequestSnapshotModelRoute,
    RequestSnapshotRecord,
    RequestSnapshotResult,
    RequestSnapshotRewrite,
)
from backend.app.schemas.request_trace import RequestTraceRecord, RequestTraceStage
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.event_log_service import EventLogService
from backend.app.services.identity_service import get_identity_service
from backend.app.services.ops_service import OpsService, get_ops_service
from backend.app.services.request_snapshot_service import RequestSnapshotService
from backend.app.services.request_trace_service import RequestTraceService
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
        request_trace_dir=data_dir / "request_traces",
        request_snapshot_dir=data_dir / "request_snapshots",
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
    target_id: str,
    duration_ms: int,
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
            target_id=target_id,
            mode="accurate",
            top_k=8,
            candidate_top_k=16,
            rerank_top_n=5,
            total_duration_ms=duration_ms,
            response_mode="rag",
            stages=[
                RequestTraceStage(stage="retrieval", status="success", duration_ms=40, input_size=12, output_size=5),
                RequestTraceStage(stage="rerank", status="degraded", duration_ms=10, input_size=5, output_size=3),
                RequestTraceStage(stage="llm", status="success", duration_ms=70, input_size=3, output_size=200),
                RequestTraceStage(stage="answer", status="success", duration_ms=0, input_size=3, output_size=200),
            ],
            details={"source": "test"},
        )
    )


def _append_snapshot(
    request_snapshot_service: RequestSnapshotService,
    *,
    snapshot_id: str,
    trace_id: str,
    request_id: str,
    username: str,
    user_id: str,
    role_id: str,
    department_id: str,
    occurred_at: str,
    target_id: str,
) -> None:
    request_snapshot_service.repository.append(
        RequestSnapshotRecord(
            snapshot_id=snapshot_id,
            trace_id=trace_id,
            request_id=request_id,
            category="chat",
            action="answer",
            outcome="success",
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
            request={"question": "数字化部如何处理异常？", "document_id": target_id},
            profile={
                "purpose": "chat",
                "mode": "accurate",
                "top_k": 8,
                "candidate_top_k": 16,
                "rerank_top_n": 5,
                "timeout_budget_seconds": 24.0,
                "fallback_mode": "fast",
            },
            memory_summary=None,
            rewrite=RequestSnapshotRewrite(
                status="skipped",
                original_question="数字化部如何处理异常？",
                rewritten_question=None,
                details={"reason": "query rewrite is not enabled in the current V1 slice."},
            ),
            contexts=[],
            citations=[],
            model_route=RequestSnapshotModelRoute(
                provider="openai",
                base_url="http://llm.test/v1",
                model="Qwen/Test-7B",
            ),
            component_versions=RequestSnapshotComponentVersions(
                prompt_version="chat-rag-v1",
                embedding_provider="openai",
                embedding_model="bge-m3",
                reranker_provider="heuristic",
                reranker_model="bge-reranker",
            ),
            result=RequestSnapshotResult(
                response_mode="rag",
                model="Qwen/Test-7B",
                answer_preview="先停机再检查。",
                answer_chars=8,
                citation_count=0,
                rerank_strategy="heuristic",
            ),
            details={"source": "test"},
        )
    )


def _build_client(tmp_path: Path) -> tuple[TestClient, EventLogService, RequestTraceService, RequestSnapshotService]:
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
    request_trace_service = RequestTraceService(settings)
    request_snapshot_service = RequestSnapshotService(settings)
    system_config_service = SystemConfigService(settings)
    ops_service = OpsService(
        settings,
        event_log_service=event_log_service,
        request_trace_service=request_trace_service,
        request_snapshot_service=request_snapshot_service,
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
    return TestClient(app), event_log_service, request_trace_service, request_snapshot_service


def _persist_document_with_job(
    tmp_path: Path,
    *,
    doc_id: str,
    job_id: str,
    file_name: str,
    department_id: str,
    updated_at: str,
    document_status: str = "queued",
    job_status: str = "queued",
    stage: str = "queued",
    progress: int = 0,
    with_artifacts: bool = False,
) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    timestamp = datetime.fromisoformat(updated_at).astimezone(timezone.utc)
    document = DocumentRecord(
        doc_id=doc_id,
        tenant_id="wl",
        file_name=file_name,
        file_hash=f"hash-{doc_id}",
        source_type="docx",
        department_id=department_id,
        department_ids=[department_id],
        visibility="department",
        classification="internal",
        status=document_status,  # type: ignore[arg-type]
        latest_job_id=job_id,
        storage_path=str(settings.upload_dir / f"{doc_id}__source.docx"),
        created_at=timestamp,
        updated_at=timestamp,
    )
    job = IngestJobRecord(
        job_id=job_id,
        doc_id=doc_id,
        version=1,
        file_name=file_name,
        status=job_status,  # type: ignore[arg-type]
        stage=stage,
        progress=progress,
        created_at=timestamp,
        updated_at=timestamp,
    )
    (settings.document_dir / f"{doc_id}.json").write_text(document.model_dump_json(indent=2), encoding="utf-8")
    (settings.job_dir / f"{job_id}.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")
    if with_artifacts:
        (settings.parsed_dir / f"{doc_id}.txt").write_text("parsed text ready", encoding="utf-8")


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_ops_summary_returns_runtime_snapshot_for_sys_admin(tmp_path: Path) -> None:
    client, event_log_service, request_trace_service, request_snapshot_service = _build_client(tmp_path)
    _persist_document_with_job(
        tmp_path,
        doc_id="doc_stuck_1",
        job_id="job_stuck_1",
        file_name="数字化交接班.docx",
        department_id="dept_digitalization",
        updated_at="2020-01-01T00:00:00+00:00",
        document_status="queued",
        job_status="queued",
        stage="queued",
        progress=0,
        with_artifacts=True,
    )
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
    _append_trace(
        request_trace_service,
        trace_id="trc_chat_2",
        request_id="req_chat_2",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:01:00+00:00",
        outcome="failed",
        target_id="chat_002",
        duration_ms=240,
    )
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_chat_2",
        trace_id="trc_chat_2",
        request_id="req_chat_2",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:01:00+00:00",
        target_id="chat_002",
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
    assert payload["runtime_gate"]["acquire_timeout_ms"] == 800
    assert payload["runtime_gate"]["busy_retry_after_seconds"] == 5
    assert payload["runtime_gate"]["per_user_online_max_inflight"] == 3
    assert payload["runtime_gate"]["active_users"] == 0
    assert payload["runtime_gate"]["max_user_inflight"] == 0
    assert payload["runtime_gate"]["channels"][0]["channel"] == "chat_fast"
    assert isinstance(payload["health"]["reranker"]["effective_provider"], str)
    assert isinstance(payload["health"]["reranker"]["effective_model"], str)
    assert isinstance(payload["health"]["reranker"]["effective_strategy"], str)
    assert isinstance(payload["health"]["reranker"]["fallback_enabled"], bool)
    assert isinstance(payload["health"]["reranker"]["failure_cooldown_seconds"], (int, float))
    assert isinstance(payload["health"]["reranker"]["lock_active"], bool)
    assert payload["health"]["reranker"]["lock_source"] is None or isinstance(payload["health"]["reranker"]["lock_source"], str)
    assert isinstance(payload["health"]["reranker"]["cooldown_remaining_seconds"], (int, float))
    assert payload["recent_window"]["sample_size"] == 2
    assert payload["stuck_ingest_jobs"][0]["doc_id"] == "doc_stuck_1"
    assert payload["stuck_ingest_jobs"][0]["reason"] == "artifacts_ready_but_inflight"
    assert payload["stuck_ingest_jobs"][0]["has_materialized_artifacts"] is True
    assert payload["recent_window"]["failed_count"] == 1
    assert payload["recent_window"]["timeout_count"] == 1
    assert payload["recent_window"]["downgraded_count"] == 1
    assert payload["recent_window"]["duration_p95_ms"] == 240
    assert payload["config"]["model_routing"]["fast_model"] == "Qwen/Test-7B"
    assert payload["recent_failures"][0]["event_id"] == "evt_chat_2"
    assert payload["recent_degraded"][0]["event_id"] == "evt_chat_2"
    assert payload["recent_traces"][0]["trace_id"] == "trc_chat_2"
    assert payload["recent_traces"][0]["stages"][1]["status"] == "degraded"
    assert payload["recent_snapshots"][0]["snapshot_id"] == "rsp_chat_2"


def test_ops_summary_scopes_logs_for_department_admin(tmp_path: Path) -> None:
    client, event_log_service, request_trace_service, request_snapshot_service = _build_client(tmp_path)
    _persist_document_with_job(
        tmp_path,
        doc_id="doc_scope_visible",
        job_id="job_scope_visible",
        file_name="数字化异常处理.docx",
        department_id="dept_digitalization",
        updated_at="2020-01-01T00:00:00+00:00",
        document_status="queued",
        job_status="queued",
        stage="queued",
        progress=0,
        with_artifacts=False,
    )
    _persist_document_with_job(
        tmp_path,
        doc_id="doc_scope_hidden",
        job_id="job_scope_hidden",
        file_name="装配异常处理.docx",
        department_id="dept_assembly",
        updated_at="2020-01-01T00:00:00+00:00",
        document_status="queued",
        job_status="queued",
        stage="queued",
        progress=0,
        with_artifacts=True,
    )
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
    _append_trace(
        request_trace_service,
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:00:00+00:00",
        outcome="success",
        target_id="doc_001",
        duration_ms=80,
    )
    _append_trace(
        request_trace_service,
        trace_id="trc_other_1",
        request_id="req_other_1",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-27T01:01:00+00:00",
        outcome="failed",
        target_id="doc_002",
        duration_ms=140,
    )
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_digitalization_1",
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T01:00:00+00:00",
        target_id="doc_001",
    )
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_other_1",
        trace_id="trc_other_1",
        request_id="req_other_1",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-27T01:01:00+00:00",
        target_id="doc_002",
    )

    try:
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/ops/summary", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_gate"]["channels"][2]["channel"] == "sop_generation"
    assert payload["recent_window"]["sample_size"] == 1
    assert payload["categories"][1]["category"] == "document"
    assert payload["categories"][1]["total"] == 1
    assert len(payload["stuck_ingest_jobs"]) == 1
    assert payload["stuck_ingest_jobs"][0]["doc_id"] == "doc_scope_visible"
    assert payload["stuck_ingest_jobs"][0]["reason"] == "stale_inflight"
    assert payload["recent_failures"] == []
    assert payload["recent_traces"][0]["trace_id"] == "trc_digitalization_1"
    assert payload["recent_snapshots"][0]["snapshot_id"] == "rsp_digitalization_1"


def test_ops_summary_rejects_employee_access(tmp_path: Path) -> None:
    client, _, _, _ = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="digitalization.employee", password="digitalization-employee-pass")
        response = client.get("/api/v1/ops/summary", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to runtime operations."
