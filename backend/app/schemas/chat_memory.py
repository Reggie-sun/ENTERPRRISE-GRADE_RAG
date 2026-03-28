from datetime import datetime

from pydantic import BaseModel, Field


class ChatMemoryTurn(BaseModel):
    turn_id: str
    asked_at: datetime
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    response_mode: str = Field(min_length=1)
    document_id: str | None = None
    citation_count: int = Field(default=0, ge=0)


class ChatMemorySession(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    user_id: str = Field(min_length=1)
    username: str | None = None
    department_id: str | None = None
    updated_at: datetime
    turns: list[ChatMemoryTurn] = Field(default_factory=list)
