from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, status

from ..core.config import Settings, get_settings
from ..db.system_config_repository import FilesystemSystemConfigRepository, SystemConfigRepository
from ..schemas.auth import AuthContext
from ..schemas.query_profile import QueryMode, QueryPurpose
from ..schemas.system_config import (
    DegradeControlsConfig,
    ModelRoutingConfig,
    QueryModeConfig,
    QueryProfilesConfig,
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
        self._validate_retry_controls(payload.retry_controls)
        record = SystemConfigResponse(
            query_profiles=payload.query_profiles,
            model_routing=payload.model_routing,
            degrade_controls=payload.degrade_controls,
            retry_controls=payload.retry_controls,
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

    def get_degrade_controls(self) -> DegradeControlsConfig:
        return self._load_config().degrade_controls

    def get_retry_controls(self) -> RetryControlsConfig:
        return self._load_config().retry_controls

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
                    rerank_top_n=self.settings.query_fast_rerank_top_n,
                    timeout_budget_seconds=self.settings.query_fast_timeout_budget_seconds,
                ),
                accurate=QueryModeConfig(
                    top_k_default=self.settings.query_accurate_top_k_default,
                    candidate_multiplier=self.settings.query_accurate_candidate_multiplier,
                    rerank_top_n=self.settings.query_accurate_rerank_top_n,
                    timeout_budget_seconds=self.settings.query_accurate_timeout_budget_seconds,
                ),
            ),
            model_routing=ModelRoutingConfig(
                fast_model=self._default_llm_model_name(),
                accurate_model=self._default_llm_model_name(),
                sop_generation_model=self._default_llm_model_name(),
            ),
            degrade_controls=DegradeControlsConfig(),
            retry_controls=RetryControlsConfig(),
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


@lru_cache
def get_system_config_service() -> SystemConfigService:
    return SystemConfigService()
