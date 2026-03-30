from pydantic import BaseModel


class HealthVectorStore(BaseModel):
    provider: str  # 主契约稳定字段：向量库 provider。
    url: str  # 主契约稳定字段：向量库地址。
    collection: str  # 主契约稳定字段：当前 collection。


class HealthLLM(BaseModel):
    provider: str  # 主契约稳定字段：LLM provider。
    base_url: str  # 主契约稳定字段：LLM base_url。
    model: str  # 主契约稳定字段：当前 LLM model。


class HealthEmbedding(BaseModel):
    provider: str  # 主契约稳定字段：Embedding provider。
    base_url: str  # 主契约稳定字段：Embedding base_url。
    model: str  # 主契约稳定字段：当前 embedding model。


class HealthReranker(BaseModel):
    provider: str  # 主契约稳定字段：配置的 provider。
    base_url: str  # 主契约稳定字段：rerank base_url。
    model: str  # 主契约稳定字段：配置的 model。
    default_strategy: str  # 主契约稳定字段：默认策略。
    timeout_seconds: float  # 主契约稳定字段：超时配置。
    failure_cooldown_seconds: float  # 主契约稳定字段：冷却配置。
    effective_provider: str  # 主契约稳定字段：实际生效 provider。
    effective_model: str  # 主契约稳定字段：实际生效 model。
    effective_strategy: str  # 主契约稳定字段：实际生效策略。
    fallback_enabled: bool  # 主契约稳定字段：是否允许 fallback。
    lock_active: bool  # 主契约稳定字段：当前是否处于锁定窗口。
    lock_source: str | None = None  # 诊断字段：锁定来源。
    cooldown_remaining_seconds: float  # 主契约稳定字段：剩余冷却秒数。
    ready: bool  # 主契约稳定字段：当前 provider 是否 ready。
    detail: str | None = None  # 诊断字段：探活失败或异常详情。


class HealthQueue(BaseModel):
    provider: str  # 主契约稳定字段：队列 provider。
    broker_url: str  # 主契约稳定字段：broker 地址。
    result_backend: str  # 主契约稳定字段：result backend 地址。
    ingest_queue: str  # 主契约稳定字段：ingest queue 名称。


class HealthMetadataStore(BaseModel):
    provider: str  # 主契约稳定字段：metadata store provider。
    postgres_enabled: bool  # 主契约稳定字段：是否启用 postgres。
    dsn_configured: bool  # 主契约稳定字段：dsn 是否配置。


class HealthOCR(BaseModel):
    provider: str  # 主契约稳定字段：OCR provider。
    language: str  # 主契约稳定字段：OCR 语言配置。
    enabled: bool  # 主契约稳定字段：是否启用 OCR。
    ready: bool  # 主契约稳定字段：OCR 是否 ready。
    pdf_native_text_min_chars: int  # 主契约稳定字段：PDF 原生文本阈值。
    angle_cls_enabled: bool  # 主契约稳定字段：angle cls 开关。
    detail: str | None = None  # 诊断字段：OCR 初始化/探活详情。


class HealthTokenizer(BaseModel):
    provider: str  # 主契约稳定字段：tokenizer provider。
    model: str  # 主契约稳定字段：tokenizer 对应模型名或当前估算目标模型。
    ready: bool  # 主契约稳定字段：tokenizer 预算服务是否 ready。
    trust_remote_code: bool  # 主契约稳定字段：是否允许 remote code。
    detail: str | None = None  # 诊断字段：当前 tokenizer 运行说明。
    error: str | None = None  # 诊断字段：加载/探活失败详情。


class HealthResponse(BaseModel):
    status: str  # 主契约稳定字段：整体状态。
    app_name: str  # 主契约稳定字段：应用名。
    environment: str  # 主契约稳定字段：环境名。
    vector_store: HealthVectorStore  # 主契约稳定字段：向量库摘要。
    llm: HealthLLM  # 主契约稳定字段：LLM 摘要。
    embedding: HealthEmbedding  # 主契约稳定字段：Embedding 摘要。
    reranker: HealthReranker  # 主契约稳定字段：Reranker 摘要。
    queue: HealthQueue  # 主契约稳定字段：队列摘要。
    metadata_store: HealthMetadataStore  # 主契约稳定字段：元数据存储摘要。
    ocr: HealthOCR  # 主契约稳定字段：OCR 摘要。
    tokenizer: HealthTokenizer  # 主契约稳定字段：tokenizer 预算摘要。
