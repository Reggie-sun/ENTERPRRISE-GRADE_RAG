from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .document import DocumentLifecycleStatus, IngestJobStatus
from .event_log import EventLogCategory, EventLogRecord
from .health import HealthResponse
from .rerank_canary import RerankCanarySummary
from .request_snapshot import RequestSnapshotRecord
from .request_trace import RequestTraceRecord
from .system_config import SystemConfigResponse


class OpsQueueSummary(BaseModel):
    available: bool  # 主契约稳定字段：队列探活是否可用。
    ingest_queue: str  # 主契约稳定字段：当前 ingest 队列名。
    backlog: int | None = Field(default=None, ge=0)  # 主契约稳定字段：当前积压数量。
    error: str | None = None  # 主契约稳定字段：探活失败时的最小错误说明。


class OpsRecentWindowSummary(BaseModel):
    sample_size: int = Field(default=0, ge=0)  # 主契约稳定字段：统计窗口样本数。
    failed_count: int = Field(default=0, ge=0)  # 主契约稳定字段：失败数。
    timeout_count: int = Field(default=0, ge=0)  # 主契约稳定字段：超时数。
    downgraded_count: int = Field(default=0, ge=0)  # 主契约稳定字段：降级数。
    duration_count: int = Field(default=0, ge=0)  # 主契约稳定字段：参与耗时统计的样本数。
    duration_p50_ms: int | None = Field(default=None, ge=0)  # 主契约稳定字段：P50。
    duration_p95_ms: int | None = Field(default=None, ge=0)  # 主契约稳定字段：P95。
    duration_p99_ms: int | None = Field(default=None, ge=0)  # 主契约稳定字段：P99。


class OpsRerankUsageSummary(BaseModel):
    sample_size: int = Field(default=0, ge=0)  # 主契约稳定字段：统计窗口样本数。
    provider_count: int = Field(default=0, ge=0)  # 主契约稳定字段：实际走 provider 的次数。
    heuristic_count: int = Field(default=0, ge=0)  # 主契约稳定字段：实际走 heuristic 的次数。
    skipped_count: int = Field(default=0, ge=0)  # 主契约稳定字段：跳过 rerank 的次数。
    document_preview_count: int = Field(default=0, ge=0)  # 主契约稳定字段：走 document preview 的次数。
    fallback_profile_count: int = Field(default=0, ge=0)  # 主契约稳定字段：走 fallback profile 的次数。
    unknown_count: int = Field(default=0, ge=0)  # 主契约稳定字段：历史老日志或未知策略数。
    other_count: int = Field(default=0, ge=0)  # 主契约稳定字段：其余策略数。
    last_provider_at: datetime | None = None  # 诊断字段：最近一次 provider 命中时间。
    last_heuristic_at: datetime | None = None  # 诊断字段：最近一次 heuristic 命中时间。


class OpsRerankDecisionSummary(BaseModel):
    decision: str  # 主契约稳定字段：observe_canary / keep_heuristic 等结论码。
    message: str  # 主契约稳定字段：当前结论说明。
    min_provider_samples: int = Field(default=0, ge=0)  # 主契约稳定字段：最小 provider 样本阈值。
    provider_sample_count: int = Field(default=0, ge=0)  # 主契约稳定字段：provider 样本数。
    heuristic_sample_count: int = Field(default=0, ge=0)  # 主契约稳定字段：heuristic 样本数。
    should_promote_to_provider: bool = False  # 主契约稳定字段：是否建议切到 provider。
    should_rollback_to_heuristic: bool = False  # 主契约稳定字段：是否建议回滚 heuristic。


class OpsCategorySummary(BaseModel):
    category: EventLogCategory  # 主契约稳定字段：chat / document / sop_generation。
    total: int = Field(default=0, ge=0)  # 主契约稳定字段：总量。
    failed_count: int = Field(default=0, ge=0)  # 主契约稳定字段：失败量。
    timeout_count: int = Field(default=0, ge=0)  # 主契约稳定字段：超时量。
    downgraded_count: int = Field(default=0, ge=0)  # 主契约稳定字段：降级量。
    last_event_at: datetime | None = None  # 诊断字段：最近一条事件时间。
    last_failed_at: datetime | None = None  # 诊断字段：最近一条失败时间。


class OpsRuntimeChannelSummary(BaseModel):
    channel: str  # 主契约稳定字段：chat_fast / chat_accurate / sop_generation。
    inflight: int = Field(default=0, ge=0)  # 主契约稳定字段：当前占用。
    limit: int = Field(default=0, ge=0)  # 主契约稳定字段：通道上限。
    available_slots: int = Field(default=0, ge=0)  # 主契约稳定字段：剩余槽位。


class OpsRuntimeGateSummary(BaseModel):
    acquire_timeout_ms: int = Field(default=0, ge=0)  # 主契约稳定字段：闸门获取超时。
    busy_retry_after_seconds: int = Field(default=0, ge=0)  # 主契约稳定字段：忙时 Retry-After。
    per_user_online_max_inflight: int = Field(default=0, ge=0)  # 主契约稳定字段：单用户上限。
    active_users: int = Field(default=0, ge=0)  # 主契约稳定字段：当前活跃用户数。
    max_user_inflight: int = Field(default=0, ge=0)  # 主契约稳定字段：当前单用户峰值。
    channels: list[OpsRuntimeChannelSummary] = Field(default_factory=list)  # 主契约稳定字段：通道占用。


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
    checked_at: datetime  # 主契约稳定字段：摘要生成时间。
    health: HealthResponse  # 主契约稳定字段：系统健康总览。
    queue: OpsQueueSummary  # 主契约稳定字段：队列积压总览。
    runtime_gate: OpsRuntimeGateSummary  # 主契约稳定字段：并发闸门总览。
    recent_window: OpsRecentWindowSummary  # 主契约稳定字段：最近窗口统计。
    rerank_usage: OpsRerankUsageSummary  # 主契约稳定字段：rerank 实际流量摘要。
    rerank_decision: OpsRerankDecisionSummary  # 主契约稳定字段：默认策略建议。
    rerank_canary: RerankCanarySummary  # 诊断字段：rerank canary 样本摘要。
    stuck_ingest_jobs: list[OpsStuckIngestJobSummary] = Field(default_factory=list)  # 诊断字段：卡住的 ingest jobs。
    categories: list[OpsCategorySummary] = Field(default_factory=list)  # 主契约稳定字段：按类别聚合统计。
    recent_failures: list[EventLogRecord] = Field(default_factory=list)  # 主契约稳定字段：最近失败事件简表。
    recent_degraded: list[EventLogRecord] = Field(default_factory=list)  # 主契约稳定字段：最近降级事件简表。
    recent_traces: list[RequestTraceRecord] = Field(default_factory=list)  # 诊断字段：最近 trace 列表。
    recent_snapshots: list[RequestSnapshotRecord] = Field(default_factory=list)  # 诊断字段：最近 snapshot 列表。
    config: SystemConfigResponse  # 主契约稳定字段：当前系统配置总览。
