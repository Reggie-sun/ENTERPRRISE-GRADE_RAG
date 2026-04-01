from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EventLogCategory = Literal["chat", "document", "retrieval", "sop_generation"]
EventLogOutcome = Literal["success", "failed"]


class EventLogActor(BaseModel):
    tenant_id: str | None = None  # 主契约稳定字段：租户上下文。
    user_id: str | None = None  # 主契约稳定字段：操作人 user_id。
    username: str | None = None  # 主契约稳定字段：操作人用户名。
    role_id: str | None = None  # 主契约稳定字段：操作时角色。
    department_id: str | None = None  # 主契约稳定字段：操作时部门。


class EventLogRecord(BaseModel):
    event_id: str  # 主契约稳定字段：事件唯一 ID。
    category: EventLogCategory  # 主契约稳定字段：业务类别。
    action: str = Field(min_length=1, max_length=64)  # 主契约稳定字段：动作名。
    outcome: EventLogOutcome  # 主契约稳定字段：success / failed。
    occurred_at: datetime  # 主契约稳定字段：事件发生时间。
    actor: EventLogActor = Field(default_factory=EventLogActor)  # 主契约稳定字段：操作人上下文。
    target_type: str | None = None  # 诊断字段：目标对象类型，允许继续扩展。
    target_id: str | None = None  # 主契约稳定字段：目标对象 ID。
    mode: str | None = None  # 主契约稳定字段：fast / accurate 等模式。
    top_k: int | None = Field(default=None, ge=1)  # 诊断字段：实际召回 top_k。
    candidate_top_k: int | None = Field(default=None, ge=1)  # 诊断字段：候选召回数。
    rerank_top_n: int | None = Field(default=None, ge=1)  # 诊断字段：rerank top_n。
    rerank_strategy: str | None = None  # 主契约稳定字段：heuristic / provider / skipped 等。
    rerank_provider: str | None = None  # 主契约稳定字段：heuristic / openai_compatible 等。
    rerank_model: str | None = None  # 诊断字段：具体 reranker model，允许继续演进。
    duration_ms: int | None = Field(default=None, ge=0)  # 主契约稳定字段：总耗时。
    timeout_flag: bool = False  # 诊断字段：是否命中过超时路径。
    downgraded_from: str | None = None  # 主契约稳定字段：若有降级，记录原模式。
    details: dict[str, Any] = Field(default_factory=dict)  # 诊断字段：排障扩展信息，不冻结内部结构。


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
    rerank_strategy: str | None = None
    rerank_provider: str | None = None
    date_from: date | None = None
    date_to: date | None = None
