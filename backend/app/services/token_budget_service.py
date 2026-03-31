"""Token 预算服务模块。计算 Prompt 组装时的 Token 用量，确保不超出模型上下文窗口。"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Callable

from ..core.config import Settings, get_settings


TokenizerFactory = Callable[[str, bool], Any]


class TokenBudgetService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        tokenizer_factory: TokenizerFactory | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tokenizer_factory = tokenizer_factory
        self._tokenizer: Any | None = None
        self._tokenizer_provider: str | None = None
        self._tokenizer_model_name: str | None = None
        self._tokenizer_error: str | None = None

    def estimate_token_count(self, text: str, *, model_name: str | None = None) -> int:
        normalized = text or ""
        if not normalized:
            return 0
        tokenizer = self._get_tokenizer(model_name=model_name)
        if tokenizer is not None:
            try:
                encoded = tokenizer.encode(normalized, add_special_tokens=False)
                return max(0, len(encoded))
            except Exception as exc:
                self._tokenizer_error = str(exc)
        return self._estimate_with_heuristic(normalized)

    def truncate_text_to_token_budget(
        self,
        text: str,
        token_budget: int,
        *,
        model_name: str | None = None,
        ellipsis: str = " ...",
    ) -> str:
        normalized = text or ""
        normalized_budget = max(0, token_budget)
        if not normalized or normalized_budget <= 0:
            return ""
        if self.estimate_token_count(normalized, model_name=model_name) <= normalized_budget:
            return normalized

        low = 0
        high = len(normalized)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            candidate = normalized[:mid].rstrip()
            if not candidate:
                low = mid + 1
                continue
            if self.estimate_token_count(candidate, model_name=model_name) <= normalized_budget:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1

        if not best:
            return normalized[: max(1, min(len(normalized), normalized_budget))].rstrip()

        if best != normalized:
            while best and self.estimate_token_count(f"{best}{ellipsis}", model_name=model_name) > normalized_budget:
                best = best[:-1].rstrip()
            if best:
                return f"{best}{ellipsis}"
        return best

    def get_runtime_info(self, *, model_name: str | None = None) -> dict[str, object]:
        provider = self._tokenizer_provider or self._resolve_provider()
        effective_model = self._tokenizer_model_name or self._resolve_model_name(model_name)
        if provider == "heuristic":
            self._tokenizer_provider = provider
            self._tokenizer_model_name = effective_model
            self._tokenizer_error = None
            return {
                "provider": provider,
                "model": effective_model,
                "ready": True,
                "detail": "Heuristic token estimator is active.",
                "error": None,
            }

        tokenizer = self._get_tokenizer(model_name=model_name)
        return {
            "provider": provider,
            "model": effective_model,
            "ready": tokenizer is not None,
            "detail": "Transformers tokenizer is ready." if tokenizer is not None else "Tokenizer probe failed.",
            "error": self._tokenizer_error,
        }

    def _get_tokenizer(self, *, model_name: str | None = None) -> Any | None:
        provider = self._resolve_provider()
        self._tokenizer_provider = provider
        if provider != "transformers_auto":
            self._tokenizer_error = None
            return None

        resolved_model_name = self._resolve_model_name(model_name)
        if not resolved_model_name:
            self._tokenizer_error = "Tokenizer model is not configured."
            return None

        if self._tokenizer is not None and self._tokenizer_model_name == resolved_model_name:
            return self._tokenizer

        try:
            factory = self.tokenizer_factory or self._default_tokenizer_factory
            tokenizer = factory(resolved_model_name, self.settings.tokenizer_trust_remote_code)
        except Exception as exc:
            self._tokenizer = None
            self._tokenizer_model_name = resolved_model_name
            self._tokenizer_error = str(exc)
            return None

        self._tokenizer = tokenizer
        self._tokenizer_model_name = resolved_model_name
        self._tokenizer_error = None
        return tokenizer

    def _resolve_provider(self) -> str:
        provider = (self.settings.tokenizer_provider or "").strip().lower()
        if provider in {"transformers", "transformers_auto"}:
            return "transformers_auto"
        return "heuristic"

    def _resolve_model_name(self, model_name: str | None) -> str:
        resolved = (model_name or "").strip()
        if resolved:
            return resolved
        configured = (self.settings.tokenizer_model or "").strip()
        if configured:
            return configured
        return (self.settings.llm_model or self.settings.ollama_model).strip()

    @staticmethod
    def _default_tokenizer_factory(model_name: str, trust_remote_code: bool) -> Any:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(model_name, trust_remote_code=trust_remote_code)

    @staticmethod
    def _estimate_with_heuristic(text: str) -> int:
        token_count = 0
        ascii_run = 0

        def flush_ascii_run() -> int:
            nonlocal ascii_run
            if ascii_run <= 0:
                return 0
            estimated = max(1, math.ceil(ascii_run / 4))
            ascii_run = 0
            return estimated

        for char in text:
            if ord(char) < 128:
                if char.isalnum() or char in {"_", "-", "/"}:
                    ascii_run += 1
                    continue
                token_count += flush_ascii_run()
                if not char.isspace():
                    token_count += 1
                continue
            token_count += flush_ascii_run()
            token_count += 1

        token_count += flush_ascii_run()
        return max(1, token_count)


@lru_cache
def get_token_budget_service() -> TokenBudgetService:
    return TokenBudgetService()
