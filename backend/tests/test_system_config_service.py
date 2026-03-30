from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.db.system_config_repository import FilesystemSystemConfigRepository
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.system_config import (
    ConcurrencyControlsConfig,
    DegradeControlsConfig,
    ModelRoutingConfig,
    PromptBudgetConfig,
    QueryModeConfig,
    QueryProfilesConfig,
    RerankerRoutingConfig,
    RetryControlsConfig,
    SystemConfigUpdateRequest,
)
from backend.app.services.query_profile_service import QueryProfileService
from backend.app.services.system_config_service import SystemConfigService


def _build_auth_context(role_id: str = "sys_admin") -> AuthContext:
    department = DepartmentRecord(
        department_id="dept_digitalization",
        tenant_id="wl",
        department_name="数字化部",
    )
    role = RoleDefinition(
        role_id=role_id,
        name=role_id,
        description=role_id,
        data_scope="global" if role_id == "sys_admin" else "department",
        is_admin=role_id != "employee",
    )
    user = UserRecord(
        user_id=f"user_{role_id}",
        tenant_id="wl",
        username=f"{role_id}.user",
        display_name=role_id,
        department_id=department.department_id,
        role_id=role_id,
    )
    return AuthContext(
        user=user,
        role=role,
        department=department,
        accessible_department_ids=[department.department_id],
        token_id="token_001",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        system_config_path=tmp_path / "data" / "system_config.json",
    )


def test_system_config_service_returns_default_query_profiles_when_file_missing(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    payload = service.get_config(auth_context=_build_auth_context())

    assert payload.query_profiles.fast.top_k_default == 5
    assert payload.query_profiles.fast.candidate_multiplier == 2
    assert payload.query_profiles.fast.lexical_top_k == 10
    assert payload.query_profiles.fast.rerank_top_n == 3
    assert payload.query_profiles.fast.timeout_budget_seconds == 12.0
    assert payload.query_profiles.accurate.top_k_default == 8
    assert payload.query_profiles.accurate.lexical_top_k == 32
    assert payload.model_routing.fast_model == "qwen2.5:7b"
    assert payload.reranker_routing.provider == "heuristic"
    assert payload.reranker_routing.default_strategy == "heuristic"
    assert payload.reranker_routing.model == "BAAI/bge-reranker-v2-m3"
    assert payload.reranker_routing.timeout_seconds == 12.0
    assert payload.reranker_routing.failure_cooldown_seconds == 15.0
    assert payload.degrade_controls.rerank_fallback_enabled is True
    assert payload.retry_controls.llm_retry_max_attempts == 2
    assert payload.concurrency_controls.fast_max_inflight == 24
    assert payload.concurrency_controls.accurate_max_inflight == 6
    assert payload.concurrency_controls.sop_generation_max_inflight == 3
    assert payload.concurrency_controls.per_user_online_max_inflight == 3
    assert payload.prompt_budget.max_prompt_tokens == 2200
    assert payload.prompt_budget.reserved_completion_tokens == 512
    assert payload.prompt_budget.memory_prompt_tokens == 360
    assert payload.updated_at is None
    assert payload.updated_by is None


def test_system_config_service_persists_updated_query_profiles(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    repository = FilesystemSystemConfigRepository(settings.system_config_path)
    service = SystemConfigService(settings, repository=repository)

    updated = service.update_config(
        SystemConfigUpdateRequest(
            query_profiles=QueryProfilesConfig(
                fast=QueryModeConfig(
                    top_k_default=6,
                    candidate_multiplier=3,
                    lexical_top_k=12,
                    rerank_top_n=4,
                    timeout_budget_seconds=10.0,
                ),
                accurate=QueryModeConfig(
                    top_k_default=10,
                    candidate_multiplier=5,
                    lexical_top_k=24,
                    rerank_top_n=6,
                    timeout_budget_seconds=20.0,
                ),
            ),
            model_routing=ModelRoutingConfig(
                fast_model="Qwen/Fast-7B",
                accurate_model="Qwen/Accurate-14B",
                sop_generation_model="Qwen/SOP-14B",
            ),
            reranker_routing=RerankerRoutingConfig(
                provider="openai_compatible",
                default_strategy="provider",
                model="Qwen/Reranker-Prod",
                timeout_seconds=9.5,
                failure_cooldown_seconds=22.0,
            ),
            degrade_controls=DegradeControlsConfig(
                rerank_fallback_enabled=False,
                accurate_to_fast_fallback_enabled=True,
                retrieval_fallback_enabled=False,
            ),
            retry_controls=RetryControlsConfig(
                llm_retry_enabled=True,
                llm_retry_max_attempts=3,
                llm_retry_backoff_ms=800,
            ),
            concurrency_controls=ConcurrencyControlsConfig(
                fast_max_inflight=30,
                accurate_max_inflight=8,
                sop_generation_max_inflight=4,
                per_user_online_max_inflight=3,
                acquire_timeout_ms=1200,
                busy_retry_after_seconds=9,
            ),
            prompt_budget=PromptBudgetConfig(
                max_prompt_tokens=2400,
                reserved_completion_tokens=640,
                memory_prompt_tokens=320,
            ),
        ),
        auth_context=_build_auth_context(),
    )

    reloaded = service.get_config(auth_context=_build_auth_context())
    query_profile_service = QueryProfileService(settings, system_config_service=service)
    fast_profile = query_profile_service.resolve(purpose="chat")
    accurate_profile = query_profile_service.resolve(purpose="sop_generation")

    assert updated.updated_by == "user_sys_admin"
    assert reloaded.query_profiles.fast.top_k_default == 6
    assert reloaded.model_routing.fast_model == "Qwen/Fast-7B"
    assert reloaded.reranker_routing.provider == "openai_compatible"
    assert reloaded.reranker_routing.default_strategy == "provider"
    assert reloaded.reranker_routing.model == "Qwen/Reranker-Prod"
    assert reloaded.reranker_routing.timeout_seconds == 9.5
    assert reloaded.reranker_routing.failure_cooldown_seconds == 22.0
    assert reloaded.degrade_controls.retrieval_fallback_enabled is False
    assert reloaded.retry_controls.llm_retry_max_attempts == 3
    assert reloaded.concurrency_controls.fast_max_inflight == 30
    assert reloaded.concurrency_controls.per_user_online_max_inflight == 3
    assert reloaded.concurrency_controls.acquire_timeout_ms == 1200
    assert reloaded.prompt_budget.max_prompt_tokens == 2400
    assert reloaded.prompt_budget.reserved_completion_tokens == 640
    assert reloaded.prompt_budget.memory_prompt_tokens == 320
    assert fast_profile.top_k == 6
    assert fast_profile.candidate_top_k == 18
    assert fast_profile.lexical_top_k == 12
    assert fast_profile.rerank_top_n == 4
    assert fast_profile.timeout_budget_seconds == 10.0
    assert accurate_profile.top_k == 10
    assert accurate_profile.candidate_top_k == 50
    assert accurate_profile.lexical_top_k == 24
    assert accurate_profile.rerank_top_n == 6
    assert accurate_profile.timeout_budget_seconds == 20.0


def test_system_config_service_rejects_non_sys_admin_access(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.get_config(auth_context=_build_auth_context("department_admin"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You do not have access to system configuration."


def test_system_config_service_validates_query_profile_relationships(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=QueryProfilesConfig(
                    fast=QueryModeConfig(
                        top_k_default=5,
                        candidate_multiplier=2,
                        lexical_top_k=5,
                        rerank_top_n=6,
                        timeout_budget_seconds=12.0,
                    ),
                    accurate=QueryModeConfig(
                        top_k_default=8,
                        candidate_multiplier=4,
                        lexical_top_k=8,
                        rerank_top_n=5,
                        timeout_budget_seconds=24.0,
                    ),
                ),
                model_routing=ModelRoutingConfig(
                    fast_model="Qwen/Fast-7B",
                    accurate_model="Qwen/Accurate-14B",
                    sop_generation_model="Qwen/SOP-14B",
                ),
                reranker_routing=RerankerRoutingConfig(
                    provider="heuristic",
                    default_strategy="heuristic",
                    model="BAAI/bge-reranker-v2-m3",
                    timeout_seconds=12.0,
                    failure_cooldown_seconds=15.0,
                ),
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "fast.rerank_top_n cannot be greater than fast.top_k_default."


def test_system_config_service_validates_lexical_top_k_relationships(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=QueryProfilesConfig(
                    fast=QueryModeConfig(
                        top_k_default=5,
                        candidate_multiplier=2,
                        lexical_top_k=4,
                        rerank_top_n=3,
                        timeout_budget_seconds=12.0,
                    ),
                    accurate=QueryModeConfig(
                        top_k_default=8,
                        candidate_multiplier=4,
                        lexical_top_k=8,
                        rerank_top_n=5,
                        timeout_budget_seconds=24.0,
                    ),
                ),
                model_routing=ModelRoutingConfig(
                    fast_model="Qwen/Fast-7B",
                    accurate_model="Qwen/Accurate-14B",
                    sop_generation_model="Qwen/SOP-14B",
                ),
                reranker_routing=RerankerRoutingConfig(
                    provider="heuristic",
                    default_strategy="heuristic",
                    model="BAAI/bge-reranker-v2-m3",
                    timeout_seconds=12.0,
                ),
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "fast.lexical_top_k cannot be smaller than fast.top_k_default."


def test_system_config_service_rejects_empty_model_route(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=service.get_config(auth_context=_build_auth_context()).query_profiles,
                model_routing=ModelRoutingConfig(
                    fast_model=" ",
                    accurate_model="Qwen/Accurate-14B",
                    sop_generation_model="Qwen/SOP-14B",
                ),
                reranker_routing=service.get_config(auth_context=_build_auth_context()).reranker_routing,
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "fast_model cannot be empty."


def test_system_config_service_validates_concurrency_relationships(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=service.get_config(auth_context=_build_auth_context()).query_profiles,
                model_routing=service.get_config(auth_context=_build_auth_context()).model_routing,
                reranker_routing=service.get_config(auth_context=_build_auth_context()).reranker_routing,
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(
                    fast_max_inflight=4,
                    accurate_max_inflight=5,
                    sop_generation_max_inflight=3,
                    per_user_online_max_inflight=2,
                    acquire_timeout_ms=800,
                    busy_retry_after_seconds=5,
                ),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "accurate_max_inflight cannot be greater than fast_max_inflight."


def test_system_config_service_validates_per_user_concurrency_relationships(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=service.get_config(auth_context=_build_auth_context()).query_profiles,
                model_routing=service.get_config(auth_context=_build_auth_context()).model_routing,
                reranker_routing=service.get_config(auth_context=_build_auth_context()).reranker_routing,
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(
                    fast_max_inflight=4,
                    accurate_max_inflight=2,
                    sop_generation_max_inflight=1,
                    per_user_online_max_inflight=5,
                    acquire_timeout_ms=800,
                    busy_retry_after_seconds=5,
                ),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "per_user_online_max_inflight cannot be greater than fast_max_inflight."


def test_system_config_service_rejects_provider_default_strategy_when_provider_is_heuristic(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=service.get_config(auth_context=_build_auth_context()).query_profiles,
                model_routing=service.get_config(auth_context=_build_auth_context()).model_routing,
                reranker_routing=RerankerRoutingConfig(
                    provider="heuristic",
                    default_strategy="provider",
                    model="BAAI/bge-reranker-v2-m3",
                    timeout_seconds=12.0,
                    failure_cooldown_seconds=15.0,
                ),
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(),
                prompt_budget=PromptBudgetConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "reranker_routing.default_strategy must be heuristic when provider is heuristic."


def test_system_config_service_validates_prompt_budget_relationships(tmp_path: Path) -> None:
    service = SystemConfigService(_build_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        service.update_config(
            SystemConfigUpdateRequest(
                query_profiles=service.get_config(auth_context=_build_auth_context()).query_profiles,
                model_routing=service.get_config(auth_context=_build_auth_context()).model_routing,
                reranker_routing=service.get_config(auth_context=_build_auth_context()).reranker_routing,
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
                concurrency_controls=ConcurrencyControlsConfig(),
                prompt_budget=PromptBudgetConfig(
                    max_prompt_tokens=512,
                    reserved_completion_tokens=256,
                    memory_prompt_tokens=512,
                ),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "prompt_budget.memory_prompt_tokens must be smaller than prompt_budget.max_prompt_tokens."
