from pathlib import Path
import httpx
import pytest

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.rag.rerankers.client import RerankerClient
from backend.app.schemas.chat import ChatRequest
from backend.app.schemas.retrieval import RetrievalResponse
from backend.app.schemas.retrieval import RetrievedChunk
from backend.app.services.chat_service import ChatService
from backend.app.services.query_profile_service import QueryProfileService
from backend.app.services.system_config_service import SystemConfigService
from backend.app.schemas.system_config import (
    ConcurrencyControlsConfig,
    DegradeControlsConfig,
    ModelRoutingConfig,
    QueryModeConfig,
    QueryProfilesConfig,
    RerankerRoutingConfig,
    RetryControlsConfig,
    SystemConfigUpdateRequest,
)
from backend.tests.test_system_config_service import _build_auth_context


@pytest.fixture(autouse=True)
def _reset_reranker_route_health_cache() -> None:
    RerankerClient._ROUTE_HEALTH_CACHE.clear()
    yield
    RerankerClient._ROUTE_HEALTH_CACHE.clear()


def _build_settings(tmp_path: Path, **overrides) -> Settings:
    data_dir = tmp_path / "data"
    payload = {
        "_env_file": None,
        "data_dir": data_dir,
        "upload_dir": data_dir / "uploads",
        "parsed_dir": data_dir / "parsed",
        "chunk_dir": data_dir / "chunks",
        "ocr_artifact_dir": data_dir / "ocr_artifacts",
        "document_dir": data_dir / "documents",
        "job_dir": data_dir / "jobs",
        "event_log_dir": data_dir / "event_logs",
        "request_trace_dir": data_dir / "request_traces",
        "request_snapshot_dir": data_dir / "request_snapshots",
        "system_config_path": tmp_path / "data" / "system_config.json",
        "postgres_metadata_enabled": False,
        "postgres_metadata_dsn": None,
        "llm_provider": "mock",
        "reranker_provider": "heuristic",
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_timeout_seconds": 12.0,
    }
    payload.update(overrides)
    return Settings(
        **payload,
    )


def _build_candidates() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="chunk_1",
            document_id="doc_1",
            document_name="设备告警处理手册",
            text="alarm E201 发生后先检查温控模块和线缆连接。",
            score=0.91,
            source_path="/tmp/doc_1.txt",
        ),
        RetrievedChunk(
            chunk_id="chunk_2",
            document_id="doc_2",
            document_name="伺服维修指南",
            text="servo reset 前先确认急停释放，再重新上电。",
            score=0.86,
            source_path="/tmp/doc_2.txt",
        ),
        RetrievedChunk(
            chunk_id="chunk_3",
            document_id="doc_3",
            document_name="真空阀排障记录",
            text="vacuum valve 异常时检查阀体污染和供气压力。",
            score=0.82,
            source_path="/tmp/doc_3.txt",
        ),
    ]


class _FakeRetrievalService:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results

    def search(self, request, *, auth_context=None):
        return RetrievalResponse(query=request.query, top_k=request.top_k or 0, mode="fake", results=self.results)


class _FakeGenerationClient:
    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        return "基于证据生成的回答"


def _persist_openai_reranker_route(system_config_service: SystemConfigService) -> None:
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=QueryProfilesConfig(
                fast=QueryModeConfig(top_k_default=5, candidate_multiplier=2, lexical_top_k=10, rerank_top_n=3, timeout_budget_seconds=12.0),
                accurate=QueryModeConfig(top_k_default=8, candidate_multiplier=4, lexical_top_k=32, rerank_top_n=5, timeout_budget_seconds=24.0),
            ),
            model_routing=ModelRoutingConfig(
                fast_model="Qwen/Fast-7B",
                accurate_model="Qwen/Accurate-14B",
                sop_generation_model="Qwen/SOP-14B",
            ),
            reranker_routing=RerankerRoutingConfig(
                provider="openai_compatible",
                default_strategy="provider",
                model="BAAI/bge-reranker-v2-m3-prod",
                timeout_seconds=9.5,
            ),
            degrade_controls=DegradeControlsConfig(),
            retry_controls=RetryControlsConfig(),
            concurrency_controls=ConcurrencyControlsConfig(),
            prompt_budget=system_config_service.get_config(auth_context=_build_auth_context()).prompt_budget,
        ),
        auth_context=_build_auth_context(),
    )


def test_reranker_client_uses_openai_compatible_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8001/v1",
        reranker_api_key="test-key",
    )
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    client = RerankerClient(settings, system_config_service=system_config_service)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "results": [
                    {"index": 2, "relevance_score": 0.98},
                    {"index": 0, "relevance_score": 0.77},
                ]
            }

    def fake_post(url: str, **kwargs):
        assert url == "http://127.0.0.1:8001/v1/rerank"
        assert kwargs["json"]["model"] == "BAAI/bge-reranker-v2-m3-prod"
        assert kwargs["json"]["query"] == "真空阀异常怎么处理？"
        assert kwargs["json"]["documents"] == [candidate.text for candidate in _build_candidates()]
        assert kwargs["json"]["top_n"] == 2
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["timeout"] == 9.5
        return FakeResponse()

    monkeypatch.setattr(
        "backend.app.rag.rerankers.client.httpx.get",
        lambda url, **kwargs: FakeResponse(),
    )
    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    reranked = client.rerank(query="真空阀异常怎么处理？", candidates=_build_candidates(), top_n=2)

    assert [item.chunk_id for item in reranked] == ["chunk_3", "chunk_1"]
    assert reranked[0].score == 0.98
    assert reranked[1].score == 0.77


def test_reranker_client_rejects_non_ascii_api_key(tmp_path: Path) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8001/v1",
        reranker_api_key="你的key",
    )
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    client = RerankerClient(settings, system_config_service=system_config_service)

    with pytest.raises(RuntimeError, match="non-ASCII"):
        client.rerank(query="q", candidates=_build_candidates(), top_n=2)


def test_reranker_client_runtime_status_checks_openai_health_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8003/v1",
    )
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    client = RerankerClient(settings, system_config_service=system_config_service)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        assert url == "http://127.0.0.1:8003/health"
        assert kwargs["timeout"] == 2.0
        return FakeResponse()

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.get", fake_get)

    status = client.get_runtime_status()

    assert status["provider"] == "openai_compatible"
    assert status["default_strategy"] == "provider"
    assert status["base_url"] == "http://127.0.0.1:8003/v1"
    assert status["effective_provider"] == "openai_compatible"
    assert status["effective_model"] == "BAAI/bge-reranker-v2-m3-prod"
    assert status["effective_strategy"] == "provider"
    assert status["fallback_enabled"] is True
    assert status["failure_cooldown_seconds"] == 15.0
    assert status["lock_active"] is False
    assert status["lock_source"] is None
    assert status["cooldown_remaining_seconds"] == 0.0
    assert status["ready"] is True
    assert status["detail"] == "OpenAI-compatible reranker health probe succeeded."
    assert calls == ["http://127.0.0.1:8003/health"]


def test_reranker_client_short_circuits_after_recent_health_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8003/v1",
    )
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    client = RerankerClient(settings, system_config_service=system_config_service)

    request = httpx.Request("GET", "http://127.0.0.1:8003/health")
    health_calls = 0
    rerank_calls = 0

    def fake_get(url: str, **kwargs):
        nonlocal health_calls
        health_calls += 1
        response = httpx.Response(status_code=502, request=request)
        raise httpx.HTTPStatusError("bad gateway", request=request, response=response)

    def fake_post(url: str, **kwargs):
        nonlocal rerank_calls
        rerank_calls += 1
        raise AssertionError("rerank endpoint should not be called after failed health probe")

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.get", fake_get)
    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    with pytest.raises(RuntimeError, match="health probe failed with HTTP error"):
        client.rerank(query="servo reset", candidates=_build_candidates(), top_n=2)

    with pytest.raises(RuntimeError, match="health probe failed with HTTP error"):
        client.rerank(query="servo reset", candidates=_build_candidates(), top_n=2)

    status = client.get_runtime_status()

    assert health_calls == 1
    assert rerank_calls == 0
    assert status["ready"] is False
    assert status["default_strategy"] == "provider"
    assert status["effective_provider"] == "heuristic"
    assert status["effective_model"] == "heuristic"
    assert status["effective_strategy"] == "heuristic"
    assert status["fallback_enabled"] is True
    assert status["failure_cooldown_seconds"] == 15.0
    assert status["lock_active"] is True
    assert status["lock_source"] == "probe"
    assert 0 < status["cooldown_remaining_seconds"] <= 15.0


def test_reranker_heuristic_gently_prefers_higher_quality_ocr_candidates(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path, reranker_provider="heuristic")
    client = RerankerClient(settings)
    candidates = [
        RetrievedChunk(
            chunk_id="chunk_low",
            document_id="doc_low",
            document_name="低质量 OCR 片段",
            text="servo reset 前先确认急停释放，再重新上电。",
            score=0.9,
            source_path="/tmp/doc_low.txt",
            ocr_used=True,
            quality_score=0.2,
        ),
        RetrievedChunk(
            chunk_id="chunk_high",
            document_id="doc_high",
            document_name="高质量 OCR 片段",
            text="servo reset 前先确认急停释放，再重新上电。",
            score=0.9,
            source_path="/tmp/doc_high.txt",
            ocr_used=True,
            quality_score=0.95,
        ),
    ]

    reranked = client.rerank(query="servo reset", candidates=candidates, top_n=2)

    assert [item.chunk_id for item in reranked] == ["chunk_high", "chunk_low"]


def test_reranker_client_pins_default_route_to_heuristic_by_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8001/v1",
    )
    system_config_service = SystemConfigService(settings)
    current = system_config_service.get_config(auth_context=_build_auth_context())
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current.query_profiles,
            model_routing=current.model_routing,
            reranker_routing=RerankerRoutingConfig(
                provider="openai_compatible",
                default_strategy="heuristic",
                model="BAAI/bge-reranker-v2-m3-prod",
                timeout_seconds=9.5,
                failure_cooldown_seconds=15.0,
            ),
            degrade_controls=current.degrade_controls,
            retry_controls=current.retry_controls,
            concurrency_controls=current.concurrency_controls,
            prompt_budget=current.prompt_budget,
        ),
        auth_context=_build_auth_context(),
    )
    client = RerankerClient(settings, system_config_service=system_config_service)

    class FakeHealthResponse:
        def raise_for_status(self) -> None:
            return None

    def fail_post(url: str, **kwargs):
        raise AssertionError("provider rerank should not be called when default_strategy is heuristic")

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.get", lambda url, **kwargs: FakeHealthResponse())
    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fail_post)

    reranked = client.rerank(query="servo reset", candidates=_build_candidates(), top_n=2)
    status = client.get_runtime_status()

    assert [item.chunk_id for item in reranked] == ["chunk_2", "chunk_1"]
    assert status["provider"] == "openai_compatible"
    assert status["default_strategy"] == "heuristic"
    assert status["ready"] is True
    assert status["effective_provider"] == "heuristic"
    assert status["effective_model"] == "heuristic"
    assert status["effective_strategy"] == "heuristic"
    assert "pinned to heuristic by policy" in str(status["detail"])


def test_query_profile_service_falls_back_to_heuristic_when_openai_reranker_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8001/v1",
    )
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    client = RerankerClient(settings, system_config_service=system_config_service)
    service = QueryProfileService(settings)
    profile = service.resolve(purpose="chat", requested_mode="accurate", requested_top_k=3)

    class FakeHealthResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, **kwargs):
        request = httpx.Request("POST", url)
        raise httpx.RequestError("connection failed", request=request)

    monkeypatch.setattr(
        "backend.app.rag.rerankers.client.httpx.get",
        lambda url, **kwargs: FakeHealthResponse(),
    )
    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    reranked, strategy = service.rerank_with_fallback(
        query="servo reset",
        candidates=_build_candidates(),
        profile=profile,
        reranker_client=client,
    )

    assert strategy == "heuristic"
    assert len(reranked) == 3
    assert reranked[0].chunk_id == "chunk_2"


def test_chat_service_uses_openai_reranker_for_citation_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="heuristic",
        reranker_base_url="http://127.0.0.1:8001/v1",
    )
    ensure_data_directories(settings)
    system_config_service = SystemConfigService(settings)
    _persist_openai_reranker_route(system_config_service)
    chat_service = ChatService(settings)
    chat_service.retrieval_service = _FakeRetrievalService(_build_candidates())
    chat_service.generation_client = _FakeGenerationClient()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "data": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.88},
                    {"index": 2, "relevance_score": 0.72},
                ]
            }

    def fake_post(url: str, **kwargs):
        assert url == "http://127.0.0.1:8001/v1/rerank"
        return FakeResponse()

    monkeypatch.setattr(
        "backend.app.rag.rerankers.client.httpx.get",
        lambda url, **kwargs: FakeResponse(),
    )
    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    response = chat_service.answer(ChatRequest(question="servo reset"), auth_context=None)

    assert response.mode == "rag"
    assert [item.chunk_id for item in response.citations] == ["chunk_2", "chunk_1", "chunk_3"]
