from typing import Any

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    message: str
    status_code: int


class ErrorEnvelope(BaseModel):
    detail: Any
    error: ErrorInfo
