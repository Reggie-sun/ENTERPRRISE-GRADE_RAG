from pydantic import AliasChoices, BaseModel, Field  # 导入 Pydantic 基类、字段约束和别名工具。

from .query_profile import QueryMode


class RetrievalRequest(BaseModel):  # 定义检索接口的请求结构。
    query: str = Field(min_length=1, max_length=2000)  # 用户输入的检索问题。
    top_k: int | None = Field(default=None, ge=1, le=200)  # 可选覆盖默认档位的返回数量；为空时按档位默认值展开，内部链路允许更大的候选上限。
    mode: QueryMode | None = Field(default=None)  # 可选查询档位；为空时检索默认走 fast。
    candidate_top_k: int | None = Field(default=None, ge=1, le=200)  # 可选内部候选召回量，给问答/SOP 的后置 rerank 与权限过滤留余量。
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("document_id", "doc_id"),  # 兼容历史客户端传 doc_id，统一归一到 document_id。
        serialization_alias="document_id",
    )  # 可选文档过滤条件，只检索指定文档。


class RetrievedChunk(BaseModel):  # 定义单条检索结果的结构。
    chunk_id: str  # chunk 唯一标识。
    document_id: str  # chunk 所属文档唯一标识。
    document_name: str  # chunk 所属文档名称。
    text: str  # chunk 文本内容。
    score: float  # chunk 匹配分数。
    source_path: str  # 原始文档路径。
    retrieval_strategy: str | None = None  # 当前结果的召回策略，例如 qdrant / hybrid / document_preview。
    vector_score: float | None = None  # 原始向量召回分数。
    lexical_score: float | None = None  # 关键词召回分数；纯向量召回时为空。
    fused_score: float | None = None  # 最终用于排序/返回的融合分数。
    ocr_used: bool = False  # 当前结果是否来自 OCR 参与的解析链路。
    parser_name: str | None = None  # 当前结果的解析器名称。
    page_no: int | None = None  # OCR 可可靠定位时返回页码。
    ocr_confidence: float | None = None  # OCR 置信度摘要，供前端和后续排序策略复用。
    quality_score: float | None = None  # 通用质量分，当前优先复用 OCR 置信度。


class RetrievalResponse(BaseModel):  # 定义检索接口的响应结构。
    query: str  # 原始查询文本。
    top_k: int  # 本次请求的 top_k 值。
    mode: str  # 当前检索模式，例如 placeholder 或 real。
    results: list[RetrievedChunk]  # 返回的检索结果列表。


class RerankComparisonResult(BaseModel):  # 定义单一路由下的 rerank 对比结果。
    label: str  # 当前展示名称，例如 configured / heuristic。
    provider: str  # 当前路由的 provider 标识。
    model: str | None = None  # 当前路由模型名；heuristic 可为空。
    strategy: str  # 实际生效策略，例如 provider / heuristic / failed。
    error_message: str | None = None  # provider 失败时保留错误，方便页面解释为什么已降级。
    results: list[RetrievedChunk]  # 当前路由下的 top_n 结果。


class RerankComparisonSummary(BaseModel):  # 定义两条 rerank 路由的差异摘要。
    overlap_count: int  # 两条结果里共同命中的 chunk 数。
    top1_same: bool  # 第一条结果是否相同。
    configured_only_chunk_ids: list[str]  # 仅当前默认路由命中的 chunk。
    heuristic_only_chunk_ids: list[str]  # 仅 heuristic 命中的 chunk。


class RerankPromotionRecommendation(BaseModel):  # 定义是否适合把 provider 切成默认策略的建议。
    decision: str  # 决策类型，例如 eligible / hold / provider_active / rollback_active / not_applicable。
    should_switch_default_strategy: bool  # 当前是否建议把 default_strategy 切成 provider。
    message: str  # 面向管理页/检索页展示的建议说明。


class RetrievalRerankRouteStatus(BaseModel):  # 定义当前默认 rerank 路由的实时运行状态。
    provider: str  # 当前配置的 provider。
    model: str  # 当前配置的模型。
    default_strategy: str  # 当前默认路由策略，决定健康时优先走 provider 还是 heuristic。
    failure_cooldown_seconds: float  # 最近失败后的 provider 锁定窗口。
    effective_provider: str  # 当前实际生效的 provider。
    effective_model: str  # 当前实际生效的模型或 heuristic。
    effective_strategy: str  # 当前实际生效策略，例如 provider / heuristic / failed。
    fallback_enabled: bool  # 当前是否允许 provider 失败时回退到 heuristic。
    lock_active: bool  # 当前 provider 是否因最近失败而处于锁定窗口。
    lock_source: str | None = None  # 锁定来自 health probe 还是真实请求。
    cooldown_remaining_seconds: float  # 当前锁定窗口剩余秒数。
    ready: bool  # 当前 provider 路由是否 ready。
    detail: str | None = None  # 当前路由状态说明。


class RetrievalRerankCompareResponse(BaseModel):  # 定义 rerank 对比接口的响应结构。
    query: str  # 原始查询文本。
    mode: str  # 实际检索模式，例如 qdrant / hybrid。
    candidate_count: int  # 进入 rerank 对比的候选数。
    rerank_top_n: int  # 本次实际参与 rerank 后返回的数量。
    route_status: RetrievalRerankRouteStatus  # 当前默认 rerank 路由的实时运行状态。
    configured: RerankComparisonResult  # 当前默认 rerank 路由的实际结果。
    provider_candidate: RerankComparisonResult | None = None  # 显式验证 provider 候选路由的结果；默认 heuristic 时仍可拿来做切换评估。
    heuristic: RerankComparisonResult  # 启发式 rerank 基线结果。
    summary: RerankComparisonSummary  # 当前默认路由与 heuristic 的差异摘要。
    provider_candidate_summary: RerankComparisonSummary | None = None  # provider 候选与 heuristic 的差异摘要。
    recommendation: RerankPromotionRecommendation  # 当前是否建议把默认策略切到 provider。
