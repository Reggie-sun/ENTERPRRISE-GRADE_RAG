from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_returns_metadata_store_status() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert "metadata_store" in payload
    assert payload["metadata_store"]["provider"] in {"local_json", "postgres"}
    assert isinstance(payload["metadata_store"]["postgres_enabled"], bool)
    assert isinstance(payload["metadata_store"]["dsn_configured"], bool)
    assert "ocr" in payload
    assert payload["ocr"]["provider"] in {"disabled", "mock", "paddleocr"}
    assert isinstance(payload["ocr"]["enabled"], bool)
    assert isinstance(payload["ocr"]["ready"], bool)
    assert "reranker" in payload
    assert isinstance(payload["reranker"]["provider"], str)
    assert isinstance(payload["reranker"]["model"], str)
    assert isinstance(payload["reranker"]["base_url"], str)
    assert isinstance(payload["reranker"]["default_strategy"], str)
    assert isinstance(payload["reranker"]["timeout_seconds"], (int, float))
    assert isinstance(payload["reranker"]["effective_provider"], str)
    assert isinstance(payload["reranker"]["effective_model"], str)
    assert isinstance(payload["reranker"]["effective_strategy"], str)
    assert isinstance(payload["reranker"]["fallback_enabled"], bool)
    assert isinstance(payload["reranker"]["failure_cooldown_seconds"], (int, float))
    assert isinstance(payload["reranker"]["lock_active"], bool)
    assert payload["reranker"]["lock_source"] is None or isinstance(payload["reranker"]["lock_source"], str)
    assert isinstance(payload["reranker"]["cooldown_remaining_seconds"], (int, float))
    assert isinstance(payload["reranker"]["ready"], bool)
