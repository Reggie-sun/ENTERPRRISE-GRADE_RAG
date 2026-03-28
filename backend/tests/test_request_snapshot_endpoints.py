from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.main import app
from backend.app.schemas.auth import AuthContext
from backend.app.schemas.chat import ChatRequest, ChatResponse
from backend.app.schemas.event_log import EventLogActor
from backend.app.schemas.query_profile import QueryProfile
from backend.app.schemas.request_snapshot import (
    RequestSnapshotComponentVersions,
    RequestSnapshotModelRoute,
    RequestSnapshotRecord,
    RequestSnapshotResult,
    RequestSnapshotRewrite,
)
from backend.app.schemas.sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerationDraftResponse,
)
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.chat_service import get_chat_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.request_snapshot_service import RequestSnapshotService, get_request_snapshot_service
from backend.app.services.sop_generation_service import get_sop_generation_service
from backend.tests.test_sop_generation_service import _build_identity_service


class _FakeChatService:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def answer(self, request: ChatRequest, *, auth_context: AuthContext | None = None) -> ChatResponse:
        self.requests.append(request.model_copy(deep=True))
        return ChatResponse(
            question=request.question,
            answer=f"replayed:{request.mode or 'default'}:{request.top_k}",
            mode="rag",
            model="fake",
            citations=[],
        )


class _FakeSopGenerationService:
    def __init__(self) -> None:
        self.requests: list[SopGenerateByDocumentRequest] = []

    def generate_from_document(
        self,
        request: SopGenerateByDocumentRequest,
        *,
        auth_context: AuthContext | None = None,
    ) -> SopGenerationDraftResponse:
        self.requests.append(request.model_copy(deep=True))
        return SopGenerationDraftResponse(
            request_mode="document",
            generation_mode="rag",
            title="重放后的 SOP 草稿",
            department_id=auth_context.department.department_id if auth_context else "dept_digitalization",
            department_name=auth_context.department.department_name if auth_context else "数字化部",
            process_name=request.process_name,
            scenario_name=request.scenario_name,
            topic="来源文档",
            content=f"sop-replayed:{request.mode or 'default'}:{request.top_k}",
            model="fake",
            citations=[],
        )


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
        request_snapshot_dir=data_dir / "request_snapshots",
        llm_provider="openai",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Test-14B",
    )


def _build_client(tmp_path: Path) -> tuple[TestClient, RequestSnapshotService, _FakeChatService, _FakeSopGenerationService]:
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
    request_snapshot_service = RequestSnapshotService(settings)
    fake_chat_service = _FakeChatService()
    fake_sop_generation_service = _FakeSopGenerationService()

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_request_snapshot_service] = lambda: request_snapshot_service
    app.dependency_overrides[get_chat_service] = lambda: fake_chat_service
    app.dependency_overrides[get_sop_generation_service] = lambda: fake_sop_generation_service
    return TestClient(app), request_snapshot_service, fake_chat_service, fake_sop_generation_service


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _build_auth_context(tmp_path: Path, *, username: str, password: str) -> AuthContext:
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
    login_response = auth_service.login(username, password)
    return auth_service.build_auth_context(login_response.access_token)


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
            target_id="doc_001",
            request=ChatRequest(question="数字化部如何处理异常？", session_id="sess_chat_001"),
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
                model="Qwen/Test-14B",
            ),
            component_versions=RequestSnapshotComponentVersions(
                prompt_version="chat-rag-v1",
                embedding_provider="mock",
                embedding_model="bge-m3",
                reranker_provider="heuristic",
                reranker_model="bge-reranker",
            ),
            result=RequestSnapshotResult(
                response_mode="rag",
                model="Qwen/Test-14B",
                answer_preview="先停机再检查。",
                answer_chars=8,
                citation_count=0,
                rerank_strategy="heuristic",
            ),
            details={"source": "test"},
        )
    )


def test_request_snapshot_list_endpoint_filters_department_admin_scope(tmp_path: Path) -> None:
    client, request_snapshot_service, _, _ = _build_client(tmp_path)
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_digitalization_1",
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="digitalization.admin",
        user_id="user_digitalization_admin",
        role_id="department_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T08:00:00+00:00",
    )
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_assembly_1",
        trace_id="trc_assembly_1",
        request_id="req_assembly_1",
        username="assembly.admin",
        user_id="user_assembly_admin",
        role_id="department_admin",
        department_id="dept_assembly",
        occurred_at="2026-03-27T09:00:00+00:00",
    )

    try:
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/request-snapshots?page=1&page_size=20", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["snapshot_id"] == "rsp_digitalization_1"


def test_request_snapshot_replay_endpoint_supports_original_and_current_modes(tmp_path: Path) -> None:
    client, request_snapshot_service, fake_chat_service, _ = _build_client(tmp_path)
    _append_snapshot(
        request_snapshot_service,
        snapshot_id="rsp_digitalization_1",
        trace_id="trc_digitalization_1",
        request_id="req_digitalization_1",
        username="sys.admin",
        user_id="user_sys_admin",
        role_id="sys_admin",
        department_id="dept_digitalization",
        occurred_at="2026-03-27T08:00:00+00:00",
    )

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        original = client.post(
            "/api/v1/request-snapshots/rsp_digitalization_1/replay",
            json={"replay_mode": "original"},
            headers=headers,
        )
        current = client.post(
            "/api/v1/request-snapshots/rsp_digitalization_1/replay",
            json={"replay_mode": "current"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert original.status_code == 200
    assert current.status_code == 200
    assert original.json()["replayed_request"]["mode"] == "accurate"
    assert original.json()["replayed_request"]["top_k"] == 8
    assert original.json()["replayed_request"]["session_id"] is None
    assert current.json()["replayed_request"]["mode"] is None
    assert current.json()["replayed_request"]["top_k"] is None
    assert current.json()["replayed_request"]["session_id"] is None
    assert fake_chat_service.requests[0].mode == "accurate"
    assert fake_chat_service.requests[1].mode is None


def test_request_snapshot_replay_endpoint_supports_sop_generation_snapshots(tmp_path: Path) -> None:
    client, request_snapshot_service, _, fake_sop_generation_service = _build_client(tmp_path)
    request_snapshot_service.record_sop_snapshot(
        request_mode="document",
        outcome="success",
        request=SopGenerateByDocumentRequest(document_id="doc_digitalization", process_name="巡检"),
        profile=QueryProfile(
            purpose="sop_generation",
            mode="accurate",
            top_k=9,
            candidate_top_k=18,
            rerank_top_n=6,
            timeout_budget_seconds=24.0,
            fallback_mode="fast",
        ),
        auth_context=_build_auth_context(tmp_path, username="sys.admin", password="sys-admin-pass"),
        citations=[],
        response=SopGenerationDraftResponse(
            request_mode="document",
            generation_mode="rag",
            title="数字化部 SOP 草稿",
            department_id="dept_digitalization",
            department_name="数字化部",
            process_name="巡检",
            scenario_name=None,
            topic="来源文档",
            content="原始 SOP 内容",
            model="Qwen/Test-14B",
            citations=[],
        ),
        rerank_strategy="heuristic",
        model="Qwen/Test-14B",
        content="原始 SOP 内容",
    )
    snapshot_id = request_snapshot_service.repository.list_records(limit=1)[0].snapshot_id

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        original = client.post(
            f"/api/v1/request-snapshots/{snapshot_id}/replay",
            json={"replay_mode": "original"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert original.status_code == 200
    assert original.json()["replayed_request"]["mode"] == "accurate"
    assert original.json()["response"]["request_mode"] == "document"
    assert original.json()["response"]["content"] == "sop-replayed:accurate:9"
    assert fake_sop_generation_service.requests[0].mode == "accurate"
