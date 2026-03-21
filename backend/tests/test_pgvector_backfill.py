from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.tools import pgvector_backfill
from backend.app.tools.pgvector_backfill import PgvectorTargetChunk


def test_extract_vector_supports_dense_list_and_named_vectors() -> None:
    assert pgvector_backfill._extract_vector([1, 2.5, "3"]) == [1.0, 2.5, 3.0]
    assert pgvector_backfill._extract_vector({"dense": [0.1, 0.2]}) == [0.1, 0.2]
    assert pgvector_backfill._extract_vector(None) is None


def test_vector_to_pg_literal_formats_pgvector_value() -> None:
    assert pgvector_backfill._vector_to_pg_literal([0.1, -2, 3.25]) == "[0.1,-2,3.25]"


def test_backfill_pgvector_hybrid_prefers_qdrant_then_reembed(monkeypatch) -> None:
    writes: list[list[dict[str, str]]] = []

    def fake_fetch_target_chunks(*, dsn: str, only_missing: bool) -> list[PgvectorTargetChunk]:
        assert dsn == "postgresql://example"
        assert only_missing is True
        return [
            PgvectorTargetChunk(chunk_id="chunk-a", content="alpha"),
            PgvectorTargetChunk(chunk_id="chunk-b", content="beta"),
            PgvectorTargetChunk(chunk_id="chunk-c", content=""),
        ]

    def fake_load_qdrant_vectors(*, qdrant_url: str, qdrant_collection: str, batch_size: int, target_chunk_ids: set[str] | None):
        assert qdrant_url == "http://qdrant.test:6333"
        assert qdrant_collection == "enterprise_rag_v1_local_bge_m3"
        assert batch_size == 128
        assert target_chunk_ids == {"chunk-a", "chunk-b", "chunk-c"}
        return {"chunk-a": [0.1, 0.2]}, 7, []

    def fake_write_pgvector_updates(*, dsn: str, rows: list[dict[str, str]], only_missing: bool) -> int:
        assert dsn == "postgresql://example"
        assert only_missing is True
        writes.append(rows)
        return len(rows)

    def fake_count_chunks_without_embedding(*, dsn: str) -> int:
        assert dsn == "postgresql://example"
        return 1

    def fake_sync_document_version_vector_counts(*, dsn: str) -> int:
        assert dsn == "postgresql://example"
        return 2

    class FakeEmbeddingClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            assert texts == ["beta"]
            return [[0.3, 0.4]]

    monkeypatch.setattr(pgvector_backfill, "_fetch_target_chunks", fake_fetch_target_chunks)
    monkeypatch.setattr(pgvector_backfill, "_load_qdrant_vectors", fake_load_qdrant_vectors)
    monkeypatch.setattr(pgvector_backfill, "_write_pgvector_updates", fake_write_pgvector_updates)
    monkeypatch.setattr(pgvector_backfill, "_count_chunks_without_embedding", fake_count_chunks_without_embedding)
    monkeypatch.setattr(
        pgvector_backfill,
        "_sync_document_version_vector_counts",
        fake_sync_document_version_vector_counts,
    )
    monkeypatch.setattr(pgvector_backfill, "EmbeddingClient", FakeEmbeddingClient)

    settings = Settings(
        _env_file=None,
        qdrant_url="http://qdrant.test:6333",
        qdrant_collection="enterprise_rag_v1_local_bge_m3",
        embedding_provider="openai",
        embedding_model="BAAI/bge-m3",
        embedding_batch_size=8,
    )

    report = pgvector_backfill.backfill_pgvector(
        dsn="postgresql://example",
        settings=settings,
        mode="hybrid",
        only_missing=True,
        vector_dim=2,
        qdrant_batch_size=128,
        dry_run=False,
    )

    assert report.target_chunks == 3
    assert report.qdrant_points_scanned == 7
    assert report.qdrant_matches == 1
    assert report.qdrant_written == 1
    assert report.reembed_candidates == 2
    assert report.reembedded == 1
    assert report.skipped_empty_content == 1
    assert report.skipped_vector_dim == 0
    assert report.version_counts_synced == 2
    assert report.remaining_without_embedding == 1
    assert writes[0][0]["chunk_id"] == "chunk-a"
    assert writes[1][0]["chunk_id"] == "chunk-b"


def test_backfill_pgvector_hybrid_fail_fast_without_fallback(monkeypatch) -> None:
    def fake_fetch_target_chunks(*, dsn: str, only_missing: bool) -> list[PgvectorTargetChunk]:
        return [PgvectorTargetChunk(chunk_id="chunk-a", content="alpha")]

    def fake_load_qdrant_vectors(**kwargs):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(pgvector_backfill, "_fetch_target_chunks", fake_fetch_target_chunks)
    monkeypatch.setattr(pgvector_backfill, "_load_qdrant_vectors", fake_load_qdrant_vectors)

    settings = Settings(_env_file=None, qdrant_url="http://qdrant.test:6333", qdrant_collection="enterprise")

    try:
        pgvector_backfill.backfill_pgvector(
            dsn="postgresql://example",
            settings=settings,
            mode="hybrid",
            allow_qdrant_fallback=False,
            dry_run=True,
        )
    except RuntimeError as exc:
        assert "qdrant unavailable" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when qdrant fails and fallback is disabled")
