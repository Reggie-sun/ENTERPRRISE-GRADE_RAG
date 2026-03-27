from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.rag.generators.client import (
    LLMGenerationClient,
    LLMGenerationFatalError,
    LLMGenerationRetryableError,
)
from backend.app.schemas.system_config import SystemConfigUpdateRequest
from backend.app.services.system_config_service import SystemConfigService
from backend.tests.test_system_config_service import _build_auth_context


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, system_config_path=tmp_path / "data" / "system_config.json")


def test_llm_generation_client_retries_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(tmp_path)
    system_config_service = SystemConfigService(settings)
    current_config = system_config_service.get_config(auth_context=_build_auth_context())
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing,
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls.model_copy(
                update={
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 2,
                    "llm_retry_backoff_ms": 0,
                }
            ),
        ),
        auth_context=_build_auth_context(),
    )
    client = LLMGenerationClient(settings, system_config_service=system_config_service)
    state = {"count": 0}

    def fake_generate_once(*, question: str, contexts: list[str], timeout_seconds: float | None = None, model_name: str | None = None) -> str:
        state["count"] += 1
        if state["count"] == 1:
            raise LLMGenerationRetryableError("temporary failure")
        return "ok"

    monkeypatch.setattr(client, "_generate_once", fake_generate_once)

    result = client.generate(question="q", contexts=["context"])

    assert result == "ok"
    assert state["count"] == 2


def test_llm_generation_client_skips_retry_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(tmp_path)
    system_config_service = SystemConfigService(settings)
    current_config = system_config_service.get_config(auth_context=_build_auth_context())
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing,
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls.model_copy(
                update={
                    "llm_retry_enabled": False,
                    "llm_retry_max_attempts": 3,
                    "llm_retry_backoff_ms": 0,
                }
            ),
        ),
        auth_context=_build_auth_context(),
    )
    client = LLMGenerationClient(settings, system_config_service=system_config_service)
    state = {"count": 0}

    def fake_generate_once(*, question: str, contexts: list[str], timeout_seconds: float | None = None, model_name: str | None = None) -> str:
        state["count"] += 1
        raise LLMGenerationRetryableError("temporary failure")

    monkeypatch.setattr(client, "_generate_once", fake_generate_once)

    with pytest.raises(LLMGenerationRetryableError):
        client.generate(question="q", contexts=["context"])

    assert state["count"] == 1


def test_llm_generation_client_supports_deepseek_provider_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-chat",
        llm_api_key="test-key",
    )
    client = LLMGenerationClient(settings, system_config_service=SystemConfigService(settings))

    captured: dict[str, object] = {}

    def fake_generate_with_openai(
        *,
        question: str,
        contexts: list[str],
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        captured["question"] = question
        captured["contexts"] = contexts
        captured["model_name"] = model_name
        return "deepseek-ok"

    monkeypatch.setattr(client, "_generate_with_openai", fake_generate_with_openai)

    result = client.generate(question="q", contexts=["context"], model_name="deepseek-chat")

    assert result == "deepseek-ok"
    assert captured["question"] == "q"
    assert captured["contexts"] == ["context"]
    assert captured["model_name"] == "deepseek-chat"


def test_llm_generation_client_rejects_non_ascii_api_key_for_openai_compatible_provider(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-chat",
        llm_api_key="你的key",
    )
    client = LLMGenerationClient(settings, system_config_service=SystemConfigService(settings))

    with pytest.raises(LLMGenerationFatalError, match="non-ASCII"):
        client.generate(question="q", contexts=["context"])
