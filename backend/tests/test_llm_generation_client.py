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
            reranker_routing=current_config.reranker_routing,
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls.model_copy(
                update={
                    "llm_retry_enabled": True,
                    "llm_retry_max_attempts": 2,
                    "llm_retry_backoff_ms": 0,
                }
            ),
            concurrency_controls=current_config.concurrency_controls,
            prompt_budget=current_config.prompt_budget,
        ),
        auth_context=_build_auth_context(),
    )
    client = LLMGenerationClient(settings, system_config_service=system_config_service)
    state = {"count": 0}

    def fake_generate_once(
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
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
            reranker_routing=current_config.reranker_routing,
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls.model_copy(
                update={
                    "llm_retry_enabled": False,
                    "llm_retry_max_attempts": 3,
                    "llm_retry_backoff_ms": 0,
                }
            ),
            concurrency_controls=current_config.concurrency_controls,
            prompt_budget=current_config.prompt_budget,
        ),
        auth_context=_build_auth_context(),
    )
    client = LLMGenerationClient(settings, system_config_service=system_config_service)
    state = {"count": 0}

    def fake_generate_once(
        *,
        question: str,
        contexts: list[str],
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
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
        memory_text: str | None = None,
        timeout_seconds: float | None = None,
        model_name: str | None = None,
    ) -> str:
        captured["question"] = question
        captured["contexts"] = contexts
        captured["memory_text"] = memory_text
        captured["model_name"] = model_name
        return "deepseek-ok"

    monkeypatch.setattr(client, "_generate_with_openai", fake_generate_with_openai)

    result = client.generate(question="q", contexts=["context"], model_name="deepseek-chat")

    assert result == "deepseek-ok"
    assert captured["question"] == "q"
    assert captured["contexts"] == ["context"]
    assert captured["memory_text"] is None
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


def test_llm_generation_client_trims_prompt_to_budget(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="openai",
        llm_base_url="http://example.com/v1",
        llm_model="test-model",
        llm_max_prompt_tokens=256,
        llm_reserved_completion_tokens=64,
    )
    client = LLMGenerationClient(settings, system_config_service=SystemConfigService(settings))

    prompt = client._build_prompt(
        question="解释一下悖论放松法",
        contexts=[
            "甲" * 200,
            "乙" * 200,
        ],
    )

    assert client._estimate_token_count(prompt) <= settings.llm_max_prompt_tokens
    assert "[Context 1]" in prompt
    assert "甲" in prompt


def test_llm_generation_client_includes_recent_memory_in_prompt(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="openai",
        llm_base_url="http://example.com/v1",
        llm_model="test-model",
        chat_memory_max_prompt_tokens=80,
    )
    client = LLMGenerationClient(settings, system_config_service=SystemConfigService(settings))

    prompt = client._build_prompt(
        question="那第二步呢？",
        contexts=["步骤一：停机并检查报警记录。"],
        memory_text="[Recent Turn 1]\nUser: 悖论放松法是什么？\nAssistant: 先接受矛盾，再逐步降低紧张感。",
    )

    assert "[Recent Conversation]" in prompt
    assert "那第二步呢？" in prompt
    assert "步骤一：停机并检查报警记录。" in prompt


def test_llm_generation_client_sets_max_tokens_for_openai_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="openai",
        llm_base_url="http://example.com/v1",
        llm_model="test-model",
        llm_reserved_completion_tokens=321,
    )
    client = LLMGenerationClient(settings, system_config_service=SystemConfigService(settings))
    captured: dict[str, object] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float, trust_env: bool):
        captured["url"] = url
        captured["payload"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["trust_env"] = trust_env
        return DummyResponse()

    monkeypatch.setattr("backend.app.rag.generators.client.httpx.post", fake_post)

    result = client.generate(question="q", contexts=["context"])

    assert result == "ok"
    assert captured["payload"]["max_tokens"] == 321


def test_llm_generation_client_prefers_system_config_prompt_budget_over_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_provider="openai",
        llm_base_url="http://example.com/v1",
        llm_model="test-model",
        llm_max_prompt_tokens=3000,
        llm_reserved_completion_tokens=900,
        chat_memory_max_prompt_tokens=700,
    )
    system_config_service = SystemConfigService(settings)
    current_config = system_config_service.get_config(auth_context=_build_auth_context())
    system_config_service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=current_config.query_profiles,
            model_routing=current_config.model_routing,
            reranker_routing=current_config.reranker_routing,
            degrade_controls=current_config.degrade_controls,
            retry_controls=current_config.retry_controls,
            concurrency_controls=current_config.concurrency_controls,
            prompt_budget=current_config.prompt_budget.model_copy(
                update={
                    "max_prompt_tokens": 512,
                    "reserved_completion_tokens": 222,
                    "memory_prompt_tokens": 96,
                }
            ),
        ),
        auth_context=_build_auth_context(),
    )
    client = LLMGenerationClient(settings, system_config_service=system_config_service)
    captured: dict[str, object] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float, trust_env: bool):
        captured["payload"] = json
        return DummyResponse()

    monkeypatch.setattr("backend.app.rag.generators.client.httpx.post", fake_post)

    prompt = client._build_prompt(
        question="解释一下悖论放松法",
        contexts=["甲" * 400, "乙" * 400],
        memory_text="[Recent Turn 1]\nUser: 上一轮说了什么？\nAssistant: 这里是一段需要被压缩的历史回答。" * 4,
    )
    result = client.generate(question="q", contexts=["context"])

    assert result == "ok"
    assert client._estimate_token_count(prompt) <= 512
    assert captured["payload"]["max_tokens"] == 222
