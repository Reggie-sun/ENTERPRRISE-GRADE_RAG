from backend.app.core.config import Settings, get_postgres_metadata_dsn, get_reranker_base_url  # 导入配置对象和 DSN 解析函数，覆盖默认值与优先级行为。


def test_settings_defaults_match_local_dev_baseline() -> None:  # 验证关键默认配置不是容器域名，而是本机可直连配置。
    assert Settings.model_fields["qdrant_url"].default == "http://127.0.0.1:6333"  # 向量库默认应走本机端口。
    assert Settings.model_fields["ollama_base_url"].default == "http://127.0.0.1:11434"  # Ollama 默认应走本机端口。
    assert Settings.model_fields["embedding_provider"].default == "mock"  # embedding 默认应为 mock，便于零依赖启动。
    assert Settings.model_fields["asset_store_backend"].default == "filesystem"  # 上传原文件默认仍走本地文件系统，避免打断开发基线。
    assert Settings.model_fields["data_asset_store_binary_enabled"].default is True  # 默认保留二进制落库能力，避免影响现有流程。
    assert Settings.model_fields["data_asset_binary_max_bytes"].default == 1 * 1024 * 1024  # 默认仅允许 1MB 以内二进制入库。
    assert Settings.model_fields["event_log_dir"].default.name == "event_logs"  # 事件日志目录默认应固定，便于 v0.6 查询与追溯复用。
    assert Settings.model_fields["system_config_path"].default.name == "system_config.json"  # 系统配置文件默认应固定，便于管理后台和查询档位复用。
    assert Settings.model_fields["identity_bootstrap_path"].default.name == "identity_bootstrap.json"  # 身份目录 bootstrap 默认应有固定文件名，便于 v0.3 复用。
    assert Settings.model_fields["auth_token_issuer"].default == "enterprise-rag-api"  # auth token issuer 默认应固定，便于 v0.3 登录模块复用。
    assert Settings.model_fields["auth_token_expire_minutes"].default == 60  # access token 默认有效期应固定为 60 分钟。
    assert Settings.model_fields["ingest_inflight_stale_seconds"].default == 30 * 60  # 过期 in-flight job 的默认阈值应固定为 30 分钟。
    assert Settings.model_fields["query_fast_top_k_default"].default == 5  # fast 档默认 top_k 应稳定，便于门户问答低延迟基线。
    assert Settings.model_fields["query_accurate_top_k_default"].default == 8  # accurate 档默认 top_k 应稳定，便于 SOP 生成复用。
    assert Settings.model_fields["query_fast_timeout_budget_seconds"].default == 12.0  # fast 档超时预算默认应固定。
    assert Settings.model_fields["query_accurate_timeout_budget_seconds"].default == 24.0  # accurate 档超时预算默认应固定。
    assert Settings.model_fields["retrieval_strategy_default"].default == "hybrid"  # 当前默认检索策略应启用 hybrid，保留纯向量 fallback。
    assert Settings.model_fields["retrieval_hybrid_rrf_k"].default == 60  # hybrid 融合常量默认应固定，便于结果排序稳定。
    assert Settings.model_fields["reranker_provider"].default == "heuristic"  # rerank 默认仍应保留启发式 provider，便于零依赖启动。
    assert Settings.model_fields["reranker_timeout_seconds"].default == 12.0  # rerank 超时预算默认应与 fast 档保持同量级。
    assert Settings.model_fields["ocr_provider"].default == "disabled"  # OCR 默认应关闭，避免本地开发环境强依赖大包。
    assert Settings.model_fields["ocr_pdf_native_text_min_chars"].default == 80  # PDF OCR fallback 阈值默认应固定。
    assert Settings(_env_file=None).ocr_artifact_dir.name == "ocr_artifacts"  # OCR 中间产物目录默认应独立于 parsed/chunks。
    assert Settings(_env_file=None).request_trace_dir.name == "request_traces"  # 请求级 trace 目录默认应派生到 data/request_traces。
    assert Settings(_env_file=None).request_snapshot_dir.name == "request_snapshots"  # 请求快照目录默认应派生到 data/request_snapshots。


def test_postgres_metadata_dsn_prefers_rag_prefixed_setting(monkeypatch) -> None:  # 显式配置 RAG_POSTGRES_METADATA_DSN 时应优先使用它。
    monkeypatch.setenv("RAG_POSTGRES_METADATA_DSN", "postgresql://rag-prefixed")
    monkeypatch.setenv("DATABASE_URL", "postgresql://database-url")
    settings = Settings(_env_file=None)
    assert get_postgres_metadata_dsn(settings) == "postgresql://rag-prefixed"


def test_postgres_metadata_dsn_falls_back_to_database_url(monkeypatch) -> None:  # 未配置 RAG_POSTGRES_METADATA_DSN 时应回退到 DATABASE_URL。
    monkeypatch.delenv("RAG_POSTGRES_METADATA_DSN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://database-url")
    settings = Settings(_env_file=None)
    assert get_postgres_metadata_dsn(settings) == "postgresql://database-url"


def test_reranker_base_url_prefers_dedicated_setting() -> None:
    settings = Settings(
        _env_file=None,
        reranker_base_url="http://reranker.test/v1",
        embedding_base_url="http://embedding.test/v1",
        llm_base_url="http://llm.test/v1",
    )
    assert get_reranker_base_url(settings) == "http://reranker.test/v1"


def test_reranker_base_url_falls_back_to_embedding_then_llm() -> None:
    embedding_first = Settings(
        _env_file=None,
        reranker_base_url=None,
        embedding_base_url="http://embedding.test/v1",
        llm_base_url="http://llm.test/v1",
    )
    llm_fallback = Settings(
        _env_file=None,
        reranker_base_url=None,
        embedding_base_url=None,
        llm_base_url="http://llm.test/v1",
    )

    assert get_reranker_base_url(embedding_first) == "http://embedding.test/v1"
    assert get_reranker_base_url(llm_fallback) == "http://llm.test/v1"
