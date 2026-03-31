"""查询档位配置模型。定义 fast/accurate 模式的参数结构。"""
from typing import Literal

from pydantic import BaseModel, Field

QueryMode = Literal["fast", "accurate"]
QueryPurpose = Literal["retrieval", "chat", "sop_generation"]


class QueryProfile(BaseModel):
    purpose: QueryPurpose
    mode: QueryMode
    top_k: int = Field(ge=1, le=20)
    candidate_top_k: int = Field(ge=1, le=200)
    lexical_top_k: int = Field(default=20, ge=1, le=200)
    rerank_top_n: int = Field(ge=1, le=20)
    timeout_budget_seconds: float = Field(gt=0)
    fallback_mode: QueryMode | None = None
