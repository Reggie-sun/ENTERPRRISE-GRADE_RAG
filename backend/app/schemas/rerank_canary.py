from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .event_log import EventLogActor
from .retrieval import (
    RetrievalRerankRouteStatus,
    RerankComparisonSummary,
    RerankPromotionRecommendation,
)


class RerankCanarySampleRecord(BaseModel):
    sample_id: str
    occurred_at: datetime
    actor: EventLogActor = Field(default_factory=EventLogActor)
    query: str = Field(min_length=1, max_length=2000)
    mode: str
    target_id: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    rerank_top_n: int = Field(default=0, ge=0)
    route_status: RetrievalRerankRouteStatus
    configured_provider: str
    configured_strategy: str
    configured_error_message: str | None = None
    heuristic_strategy: str = "heuristic"
    provider_candidate_strategy: str | None = None
    provider_candidate_error_message: str | None = None
    summary: RerankComparisonSummary
    provider_candidate_summary: RerankComparisonSummary | None = None
    recommendation: RerankPromotionRecommendation
    details: dict[str, Any] = Field(default_factory=dict)


class RerankCanarySummary(BaseModel):
    sample_size: int = Field(default=0, ge=0)
    eligible_count: int = Field(default=0, ge=0)
    hold_count: int = Field(default=0, ge=0)
    provider_active_count: int = Field(default=0, ge=0)
    rollback_active_count: int = Field(default=0, ge=0)
    not_applicable_count: int = Field(default=0, ge=0)
    other_count: int = Field(default=0, ge=0)
    latest_sample_id: str | None = None
    latest_decision: str | None = None
    latest_message: str | None = None
    last_sample_at: datetime | None = None
    last_eligible_at: datetime | None = None


class RerankCanaryListResponse(BaseModel):
    limit: int = Field(default=20, ge=1)
    items: list[RerankCanarySampleRecord] = Field(default_factory=list)
