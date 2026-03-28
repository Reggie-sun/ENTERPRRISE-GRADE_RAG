from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueryModeConfig(BaseModel):
    top_k_default: int = Field(ge=1, le=20)
    candidate_multiplier: int = Field(ge=1, le=20)
    lexical_top_k: int = Field(ge=1, le=200)
    rerank_top_n: int = Field(ge=1, le=20)
    timeout_budget_seconds: float = Field(gt=0)


class QueryProfilesConfig(BaseModel):
    fast: QueryModeConfig
    accurate: QueryModeConfig


class ModelRoutingConfig(BaseModel):
    fast_model: str = Field(min_length=1)
    accurate_model: str = Field(min_length=1)
    sop_generation_model: str = Field(min_length=1)


RerankerRoutingProvider = Literal["heuristic", "openai_compatible"]
RerankerDefaultStrategy = Literal["heuristic", "provider"]


class RerankerRoutingConfig(BaseModel):
    provider: RerankerRoutingProvider = "heuristic"
    default_strategy: RerankerDefaultStrategy = "heuristic"
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, le=60)
    failure_cooldown_seconds: float = Field(default=15.0, gt=0, le=300)


class DegradeControlsConfig(BaseModel):
    rerank_fallback_enabled: bool = True
    accurate_to_fast_fallback_enabled: bool = True
    retrieval_fallback_enabled: bool = True


class RetryControlsConfig(BaseModel):
    llm_retry_enabled: bool = True
    llm_retry_max_attempts: int = Field(default=2, ge=1, le=5)
    llm_retry_backoff_ms: int = Field(default=400, ge=0, le=10_000)


class ConcurrencyControlsConfig(BaseModel):
    fast_max_inflight: int = Field(default=24, ge=1, le=200)
    accurate_max_inflight: int = Field(default=6, ge=1, le=100)
    sop_generation_max_inflight: int = Field(default=3, ge=1, le=50)
    per_user_online_max_inflight: int = Field(default=3, ge=1, le=20)
    acquire_timeout_ms: int = Field(default=800, ge=0, le=30_000)
    busy_retry_after_seconds: int = Field(default=5, ge=1, le=300)


class SystemConfigUpdateRequest(BaseModel):
    query_profiles: QueryProfilesConfig
    model_routing: ModelRoutingConfig
    reranker_routing: RerankerRoutingConfig
    degrade_controls: DegradeControlsConfig
    retry_controls: RetryControlsConfig
    concurrency_controls: ConcurrencyControlsConfig


class SystemConfigResponse(BaseModel):
    query_profiles: QueryProfilesConfig
    model_routing: ModelRoutingConfig
    reranker_routing: RerankerRoutingConfig
    degrade_controls: DegradeControlsConfig
    retry_controls: RetryControlsConfig
    concurrency_controls: ConcurrencyControlsConfig
    updated_at: datetime | None = None
    updated_by: str | None = None
