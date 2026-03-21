from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row
from qdrant_client import QdrantClient

from ..core.config import Settings
from ..db.postgres_metadata_store import PostgresMetadataStore
from ..rag.embeddings.client import EmbeddingClient


@dataclass(slots=True)
class PgvectorTargetChunk:
    chunk_id: str
    content: str


@dataclass(slots=True)
class PgvectorBackfillReport:
    mode: str
    dry_run: bool
    only_missing: bool
    target_chunks: int
    qdrant_points_scanned: int = 0
    qdrant_matches: int = 0
    qdrant_written: int = 0
    reembed_candidates: int = 0
    reembedded: int = 0
    skipped_empty_content: int = 0
    skipped_vector_dim: int = 0
    version_counts_synced: int = 0
    ann_index_method: str | None = None
    remaining_without_embedding: int = 0
    warnings: list[str] = field(default_factory=list)


def backfill_pgvector(
    *,
    dsn: str,
    settings: Settings,
    mode: str = "hybrid",
    only_missing: bool = True,
    vector_dim: int = 1024,
    qdrant_batch_size: int = 256,
    allow_qdrant_fallback: bool = False,
    dry_run: bool = False,
) -> PgvectorBackfillReport:
    if mode not in {"qdrant", "reembed", "hybrid"}:
        raise ValueError(f"Unsupported mode: {mode}")

    target_chunks = _fetch_target_chunks(dsn=dsn, only_missing=only_missing)
    pending_by_chunk_id = {row.chunk_id: row for row in target_chunks}

    report = PgvectorBackfillReport(
        mode=mode,
        dry_run=dry_run,
        only_missing=only_missing,
        target_chunks=len(target_chunks),
    )

    if mode in {"qdrant", "hybrid"} and pending_by_chunk_id:
        try:
            qdrant_vectors, scanned_count, warnings = _load_qdrant_vectors(
                qdrant_url=settings.qdrant_url,
                qdrant_collection=settings.qdrant_collection,
                batch_size=qdrant_batch_size,
                target_chunk_ids=set(pending_by_chunk_id),
            )
            report.qdrant_points_scanned = scanned_count
            report.warnings.extend(warnings)

            qdrant_updates: list[dict[str, str]] = []
            for chunk_id in list(pending_by_chunk_id):
                vector = qdrant_vectors.get(chunk_id)
                if vector is None:
                    continue
                report.qdrant_matches += 1
                if vector_dim > 0 and len(vector) != vector_dim:
                    report.skipped_vector_dim += 1
                    report.warnings.append(
                        f"skip qdrant chunk={chunk_id}, vector_dim={len(vector)} does not match expected {vector_dim}"
                    )
                    continue
                qdrant_updates.append(
                    {
                        "chunk_id": chunk_id,
                        "embedding_model": settings.embedding_model,
                        "embedding": _vector_to_pg_literal(vector),
                    }
                )

            if not dry_run:
                report.qdrant_written = _write_pgvector_updates(
                    dsn=dsn,
                    rows=qdrant_updates,
                    only_missing=only_missing,
                )
            else:
                report.qdrant_written = len(qdrant_updates)

            for row in qdrant_updates:
                pending_by_chunk_id.pop(row["chunk_id"], None)
        except Exception as exc:  # noqa: BLE001
            if mode == "qdrant" or not allow_qdrant_fallback:
                raise
            report.warnings.append(f"qdrant backfill skipped (fallback enabled): {exc}")

    if mode in {"reembed", "hybrid"} and pending_by_chunk_id:
        embedder = EmbeddingClient(settings)
        pending_rows = [pending_by_chunk_id[chunk_id] for chunk_id in sorted(pending_by_chunk_id)]
        report.reembed_candidates = len(pending_rows)

        for batch_start in range(0, len(pending_rows), max(1, settings.embedding_batch_size)):
            batch_rows = pending_rows[batch_start : batch_start + max(1, settings.embedding_batch_size)]
            text_batch: list[str] = []
            chunk_id_batch: list[str] = []
            for row in batch_rows:
                text = row.content.strip()
                if not text:
                    report.skipped_empty_content += 1
                    continue
                text_batch.append(text)
                chunk_id_batch.append(row.chunk_id)

            if not text_batch:
                continue

            vectors = embedder.embed_texts(text_batch)
            if len(vectors) != len(chunk_id_batch):
                raise RuntimeError(
                    f"Embedding count mismatch: requested={len(chunk_id_batch)} returned={len(vectors)}"
                )

            reembed_updates: list[dict[str, str]] = []
            for chunk_id, vector in zip(chunk_id_batch, vectors, strict=True):
                if vector_dim > 0 and len(vector) != vector_dim:
                    report.skipped_vector_dim += 1
                    report.warnings.append(
                        f"skip reembed chunk={chunk_id}, vector_dim={len(vector)} does not match expected {vector_dim}"
                    )
                    continue
                reembed_updates.append(
                    {
                        "chunk_id": chunk_id,
                        "embedding_model": settings.embedding_model,
                        "embedding": _vector_to_pg_literal(vector),
                    }
                )

            if not dry_run:
                report.reembedded += _write_pgvector_updates(
                    dsn=dsn,
                    rows=reembed_updates,
                    only_missing=only_missing,
                )
            else:
                report.reembedded += len(reembed_updates)

            for row in reembed_updates:
                pending_by_chunk_id.pop(row["chunk_id"], None)

    if not dry_run:
        report.version_counts_synced = _sync_document_version_vector_counts(dsn=dsn)

    report.remaining_without_embedding = len(pending_by_chunk_id) if dry_run else _count_chunks_without_embedding(dsn=dsn)
    return report


def ensure_pgvector_target_table(dsn: str) -> None:
    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", ("public.rag_knowledge_chunks",))
            row = cur.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError(
                    "PostgreSQL table public.rag_knowledge_chunks is missing. "
                    "Run `npx prisma@6.19.0 db push --schema prisma/schema.prisma` first."
                )


def ensure_pgvector_ann_index(
    dsn: str,
    *,
    method: str = "auto",
    ivfflat_lists: int = 100,
) -> str | None:
    normalized_method = method.strip().lower()
    if normalized_method == "none":
        return None
    if normalized_method not in {"auto", "hnsw", "ivfflat"}:
        raise ValueError(f"Unsupported ann index method: {method}")

    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

            if normalized_method in {"auto", "hnsw"}:
                try:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS rag_knowledge_chunks_embedding_hnsw_idx
                        ON public.rag_knowledge_chunks
                        USING hnsw (embedding vector_cosine_ops)
                        WHERE embedding IS NOT NULL
                        """
                    )
                    conn.commit()
                    return "hnsw"
                except Exception:
                    if normalized_method == "hnsw":
                        raise
                    conn.rollback()

            if normalized_method in {"auto", "ivfflat"}:
                safe_lists = max(1, int(ivfflat_lists))
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS rag_knowledge_chunks_embedding_ivfflat_idx
                    ON public.rag_knowledge_chunks
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = {safe_lists})
                    WHERE embedding IS NOT NULL
                    """
                )
                conn.commit()
                return "ivfflat"

    return None


def _fetch_target_chunks(*, dsn: str, only_missing: bool) -> list[PgvectorTargetChunk]:
    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    sql = """
        SELECT "chunkId", content
        FROM public.rag_knowledge_chunks
    """
    if only_missing:
        sql += ' WHERE embedding IS NULL'
    sql += ' ORDER BY "docId", "chunkIndex"'

    with psycopg.connect(psycopg_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [
        PgvectorTargetChunk(
            chunk_id=str(row["chunkId"]),
            content=str(row["content"] or ""),
        )
        for row in rows
    ]


def _count_chunks_without_embedding(*, dsn: str) -> int:
    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM public.rag_knowledge_chunks WHERE embedding IS NULL')
            row = cur.fetchone()
            return int(row[0] if row is not None else 0)


def _sync_document_version_vector_counts(*, dsn: str) -> int:
    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE public.rag_document_versions SET "vectorCount" = 0 WHERE "vectorCount" <> 0')
            cur.execute(
                """
                WITH counters AS (
                    SELECT "docId", version, COUNT(*)::int AS cnt
                    FROM public.rag_knowledge_chunks
                    WHERE embedding IS NOT NULL
                    GROUP BY "docId", version
                )
                UPDATE public.rag_document_versions AS v
                SET "vectorCount" = counters.cnt,
                    "updatedAt" = NOW()
                FROM counters
                WHERE v."docId" = counters."docId"
                  AND v.version = counters.version
                """
            )
            updated = cur.rowcount or 0
        conn.commit()
    return int(updated)


def _write_pgvector_updates(*, dsn: str, rows: list[dict[str, str]], only_missing: bool) -> int:
    if not rows:
        return 0

    psycopg_dsn = PostgresMetadataStore._normalize_psycopg_dsn(dsn)
    sql = """
        UPDATE public.rag_knowledge_chunks
        SET "embeddingModel" = %(embedding_model)s,
            "embedding" = %(embedding)s::vector,
            "updatedAt" = NOW()
        WHERE "chunkId" = %(chunk_id)s
    """
    if only_missing:
        sql += " AND embedding IS NULL"

    updated = 0
    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, row)
                updated += cur.rowcount or 0
        conn.commit()
    return updated


def _build_qdrant_client(qdrant_url: str) -> QdrantClient:
    normalized = qdrant_url.strip()
    if normalized == ":memory:":
        return QdrantClient(":memory:")
    if normalized.startswith(("http://", "https://")):
        return QdrantClient(url=normalized, trust_env=False, check_compatibility=False)
    return QdrantClient(path=normalized)


def _load_qdrant_vectors(
    *,
    qdrant_url: str,
    qdrant_collection: str,
    batch_size: int,
    target_chunk_ids: set[str] | None = None,
) -> tuple[dict[str, list[float]], int, list[str]]:
    client = _build_qdrant_client(qdrant_url)
    collection_names = {item.name for item in client.get_collections().collections}
    if qdrant_collection not in collection_names:
        raise RuntimeError(
            f"Qdrant collection not found: {qdrant_collection}. Available={sorted(collection_names)}"
        )

    vectors_by_chunk_id: dict[str, list[float]] = {}
    warnings: list[str] = []
    scanned_points = 0
    offset: Any = None

    while True:
        points, offset = client.scroll(
            collection_name=qdrant_collection,
            limit=max(1, batch_size),
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break

        for point in points:
            scanned_points += 1
            payload = point.payload or {}
            chunk_id = str(payload.get("chunk_id") or payload.get("chunkId") or "").strip()
            if not chunk_id:
                warnings.append(f"qdrant point {point.id} missing chunk_id")
                continue
            if target_chunk_ids is not None and chunk_id not in target_chunk_ids:
                continue
            vector = _extract_vector(point.vector)
            if vector is None:
                warnings.append(f"qdrant point {point.id} chunk_id={chunk_id} has no vector")
                continue
            vectors_by_chunk_id[chunk_id] = vector

        if offset is None:
            break

    return vectors_by_chunk_id, scanned_points, warnings


def _extract_vector(raw_vector: Any) -> list[float] | None:
    if raw_vector is None:
        return None
    if isinstance(raw_vector, dict):
        if not raw_vector:
            return None
        first_value = next(iter(raw_vector.values()))
        return _extract_vector(first_value)
    if isinstance(raw_vector, (list, tuple)):
        try:
            return [float(item) for item in raw_vector]
        except (TypeError, ValueError):
            return None
    return None


def _vector_to_pg_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".12g") for value in vector) + "]"
