"""检索配置：Chunking、Hybrid 策略、Query 分档、并发控制、词法召回。

本模块管理 RAG 检索链路的全部可调参数，涵盖文本分块、混合检索权重、
查询分档（Fast/Accurate）、并发限流等核心参数。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class _RetrievalSettings(BaseSettings):
    """Retrieval settings mixin — 被 Settings 通过多继承组合。

    包含六大模块：Chunking 文本分块、Retrieval Strategy 检索策略、
    Lexical 词法检索、Top-K/Rerank 召回排序、Fast/Accurate 查询分档、Concurrency 并发控制。
    """

    # ── Chunking 文本分块配置 ──────────────────────────────────────────────
    chunk_size_chars: int = 800            # 每个文本块的目标字符数
    chunk_overlap_chars: int = 120         # 相邻块重叠字符数（保证上下文连续性）
    chunk_min_chars: int = 200             # 最小有效块字符数

    # ── Retrieval Strategy 检索策略配置 ──────────────────────────────────────
    retrieval_strategy_default: str = "hybrid"  # 默认检索策略: hybrid / vector / lexical
    retrieval_hybrid_rrf_k: int = Field(default=60, ge=1, le=500)  # RRF（倒数秩融合）常数 k
    retrieval_dynamic_weighting_enabled: bool = False               # 是否启用动态权重调整
    # 各查询类型对应的向量/词法权重
    retrieval_hybrid_fixed_vector_weight: float = Field(default=1.0, ge=0.0, le=1.0)      # 固定权重模式：向量权重
    retrieval_hybrid_fixed_lexical_weight: float = Field(default=1.0, ge=0.0, le=1.0)     # 固定权重模式：词法权重
    retrieval_hybrid_exact_vector_weight: float = Field(default=0.3, ge=0.0, le=1.0)      # 精确查询：向量权重（词法为主）
    retrieval_hybrid_exact_lexical_weight: float = Field(default=0.7, ge=0.0, le=1.0)     # 精确查询：词法权重
    retrieval_hybrid_semantic_vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)   # 语义查询：向量权重（向量为主）
    retrieval_hybrid_semantic_lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)  # 语义查询：词法权重
    retrieval_hybrid_mixed_vector_weight: float = Field(default=0.5, ge=0.0, le=1.0)      # 混合查询：向量权重
    retrieval_hybrid_mixed_lexical_weight: float = Field(default=0.5, ge=0.0, le=1.0)     # 混合查询：词法权重
    # 查询分类器的信号阈值
    retrieval_query_classifier_exact_signal_threshold: int = Field(default=2, ge=1, le=10)     # 判定为精确查询的信号阈值
    retrieval_query_classifier_semantic_signal_threshold: int = Field(default=2, ge=1, le=10)  # 判定为语义查询的信号阈值

    # ── Lexical 词法检索配置 ─────────────────────────────────────────────────
    retrieval_lexical_chinese_tokenizer: str = "jieba_search"               # 中文分词器类型
    retrieval_lexical_supplemental_bigram_weight: float = Field(default=0.35, ge=0.0, le=2.0)  # 补充二元组权重

    # ── Top-K / Rerank 召回与排序配置 ────────────────────────────────────────
    top_k_default: int = 5                 # 默认召回文档数
    rerank_top_n: int = 3                  # 重排序后返回的文档数

    # ── Fast 快速档配置（优先延迟） ──────────────────────────────────────────
    query_fast_top_k_default: int = Field(default=5, ge=1, le=20)           # 向量召回数
    query_fast_candidate_multiplier: int = Field(default=2, ge=1, le=20)    # 候选集倍数
    query_fast_lexical_top_k_default: int = Field(default=10, ge=1, le=200) # 词法召回数
    query_fast_rerank_top_n: int = Field(default=3, ge=1, le=20)            # 重排序返回数
    query_fast_timeout_budget_seconds: float = Field(default=12.0, gt=0)    # 超时预算（秒）

    # ── Accurate 精确档配置（优先质量） ───────────────────────────────────────
    query_accurate_top_k_default: int = Field(default=8, ge=1, le=20)           # 向量召回数
    query_accurate_candidate_multiplier: int = Field(default=4, ge=1, le=20)    # 候选集倍数
    query_accurate_lexical_top_k_default: int = Field(default=32, ge=1, le=200) # 词法召回数
    query_accurate_rerank_top_n: int = Field(default=5, ge=1, le=20)            # 重排序返回数
    query_accurate_timeout_budget_seconds: float = Field(default=24.0, gt=0)    # 超时预算（秒）

    # ── Concurrency 并发控制配置 ──────────────────────────────────────────────
    concurrency_fast_max_inflight: int = Field(default=24, ge=1, le=200)              # 快速档最大并发数
    concurrency_accurate_max_inflight: int = Field(default=6, ge=1, le=100)           # 精确档最大并发数
    concurrency_sop_generation_max_inflight: int = Field(default=3, ge=1, le=50)      # SOP 生成最大并发数
    concurrency_per_user_online_max_inflight: int = Field(default=3, ge=1, le=20)     # 单用户最大并发数
    concurrency_acquire_timeout_ms: int = Field(default=800, ge=0, le=30_000)         # 并发槽获取超时（毫秒）
    concurrency_busy_retry_after_seconds: int = Field(default=5, ge=1, le=300)        # 服务繁忙时重试等待时间
