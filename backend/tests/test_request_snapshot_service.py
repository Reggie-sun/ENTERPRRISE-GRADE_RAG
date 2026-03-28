from pathlib import Path

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.schemas.auth import AuthContext
from backend.app.schemas.chat import ChatRequest, ChatResponse, Citation
from backend.app.schemas.query_profile import QueryProfile
from backend.app.schemas.request_snapshot import RequestSnapshotReplayResponse
from backend.app.schemas.sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerationDraftResponse,
)
from backend.app.services.auth_service import AuthService
from backend.app.services.request_snapshot_service import RequestSnapshotService
from backend.tests.test_sop_generation_service import _build_identity_service


class _FakeChatService:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def answer(self, request: ChatRequest, *, auth_context: AuthContext | None = None) -> ChatResponse:
        self.requests.append(request.model_copy(deep=True))
        return ChatResponse(
            question=request.question,
            answer=f"replayed via {request.mode or 'default'} / top_k={request.top_k}",
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
            content=f"replayed sop via {request.mode or 'default'} / top_k={request.top_k}",
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
        embedding_provider="openai",
        embedding_model="bge-m3",
        reranker_provider="heuristic",
        reranker_model="bge-reranker",
    )


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


def test_record_chat_snapshot_persists_context_and_versions(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    service = RequestSnapshotService(settings)
    auth_context = _build_auth_context(tmp_path, username="digitalization.admin", password="digitalization-admin-pass")

    record = service.record_chat_snapshot(
        trace_id="trc_test_001",
        request_id="req_test_001",
        action="answer",
        outcome="success",
        request=ChatRequest(question="数字化部如何处理设备异常？", document_id="doc_001"),
        profile=QueryProfile(
            purpose="chat",
            mode="accurate",
            top_k=8,
            candidate_top_k=16,
            rerank_top_n=5,
            timeout_budget_seconds=24.0,
            fallback_mode="fast",
        ),
        auth_context=auth_context,
        citations=[
            Citation(
                chunk_id="chunk_001",
                document_id="doc_001",
                document_name="异常处理规范.docx",
                snippet="发现设备异常后先执行停机检查。",
                score=0.95,
                source_path="asset://doc_001",
                retrieval_strategy="hybrid",
                vector_score=0.88,
                lexical_score=2.1,
                fused_score=0.95,
            )
        ],
        response_mode="rag",
        rerank_strategy="provider",
        model="Qwen/Test-14B",
        answer_text="先停机，再检查报警信息。",
    )

    persisted = service.get_snapshot(record.snapshot_id, auth_context=auth_context)
    assert persisted.trace_id == "trc_test_001"
    assert persisted.contexts[0].chunk_id == "chunk_001"
    assert persisted.contexts[0].retrieval_strategy == "hybrid"
    assert persisted.contexts[0].vector_score == 0.88
    assert persisted.contexts[0].lexical_score == 2.1
    assert persisted.contexts[0].fused_score == 0.95
    assert persisted.citations[0].retrieval_strategy == "hybrid"
    assert persisted.component_versions.prompt_version == "chat-rag-v1"
    assert persisted.model_route.model == "Qwen/Test-14B"
    assert persisted.result.answer_preview == "先停机，再检查报警信息。"


def test_replay_snapshot_supports_original_and_current_modes(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    service = RequestSnapshotService(settings)
    auth_context = _build_auth_context(tmp_path, username="sys.admin", password="sys-admin-pass")
    fake_chat_service = _FakeChatService()

    record = service.record_chat_snapshot(
        trace_id="trc_test_002",
        request_id="req_test_002",
        action="answer",
        outcome="success",
        request=ChatRequest(question="数字化部如何上报异常？"),
        profile=QueryProfile(
            purpose="chat",
            mode="accurate",
            top_k=7,
            candidate_top_k=14,
            rerank_top_n=5,
            timeout_budget_seconds=24.0,
            fallback_mode="fast",
        ),
        auth_context=auth_context,
        citations=[],
        response_mode="rag",
        rerank_strategy="heuristic",
        model="Qwen/Test-14B",
        answer_text="通过系统异常工单流程上报。",
    )

    original = service.replay_snapshot(
        snapshot_id=record.snapshot_id,
        replay_mode="original",
        auth_context=auth_context,
        chat_service=fake_chat_service,
        sop_generation_service=_FakeSopGenerationService(),
    )
    current = service.replay_snapshot(
        snapshot_id=record.snapshot_id,
        replay_mode="current",
        auth_context=auth_context,
        chat_service=fake_chat_service,
        sop_generation_service=_FakeSopGenerationService(),
    )

    assert isinstance(original, RequestSnapshotReplayResponse)
    assert original.replayed_request.mode == "accurate"
    assert original.replayed_request.top_k == 7
    assert current.replayed_request.mode is None
    assert current.replayed_request.top_k is None
    assert fake_chat_service.requests[0].mode == "accurate"
    assert fake_chat_service.requests[1].mode is None


def test_replay_sop_snapshot_supports_original_and_current_modes(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    ensure_data_directories(settings)
    service = RequestSnapshotService(settings)
    auth_context = _build_auth_context(tmp_path, username="sys.admin", password="sys-admin-pass")
    fake_chat_service = _FakeChatService()
    fake_sop_generation_service = _FakeSopGenerationService()

    record = service.record_sop_snapshot(
        request_mode="document",
        outcome="success",
        request=SopGenerateByDocumentRequest(document_id="doc_001", process_name="巡检"),
        profile=QueryProfile(
            purpose="sop_generation",
            mode="accurate",
            top_k=9,
            candidate_top_k=18,
            rerank_top_n=6,
            timeout_budget_seconds=24.0,
            fallback_mode="fast",
        ),
        auth_context=auth_context,
        citations=[],
        response=SopGenerationDraftResponse(
            request_mode="document",
            generation_mode="rag",
            title="原始 SOP 草稿",
            department_id="dept_digitalization",
            department_name="数字化部",
            process_name="巡检",
            scenario_name=None,
            topic="来源文档",
            content="请根据文档生成 SOP。",
            model="Qwen/Test-14B",
            citations=[],
        ),
        rerank_strategy="heuristic",
        model="Qwen/Test-14B",
        content="请根据文档生成 SOP。",
    )

    original = service.replay_snapshot(
        snapshot_id=record.snapshot_id,
        replay_mode="original",
        auth_context=auth_context,
        chat_service=fake_chat_service,
        sop_generation_service=fake_sop_generation_service,
    )
    current = service.replay_snapshot(
        snapshot_id=record.snapshot_id,
        replay_mode="current",
        auth_context=auth_context,
        chat_service=fake_chat_service,
        sop_generation_service=fake_sop_generation_service,
    )

    assert isinstance(original, RequestSnapshotReplayResponse)
    assert original.replayed_request.mode == "accurate"
    assert original.replayed_request.top_k == 9
    assert current.replayed_request.mode is None
    assert current.replayed_request.top_k is None
    assert original.response.request_mode == "document"
    assert fake_sop_generation_service.requests[0].mode == "accurate"
    assert fake_sop_generation_service.requests[1].mode is None
