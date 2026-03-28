from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..db.system_config_repository import FilesystemSystemConfigRepository, SystemConfigRepository
from ..schemas.auth import AuthContext
from ..schemas.query_profile import QueryMode, QueryPurpose
from ..schemas.system_config import (
    ConcurrencyControlsConfig,
    DegradeControlsConfig,
    ModelRoutingConfig,
    QueryModeConfig,
    QueryProfilesConfig,
    RerankerRoutingConfig,
    RetryControlsConfig,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
)


class SystemConfigService:
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
        record = SystemConfigResponse(
            query_profiles=payload.query_profiles,
            model_routing=payload.model_routing,
            reranker_routing=payload.reranker_routing,
            degrade_controls=payload.degrade_controls,
            retry_controls=payload.retry_controls,
            concurrency_controls=payload.concurrency_controls,
            updated_at=datetime.now(timezone.utc),
            updated_by=auth_context.user.user_id,
        )
        self.repository.write(record.model_dump(mode="json"))
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

    def get_llm_model_for_request(self, *, purpose: QueryPurpose, mode: QueryMode) -> str:
        config = self.get_model_routing()
        if purpose == "sop_generation":
            return config.sop_generation_model.strip()
        if mode == "accurate":
            return config.accurate_model.strip()
        return config.fast_model.strip()

    def _load_config(self) -> SystemConfigResponse:
        defaults = self._build_default_config()
        stored = self.repository.read()
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
        )

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

    def _default_reranker_provider(self) -> str:
        provider = self.settings.reranker_provider.lower().strip()
        if provider in {"heuristic", "mock"}:
            return "heuristic"
        if provider in {"openai", "openai-compatible", "openai_compatible"}:
            return "openai_compatible"
        return "heuristic"

    def _default_reranker_model_name(self) -> str:
        return self.settings.reranker_model.strip() or "default-reranker-model"


@lru_cache
def get_system_config_service() -> SystemConfigService:
    return SystemConfigService()
