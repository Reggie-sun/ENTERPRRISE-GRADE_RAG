from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .chat import ChatRequest, ChatResponse, Citation
from .event_log import EventLogActor, EventLogCategory, EventLogOutcome
from .query_profile import QueryProfile
from .sop_generation import (
    SopGenerateByDocumentRequest,
    SopGenerateByScenarioRequest,
    SopGenerateByTopicRequest,
    SopGenerationDraftResponse,
)

RequestSnapshotReplayMode = Literal["original", "current"]
RequestSnapshotRewriteStatus = Literal["skipped", "applied", "failed"]
RequestSnapshotRequestPayload = (
    ChatRequest
    | SopGenerateByDocumentRequest
    | SopGenerateByScenarioRequest
    | SopGenerateByTopicRequest
)
RequestSnapshotResponsePayload = ChatResponse | SopGenerationDraftResponse


class RequestSnapshotRewrite(BaseModel):
    status: RequestSnapshotRewriteStatus
    original_question: str = Field(min_length=1)
    rewritten_question: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RequestSnapshotContext(BaseModel):
    rank: int = Field(ge=1)
    chunk_id: str
    document_id: str
    document_name: str
    snippet: str
    score: float
    source_path: str
    retrieval_strategy: str | None = None
    vector_score: float | None = None
    lexical_score: float | None = None
    fused_score: float | None = None


class RequestSnapshotModelRoute(BaseModel):
    provider: str
    base_url: str | None = None
    model: str


class RequestSnapshotComponentVersions(BaseModel):
    prompt_version: str
    embedding_provider: str
    embedding_model: str
    reranker_provider: str
    reranker_model: str


class RequestSnapshotResult(BaseModel):
    response_mode: str
    model: str
    answer_preview: str | None = None
    answer_chars: int = Field(default=0, ge=0)
    citation_count: int = Field(default=0, ge=0)
    rerank_strategy: str = Field(default="skipped")
    downgraded_from: str | None = None
    timeout_flag: bool = False
    error_message: str | None = None


class RequestSnapshotRecord(BaseModel):
    snapshot_id: str
    trace_id: str
    request_id: str
    category: EventLogCategory
    action: str = Field(min_length=1, max_length=64)
    outcome: EventLogOutcome
    occurred_at: datetime
    actor: EventLogActor = Field(default_factory=EventLogActor)
    target_type: str | None = None
    target_id: str | None = None
    request: RequestSnapshotRequestPayload
    profile: QueryProfile
    memory_summary: str | None = None
    rewrite: RequestSnapshotRewrite
    contexts: list[RequestSnapshotContext] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    model_route: RequestSnapshotModelRoute
    component_versions: RequestSnapshotComponentVersions
    result: RequestSnapshotResult
    details: dict[str, Any] = Field(default_factory=dict)


class RequestSnapshotQueryFilters(BaseModel):
    category: EventLogCategory | None = None
    action: str | None = None
    outcome: EventLogOutcome | None = None
    username: str | None = None
    user_id: str | None = None
    department_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    snapshot_id: str | None = None
    target_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class RequestSnapshotListResponse(BaseModel):
    items: list[RequestSnapshotRecord] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RequestSnapshotReplayRequest(BaseModel):
    replay_mode: RequestSnapshotReplayMode = "original"


class RequestSnapshotReplayResponse(BaseModel):
    snapshot_id: str
    replay_mode: RequestSnapshotReplayMode
    original_trace_id: str
    original_request_id: str
    replayed_request: RequestSnapshotRequestPayload
    response: RequestSnapshotResponsePayload
