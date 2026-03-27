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
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        return "基于证据生成的回答"


def test_reranker_client_uses_openai_compatible_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="openai",
        reranker_base_url="http://127.0.0.1:8001/v1",
        reranker_api_key="test-key",
    )
    client = RerankerClient(settings)

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
        assert kwargs["json"]["model"] == "BAAI/bge-reranker-v2-m3"
        assert kwargs["json"]["query"] == "真空阀异常怎么处理？"
        assert kwargs["json"]["documents"] == [candidate.text for candidate in _build_candidates()]
        assert kwargs["json"]["top_n"] == 2
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        return FakeResponse()

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    reranked = client.rerank(query="真空阀异常怎么处理？", candidates=_build_candidates(), top_n=2)

    assert [item.chunk_id for item in reranked] == ["chunk_3", "chunk_1"]
    assert reranked[0].score == 0.98
    assert reranked[1].score == 0.77


def test_reranker_client_rejects_non_ascii_api_key(tmp_path: Path) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="openai",
        reranker_base_url="http://127.0.0.1:8001/v1",
        reranker_api_key="你的key",
    )
    client = RerankerClient(settings)

    with pytest.raises(RuntimeError, match="non-ASCII"):
        client.rerank(query="q", candidates=_build_candidates(), top_n=2)


def test_query_profile_service_falls_back_to_heuristic_when_openai_reranker_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        tmp_path,
        reranker_provider="openai",
        reranker_base_url="http://127.0.0.1:8001/v1",
    )
    client = RerankerClient(settings)
    service = QueryProfileService(settings)
    profile = service.resolve(purpose="chat", requested_mode="accurate", requested_top_k=3)

    def fake_post(url: str, **kwargs):
        request = httpx.Request("POST", url)
        raise httpx.RequestError("connection failed", request=request)

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
        reranker_provider="openai",
        reranker_base_url="http://127.0.0.1:8001/v1",
    )
    ensure_data_directories(settings)
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

    monkeypatch.setattr("backend.app.rag.rerankers.client.httpx.post", fake_post)

    response = chat_service.answer(ChatRequest(question="servo reset"), auth_context=None)

    assert response.mode == "rag"
    assert [item.chunk_id for item in response.citations] == ["chunk_2", "chunk_1", "chunk_3"]
