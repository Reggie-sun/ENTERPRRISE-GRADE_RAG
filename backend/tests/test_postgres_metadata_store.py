from datetime import datetime, timezone

from psycopg.types.json import Json

import backend.app.db.postgres_metadata_store as postgres_metadata_store_module
from backend.app.db.postgres_metadata_store import PostgresMetadataStore
from backend.app.schemas.document import DocumentRecord


class _FakeCursor:
    def __init__(self) -> None:
        self.params: dict[str, object] | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, _sql: str, params: dict[str, object] | None = None) -> None:
        self.params = params


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return self._cursor


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


def test_save_document_adapts_metadata_as_json(monkeypatch) -> None:
    captured_cursor = _FakeCursor()

    def fake_connect(_dsn: str) -> _FakeConnection:
        return _FakeConnection(captured_cursor)

    monkeypatch.setattr(postgres_metadata_store_module.psycopg, "connect", fake_connect)
    store = PostgresMetadataStore("postgresql://user:pass@localhost:5432/rag")
    now = datetime.now(timezone.utc)
    record = DocumentRecord(
        doc_id="doc_001",
        tenant_id="tenant_a",
        file_name="manual.pdf",
        file_hash="hash_001",
        source_type="pdf",
        department_id="dept_1",
        department_ids=["dept_1"],
        category_id="cat_1",
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=[],
        source_system=None,
        status="queued",
        current_version=1,
        latest_job_id="job_001",
        storage_path="/tmp/manual.pdf",
        uploaded_by="alice",
        created_by="alice",
        created_at=now,
        updated_at=now,
    )

    store.save_document(record)

    assert captured_cursor.params is not None
    metadata_param = captured_cursor.params["metadata"]
    assert isinstance(metadata_param, Json)
    assert metadata_param.obj == {"department_id": "dept_1", "category_id": "cat_1", "uploaded_by": "alice"}
