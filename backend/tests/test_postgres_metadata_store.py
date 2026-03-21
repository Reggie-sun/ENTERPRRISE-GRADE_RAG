from backend.app.db.postgres_metadata_store import PostgresMetadataStore


def test_normalize_psycopg_dsn_drops_public_schema_query() -> None:
    dsn = "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
    normalized = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    assert normalized == "postgresql://root:123456@192.168.10.200:5432/welllihaidb"


def test_normalize_psycopg_dsn_converts_non_public_schema_to_search_path() -> None:
    dsn = "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=rag&sslmode=disable"
    normalized = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    assert "schema=rag" not in normalized
    assert "sslmode=disable" in normalized
    assert "options=-c+search_path%3Drag" in normalized


def test_stable_uuid_is_deterministic() -> None:
    left = PostgresMetadataStore._stable_uuid("rag-source-document", "doc_001")
    right = PostgresMetadataStore._stable_uuid("rag-source-document", "doc_001")
    other = PostgresMetadataStore._stable_uuid("rag-source-document", "doc_002")
    assert left == right
    assert left != other
