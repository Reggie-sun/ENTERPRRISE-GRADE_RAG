from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EventLogCategory = Literal["chat", "document", "sop_generation"]
EventLogOutcome = Literal["success", "failed"]


class EventLogActor(BaseModel):
    tenant_id: str | None = None
    user_id: str | None = None
    username: str | None = None
    role_id: str | None = None
    department_id: str | None = None


class EventLogRecord(BaseModel):
    event_id: str
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
    duration_ms: int | None = Field(default=None, ge=0)
    timeout_flag: bool = False
    downgraded_from: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EventLogListResponse(BaseModel):
    items: list[EventLogRecord] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class EventLogQueryFilters(BaseModel):
    category: EventLogCategory | None = None
    action: str | None = None
    outcome: EventLogOutcome | None = None
    username: str | None = None
    user_id: str | None = None
    department_id: str | None = None
    target_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
