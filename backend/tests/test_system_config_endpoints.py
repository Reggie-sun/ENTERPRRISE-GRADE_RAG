import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.services.auth_service import AuthService, get_auth_service
from backend.app.services.identity_service import get_identity_service
from backend.app.services.system_config_service import SystemConfigService, get_system_config_service
from backend.tests.test_sop_generation_service import _build_identity_service


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
    )


def _build_client(tmp_path: Path) -> TestClient:
    settings = _build_settings(tmp_path)
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
    system_config_service = SystemConfigService(settings)

    app.dependency_overrides[get_identity_service] = lambda: identity_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_system_config_service] = lambda: system_config_service
    return TestClient(app)


def _login_headers(client: TestClient, *, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_get_system_config_endpoint_requires_authentication(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        response = client.get("/api/v1/system-config")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication credentials were not provided."


def test_get_system_config_endpoint_returns_defaults_for_sys_admin(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.get("/api/v1/system-config", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_profiles"]["fast"]["top_k_default"] == 5
    assert payload["query_profiles"]["fast"]["lexical_top_k"] == 20
    assert payload["query_profiles"]["accurate"]["top_k_default"] == 8
    assert payload["query_profiles"]["accurate"]["lexical_top_k"] == 32
    assert payload["model_routing"]["fast_model"] == "qwen2.5:7b"
    assert payload["reranker_routing"]["provider"] == "heuristic"
    assert payload["reranker_routing"]["default_strategy"] == "heuristic"
    assert payload["reranker_routing"]["model"] == "BAAI/bge-reranker-v2-m3"
    assert payload["reranker_routing"]["timeout_seconds"] == 12.0
    assert payload["reranker_routing"]["failure_cooldown_seconds"] == 15.0
    assert payload["degrade_controls"]["rerank_fallback_enabled"] is True
    assert payload["retry_controls"]["llm_retry_max_attempts"] == 2
    assert payload["concurrency_controls"]["fast_max_inflight"] == 24
    assert payload["concurrency_controls"]["accurate_max_inflight"] == 6
    assert payload["concurrency_controls"]["per_user_online_max_inflight"] == 3
    assert payload["prompt_budget"]["max_prompt_tokens"] == 2200
    assert payload["prompt_budget"]["reserved_completion_tokens"] == 512
    assert payload["prompt_budget"]["memory_prompt_tokens"] == 360


def test_get_system_config_endpoint_rejects_department_admin(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="digitalization.admin", password="digitalization-admin-pass")
        response = client.get("/api/v1/system-config", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to system configuration."


def test_update_system_config_endpoint_persists_config(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.put(
            "/api/v1/system-config",
            headers=headers,
            json={
                "query_profiles": {
                    "fast": {
                        "top_k_default": 6,
                        "candidate_multiplier": 3,
                        "lexical_top_k": 12,
                        "rerank_top_n": 4,
                        "timeout_budget_seconds": 10.0,
                    },
                    "accurate": {
                        "top_k_default": 10,
                        "candidate_multiplier": 5,
                        "lexical_top_k": 24,
                        "rerank_top_n": 6,
                        "timeout_budget_seconds": 20.0,
                    },
                },
                "model_routing": {
                    "fast_model": "Qwen/Fast-7B",
                    "accurate_model": "Qwen/Accurate-14B",
                    "sop_generation_model": "Qwen/SOP-14B",
                },
                "reranker_routing": {
                    "provider": "openai_compatible",
                    "default_strategy": "provider",
                    "model": "Qwen/Reranker-Prod",
                    "timeout_seconds": 9.5,
                    "failure_cooldown_seconds": 21.0,
                },
                "degrade_controls": {
                    "rerank_fallback_enabled": False,
                    "accurate_to_fast_fallback_enabled": True,
                    "retrieval_fallback_enabled": False,
                },
                "retry_controls": {
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 3,
                    "llm_retry_backoff_ms": 900,
                },
                "concurrency_controls": {
                    "fast_max_inflight": 30,
                    "accurate_max_inflight": 8,
                    "sop_generation_max_inflight": 4,
                    "per_user_online_max_inflight": 3,
                    "acquire_timeout_ms": 1200,
                    "busy_retry_after_seconds": 9,
                },
                "prompt_budget": {
                    "max_prompt_tokens": 2400,
                    "reserved_completion_tokens": 640,
                    "memory_prompt_tokens": 320,
                },
            },
        )
        follow_up = client.get("/api/v1/system-config", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["updated_by"] == "user_sys_admin"
    assert follow_up.status_code == 200
    assert follow_up.json()["query_profiles"]["fast"]["top_k_default"] == 6
    assert follow_up.json()["query_profiles"]["fast"]["lexical_top_k"] == 12
    assert follow_up.json()["query_profiles"]["accurate"]["rerank_top_n"] == 6
    assert follow_up.json()["model_routing"]["accurate_model"] == "Qwen/Accurate-14B"
    assert follow_up.json()["reranker_routing"]["provider"] == "openai_compatible"
    assert follow_up.json()["reranker_routing"]["default_strategy"] == "provider"
    assert follow_up.json()["reranker_routing"]["model"] == "Qwen/Reranker-Prod"
    assert follow_up.json()["reranker_routing"]["failure_cooldown_seconds"] == 21.0
    assert follow_up.json()["degrade_controls"]["retrieval_fallback_enabled"] is False
    assert follow_up.json()["retry_controls"]["llm_retry_max_attempts"] == 3
    assert follow_up.json()["concurrency_controls"]["fast_max_inflight"] == 30
    assert follow_up.json()["concurrency_controls"]["per_user_online_max_inflight"] == 3
    assert follow_up.json()["concurrency_controls"]["busy_retry_after_seconds"] == 9
    assert follow_up.json()["prompt_budget"]["max_prompt_tokens"] == 2400
    assert follow_up.json()["prompt_budget"]["reserved_completion_tokens"] == 640
    assert follow_up.json()["prompt_budget"]["memory_prompt_tokens"] == 320


def test_update_system_config_endpoint_preserves_internal_retrieval_controls(tmp_path: Path) -> None:
    config_path = tmp_path / "data" / "system_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "_internal_retrieval_controls": {
                    "supplemental_quality_thresholds": {
                        "top1_threshold": 0.72,
                        "avg_top_n_threshold": 0.69,
                        "fine_query_top1_threshold": 0.91,
                        "fine_query_avg_top_n_threshold": 0.77,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.put(
            "/api/v1/system-config",
            headers=headers,
            json={
                "query_profiles": {
                    "fast": {
                        "top_k_default": 6,
                        "candidate_multiplier": 3,
                        "lexical_top_k": 12,
                        "rerank_top_n": 4,
                        "timeout_budget_seconds": 10.0,
                    },
                    "accurate": {
                        "top_k_default": 10,
                        "candidate_multiplier": 5,
                        "lexical_top_k": 24,
                        "rerank_top_n": 6,
                        "timeout_budget_seconds": 20.0,
                    },
                },
                "model_routing": {
                    "fast_model": "Qwen/Fast-7B",
                    "accurate_model": "Qwen/Accurate-14B",
                    "sop_generation_model": "Qwen/SOP-14B",
                },
                "reranker_routing": {
                    "provider": "openai_compatible",
                    "default_strategy": "provider",
                    "model": "Qwen/Reranker-Prod",
                    "timeout_seconds": 9.5,
                    "failure_cooldown_seconds": 21.0,
                },
                "degrade_controls": {
                    "rerank_fallback_enabled": False,
                    "accurate_to_fast_fallback_enabled": True,
                    "retrieval_fallback_enabled": False,
                },
                "retry_controls": {
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 3,
                    "llm_retry_backoff_ms": 900,
                },
                "concurrency_controls": {
                    "fast_max_inflight": 30,
                    "accurate_max_inflight": 8,
                    "sop_generation_max_inflight": 4,
                    "per_user_online_max_inflight": 3,
                    "acquire_timeout_ms": 1200,
                    "busy_retry_after_seconds": 9,
                },
                "prompt_budget": {
                    "max_prompt_tokens": 2400,
                    "reserved_completion_tokens": 640,
                    "memory_prompt_tokens": 320,
                },
            },
        )
        stored = json.loads(config_path.read_text(encoding="utf-8"))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "_internal_retrieval_controls" not in response.json()
    assert stored["_internal_retrieval_controls"] == {
        "supplemental_quality_thresholds": {
            "top1_threshold": 0.72,
            "avg_top_n_threshold": 0.69,
            "fine_query_top1_threshold": 0.91,
            "fine_query_avg_top_n_threshold": 0.77,
        }
    }


def test_update_system_config_endpoint_validates_profile_relationships(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.put(
            "/api/v1/system-config",
            headers=headers,
            json={
                "query_profiles": {
                    "fast": {
                        "top_k_default": 5,
                        "candidate_multiplier": 2,
                        "lexical_top_k": 5,
                        "rerank_top_n": 6,
                        "timeout_budget_seconds": 12.0,
                    },
                    "accurate": {
                        "top_k_default": 8,
                        "candidate_multiplier": 4,
                        "lexical_top_k": 8,
                        "rerank_top_n": 5,
                        "timeout_budget_seconds": 24.0,
                    },
                },
                "model_routing": {
                    "fast_model": "Qwen/Fast-7B",
                    "accurate_model": "Qwen/Accurate-14B",
                    "sop_generation_model": "Qwen/SOP-14B",
                },
                "reranker_routing": {
                    "provider": "heuristic",
                    "default_strategy": "heuristic",
                    "model": "BAAI/bge-reranker-v2-m3",
                    "timeout_seconds": 12.0,
                    "failure_cooldown_seconds": 15.0,
                },
                "degrade_controls": {
                    "rerank_fallback_enabled": True,
                    "accurate_to_fast_fallback_enabled": True,
                    "retrieval_fallback_enabled": True,
                },
                "retry_controls": {
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 2,
                    "llm_retry_backoff_ms": 400,
                },
                "concurrency_controls": {
                    "fast_max_inflight": 24,
                    "accurate_max_inflight": 6,
                    "sop_generation_max_inflight": 3,
                    "per_user_online_max_inflight": 3,
                    "acquire_timeout_ms": 800,
                    "busy_retry_after_seconds": 5,
                },
                "prompt_budget": {
                    "max_prompt_tokens": 2200,
                    "reserved_completion_tokens": 512,
                    "memory_prompt_tokens": 360,
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "fast.rerank_top_n cannot be greater than fast.top_k_default."


def test_update_system_config_endpoint_rejects_provider_default_strategy_when_provider_is_heuristic(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    try:
        headers = _login_headers(client, username="sys.admin", password="sys-admin-pass")
        response = client.put(
            "/api/v1/system-config",
            headers=headers,
            json={
                "query_profiles": {
                    "fast": {
                        "top_k_default": 5,
                        "candidate_multiplier": 2,
                        "lexical_top_k": 10,
                        "rerank_top_n": 3,
                        "timeout_budget_seconds": 12.0,
                    },
                    "accurate": {
                        "top_k_default": 8,
                        "candidate_multiplier": 4,
                        "lexical_top_k": 32,
                        "rerank_top_n": 5,
                        "timeout_budget_seconds": 24.0,
                    },
                },
                "model_routing": {
                    "fast_model": "Qwen/Fast-7B",
                    "accurate_model": "Qwen/Accurate-14B",
                    "sop_generation_model": "Qwen/SOP-14B",
                },
                "reranker_routing": {
                    "provider": "heuristic",
                    "default_strategy": "provider",
                    "model": "BAAI/bge-reranker-v2-m3",
                    "timeout_seconds": 12.0,
                    "failure_cooldown_seconds": 15.0,
                },
                "degrade_controls": {
                    "rerank_fallback_enabled": True,
                    "accurate_to_fast_fallback_enabled": True,
                    "retrieval_fallback_enabled": True,
                },
                "retry_controls": {
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 2,
                    "llm_retry_backoff_ms": 400,
                },
                "concurrency_controls": {
                    "fast_max_inflight": 24,
                    "accurate_max_inflight": 6,
                    "sop_generation_max_inflight": 3,
                    "per_user_online_max_inflight": 3,
                    "acquire_timeout_ms": 800,
                    "busy_retry_after_seconds": 5,
                },
                "prompt_budget": {
                    "max_prompt_tokens": 2200,
                    "reserved_completion_tokens": 512,
                    "memory_prompt_tokens": 360,
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "reranker_routing.default_strategy must be heuristic when provider is heuristic."
