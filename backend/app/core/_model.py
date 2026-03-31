"""模型与推理配置：LLM、Embedding、Tokenizer、Chat Memory、Query Rewrite、Reranker。

本模块集中管理所有与 AI 模型调用相关的配置参数。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class _ModelSettings(BaseSettings):
    """Model / inference settings mixin — 被 Settings 通过多继承组合。

    包含六大模块配置：LLM 大语言模型、Tokenizer 分词器、Chat Memory 对话记忆、
    Query Rewrite 查询改写、Embedding 向量嵌入、Reranker 重排序。
    """

    # ── LLM 大语言模型配置 ──────────────────────────────────────────────────
    llm_provider: str = "mock"                     # 提供商: mock / openai / ollama 等
    llm_base_url: str | None = None                # 自定义 LLM API 地址（优先于 ollama）
    llm_api_key: str | None = None                 # API 密钥
    llm_model: str | None = None                   # 模型名称（优先于 ollama_model）
    ollama_base_url: str = "http://127.0.0.1:11434"  # Ollama 本地服务地址
    ollama_model: str = "qwen2.5:7b"               # Ollama 默认模型
    llm_timeout_seconds: float = 180.0             # 请求超时时间（秒）
    llm_temperature: float = 0.1                   # 生成温度，越低越确定
    llm_max_prompt_tokens: int = Field(default=2200, ge=256, le=32000)          # Prompt 最大 Token 数
    llm_reserved_completion_tokens: int = Field(default=512, ge=64, le=8192)    # 预留给回复的 Token 数

    # ── Tokenizer 分词器配置 ────────────────────────────────────────────────
    tokenizer_provider: str = "heuristic"          # 分词方式: heuristic(启发式) / tiktoken / custom
    tokenizer_model: str | None = None             # 自定义分词模型路径
    tokenizer_trust_remote_code: bool = False      # 是否信任远程代码（用于 HuggingFace 分词器）

    # ── Chat Memory 对话记忆配置 ────────────────────────────────────────────
    chat_memory_enabled: bool = True               # 是否启用多轮对话记忆
    chat_memory_max_turns: int = Field(default=6, ge=1, le=12)                  # 保留的最大对话轮数
    chat_memory_max_prompt_tokens: int = Field(default=360, ge=64, le=4096)     # 记忆上下文最大 Token 数
    chat_memory_question_max_chars: int = Field(default=200, ge=20, le=4000)    # 单条问题最大字符数
    chat_memory_answer_max_chars: int = Field(default=400, ge=20, le=8000)      # 单条回答最大字符数

    # ── Query Rewrite 查询改写配置 ──────────────────────────────────────────
    query_rewrite_enabled: bool = True             # 是否启用查询改写
    query_rewrite_short_question_max_chars: int = Field(default=18, ge=4, le=200)  # 短问题判定阈值（字符数）

    # ── Embedding 向量嵌入配置 ──────────────────────────────────────────────
    embedding_provider: str = "mock"               # 提供商: mock / openai / ollama 等
    embedding_base_url: str | None = None          # 自定义 Embedding API 地址
    embedding_api_key: str | None = None           # API 密钥
    embedding_model: str = "BAAI/bge-m3"           # 默认嵌入模型（BGE-M3 多语言模型）
    embedding_timeout_seconds: float = 120.0       # 请求超时时间（秒）
    embedding_batch_size: int = 16                 # 批量嵌入的单批大小
    embedding_mock_vector_size: int = 32           # Mock 模式下的向量维度

    # ── Reranker 重排序配置 ─────────────────────────────────────────────────
    reranker_provider: str = "heuristic"           # 提供商: heuristic(启发式) / api 等
    reranker_base_url: str | None = None           # 自定义 Reranker API 地址
    reranker_api_key: str | None = None            # API 密钥
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # 默认重排序模型
    reranker_default_strategy: str = "heuristic"   # 默认重排序策略
    reranker_timeout_seconds: float = 12.0         # 请求超时时间（秒）
    reranker_failure_cooldown_seconds: float = Field(default=15.0, gt=0, le=300.0)  # 失败后冷却时间
