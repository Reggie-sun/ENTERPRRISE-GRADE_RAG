from pathlib import Path

from backend.app.core.config import Settings
from backend.app.services.token_budget_service import TokenBudgetService


def _build_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
        llm_model="Qwen2.5-14B-AWQ",
        **overrides,
    )


class _FakeTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [token for token in text.split(" ") if token]


def test_token_budget_service_uses_transformers_tokenizer_when_configured(tmp_path: Path) -> None:
    settings = _build_settings(
        tmp_path,
        tokenizer_provider="transformers_auto",
        tokenizer_model="BAAI/bge-m3",
    )
    service = TokenBudgetService(settings, tokenizer_factory=lambda model, trust_remote_code: _FakeTokenizer())

    assert service.estimate_token_count("one two three") == 3
    assert service.get_runtime_info()["provider"] == "transformers_auto"
    assert service.get_runtime_info()["ready"] is True


def test_token_budget_service_falls_back_to_heuristic_when_tokenizer_probe_fails(tmp_path: Path) -> None:
    settings = _build_settings(
        tmp_path,
        tokenizer_provider="transformers_auto",
        tokenizer_model="broken-model",
    )
    service = TokenBudgetService(
        settings,
        tokenizer_factory=lambda model, trust_remote_code: (_ for _ in ()).throw(RuntimeError("load failed")),
    )

    estimate = service.estimate_token_count("中文ABC123")
    runtime = service.get_runtime_info()

    assert estimate >= 1
    assert runtime["provider"] == "transformers_auto"
    assert runtime["ready"] is False
    assert runtime["error"] == "load failed"


def test_token_budget_service_reports_heuristic_runtime_when_transformers_is_disabled(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path, tokenizer_provider="heuristic")
    service = TokenBudgetService(settings)

    runtime = service.get_runtime_info()

    assert runtime == {
        "provider": "heuristic",
        "model": "Qwen2.5-14B-AWQ",
        "ready": True,
        "detail": "Heuristic token estimator is active.",
        "error": None,
    }


def test_token_budget_service_truncates_text_to_budget_with_fake_tokenizer(tmp_path: Path) -> None:
    settings = _build_settings(
        tmp_path,
        tokenizer_provider="transformers_auto",
        tokenizer_model="BAAI/bge-m3",
    )
    service = TokenBudgetService(settings, tokenizer_factory=lambda model, trust_remote_code: _FakeTokenizer())

    truncated = service.truncate_text_to_token_budget(
        "alpha beta gamma delta epsilon",
        3,
        ellipsis=" ...",
    )

    assert truncated == "alpha beta ..."
