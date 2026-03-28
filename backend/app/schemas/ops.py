from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .document import DocumentLifecycleStatus, IngestJobStatus
from .event_log import EventLogCategory, EventLogRecord
from .health import HealthResponse
from .request_snapshot import RequestSnapshotRecord
from .request_trace import RequestTraceRecord
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


class OpsRerankUsageSummary(BaseModel):
    sample_size: int = Field(default=0, ge=0)
    provider_count: int = Field(default=0, ge=0)
    heuristic_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    document_preview_count: int = Field(default=0, ge=0)
    fallback_profile_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    other_count: int = Field(default=0, ge=0)
    last_provider_at: datetime | None = None
    last_heuristic_at: datetime | None = None


class OpsRerankDecisionSummary(BaseModel):
    decision: str
    message: str
    min_provider_samples: int = Field(default=0, ge=0)
    provider_sample_count: int = Field(default=0, ge=0)
    heuristic_sample_count: int = Field(default=0, ge=0)
    should_promote_to_provider: bool = False
    should_rollback_to_heuristic: bool = False


class OpsCategorySummary(BaseModel):
    category: EventLogCategory
    total: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    timeout_count: int = Field(default=0, ge=0)
    downgraded_count: int = Field(default=0, ge=0)
    last_event_at: datetime | None = None
    last_failed_at: datetime | None = None


class OpsRuntimeChannelSummary(BaseModel):
    channel: str
    inflight: int = Field(default=0, ge=0)
    limit: int = Field(default=0, ge=0)
    available_slots: int = Field(default=0, ge=0)


class OpsRuntimeGateSummary(BaseModel):
    acquire_timeout_ms: int = Field(default=0, ge=0)
    busy_retry_after_seconds: int = Field(default=0, ge=0)
    per_user_online_max_inflight: int = Field(default=0, ge=0)
    active_users: int = Field(default=0, ge=0)
    max_user_inflight: int = Field(default=0, ge=0)
    channels: list[OpsRuntimeChannelSummary] = Field(default_factory=list)


OpsStuckIngestJobReason = Literal["artifacts_ready_but_inflight", "stale_inflight"]


class OpsStuckIngestJobSummary(BaseModel):
    doc_id: str
    job_id: str
    file_name: str
    document_status: DocumentLifecycleStatus
    job_status: IngestJobStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    updated_at: datetime
    stale_seconds: int = Field(default=0, ge=0)
    has_materialized_artifacts: bool = False
    reason: OpsStuckIngestJobReason


class OpsSummaryResponse(BaseModel):
    checked_at: datetime
    health: HealthResponse
    queue: OpsQueueSummary
    runtime_gate: OpsRuntimeGateSummary
    recent_window: OpsRecentWindowSummary
    rerank_usage: OpsRerankUsageSummary
    rerank_decision: OpsRerankDecisionSummary
    stuck_ingest_jobs: list[OpsStuckIngestJobSummary] = Field(default_factory=list)
    categories: list[OpsCategorySummary] = Field(default_factory=list)
    recent_failures: list[EventLogRecord] = Field(default_factory=list)
    recent_degraded: list[EventLogRecord] = Field(default_factory=list)
    recent_traces: list[RequestTraceRecord] = Field(default_factory=list)
    recent_snapshots: list[RequestSnapshotRecord] = Field(default_factory=list)
    config: SystemConfigResponse
