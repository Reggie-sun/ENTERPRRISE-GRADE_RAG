from datetime import datetime

from pydantic import BaseModel, Field


class QueryModeConfig(BaseModel):
    top_k_default: int = Field(ge=1, le=20)
    candidate_multiplier: int = Field(ge=1, le=20)
    rerank_top_n: int = Field(ge=1, le=20)
    timeout_budget_seconds: float = Field(gt=0)


class QueryProfilesConfig(BaseModel):
    fast: QueryModeConfig
    accurate: QueryModeConfig


class ModelRoutingConfig(BaseModel):
    fast_model: str = Field(min_length=1)
    accurate_model: str = Field(min_length=1)
    sop_generation_model: str = Field(min_length=1)


class DegradeControlsConfig(BaseModel):
    rerank_fallback_enabled: bool = True
    accurate_to_fast_fallback_enabled: bool = True
    retrieval_fallback_enabled: bool = True


class RetryControlsConfig(BaseModel):
    llm_retry_enabled: bool = True
    llm_retry_max_attempts: int = Field(default=2, ge=1, le=5)
    llm_retry_backoff_ms: int = Field(default=400, ge=0, le=10_000)


class SystemConfigUpdateRequest(BaseModel):
    query_profiles: QueryProfilesConfig
    model_routing: ModelRoutingConfig
    degrade_controls: DegradeControlsConfig
    retry_controls: RetryControlsConfig


class SystemConfigResponse(BaseModel):
    query_profiles: QueryProfilesConfig
    model_routing: ModelRoutingConfig
    degrade_controls: DegradeControlsConfig
    retry_controls: RetryControlsConfig
    updated_at: datetime | None = None
    updated_by: str | None = None
