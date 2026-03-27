from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.rag.rerankers.client import RerankerClient
from backend.app.schemas.chat import ChatRequest
from backend.app.schemas.query_profile import QueryProfile
from backend.app.schemas.retrieval import RetrievalResponse, RetrievedChunk
from backend.app.schemas.system_config import SystemConfigUpdateRequest
from backend.app.services.chat_service import ChatService
from backend.app.services.query_profile_service import QueryProfileService
from backend.app.services.system_config_service import SystemConfigService


def _build_chunks(count: int = 12) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"chunk_{index}",
            document_id=f"doc_{index}",
            document_name=f"文档 {index}",
            text=f"数字化部巡检步骤 {index}，先检查系统状态与告警。",
            score=0.9 - index * 0.01,
            source_path=f"/tmp/doc_{index}.txt",
        )
        for index in range(count)
    ]


class _FakeRetrievalService:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.last_request = None

    def search(self, request, *, auth_context=None):
        self.last_request = request
        return RetrievalResponse(query=request.query, top_k=request.top_k or 0, mode="fake", results=self.results)


class _FakeGenerationClient:
    def __init__(self) -> None:
        self.last_timeout_seconds = None
        self.last_model_name = None

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        self.last_timeout_seconds = timeout_seconds
        self.last_model_name = model_name
        return "基于证据生成的回答"


def test_query_profile_service_resolves_fast_and_accurate_defaults() -> None:
    service = QueryProfileService(Settings(_env_file=None))

    fast_profile = service.resolve(purpose="chat")
    accurate_profile = service.resolve(purpose="sop_generation")

    assert fast_profile.mode == "fast"
    assert fast_profile.top_k == 5
    assert fast_profile.candidate_top_k == 10
    assert fast_profile.rerank_top_n == 3
    assert fast_profile.timeout_budget_seconds == 12.0
    assert fast_profile.fallback_mode is None

    assert accurate_profile.mode == "accurate"
    assert accurate_profile.top_k == 8
    assert accurate_profile.candidate_top_k == 32
    assert accurate_profile.rerank_top_n == 5
    assert accurate_profile.timeout_budget_seconds == 24.0
    assert accurate_profile.fallback_mode == "fast"


def test_query_profile_service_builds_fast_fallback_from_accurate_profile() -> None:
    service = QueryProfileService(Settings(_env_file=None))

    accurate_profile = service.resolve(purpose="chat", requested_mode="accurate", requested_top_k=6)
    fallback_profile = service.build_fallback_profile(accurate_profile)

    assert fallback_profile == QueryProfile(
        purpose="chat",
        mode="fast",
        top_k=6,
        candidate_top_k=12,
        rerank_top_n=3,
        timeout_budget_seconds=12.0,
        fallback_mode=None,
    )


def test_query_profile_service_uses_heuristic_rerank_when_provider_is_unavailable() -> None:
    settings = Settings(_env_file=None, reranker_provider="mock-provider")
    service = QueryProfileService(settings)
    reranker_client = RerankerClient(settings)
    profile = service.resolve(purpose="chat", requested_mode="accurate", requested_top_k=4)

    reranked, strategy = service.rerank_with_fallback(
        query="数字化部巡检步骤",
        candidates=_build_chunks(6),
        profile=profile,
        reranker_client=reranker_client,
    )

    assert strategy == "heuristic"
    assert len(reranked) == 4


def test_query_profile_service_disables_fallbacks_when_system_config_turns_them_off(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        reranker_provider="mock-provider",
    )
    system_config_service = SystemConfigService(settings)
    current_config = system_config_service.get_config(auth_context=_build_sys_admin_context())
    system_config_service.update_config(
        payload=SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing,
            degrade_controls=current_config.degrade_controls.model_copy(
                update={
                    "rerank_fallback_enabled": False,
                    "accurate_to_fast_fallback_enabled": False,
                }
            ),
            retry_controls=current_config.retry_controls,
        ),
        auth_context=_build_sys_admin_context(),
    )
    service = QueryProfileService(settings, system_config_service=system_config_service)
    reranker_client = RerankerClient(settings)
    accurate_profile = service.resolve(purpose="chat", requested_mode="accurate", requested_top_k=4)

    assert service.build_fallback_profile(accurate_profile) is None

    try:
        service.rerank_with_fallback(
            query="数字化部巡检步骤",
            candidates=_build_chunks(6),
            profile=accurate_profile,
            reranker_client=reranker_client,
        )
    except RuntimeError as exc:
        assert "Unsupported reranker provider" in str(exc)
    else:
        raise AssertionError("Expected rerank provider failure when rerank fallback is disabled.")


def test_chat_service_defaults_to_fast_profile_when_request_omits_mode_and_top_k() -> None:
    fake_retrieval = _FakeRetrievalService(_build_chunks())
    fake_generation = _FakeGenerationClient()
    chat_service = ChatService(Settings(_env_file=None))
    chat_service.retrieval_service = fake_retrieval
    chat_service.generation_client = fake_generation

    response = chat_service.answer(ChatRequest(question="数字化部巡检怎么做？"), auth_context=SimpleNamespace())

    assert fake_retrieval.last_request.mode == "fast"
    assert fake_retrieval.last_request.top_k == 5
    assert fake_retrieval.last_request.candidate_top_k == 10
    assert fake_generation.last_timeout_seconds == 12.0
    assert fake_generation.last_model_name == "mock"
    assert response.mode == "rag"
    assert len(response.citations) == 3


def _build_sys_admin_context():
    return SimpleNamespace(
        user=SimpleNamespace(user_id="user_sys_admin", role_id="sys_admin"),
        role=SimpleNamespace(role_id="sys_admin"),
        department=SimpleNamespace(department_id="dept_digitalization"),
        accessible_department_ids=["dept_digitalization"],
    )
