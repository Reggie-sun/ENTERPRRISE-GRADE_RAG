"""统一错误响应模型。定义标准化的错误信封(ErrorEnvelope)结构。"""
from typing import Any

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    message: str
    status_code: int


class ErrorEnvelope(BaseModel):
    detail: Any
    error: ErrorInfo
