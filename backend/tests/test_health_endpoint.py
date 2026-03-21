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

