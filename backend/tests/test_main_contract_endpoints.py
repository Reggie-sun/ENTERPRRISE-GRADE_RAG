from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.chat_service import ChatService, get_chat_service
from backend.app.services.document_service import DocumentService, get_document_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.retrieval_service import RetrievalService, get_retrieval_service
from backend.tests.test_document_ingestion import build_test_settings as build_document_settings
from backend.tests.test_event_log_endpoints import _append_record as append_event_log_record
from backend.tests.test_event_log_endpoints import _build_client as build_event_log_client
from backend.tests.test_ops_endpoints import _build_client as build_ops_client
from backend.tests.test_retrieval_chat import build_test_settings as build_retrieval_settings
from backend.tests.test_retrieval_chat import parse_sse_events
from backend.tests.test_sop_endpoints import _build_client as build_sop_asset_client
from backend.tests.test_sop_generation_endpoints import _build_client as build_sop_generation_client
from backend.tests.test_sop_generation_service import _build_identity_service
from backend.tests.test_system_config_endpoints import _build_client as build_system_config_client


def _assert_key_set(payload: dict[str, object], expected: set[str]) -> None:
    assert set(payload.keys()) == expected


def _assert_contains_keys(payload: dict[str, object], required: set[str]) -> None:
    assert required.issubset(set(payload.keys()))


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _build_auth_client(tmp_path: Path) -> TestClient:
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
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    return TestClient(app)


def test_health_and_auth_contract_shapes(tmp_path: Path) -> None:
    client = _build_auth_client(tmp_path)

    try:
        health_response = client.get("/api/v1/health")
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "sys.admin", "password": "sys-admin-pass"},
        )
        token = login_response.json()["access_token"]
        me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()

    assert health_response.status_code == 200
    health_payload = health_response.json()
    _assert_key_set(
        health_payload,
        {"status", "app_name", "environment", "vector_store", "llm", "embedding", "reranker", "queue", "metadata_store", "ocr", "tokenizer"},
    )
    _assert_key_set(health_payload["vector_store"], {"provider", "url", "collection"})
    _assert_key_set(health_payload["llm"], {"provider", "base_url", "model"})
    _assert_key_set(health_payload["embedding"], {"provider", "base_url", "model"})
    _assert_contains_keys(
        health_payload["reranker"],
        {
            "provider",
            "base_url",
            "model",
            "default_strategy",
            "timeout_seconds",
            "failure_cooldown_seconds",
            "effective_provider",
            "effective_model",
            "effective_strategy",
            "fallback_enabled",
            "lock_active",
            "cooldown_remaining_seconds",
            "ready",
        },
    )
    _assert_key_set(
        health_payload["queue"],
        {"provider", "broker_url", "result_backend", "ingest_queue"},
    )
    _assert_key_set(
        health_payload["metadata_store"],
        {"provider", "postgres_enabled", "dsn_configured"},
    )
    _assert_contains_keys(
        health_payload["ocr"],
        {"provider", "language", "enabled", "ready", "pdf_native_text_min_chars", "angle_cls_enabled"},
    )
    _assert_contains_keys(
        health_payload["tokenizer"],
        {"provider", "model", "ready", "trust_remote_code"},
    )

    assert login_response.status_code == 200
    _assert_key_set(
        login_response.json(),
        {"access_token", "token_type", "expires_in_seconds", "user", "role", "department", "accessible_department_ids", "department_query_isolation_enabled"},
    )

    assert me_response.status_code == 200
    _assert_key_set(
        me_response.json(),
        {"user", "role", "department", "accessible_department_ids", "department_query_isolation_enabled"},
    )


def test_documents_and_ingest_contract_shapes(tmp_path: Path) -> None:
    settings = build_document_settings(tmp_path)
    ensure_data_directories(settings)
    document_service = DocumentService(settings)

    app.dependency_overrides[get_document_service] = lambda: document_service
    client = TestClient(app)
    try:
        create_response = client.post(
            "/api/v1/documents",
            data={"tenant_id": "wl", "created_by": "u001"},
            files={"file": ("manual.txt", b"Alarm E102 handling guide.", "text/plain")},
        )
        create_payload = create_response.json()
        detail_response = client.get(f"/api/v1/documents/{create_payload['doc_id']}")
        list_response = client.get("/api/v1/documents?page=1&page_size=20")
        job_response = client.get(f"/api/v1/ingest/jobs/{create_payload['job_id']}")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    _assert_key_set(create_payload, {"document_id", "doc_id", "job_id", "status"})
    assert create_payload["document_id"] == create_payload["doc_id"]

    assert detail_response.status_code == 200
    _assert_key_set(
        detail_response.json(),
        {
            "document_id",
            "doc_id",
            "file_name",
            "status",
            "ingest_status",
            "department_id",
            "category_id",
            "uploaded_by",
            "current_version",
            "latest_job_id",
            "created_at",
            "updated_at",
        },
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()
    _assert_key_set(list_payload, {"total", "page", "page_size", "items"})
    _assert_key_set(
        list_payload["items"][0],
        {
            "document_id",
            "filename",
            "size_bytes",
            "parse_supported",
            "storage_path",
            "status",
            "ingest_status",
            "latest_job_id",
            "department_id",
            "category_id",
            "uploaded_by",
            "updated_at",
        },
    )

    assert job_response.status_code == 200
    _assert_key_set(
        job_response.json(),
        {
            "job_id",
            "document_id",
            "doc_id",
            "status",
            "progress",
            "stage",
            "retry_count",
            "max_retry_limit",
            "auto_retry_eligible",
            "manual_retry_allowed",
            "error_code",
            "error_message",
            "created_at",
            "updated_at",
        },
    )


def test_retrieval_and_chat_contract_shapes(tmp_path: Path) -> None:
    settings = build_retrieval_settings(tmp_path)
    ensure_data_directories(settings)
    document_service = DocumentService(settings)
    retrieval_service = RetrievalService(settings)
    chat_service = ChatService(settings)

    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    client = TestClient(app)

    try:
        upload_response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("guide.txt", b"CPPS guide.\nCPPS means chronic pelvic pain syndrome.", "text/plain")},
        )
        upload_payload = upload_response.json()
        retrieval_response = client.post(
            "/api/v1/retrieval/search",
            json={"query": "what is CPPS", "top_k": 3, "doc_id": upload_payload["document_id"]},
        )
        chat_response = client.post(
            "/api/v1/chat/ask",
            json={"question": "what is CPPS", "top_k": 3, "doc_id": upload_payload["document_id"]},
        )
        with client.stream(
            "POST",
            "/api/v1/chat/ask/stream",
            json={"question": "what is CPPS", "top_k": 3, "doc_id": upload_payload["document_id"]},
        ) as stream_response:
            stream_body = "".join(stream_response.iter_text())
    finally:
        app.dependency_overrides.clear()

    assert upload_response.status_code == 201

    assert retrieval_response.status_code == 200
    retrieval_payload = retrieval_response.json()
    _assert_key_set(retrieval_payload, {"query", "top_k", "mode", "results", "diagnostic"})
    _assert_contains_keys(
        retrieval_payload["results"][0],
        {
            "chunk_id",
            "document_id",
            "document_name",
            "text",
            "score",
            "source_path",
            "retrieval_strategy",
            "ocr_used",
            "parser_name",
            "page_no",
        },
    )

    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    _assert_key_set(chat_payload, {"question", "answer", "mode", "model", "citations"})
    _assert_contains_keys(
        chat_payload["citations"][0],
        {
            "chunk_id",
            "document_id",
            "document_name",
            "snippet",
            "score",
            "source_path",
            "retrieval_strategy",
            "ocr_used",
            "parser_name",
            "page_no",
        },
    )

    assert stream_response.status_code == 200
    events = parse_sse_events(stream_body)
    event_names = [event_name for event_name, _payload in events]
    assert "meta" in event_names
    assert "answer_delta" in event_names
    assert "done" in event_names
    meta_payload = next(payload for event_name, payload in events if event_name == "meta")
    _assert_key_set(meta_payload, {"question", "mode", "model", "citations"})
    delta_payload = next(payload for event_name, payload in events if event_name == "answer_delta")
    _assert_key_set(delta_payload, {"delta"})
    done_payload = next(payload for event_name, payload in events if event_name == "done")
    _assert_key_set(done_payload, {"question", "answer", "mode", "model", "citations"})
    _assert_contains_keys(
        done_payload["citations"][0],
        {
            "chunk_id",
            "document_id",
            "document_name",
            "snippet",
            "score",
            "source_path",
            "retrieval_strategy",
            "ocr_used",
            "parser_name",
            "page_no",
        },
    )


def test_sop_asset_contract_shapes(tmp_path: Path) -> None:
    client, _auth_service = build_sop_asset_client(tmp_path)

    try:
        employee_headers = _login_headers(
            client,
            username="digitalization.employee",
            password="digitalization-employee-pass",
        )
        list_response = client.get("/api/v1/sops?page=1&page_size=20", headers=employee_headers)
        detail_response = client.get("/api/v1/sops/sop_digitalization_daily_inspection", headers=employee_headers)
        preview_response = client.get("/api/v1/sops/sop_digitalization_daily_inspection/preview", headers=employee_headers)
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    list_payload = list_response.json()
    _assert_key_set(list_payload, {"total", "page", "page_size", "items"})
    _assert_key_set(
        list_payload["items"][0],
        {
            "sop_id",
            "title",
            "department_id",
            "department_name",
            "process_name",
            "scenario_name",
            "version",
            "status",
            "preview_available",
            "downloadable_formats",
            "updated_at",
        },
    )

    assert detail_response.status_code == 200
    _assert_key_set(
        detail_response.json(),
        {
            "sop_id",
            "title",
            "tenant_id",
            "department_id",
            "department_name",
            "process_name",
            "scenario_name",
            "version",
            "status",
            "preview_resource_path",
            "preview_resource_type",
            "download_docx_available",
            "download_pdf_available",
            "tags",
            "source_document_id",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        },
    )

    assert preview_response.status_code == 200
    _assert_key_set(
        preview_response.json(),
        {"sop_id", "title", "preview_type", "content_type", "text_content", "preview_file_url", "updated_at"},
    )


def test_sop_generation_contract_shapes(tmp_path: Path) -> None:
    client = build_sop_generation_client(tmp_path)

    try:
        headers = _login_headers(
            client,
            username="digitalization.admin",
            password="digitalization-admin-pass",
        )
        generate_response = client.post(
            "/api/v1/sops/generate/document",
            json={"document_id": "doc_digitalization", "top_k": 4},
            headers=headers,
        )
        export_response = client.post(
            "/api/v1/sops/export",
            json={
                "title": "数字化巡检 SOP 草稿",
                "content": "第一步：检查任务调度服务。",
                "format": "docx",
                "source_document_id": "doc_digitalization",
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert generate_response.status_code == 200
    generate_payload = generate_response.json()
    _assert_key_set(
        generate_payload,
        {
            "snapshot_id",
            "request_mode",
            "generation_mode",
            "title",
            "department_id",
            "department_name",
            "process_name",
            "scenario_name",
            "topic",
            "content",
            "model",
            "citations",
        },
    )
    _assert_contains_keys(
        generate_payload["citations"][0],
        {
            "chunk_id",
            "document_id",
            "document_name",
            "snippet",
            "score",
            "source_path",
            "retrieval_strategy",
            "ocr_used",
            "parser_name",
            "page_no",
        },
    )

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment;" in export_response.headers["content-disposition"]


def test_system_config_logs_and_ops_contract_shapes(tmp_path: Path) -> None:
    config_client = build_system_config_client(tmp_path)
    try:
        sys_admin_headers = _login_headers(config_client, username="sys.admin", password="sys-admin-pass")
        config_response = config_client.get("/api/v1/system-config", headers=sys_admin_headers)
    finally:
        app.dependency_overrides.clear()

    assert config_response.status_code == 200
    config_payload = config_response.json()
    _assert_key_set(
        config_payload,
        {
            "query_profiles",
            "model_routing",
            "reranker_routing",
            "degrade_controls",
            "retry_controls",
            "concurrency_controls",
            "prompt_budget",
            "updated_at",
            "updated_by",
        },
    )
    _assert_key_set(
        config_payload["query_profiles"]["fast"],
        {"top_k_default", "candidate_multiplier", "lexical_top_k", "rerank_top_n", "timeout_budget_seconds"},
    )
    _assert_key_set(
        config_payload["query_profiles"]["accurate"],
        {"top_k_default", "candidate_multiplier", "lexical_top_k", "rerank_top_n", "timeout_budget_seconds"},
    )
    _assert_key_set(
        config_payload["model_routing"],
        {"fast_model", "accurate_model", "sop_generation_model"},
    )
    _assert_key_set(
        config_payload["reranker_routing"],
        {"provider", "default_strategy", "model", "timeout_seconds", "failure_cooldown_seconds"},
    )
    _assert_key_set(
        config_payload["degrade_controls"],
        {"rerank_fallback_enabled", "accurate_to_fast_fallback_enabled", "retrieval_fallback_enabled"},
    )
    _assert_key_set(
        config_payload["retry_controls"],
        {"llm_retry_enabled", "llm_retry_max_attempts", "llm_retry_backoff_ms"},
    )
    _assert_key_set(
        config_payload["concurrency_controls"],
        {
            "fast_max_inflight",
            "accurate_max_inflight",
            "sop_generation_max_inflight",
            "per_user_online_max_inflight",
            "acquire_timeout_ms",
            "busy_retry_after_seconds",
        },
    )
    _assert_key_set(
        config_payload["prompt_budget"],
        {"max_prompt_tokens", "reserved_completion_tokens", "memory_prompt_tokens"},
    )

    log_client, event_log_service = build_event_log_client(tmp_path)
    append_event_log_record(
        event_log_service,
        event_id="evt_contract_1",
        category="chat",
        action="answer",
        outcome="success",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-30T01:00:00+00:00",
        target_id="chat_001",
        rerank_strategy="heuristic",
        rerank_provider="heuristic",
        rerank_model="heuristic",
    )
    try:
        sys_admin_headers = _login_headers(log_client, username="sys.admin", password="sys-admin-pass")
        logs_response = log_client.get("/api/v1/logs?page=1&page_size=20", headers=sys_admin_headers)
    finally:
        app.dependency_overrides.clear()

    assert logs_response.status_code == 200
    logs_payload = logs_response.json()
    _assert_key_set(logs_payload, {"items", "total", "page", "page_size"})
    _assert_contains_keys(
        logs_payload["items"][0],
        {
            "event_id",
            "category",
            "action",
            "outcome",
            "occurred_at",
            "actor",
            "target_id",
            "mode",
            "rerank_strategy",
            "rerank_provider",
            "duration_ms",
            "downgraded_from",
        },
    )
    _assert_key_set(
        logs_payload["items"][0]["actor"],
        {"tenant_id", "user_id", "username", "role_id", "department_id"},
    )

    ops_client, _event_log_service, _request_trace_service, _request_snapshot_service, _rerank_canary_service = build_ops_client(tmp_path)
    try:
        sys_admin_headers = _login_headers(ops_client, username="sys.admin", password="sys-admin-pass")
        ops_response = ops_client.get("/api/v1/ops/summary", headers=sys_admin_headers)
    finally:
        app.dependency_overrides.clear()

    assert ops_response.status_code == 200
    ops_payload = ops_response.json()
    _assert_contains_keys(
        ops_payload,
        {
            "checked_at",
            "health",
            "queue",
            "runtime_gate",
            "recent_window",
            "rerank_usage",
            "rerank_decision",
            "categories",
            "recent_failures",
            "recent_degraded",
            "config",
        },
    )
    _assert_contains_keys(
        ops_payload["queue"],
        {"available", "ingest_queue", "backlog", "error"},
    )
    _assert_contains_keys(
        ops_payload["runtime_gate"],
        {
            "acquire_timeout_ms",
            "busy_retry_after_seconds",
            "per_user_online_max_inflight",
            "active_users",
            "max_user_inflight",
            "channels",
        },
    )
    if ops_payload["runtime_gate"]["channels"]:
        _assert_contains_keys(
            ops_payload["runtime_gate"]["channels"][0],
            {"channel", "inflight", "limit", "available_slots"},
        )
    _assert_contains_keys(
        ops_payload["recent_window"],
        {
            "sample_size",
            "failed_count",
            "timeout_count",
            "downgraded_count",
            "duration_count",
            "duration_p50_ms",
            "duration_p95_ms",
            "duration_p99_ms",
        },
    )
    _assert_contains_keys(
        ops_payload["rerank_usage"],
        {
            "sample_size",
            "provider_count",
            "heuristic_count",
            "skipped_count",
            "document_preview_count",
            "fallback_profile_count",
            "unknown_count",
            "other_count",
        },
    )
    _assert_contains_keys(
        ops_payload["rerank_decision"],
        {
            "decision",
            "message",
            "min_provider_samples",
            "provider_sample_count",
            "heuristic_sample_count",
            "should_promote_to_provider",
            "should_rollback_to_heuristic",
        },
    )
    if ops_payload["categories"]:
        _assert_contains_keys(
            ops_payload["categories"][0],
            {"category", "total", "failed_count", "timeout_count", "downgraded_count"},
        )
    if ops_payload["recent_failures"]:
        _assert_contains_keys(
            ops_payload["recent_failures"][0],
            {
                "event_id",
                "category",
                "action",
                "outcome",
                "occurred_at",
                "actor",
                "target_id",
                "mode",
                "rerank_strategy",
                "rerank_provider",
                "duration_ms",
                "downgraded_from",
            },
        )
    if ops_payload["recent_degraded"]:
        _assert_contains_keys(
            ops_payload["recent_degraded"][0],
            {
                "event_id",
                "category",
                "action",
                "outcome",
                "occurred_at",
                "actor",
                "target_id",
                "mode",
                "rerank_strategy",
                "rerank_provider",
                "duration_ms",
                "downgraded_from",
            },
        )
