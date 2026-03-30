from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueryModeConfig(BaseModel):
    top_k_default: int = Field(ge=1, le=20)  # 主契约稳定字段：最终返回给 retrieval/chat 的默认 top_k。
    candidate_multiplier: int = Field(ge=1, le=20)  # 主契约稳定字段：候选召回放大倍率。
    lexical_top_k: int = Field(ge=1, le=200)  # 主契约稳定字段：hybrid 词项召回上限。
    rerank_top_n: int = Field(ge=1, le=20)  # 主契约稳定字段：rerank 后保留条数。
    timeout_budget_seconds: float = Field(gt=0)  # 主契约稳定字段：单请求预算秒数。


class QueryProfilesConfig(BaseModel):
    fast: QueryModeConfig
    accurate: QueryModeConfig


class ModelRoutingConfig(BaseModel):
    fast_model: str = Field(min_length=1)  # 主契约稳定字段：fast 档模型名。
    accurate_model: str = Field(min_length=1)  # 主契约稳定字段：accurate 档模型名。
    sop_generation_model: str = Field(min_length=1)  # 主契约稳定字段：SOP 生成模型名。


RerankerRoutingProvider = Literal["heuristic", "openai_compatible"]
RerankerDefaultStrategy = Literal["heuristic", "provider"]


class RerankerRoutingConfig(BaseModel):
    provider: RerankerRoutingProvider = "heuristic"  # 主契约稳定字段：配置的 reranker provider。
    default_strategy: RerankerDefaultStrategy = "heuristic"  # 主契约稳定字段：heuristic / provider 默认策略。
    model: str = Field(min_length=1)  # 主契约稳定字段：配置的 reranker model。
    timeout_seconds: float = Field(gt=0, le=60)  # 主契约稳定字段：单次 rerank 超时。
    failure_cooldown_seconds: float = Field(default=15.0, gt=0, le=300)  # 主契约稳定字段：失败冷却窗口。


class DegradeControlsConfig(BaseModel):
    rerank_fallback_enabled: bool = True  # 主契约稳定字段：provider -> heuristic 降级开关。
    accurate_to_fast_fallback_enabled: bool = True  # 主契约稳定字段：accurate -> fast 降级开关。
    retrieval_fallback_enabled: bool = True  # 主契约稳定字段：LLM 失败时 retrieval fallback 开关。


class RetryControlsConfig(BaseModel):
    llm_retry_enabled: bool = True  # 主契约稳定字段：是否启用 LLM 重试。
    llm_retry_max_attempts: int = Field(default=2, ge=1, le=5)  # 主契约稳定字段：最大重试次数。
    llm_retry_backoff_ms: int = Field(default=400, ge=0, le=10_000)  # 主契约稳定字段：重试退避毫秒。


class ConcurrencyControlsConfig(BaseModel):
    fast_max_inflight: int = Field(default=24, ge=1, le=200)  # 主契约稳定字段：fast 通道上限。
    accurate_max_inflight: int = Field(default=6, ge=1, le=100)  # 主契约稳定字段：accurate 通道上限。
    sop_generation_max_inflight: int = Field(default=3, ge=1, le=50)  # 主契约稳定字段：SOP 通道上限。
    per_user_online_max_inflight: int = Field(default=3, ge=1, le=20)  # 主契约稳定字段：单用户在线上限。
    acquire_timeout_ms: int = Field(default=800, ge=0, le=30_000)  # 主契约稳定字段：闸门等待超时。
    busy_retry_after_seconds: int = Field(default=5, ge=1, le=300)  # 主契约稳定字段：忙时 Retry-After。


class PromptBudgetConfig(BaseModel):
    max_prompt_tokens: int = Field(default=2200, ge=256, le=32_000)  # 主契约稳定字段：prompt 预算。
    reserved_completion_tokens: int = Field(default=512, ge=64, le=8_192)  # 主契约稳定字段：completion 预留。
    memory_prompt_tokens: int = Field(default=360, ge=64, le=4_096)  # 主契约稳定字段：memory 预算。


class SystemConfigUpdateRequest(BaseModel):
    query_profiles: QueryProfilesConfig
    model_routing: ModelRoutingConfig
    reranker_routing: RerankerRoutingConfig
    degrade_controls: DegradeControlsConfig
    retry_controls: RetryControlsConfig
    concurrency_controls: ConcurrencyControlsConfig
    prompt_budget: PromptBudgetConfig


class SystemConfigResponse(BaseModel):
    query_profiles: QueryProfilesConfig  # 主契约稳定字段：检索问答档位配置。
    model_routing: ModelRoutingConfig  # 主契约稳定字段：模型路由配置。
    reranker_routing: RerankerRoutingConfig  # 主契约稳定字段：rerank 路由配置。
    degrade_controls: DegradeControlsConfig  # 主契约稳定字段：降级开关。
    retry_controls: RetryControlsConfig  # 主契约稳定字段：重试开关。
    concurrency_controls: ConcurrencyControlsConfig  # 主契约稳定字段：并发控制配置。
    prompt_budget: PromptBudgetConfig  # 主契约稳定字段：prompt 预算配置。
    updated_at: datetime | None = None  # 主契约稳定字段：最近更新时间。
    updated_by: str | None = None  # 主契约稳定字段：最近修改人。
