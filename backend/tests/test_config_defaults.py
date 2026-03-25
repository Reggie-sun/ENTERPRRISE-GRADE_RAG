from backend.app.core.config import Settings, get_postgres_metadata_dsn  # 导入配置对象和 DSN 解析函数，覆盖默认值与优先级行为。


def test_settings_defaults_match_local_dev_baseline() -> None:  # 验证关键默认配置不是容器域名，而是本机可直连配置。
    assert Settings.model_fields["qdrant_url"].default == "http://127.0.0.1:6333"  # 向量库默认应走本机端口。
    assert Settings.model_fields["ollama_base_url"].default == "http://127.0.0.1:11434"  # Ollama 默认应走本机端口。
    assert Settings.model_fields["embedding_provider"].default == "mock"  # embedding 默认应为 mock，便于零依赖启动。
    assert Settings.model_fields["data_asset_store_binary_enabled"].default is True  # 默认保留二进制落库能力，避免影响现有流程。
    assert Settings.model_fields["data_asset_binary_max_bytes"].default == 1 * 1024 * 1024  # 默认仅允许 1MB 以内二进制入库。
    assert Settings.model_fields["identity_bootstrap_path"].default.name == "identity_bootstrap.json"  # 身份目录 bootstrap 默认应有固定文件名，便于 v0.3 复用。


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
