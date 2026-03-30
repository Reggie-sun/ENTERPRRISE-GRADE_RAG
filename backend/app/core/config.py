import os  # 导入 os，用于兼容读取标准 DATABASE_URL 环境变量。
from functools import lru_cache  # 导入缓存装饰器，避免重复创建 Settings 对象。
from pathlib import Path  # 导入 Path，方便跨平台处理目录路径。

from pydantic import Field, field_validator, model_validator  # 导入字段定义和字段校验工具。
from pydantic_settings import BaseSettings, SettingsConfigDict  # 导入基于环境变量的配置基类。

BACKEND_DIR = Path(__file__).resolve().parents[2]  # 计算 backend 目录的绝对路径。
PROJECT_ROOT = BACKEND_DIR.parent  # 再往上一层拿到项目根目录。


class Settings(BaseSettings):  # 定义项目统一配置对象，所有配置都从这里读取。
    app_name: str = "Enterprise-grade RAG API"  # 应用名称，用于文档和接口返回。
    app_env: str = "development"  # 当前运行环境，例如 development / test / production。
    debug: bool = True  # 是否开启调试模式。
    api_v1_prefix: str = "/api/v1"  # API v1 的统一前缀。
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])  # 允许跨域的来源列表。

    qdrant_url: str = "http://127.0.0.1:6333"  # Qdrant 服务地址，默认走本机端口以匹配本地开发基线。
    qdrant_collection: str = "enterprise_rag_v1"  # 默认使用的 Qdrant collection 名称。
    postgres_metadata_enabled: bool = False  # 是否启用 PostgreSQL 作为 document/job 元数据存储真源。
    postgres_metadata_dsn: str | None = None  # PostgreSQL 连接串，未配置时可回退读取 DATABASE_URL。
    database_url: str | None = Field(default=None, alias="DATABASE_URL")  # 兼容读取 Prisma 常用的 DATABASE_URL（无 RAG_ 前缀）。

    celery_broker_url: str = "redis://localhost:6379/0"  # Celery broker 地址，开发环境默认走本机 Redis。
    celery_result_backend: str = "redis://localhost:6379/1"  # Celery 结果后端地址，默认单独占一个 Redis DB。
    celery_ingest_queue: str = "ingest"  # 文档入库任务默认进入 ingest 队列。
    celery_task_always_eager: bool = False  # 测试环境可打开 eager，让任务在当前进程内直接执行。
    celery_task_eager_propagates: bool = True  # eager 模式下把任务异常直接抛出，便于测试排查。
    ingest_failure_retry_limit: int = Field(default=3, ge=1)  # 单个 ingest job 在进入 dead_letter 前允许的最大失败次数。
    ingest_retry_delay_seconds: int = Field(default=2, ge=0)  # Celery 自动重试的退避秒数。
    ingest_inflight_stale_seconds: int = Field(default=30 * 60, ge=1)  # queued/processing 任务超过该时长未刷新时视为卡死，允许重复上传补发新 job。

    llm_provider: str = "mock"  # 当前 LLM provider，支持 mock / ollama / openai / deepseek。
    llm_base_url: str | None = None  # OpenAI 兼容或通用 LLM 服务地址，未配置时回退到 ollama_base_url。
    llm_api_key: str | None = None  # OpenAI 兼容 LLM 的鉴权密钥，本地 vLLM 可留空。
    llm_model: str | None = None  # 通用 LLM 模型名称，未配置时回退到 ollama_model。
    ollama_base_url: str = "http://127.0.0.1:11434"  # Ollama 服务地址，默认走本机端口，避免容器域名缺失导致连不上。
    ollama_model: str = "qwen2.5:7b"  # 兼容旧配置的默认生成模型名称。
    llm_timeout_seconds: float = 180.0  # LLM 生成请求超时时间。
    llm_temperature: float = 0.1  # LLM 默认采样温度。
    llm_max_prompt_tokens: int = Field(default=2200, ge=256, le=32000)  # 发送到 LLM 的 prompt 软预算，避免上下文塞满后只剩极少 completion token。
    llm_reserved_completion_tokens: int = Field(default=512, ge=64, le=8192)  # 给回答保留的 completion token 数，避免准确档在大上下文下被截成半句话。
    tokenizer_provider: str = "heuristic"  # tokenizer 预算服务 provider，当前支持 heuristic / transformers_auto。
    tokenizer_model: str | None = None  # tokenizer 模型名；未配置时回退到 llm_model / ollama_model。
    tokenizer_trust_remote_code: bool = False  # 是否允许 AutoTokenizer 加载 remote code；默认关闭，避免不必要风险。
    chat_memory_enabled: bool = True  # 是否启用轻记忆；当前仅在 chat 主链路保留最近几轮会话上下文。
    chat_memory_max_turns: int = Field(default=6, ge=1, le=12)  # 轻记忆最多保留最近几轮问答。
    chat_memory_max_prompt_tokens: int = Field(default=360, ge=64, le=4096)  # 注入到 prompt 里的轻记忆软预算，避免把检索证据空间挤掉。
    chat_memory_question_max_chars: int = Field(default=200, ge=20, le=4000)  # 进入轻记忆时每轮 question 的最大保留字符数。
    chat_memory_answer_max_chars: int = Field(default=400, ge=20, le=8000)  # 进入轻记忆时每轮 answer 的最大保留字符数。
    query_rewrite_enabled: bool = True  # 是否启用最小追问改写；当前只做 chat 场景下的短追问/指代型追问收口。
    query_rewrite_short_question_max_chars: int = Field(default=18, ge=4, le=200)  # 仅当问题足够短时才尝试按最近一轮上下文改写，避免重写正常独立问题。
    department_query_isolation_enabled: bool = True  # 是否启用按部门的读链路隔离；关闭后仅放开检索/问答/文档阅读，不放开写入和管理边界。
    embedding_provider: str = "mock"  # 当前 embedding 提供方类型，默认 mock 便于零依赖启动。
    embedding_base_url: str | None = None  # 独立 embedding 服务地址，可为空。
    embedding_api_key: str | None = None  # OpenAI 兼容 embedding 服务的鉴权密钥。
    embedding_model: str = "BAAI/bge-m3"  # 默认 embedding 模型名称。
    reranker_provider: str = "heuristic"  # 当前 reranker provider，V1 默认启发式重排。
    reranker_base_url: str | None = None  # 独立 reranker 服务地址，可为空；未配置时按 embedding/llm 地址回退。
    reranker_api_key: str | None = None  # OpenAI-compatible reranker 服务的鉴权密钥。
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # 默认 reranker 模型名称。
    reranker_default_strategy: str = "heuristic"  # 当前默认 rerank 路由策略；provider 就绪时是默认走 provider 还是继续锁在 heuristic。
    reranker_timeout_seconds: float = 12.0  # reranker 请求超时时间，默认收敛在 fast 档预算内。
    reranker_failure_cooldown_seconds: float = Field(default=15.0, gt=0, le=300.0)  # 最近一次 reranker 故障后的冷却窗口；窗口内直接锁定当前 provider，避免持续打坏上游。
    embedding_timeout_seconds: float = 120.0  # embedding 请求超时时间。
    embedding_batch_size: int = 16  # embedding 批量请求大小。
    embedding_mock_vector_size: int = 32  # mock embedding 模式下生成的向量维度。
    ocr_provider: str = "disabled"  # OCR provider，当前支持 disabled / mock / paddleocr。
    ocr_language: str = "ch"  # OCR 默认语言，优先兼容中文资料。
    ocr_pdf_native_text_min_chars: int = Field(default=80, ge=0, le=10_000)  # PDF 原生抽取文本低于该阈值时尝试 OCR fallback。
    ocr_paddle_use_angle_cls: bool = False  # 兼容旧版 angle cls 开关；PaddleOCR 3.x 默认关闭，避免和 textline_orientation 冲突。
    ocr_paddle_use_doc_orientation_classify: bool = False  # 文档方向分类会额外拉起大模型，默认关闭以收敛首轮 OCR 依赖。
    ocr_paddle_use_doc_unwarping: bool = False  # 文档去畸变默认关闭，先让扫描件 OCR 主链路跑通。
    ocr_paddle_use_textline_orientation: bool = False  # 文本行方向分类默认关闭，避免额外模型下载拖慢首轮 OCR。
    ocr_paddle_ocr_version: str = "PP-OCRv5"  # 统一固定到 PP-OCRv5 产线，便于 det/rec 模型名保持一致。
    ocr_paddle_text_detection_model_name: str = "PP-OCRv5_mobile_det"  # 默认使用 mobile det，减小 CPU 首轮模型体积。
    ocr_paddle_text_recognition_model_name: str = "PP-OCRv5_mobile_rec"  # 默认使用 mobile rec，避免 server rec 首轮下载过重。
    ocr_low_quality_filter_enabled: bool = True  # 是否在在线检索阶段过滤明显低质量且可替代的 OCR 候选。
    ocr_low_quality_min_score: float = Field(default=0.55, ge=0.0, le=1.0)  # OCR 质量分低于该阈值时优先视为低质量候选。

    chunk_size_chars: int = 800  # 每个 chunk 的目标字符长度。
    chunk_overlap_chars: int = 120  # 相邻 chunk 的重叠字符长度。
    chunk_min_chars: int = 200  # chunk 切分时允许的最小字符阈值。
    retrieval_strategy_default: str = "hybrid"  # 当前在线检索默认策略，支持 qdrant / hybrid。
    retrieval_hybrid_rrf_k: int = Field(default=60, ge=1, le=500)  # hybrid 模式下 RRF 融合常量，数值越大越偏向稳态融合。
    retrieval_dynamic_weighting_enabled: bool = False  # 是否开启基于 query 类型的 hybrid 动态权重；默认关闭以保持现有排序基线。
    retrieval_hybrid_fixed_vector_weight: float = Field(default=1.0, ge=0.0, le=1.0)  # dynamic weighting 关闭时的固定向量分支权重。
    retrieval_hybrid_fixed_lexical_weight: float = Field(default=1.0, ge=0.0, le=1.0)  # dynamic weighting 关闭时的固定词法分支权重。
    retrieval_hybrid_exact_vector_weight: float = Field(default=0.3, ge=0.0, le=1.0)  # 精确检索型 query 的向量分支权重。
    retrieval_hybrid_exact_lexical_weight: float = Field(default=0.7, ge=0.0, le=1.0)  # 精确检索型 query 的词法分支权重。
    retrieval_hybrid_semantic_vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)  # 自然语言语义型 query 的向量分支权重。
    retrieval_hybrid_semantic_lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)  # 自然语言语义型 query 的词法分支权重。
    retrieval_hybrid_mixed_vector_weight: float = Field(default=0.5, ge=0.0, le=1.0)  # 混合型 query 的向量分支权重。
    retrieval_hybrid_mixed_lexical_weight: float = Field(default=0.5, ge=0.0, le=1.0)  # 混合型 query 的词法分支权重。
    retrieval_query_classifier_exact_signal_threshold: int = Field(default=2, ge=1, le=10)  # 规则分类里命中精确检索型所需的最小信号数。
    retrieval_query_classifier_semantic_signal_threshold: int = Field(default=2, ge=1, le=10)  # 规则分类里命中语义检索型所需的最小信号数。
    retrieval_lexical_chinese_tokenizer: str = "jieba_search"  # 中文词法召回默认优先走 jieba 搜索分词，兼顾召回与部署成本。
    retrieval_lexical_supplemental_bigram_weight: float = Field(default=0.35, ge=0.0, le=2.0)  # 主分词之外补充 2-gram 的融合权重。

    top_k_default: int = 5  # 默认检索返回数量。
    rerank_top_n: int = 3  # 默认 rerank 后保留的数量。
    query_fast_top_k_default: int = Field(default=5, ge=1, le=20)  # fast 档默认返回数量，优先服务问答低延迟场景。
    query_fast_candidate_multiplier: int = Field(default=2, ge=1, le=20)  # fast 档检索时的候选放大量，给权限过滤和 rerank 留余量。
    query_fast_lexical_top_k_default: int = Field(default=10, ge=1, le=200)  # fast 档关键词召回默认上限，默认与当前 candidate_top_k 基线保持一致。
    query_fast_rerank_top_n: int = Field(default=3, ge=1, le=20)  # fast 档 rerank 后保留数量。
    query_fast_timeout_budget_seconds: float = Field(default=12.0, gt=0)  # fast 档生成超时预算，后续可直接映射到系统配置页。
    query_accurate_top_k_default: int = Field(default=8, ge=1, le=20)  # accurate 档默认返回数量，优先服务高质量问答与 SOP 生成。
    query_accurate_candidate_multiplier: int = Field(default=4, ge=1, le=20)  # accurate 档候选放大量，给更深 rerank 留足证据。
    query_accurate_lexical_top_k_default: int = Field(default=32, ge=1, le=200)  # accurate 档关键词召回默认上限，默认与当前 candidate_top_k 基线保持一致。
    query_accurate_rerank_top_n: int = Field(default=5, ge=1, le=20)  # accurate 档 rerank 后保留数量。
    query_accurate_timeout_budget_seconds: float = Field(default=24.0, gt=0)  # accurate 档生成超时预算。
    concurrency_fast_max_inflight: int = Field(default=24, ge=1, le=200)  # fast 在线问答通道允许的最大并发占用。
    concurrency_accurate_max_inflight: int = Field(default=6, ge=1, le=100)  # accurate 在线问答通道允许的最大并发占用。
    concurrency_sop_generation_max_inflight: int = Field(default=3, ge=1, le=50)  # SOP 生成通道允许的最大并发占用。
    concurrency_per_user_online_max_inflight: int = Field(default=3, ge=1, le=20)  # 单用户允许同时占用的在线请求上限，防止单人把 fast/accurate/SOP 槽位吃满。
    concurrency_acquire_timeout_ms: int = Field(default=800, ge=0, le=30_000)  # 在线请求等待可用并发槽位的最长时间。
    concurrency_busy_retry_after_seconds: int = Field(default=5, ge=1, le=300)  # 忙时提示给前端/调用方的建议重试秒数。
    upload_max_file_size_bytes: int = 100 * 1024 * 1024  # 上传文件大小上限，默认 100MB。
    asset_store_backend: str = "filesystem"  # 上传原文件存储后端，默认仍走本地文件系统，可切到 postgres。
    data_asset_store_binary_enabled: bool = True  # data 资产是否写入 binaryContent（二进制落库开关）。
    data_asset_binary_max_bytes: int = 1 * 1024 * 1024  # 允许写入 binaryContent 的最大文件大小（默认 1MB）。

    data_dir: Path = Field(default=PROJECT_ROOT / "data")  # 项目数据根目录。
    upload_dir: Path = Field(default=PROJECT_ROOT / "data" / "uploads")  # 原始上传文件目录。
    parsed_dir: Path = Field(default=PROJECT_ROOT / "data" / "parsed")  # 解析后纯文本目录。
    chunk_dir: Path = Field(default=PROJECT_ROOT / "data" / "chunks")  # chunk 结果目录。
    ocr_artifact_dir: Path = Field(default=PROJECT_ROOT / "data" / "ocr_artifacts")  # OCR 中间产物目录，和最终 parsed text 分开管理。
    document_dir: Path = Field(default=PROJECT_ROOT / "data" / "documents")  # document 元数据目录。
    job_dir: Path = Field(default=PROJECT_ROOT / "data" / "jobs")  # ingest job 元数据目录。
    event_log_dir: Path = Field(default=PROJECT_ROOT / "data" / "event_logs")  # 事件日志目录，v0.6 起先落最小可追溯记录。
    request_trace_dir: Path | None = Field(default=None)  # 请求级 trace 目录，默认跟随 data_dir 派生，避免测试环境误写到仓库根 data。
    request_snapshot_dir: Path | None = Field(default=None)  # 请求快照目录，给 v0.6 的最小 replay 能力落独立真源，不和日志/trace 混写。
    rerank_canary_dir: Path | None = Field(default=None)  # rerank canary 样本目录，记录 compare 产生的最小诊断真源。
    chat_memory_dir: Path | None = Field(default=None)  # 轻记忆目录，先走文件真源，后续再迁数据库。
    system_config_path: Path = Field(default=PROJECT_ROOT / "data" / "system_config.json")  # 系统配置文件路径，v0.6 起先落最小查询配置真源。
    sop_asset_dir: Path = Field(default=PROJECT_ROOT / "data" / "sop_assets")  # SOP 本地预览/下载资源目录，独立于文档解析产物目录。
    sop_record_dir: Path = Field(default=PROJECT_ROOT / "data" / "sops")  # 已保存 SOP 当前版本目录，和 bootstrap 主数据做叠加。
    sop_version_dir: Path = Field(default=PROJECT_ROOT / "data" / "sop_versions")  # SOP 历史版本目录，供 v0.5 版本查询使用。
    identity_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "identity_bootstrap.json")  # 身份目录 bootstrap 文件路径，供 v0.3 登录/权限模块复用。
    sop_bootstrap_path: Path = Field(default=BACKEND_DIR / "app" / "bootstrap" / "sop_bootstrap.json")  # SOP 主数据 bootstrap 文件路径，供 v0.4 列表/详情接口复用。
    auth_token_secret: str = "local-dev-enterprise-rag-auth-secret"  # 本地开发用 token 签名密钥，生产环境必须通过环境变量覆盖。
    auth_token_issuer: str = "enterprise-rag-api"  # 最小 token 发行者标识，便于后续切换到标准 JWT 时保持语义稳定。
    auth_token_expire_minutes: int = Field(default=60, ge=1)  # access token 默认有效期（分钟）。

    model_config = SettingsConfigDict(  # 定义 Pydantic Settings 的加载规则。
        env_file=str(PROJECT_ROOT / ".env"),  # 默认从项目根目录的 .env 读取环境变量。
        env_file_encoding="utf-8",  # 指定 .env 文件编码。
        case_sensitive=False,  # 环境变量名大小写不敏感。
        extra="ignore",  # 忽略没有定义在 Settings 里的多余环境变量。
        env_prefix="RAG_",  # 所有项目环境变量统一使用 RAG_ 前缀。
    )

    @field_validator("cors_origins", mode="before")  # 在字段赋值前先执行这个校验函数。
    @classmethod  # 把校验函数定义成类方法。
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:  # 兼容字符串和列表两种输入格式。
        if isinstance(value, str):  # 如果环境变量传进来的是字符串。
            return [item.strip() for item in value.split(",") if item.strip()]  # 按逗号拆分并清理空白项。
        return value  # 如果本来就是列表，则直接原样返回。

    @model_validator(mode="after")
    def derive_runtime_paths(self) -> "Settings":  # 对依赖 data_dir 的派生路径做统一收口，避免测试环境把新目录写到仓库根目录。
        if self.request_trace_dir is None:
            self.request_trace_dir = self.data_dir / "request_traces"
        if self.request_snapshot_dir is None:
            self.request_snapshot_dir = self.data_dir / "request_snapshots"
        if self.rerank_canary_dir is None:
            self.rerank_canary_dir = self.data_dir / "rerank_canary"
        if self.chat_memory_dir is None:
            self.chat_memory_dir = self.data_dir / "chat_memory"
        return self


@lru_cache  # 缓存 Settings 实例，避免每次调用都重复读取环境变量。
def get_settings() -> Settings:  # 提供全局统一的配置获取入口。
    return Settings()  # 创建并返回 Settings 对象。


def ensure_data_directories(settings: Settings) -> None:  # 确保项目需要的数据目录都已经存在。
    for path in (  # 依次遍历所有关键目录。
        settings.data_dir,
        settings.upload_dir,
        settings.parsed_dir,
        settings.chunk_dir,
        settings.ocr_artifact_dir,
        settings.document_dir,
        settings.job_dir,
        settings.event_log_dir,
        settings.request_trace_dir,
        settings.request_snapshot_dir,
        settings.rerank_canary_dir,
        settings.chat_memory_dir,
        settings.sop_asset_dir,
        settings.sop_record_dir,
        settings.sop_version_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)  # 不存在就递归创建，存在则跳过。


def get_llm_base_url(settings: Settings) -> str:  # 统一解析当前生效的 LLM 服务地址。
    return (settings.llm_base_url or settings.ollama_base_url).rstrip("/")  # 优先走通用地址，兼容旧配置再回退到 Ollama。


def get_llm_model(settings: Settings) -> str:  # 统一解析当前生效的 LLM 模型名称。
    return (settings.llm_model or settings.ollama_model).strip()  # 优先走通用模型名，兼容旧配置再回退到 Ollama。


def get_reranker_base_url(settings: Settings) -> str:  # 统一解析当前生效的 reranker 服务地址。
    for value in (
        settings.reranker_base_url,
        settings.embedding_base_url,
        settings.llm_base_url,
        settings.ollama_base_url,
    ):
        normalized = (value or "").strip()
        if normalized:
            return normalized.rstrip("/")
    raise RuntimeError(
        "Reranker base URL is not configured. Set RAG_RERANKER_BASE_URL or reuse embedding/llm base URL."
    )


def get_postgres_metadata_dsn(settings: Settings) -> str | None:  # 统一解析元数据 PostgreSQL 连接串。
    configured_dsn = (settings.postgres_metadata_dsn or "").strip()  # 优先读取 RAG_POSTGRES_METADATA_DSN 配置。
    if configured_dsn:  # 如果显式配置了 DSN，直接使用。
        return configured_dsn
    aliased_dsn = (settings.database_url or "").strip()  # 再尝试读取 Settings 中 alias 到 DATABASE_URL 的值。
    if aliased_dsn:  # 如果通过 .env 或环境变量加载到了 DATABASE_URL，就直接使用。
        return aliased_dsn
    fallback_dsn = os.getenv("DATABASE_URL", "").strip()  # 回退兼容 Prisma 常用的 DATABASE_URL。
    return fallback_dsn or None  # 为空时返回 None，交由调用方决定是否启用。
