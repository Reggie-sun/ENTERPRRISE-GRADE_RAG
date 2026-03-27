from pathlib import Path

from fastapi.testclient import TestClient

from scripts.local_reranker_server import LocalRerankerService, create_app


class _FakeRerankerService(LocalRerankerService):
    def __init__(self) -> None:
        super().__init__(model_path=Path("/tmp/fake-reranker"), batch_size=8, max_length=1024, use_fp16=True)
        self.loaded = False
        self.device = "cuda"

    def load(self) -> None:
        self.loaded = True

    def rerank(self, *, query: str, documents: list[str], top_n: int | None = None) -> list[dict[str, object]]:
        if query == "raise error":
            raise RuntimeError("reranker failed")
        ranked = [
            {"index": 1, "relevance_score": 0.97, "document": documents[1]},
            {"index": 0, "relevance_score": 0.88, "document": documents[0]},
            {"index": 2, "relevance_score": 0.61, "document": documents[2]},
        ]
        return ranked[: top_n or len(ranked)]


def test_local_reranker_server_returns_openai_compatible_results() -> None:
    service = _FakeRerankerService()
    client = TestClient(create_app(service))

    response = client.post(
        "/v1/rerank",
        json={
            "model": "BAAI/bge-reranker-v2-m3",
            "query": "servo reset",
            "documents": [
                "alarm E201 发生后先检查温控模块和线缆连接。",
                "servo reset 前先确认急停释放，再重新上电。",
                "vacuum valve 异常时检查阀体污染和供气压力。",
            ],
            "top_n": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "BAAI/bge-reranker-v2-m3"
    assert [item["index"] for item in payload["results"]] == [1, 0]
    assert payload["results"][0]["relevance_score"] == 0.97
    assert payload["usage"]["prompt_tokens"] >= 1


def test_local_reranker_server_rejects_blank_documents() -> None:
    service = _FakeRerankerService()
    client = TestClient(create_app(service))

    response = client.post(
        "/v1/rerank",
        json={
            "query": "servo reset",
            "documents": [" ", ""],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "documents must contain at least one non-empty string."


def test_local_reranker_server_converts_runtime_errors_to_502() -> None:
    service = _FakeRerankerService()
    client = TestClient(create_app(service))

    response = client.post(
        "/v1/rerank",
        json={
            "query": "raise error",
            "documents": ["doc a", "doc b", "doc c"],
        },
    )

    assert response.status_code == 502
    assert "reranker failed" in response.json()["detail"]
