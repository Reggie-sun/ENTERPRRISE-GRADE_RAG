from datetime import datetime

from pydantic import BaseModel, Field

from .event_log import EventLogCategory, EventLogRecord
from .health import HealthResponse
from .system_config import SystemConfigResponse


class OpsQueueSummary(BaseModel):
    available: bool
    ingest_queue: str
    backlog: int | None = Field(default=None, ge=0)
    error: str | None = None


class OpsRecentWindowSummary(BaseModel):
    sample_size: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    timeout_count: int = Field(default=0, ge=0)
    downgraded_count: int = Field(default=0, ge=0)
    duration_count: int = Field(default=0, ge=0)
    duration_p50_ms: int | None = Field(default=None, ge=0)
    duration_p95_ms: int | None = Field(default=None, ge=0)
    duration_p99_ms: int | None = Field(default=None, ge=0)


class OpsCategorySummary(BaseModel):
    category: EventLogCategory
    total: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    timeout_count: int = Field(default=0, ge=0)
    downgraded_count: int = Field(default=0, ge=0)
    last_event_at: datetime | None = None
    last_failed_at: datetime | None = None


class OpsSummaryResponse(BaseModel):
    checked_at: datetime
    health: HealthResponse
    queue: OpsQueueSummary
    recent_window: OpsRecentWindowSummary
    categories: list[OpsCategorySummary] = Field(default_factory=list)
    recent_failures: list[EventLogRecord] = Field(default_factory=list)
    recent_degraded: list[EventLogRecord] = Field(default_factory=list)
    config: SystemConfigResponse
