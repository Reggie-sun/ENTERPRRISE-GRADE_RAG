"""系统配置服务模块。提供运行时可调的查询档位、重排序路由和降级控制等配置。"""
from datetime import datetime, timezone
from functools import lru_cache
import logging
from typing import Any

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..db.system_config_repository import FilesystemSystemConfigRepository, SystemConfigRepository
from ..schemas.auth import AuthContext
from ..schemas.query_profile import QueryMode, QueryPurpose
from ..schemas.system_config import (
    ConcurrencyControlsConfig,
    DegradeControlsConfig,
    InternalRetrievalControlsConfig,
    ModelRoutingConfig,
    PromptBudgetConfig,
    QueryModeConfig,
    QueryProfilesConfig,
    RerankerDefaultStrategy,
    RerankerRoutingConfig,
    RerankerRoutingProvider,
    RetryControlsConfig,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
)

logger = logging.getLogger(__name__)


class SystemConfigService:
    INTERNAL_RETRIEVAL_CONTROLS_KEY = "_internal_retrieval_controls"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repository: SystemConfigRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or FilesystemSystemConfigRepository(self.settings.system_config_path)

    def get_config(self, *, auth_context: AuthContext) -> SystemConfigResponse:
        self._ensure_sys_admin(auth_context)
        return self._load_config()

    def get_effective_config(self) -> SystemConfigResponse:
        return self._load_config()

    def get_internal_retrieval_controls(self) -> InternalRetrievalControlsConfig:
        defaults = self._build_default_internal_retrieval_controls()
        stored = self._read_raw_payload()
        if not stored:
            return defaults

        raw_controls = stored.get(self.INTERNAL_RETRIEVAL_CONTROLS_KEY)
        if raw_controls is None:
            return defaults
        if not isinstance(raw_controls, dict):
            logger.warning(
                "system config internal retrieval controls ignored because payload is not a mapping: %r",
                type(raw_controls).__name__,
            )
            return defaults

        try:
            merged = self._deep_merge(defaults.model_dump(mode="json"), raw_controls)
            return InternalRetrievalControlsConfig.model_validate(merged)
        except Exception:
            logger.warning(
                "system config internal retrieval controls are invalid; falling back to defaults",
                exc_info=True,
            )
            return defaults

    def update_config(
        self,
        payload: SystemConfigUpdateRequest,
        *,
        auth_context: AuthContext,
    ) -> SystemConfigResponse:
        self._ensure_sys_admin(auth_context)
        self._validate_query_profiles(payload.query_profiles)
        self._validate_model_routing(payload.model_routing)
        self._validate_reranker_routing(payload.reranker_routing)
        self._validate_retry_controls(payload.retry_controls)
        self._validate_concurrency_controls(payload.concurrency_controls)
        self._validate_prompt_budget(payload.prompt_budget)
        record = SystemConfigResponse(
            query_profiles=payload.query_profiles,
            model_routing=payload.model_routing,
            reranker_routing=payload.reranker_routing,
            degrade_controls=payload.degrade_controls,
            retry_controls=payload.retry_controls,
            concurrency_controls=payload.concurrency_controls,
            prompt_budget=payload.prompt_budget,
            updated_at=datetime.now(timezone.utc),
            updated_by=auth_context.user.user_id,
        )
        stored = self._read_raw_payload() or {}
        serialized_record = record.model_dump(mode="json")
        if self.INTERNAL_RETRIEVAL_CONTROLS_KEY in stored:
            serialized_record[self.INTERNAL_RETRIEVAL_CONTROLS_KEY] = stored[self.INTERNAL_RETRIEVAL_CONTROLS_KEY]
        self.repository.write(serialized_record)
        return record

    def get_query_mode_settings(self, mode: QueryMode) -> QueryModeConfig:
        config = self._load_config()
        if mode == "accurate":
            return config.query_profiles.accurate
        return config.query_profiles.fast

    def get_model_routing(self) -> ModelRoutingConfig:
        return self._load_config().model_routing

    def get_reranker_routing(self) -> RerankerRoutingConfig:
        return self._load_config().reranker_routing

    def get_degrade_controls(self) -> DegradeControlsConfig:
        return self._load_config().degrade_controls

    def get_retry_controls(self) -> RetryControlsConfig:
        return self._load_config().retry_controls

    def get_concurrency_controls(self) -> ConcurrencyControlsConfig:
        return self._load_config().concurrency_controls

    def get_prompt_budget(self) -> PromptBudgetConfig:
        return self._load_config().prompt_budget

    def get_llm_model_for_request(self, *, purpose: QueryPurpose, mode: QueryMode) -> str:
        config = self.get_model_routing()
        if purpose == "sop_generation":
            return config.sop_generation_model.strip()
        if mode == "accurate":
            return config.accurate_model.strip()
        return config.fast_model.strip()

    def _load_config(self) -> SystemConfigResponse:
        defaults = self._build_default_config()
        stored = self._read_raw_payload()
        if not stored:
            return defaults
        merged = self._deep_merge(defaults.model_dump(mode="json"), stored)
        return SystemConfigResponse.model_validate(merged)

    def _build_default_config(self) -> SystemConfigResponse:
        return SystemConfigResponse(
            query_profiles=QueryProfilesConfig(
                fast=QueryModeConfig(
                    top_k_default=self.settings.query_fast_top_k_default,
                    candidate_multiplier=self.settings.query_fast_candidate_multiplier,
                    lexical_top_k=self.settings.query_fast_lexical_top_k_default,
                    rerank_top_n=self.settings.query_fast_rerank_top_n,
                    timeout_budget_seconds=self.settings.query_fast_timeout_budget_seconds,
                ),
                accurate=QueryModeConfig(
                    top_k_default=self.settings.query_accurate_top_k_default,
                    candidate_multiplier=self.settings.query_accurate_candidate_multiplier,
                    lexical_top_k=self.settings.query_accurate_lexical_top_k_default,
                    rerank_top_n=self.settings.query_accurate_rerank_top_n,
                    timeout_budget_seconds=self.settings.query_accurate_timeout_budget_seconds,
                ),
            ),
            model_routing=ModelRoutingConfig(
                fast_model=self._default_llm_model_name(),
                accurate_model=self._default_llm_model_name(),
                sop_generation_model=self._default_llm_model_name(),
            ),
            reranker_routing=RerankerRoutingConfig(
                provider=self._default_reranker_provider(),
                default_strategy=self._default_reranker_strategy(),
                model=self._default_reranker_model_name(),
                timeout_seconds=self.settings.reranker_timeout_seconds,
                failure_cooldown_seconds=self.settings.reranker_failure_cooldown_seconds,
            ),
            degrade_controls=DegradeControlsConfig(),
            retry_controls=RetryControlsConfig(),
            concurrency_controls=ConcurrencyControlsConfig(
                fast_max_inflight=self.settings.concurrency_fast_max_inflight,
                accurate_max_inflight=self.settings.concurrency_accurate_max_inflight,
                sop_generation_max_inflight=self.settings.concurrency_sop_generation_max_inflight,
                per_user_online_max_inflight=self.settings.concurrency_per_user_online_max_inflight,
                acquire_timeout_ms=self.settings.concurrency_acquire_timeout_ms,
                busy_retry_after_seconds=self.settings.concurrency_busy_retry_after_seconds,
            ),
            prompt_budget=PromptBudgetConfig(
                max_prompt_tokens=self.settings.llm_max_prompt_tokens,
                reserved_completion_tokens=self.settings.llm_reserved_completion_tokens,
                memory_prompt_tokens=self.settings.chat_memory_max_prompt_tokens,
            ),
        )

    def _build_default_internal_retrieval_controls(self) -> InternalRetrievalControlsConfig:
        return InternalRetrievalControlsConfig.model_validate(
            {
                "supplemental_quality_thresholds": {
                    "top1_threshold": self.settings.retrieval_quality_top1_threshold,
                    "avg_top_n_threshold": self.settings.retrieval_quality_avg_threshold,
                    "fine_query_top1_threshold": self.settings.retrieval_fine_query_quality_top1_threshold,
                    "fine_query_avg_top_n_threshold": self.settings.retrieval_fine_query_quality_avg_threshold,
                }
            }
        )

    def _read_raw_payload(self) -> dict[str, Any] | None:
        stored = self.repository.read()
        if stored is None:
            return None
        if not isinstance(stored, dict):
            logger.warning(
                "system config repository returned a non-mapping payload; ignoring stored config type=%r",
                type(stored).__name__,
            )
            return None
        return stored

    @staticmethod
    def _ensure_sys_admin(auth_context: AuthContext) -> None:
        if auth_context.user.role_id != "sys_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to system configuration.",
            )

    @staticmethod
    def _validate_query_profiles(query_profiles: QueryProfilesConfig) -> None:
        for mode, config in (("fast", query_profiles.fast), ("accurate", query_profiles.accurate)):
            if config.lexical_top_k < config.top_k_default:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{mode}.lexical_top_k cannot be smaller than {mode}.top_k_default.",
                )
            if config.rerank_top_n > config.top_k_default:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{mode}.rerank_top_n cannot be greater than {mode}.top_k_default.",
                )
        if query_profiles.accurate.top_k_default < query_profiles.fast.top_k_default:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="accurate.top_k_default cannot be smaller than fast.top_k_default.",
            )
        if query_profiles.accurate.timeout_budget_seconds < query_profiles.fast.timeout_budget_seconds:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="accurate.timeout_budget_seconds cannot be smaller than fast.timeout_budget_seconds.",
            )

    @staticmethod
    def _validate_model_routing(model_routing: ModelRoutingConfig) -> None:
        for field_name, value in (
            ("fast_model", model_routing.fast_model),
            ("accurate_model", model_routing.accurate_model),
            ("sop_generation_model", model_routing.sop_generation_model),
        ):
            if not value.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field_name} cannot be empty.",
                )

    @staticmethod
    def _validate_reranker_routing(reranker_routing: RerankerRoutingConfig) -> None:
        if not reranker_routing.model.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reranker_routing.model cannot be empty.",
            )
        if reranker_routing.provider == "heuristic" and reranker_routing.default_strategy != "heuristic":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reranker_routing.default_strategy must be heuristic when provider is heuristic.",
            )

    @staticmethod
    def _validate_retry_controls(retry_controls: RetryControlsConfig) -> None:
        if retry_controls.llm_retry_max_attempts < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="llm_retry_max_attempts must be greater than or equal to 1.",
            )
        if retry_controls.llm_retry_backoff_ms < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="llm_retry_backoff_ms cannot be negative.",
            )

    @staticmethod
    def _validate_concurrency_controls(concurrency_controls: ConcurrencyControlsConfig) -> None:
        if concurrency_controls.accurate_max_inflight > concurrency_controls.fast_max_inflight:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="accurate_max_inflight cannot be greater than fast_max_inflight.",
            )
        if concurrency_controls.sop_generation_max_inflight > concurrency_controls.fast_max_inflight:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sop_generation_max_inflight cannot be greater than fast_max_inflight.",
            )
        if concurrency_controls.per_user_online_max_inflight > concurrency_controls.fast_max_inflight:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="per_user_online_max_inflight cannot be greater than fast_max_inflight.",
            )

    @staticmethod
    def _validate_prompt_budget(prompt_budget: PromptBudgetConfig) -> None:
        if prompt_budget.memory_prompt_tokens >= prompt_budget.max_prompt_tokens:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="prompt_budget.memory_prompt_tokens must be smaller than prompt_budget.max_prompt_tokens.",
            )
        if prompt_budget.max_prompt_tokens <= 0 or prompt_budget.reserved_completion_tokens <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="prompt_budget values must be greater than zero.",
            )

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = SystemConfigService._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _default_llm_model_name(self) -> str:
        primary_model = (self.settings.llm_model or self.settings.ollama_model).strip()
        return primary_model or "default-llm-model"

    def _default_reranker_provider(self) -> RerankerRoutingProvider:
        provider = self.settings.reranker_provider.lower().strip()
        if provider in {"heuristic", "mock"}:
            return "heuristic"
        if provider in {"openai", "openai-compatible", "openai_compatible"}:
            return "openai_compatible"
        return "heuristic"

    def _default_reranker_model_name(self) -> str:
        return self.settings.reranker_model.strip() or "default-reranker-model"

    def _default_reranker_strategy(self) -> RerankerDefaultStrategy:
        strategy = self.settings.reranker_default_strategy.lower().strip()
        if strategy == "provider" and self._default_reranker_provider() != "heuristic":
            return "provider"
        return "heuristic"


@lru_cache
def get_system_config_service() -> SystemConfigService:
    return SystemConfigService()
