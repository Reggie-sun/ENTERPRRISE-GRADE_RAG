from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.core.config import Settings
from backend.app.db.system_config_repository import FilesystemSystemConfigRepository
from backend.app.schemas.auth import AuthContext, DepartmentRecord, RoleDefinition, UserRecord
from backend.app.schemas.system_config import (
    DegradeControlsConfig,
    ModelRoutingConfig,
    QueryModeConfig,
    QueryProfilesConfig,
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
    assert payload.query_profiles.fast.rerank_top_n == 3
    assert payload.query_profiles.fast.timeout_budget_seconds == 12.0
    assert payload.query_profiles.accurate.top_k_default == 8
    assert payload.model_routing.fast_model == "qwen2.5:7b"
    assert payload.degrade_controls.rerank_fallback_enabled is True
    assert payload.retry_controls.llm_retry_max_attempts == 2
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
                    rerank_top_n=4,
                    timeout_budget_seconds=10.0,
                ),
                accurate=QueryModeConfig(
                    top_k_default=10,
                    candidate_multiplier=5,
                    rerank_top_n=6,
                    timeout_budget_seconds=20.0,
                ),
            ),
            model_routing=ModelRoutingConfig(
                fast_model="Qwen/Fast-7B",
                accurate_model="Qwen/Accurate-14B",
                sop_generation_model="Qwen/SOP-14B",
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
    assert reloaded.degrade_controls.retrieval_fallback_enabled is False
    assert reloaded.retry_controls.llm_retry_max_attempts == 3
    assert fast_profile.top_k == 6
    assert fast_profile.candidate_top_k == 18
    assert fast_profile.rerank_top_n == 4
    assert fast_profile.timeout_budget_seconds == 10.0
    assert accurate_profile.top_k == 10
    assert accurate_profile.candidate_top_k == 50
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
                        rerank_top_n=6,
                        timeout_budget_seconds=12.0,
                    ),
                    accurate=QueryModeConfig(
                        top_k_default=8,
                        candidate_multiplier=4,
                        rerank_top_n=5,
                        timeout_budget_seconds=24.0,
                    ),
                ),
                model_routing=ModelRoutingConfig(
                    fast_model="Qwen/Fast-7B",
                    accurate_model="Qwen/Accurate-14B",
                    sop_generation_model="Qwen/SOP-14B",
                ),
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "fast.rerank_top_n cannot be greater than fast.top_k_default."


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
                degrade_controls=DegradeControlsConfig(),
                retry_controls=RetryControlsConfig(),
            ),
            auth_context=_build_auth_context(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "fast_model cannot be empty."
