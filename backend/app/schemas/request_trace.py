"""请求追踪模型。定义请求阶段追踪的结构。"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .event_log import EventLogActor, EventLogCategory, EventLogOutcome

RequestTraceStageName = Literal["query_rewrite", "retrieval", "rerank", "embedding", "lexical", "fusion", "ocr_filter", "permission_filter", "llm", "answer"]
RequestTraceStageStatus = Literal["success", "failed", "skipped", "degraded"]


class RequestTraceStage(BaseModel):
    stage: RequestTraceStageName
    status: RequestTraceStageStatus
    duration_ms: int | None = Field(default=None, ge=0)
    input_size: int | None = Field(default=None, ge=0)
    output_size: int | None = Field(default=None, ge=0)
    cache_hit: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RequestTraceRecord(BaseModel):
    trace_id: str
    request_id: str
    category: EventLogCategory
    action: str = Field(min_length=1, max_length=64)
    outcome: EventLogOutcome
    occurred_at: datetime
    actor: EventLogActor = Field(default_factory=EventLogActor)
    target_type: str | None = None
    target_id: str | None = None
    mode: str | None = None
    top_k: int | None = Field(default=None, ge=1)
    candidate_top_k: int | None = Field(default=None, ge=1)
    rerank_top_n: int | None = Field(default=None, ge=1)
    total_duration_ms: int | None = Field(default=None, ge=0)
    timeout_flag: bool = False
    downgraded_from: str | None = None
    response_mode: str | None = None
    error_message: str | None = None
    stages: list[RequestTraceStage] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class RequestTraceQueryFilters(BaseModel):
    category: EventLogCategory | None = None
    action: str | None = None
    outcome: EventLogOutcome | None = None
    username: str | None = None
    user_id: str | None = None
    department_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    target_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class RequestTraceListResponse(BaseModel):
    items: list[RequestTraceRecord] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
