from typing import Any, Literal

from pydantic import BaseModel, Field

QueryRewriteStatus = Literal["skipped", "applied", "failed"]


class QueryRewriteResult(BaseModel):
    status: QueryRewriteStatus
    original_question: str = Field(min_length=1)
    rewritten_question: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
