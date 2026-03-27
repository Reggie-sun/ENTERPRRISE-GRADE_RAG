from pydantic import BaseModel


class HealthVectorStore(BaseModel):
    provider: str
    url: str
    collection: str


class HealthLLM(BaseModel):
    provider: str
    base_url: str
    model: str


class HealthEmbedding(BaseModel):
    provider: str
    base_url: str
    model: str


class HealthQueue(BaseModel):
    provider: str
    broker_url: str
    result_backend: str
    ingest_queue: str


class HealthMetadataStore(BaseModel):
    provider: str
    postgres_enabled: bool
    dsn_configured: bool


class HealthOCR(BaseModel):
    provider: str
    language: str
    enabled: bool
    ready: bool
    pdf_native_text_min_chars: int
    angle_cls_enabled: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    vector_store: HealthVectorStore
    llm: HealthLLM
    embedding: HealthEmbedding
    queue: HealthQueue
    metadata_store: HealthMetadataStore
    ocr: HealthOCR
