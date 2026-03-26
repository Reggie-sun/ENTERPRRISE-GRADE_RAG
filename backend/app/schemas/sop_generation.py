from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from .query_profile import QueryMode
from .sop import SopDownloadFormat

SopGenerationRequestMode = Literal["scenario", "topic", "document"]


class SopGenerationCitation(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    snippet: str
    score: float
    source_path: str


class SopGenerationRequestBase(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    mode: QueryMode | None = Field(default=None)
    department_id: str | None = Field(default=None, min_length=1, max_length=128)
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("document_id", "doc_id"),
        serialization_alias="document_id",
    )
    title_hint: str | None = Field(default=None, max_length=200)


class SopGenerateByScenarioRequest(SopGenerationRequestBase):
    scenario_name: str = Field(min_length=1, max_length=200)
    process_name: str | None = Field(default=None, max_length=100)


class SopGenerateByTopicRequest(SopGenerationRequestBase):
    topic: str = Field(min_length=1, max_length=300)
    process_name: str | None = Field(default=None, max_length=100)
    scenario_name: str | None = Field(default=None, max_length=200)


class SopGenerateByDocumentRequest(SopGenerationRequestBase):
    document_id: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("document_id", "doc_id"),
        serialization_alias="document_id",
    )
    process_name: str | None = Field(default=None, max_length=100)
    scenario_name: str | None = Field(default=None, max_length=200)


class SopGenerationDraftResponse(BaseModel):
    request_mode: SopGenerationRequestMode
    generation_mode: str
    title: str
    department_id: str
    department_name: str
    process_name: str | None = None
    scenario_name: str | None = None
    topic: str | None = None
    content: str
    model: str
    citations: list[SopGenerationCitation] = Field(default_factory=list)


class SopDraftExportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    format: SopDownloadFormat
    department_id: str | None = Field(default=None, min_length=1, max_length=128)
    process_name: str | None = Field(default=None, max_length=100)
    scenario_name: str | None = Field(default=None, max_length=200)
    source_document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("source_document_id", "document_id", "doc_id"),
        serialization_alias="source_document_id",
    )
