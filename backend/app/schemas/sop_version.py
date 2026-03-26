from datetime import datetime

from pydantic import BaseModel, Field

from .sop import SopStatus
from .sop_generation import SopGenerationCitation, SopGenerationRequestMode


class SopVersionRecord(BaseModel):
    sop_id: str
    version: int = Field(ge=1)
    tenant_id: str
    title: str = Field(min_length=1)
    department_id: str
    department_ids: list[str] = Field(default_factory=list)
    process_name: str | None = None
    scenario_name: str | None = None
    topic: str | None = None
    status: SopStatus = "draft"
    content: str = Field(min_length=1)
    request_mode: SopGenerationRequestMode | None = None
    generation_mode: str = "manual"
    citations: list[SopGenerationCitation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class SopSaveRequest(BaseModel):
    sop_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    department_id: str | None = Field(default=None, min_length=1, max_length=128)
    process_name: str | None = Field(default=None, max_length=100)
    scenario_name: str | None = Field(default=None, max_length=200)
    topic: str | None = Field(default=None, max_length=300)
    status: SopStatus = "draft"
    content: str = Field(min_length=1, max_length=20_000)
    request_mode: SopGenerationRequestMode | None = None
    generation_mode: str = "manual"
    citations: list[SopGenerationCitation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SopSaveResponse(BaseModel):
    sop_id: str
    version: int = Field(ge=1)
    status: SopStatus
    title: str
    saved_at: datetime


class SopVersionSummary(BaseModel):
    sop_id: str
    version: int = Field(ge=1)
    title: str
    status: SopStatus
    generation_mode: str
    request_mode: SopGenerationRequestMode | None = None
    citations_count: int = Field(ge=0)
    created_by: str | None = None
    updated_by: str | None = None
    updated_at: datetime
    is_current: bool = False


class SopVersionListResponse(BaseModel):
    sop_id: str
    current_version: int = Field(ge=1)
    items: list[SopVersionSummary] = Field(default_factory=list)


class SopVersionDetailResponse(BaseModel):
    sop_id: str
    version: int = Field(ge=1)
    title: str
    tenant_id: str
    department_id: str
    process_name: str | None = None
    scenario_name: str | None = None
    topic: str | None = None
    status: SopStatus
    content: str
    request_mode: SopGenerationRequestMode | None = None
    generation_mode: str
    citations: list[SopGenerationCitation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime
    is_current: bool = False
