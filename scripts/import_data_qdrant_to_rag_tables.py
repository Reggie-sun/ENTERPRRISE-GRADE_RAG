#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg
from psycopg.types.json import Json
from qdrant_client import QdrantClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings, get_postgres_metadata_dsn
from backend.app.schemas.document import DocumentRecord, IngestJobRecord
from backend.app.tools.postgres_metadata_backfill import load_document_records, load_job_records

DOC_STATUS_ALLOWED = {"queued", "uploaded", "active", "failed", "partial_failed"}
JOB_STATUS_ALLOWED = {
    "pending",
    "uploaded",
    "queued",
    "parsing",
    "ocr_processing",
    "chunking",
    "embedding",
    "indexing",
    "completed",
    "failed",
    "dead_letter",
    "partial_failed",
}
VISIBILITY_ALLOWED = {"public", "department", "role", "private"}
CLASSIFICATION_ALLOWED = {"public", "internal", "confidential", "secret"}
REQUIRED_TABLES = (
    "rag_source_documents",
    "rag_document_versions",
    "rag_ingest_jobs",
    "rag_knowledge_chunks",
)


@dataclass(slots=True)
class QdrantChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int | None
    text: str | None
    source_path: str | None
    parsed_path: str | None
    char_start: int | None
    char_end: int | None
    page_no: int | None
    vector: list[float] | None
    point_id: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ChunkFileRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int | None
    text: str | None
    char_start: int | None
    char_end: int | None
    page_no: int | None


@dataclass(slots=True)
class ScanSummary:
    document_valid: int
    document_invalid: int
    job_valid: int
    job_invalid: int
    chunk_files: int
    chunk_file_records: int
    qdrant_points: int


@dataclass(slots=True)
class BuildSummary:
    placeholder_documents_created: int
    skipped_jobs: int
    skipped_chunks: int
    chunks_without_embedding: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot import: data/ + Qdrant -> rag_* tables in PostgreSQL."
    )
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Fallback: RAG_POSTGRES_METADATA_DSN -> DATABASE_URL.")
    parser.add_argument("--document-dir", default="data/documents", help="Directory for DocumentRecord JSON files.")
    parser.add_argument("--job-dir", default="data/jobs", help="Directory for IngestJobRecord JSON files.")
    parser.add_argument("--chunk-dir", default="data/chunks", help="Directory for chunk JSON files.")
    parser.add_argument("--parsed-dir", default="data/parsed", help="Directory for parsed text files.")
    parser.add_argument("--qdrant-url", default="", help="Qdrant URL. Fallback: RAG_QDRANT_URL.")
    parser.add_argument("--qdrant-collection", default="", help="Qdrant collection name. Fallback: RAG_QDRANT_COLLECTION.")
    parser.add_argument("--embedding-model", default="", help="Embedding model name written into rag_knowledge_chunks.")
    parser.add_argument("--namespace", default="default", help="Namespace written into rag_* records.")
    parser.add_argument("--default-tenant-id", default="wl", help="Tenant ID for placeholder documents.")
    parser.add_argument(
        "--missing-doc-strategy",
        choices=("create", "skip", "error"),
        default="skip",
        help="When jobs/chunks reference doc_id not found in data/documents.",
    )
    parser.add_argument("--vector-dim", type=int, default=1024, help="Expected embedding dimension. Set 0 to disable validation.")
    parser.add_argument("--batch-size", type=int, default=256, help="Qdrant scroll batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and build rows only; do not write into PostgreSQL.")
    return parser.parse_args()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


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


def _vector_to_pg_literal(vector: list[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(format(value, ".12g") for value in vector) + "]"


def _safe_json(value: dict[str, Any] | None) -> Json | None:
    if value is None:
        return None
    return Json(value)


def _infer_source_type(file_name: str, source_path: str | None) -> str:
    candidate = source_path or file_name
    suffix = Path(candidate).suffix.lower().lstrip(".")
    return suffix or "unknown"


def _normalize_enum(value: str | None, allowed: set[str], default: str) -> str:
    normalized = (value or "").strip()
    if normalized in allowed:
        return normalized
    return default


def _normalize_postgres_dsn_for_psycopg(dsn: str) -> tuple[str, str | None]:
    """Convert Prisma-style `?schema=...` URI into libpq-compatible options."""
    raw = dsn.strip()
    if "://" not in raw:
        return raw, None

    parsed = urlparse(raw)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    schema_values = [value.strip() for key, value in query_items if key.lower() == "schema" and value.strip()]
    if not schema_values:
        return raw, None

    schema_name = schema_values[-1]
    query_without_schema = [(key, value) for key, value in query_items if key.lower() != "schema"]

    options_indexes = [index for index, item in enumerate(query_without_schema) if item[0].lower() == "options"]
    if options_indexes:
        target_index = options_indexes[-1]
        key, value = query_without_schema[target_index]
        if "search_path" not in value:
            merged = f"{value} -csearch_path={schema_name}".strip()
            query_without_schema[target_index] = (key, merged)
    else:
        query_without_schema.append(("options", f"-csearch_path={schema_name}"))

    normalized_query = urlencode(query_without_schema, doseq=True)
    normalized_dsn = urlunparse(parsed._replace(query=normalized_query))
    return normalized_dsn, schema_name


def _build_placeholder_document(
    doc_id: str,
    *,
    default_tenant_id: str,
    source_path: str | None,
    document_name: str | None,
    source_system: str,
) -> DocumentRecord:
    now = _now_utc()
    file_name = (document_name or "").strip() or f"{doc_id}.txt"
    inferred_source_type = _infer_source_type(file_name=file_name, source_path=source_path)
    hash_seed = f"{doc_id}|{source_path or ''}|{file_name}".encode("utf-8")
    file_hash = hashlib.sha256(hash_seed).hexdigest()
    storage_path = source_path or f"qdrant://placeholder/{doc_id}"
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id=default_tenant_id,
        file_name=file_name,
        file_hash=file_hash,
        source_type=inferred_source_type,
        department_ids=[],
        role_ids=[],
        owner_id=None,
        visibility="private",
        classification="internal",
        tags=["qdrant_import"],
        source_system=source_system,
        status="active",
        current_version=1,
        latest_job_id="",
        storage_path=storage_path,
        created_by="rag-import-script",
        created_at=now,
        updated_at=now,
    )


def _load_chunk_file_records(chunk_dir: Path) -> tuple[dict[str, ChunkFileRecord], Counter[str], int, list[str]]:
    chunk_by_id: dict[str, ChunkFileRecord] = {}
    chunk_count_by_doc: Counter[str] = Counter()
    warning_messages: list[str] = []
    files_scanned = 0

    if not chunk_dir.exists():
        return chunk_by_id, chunk_count_by_doc, files_scanned, warning_messages

    for path in sorted(chunk_dir.glob("*.json")):
        if not path.is_file() or path.name.startswith("."):
            continue
        files_scanned += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            warning_messages.append(f"invalid chunk file {path}: {exc}")
            continue

        if not isinstance(payload, list):
            warning_messages.append(f"chunk file {path} is not a JSON list")
            continue

        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                warning_messages.append(f"chunk file {path} entry #{index} is not an object")
                continue

            chunk_id = str(item.get("chunk_id") or "").strip()
            doc_id = str(item.get("document_id") or "").strip()
            if not chunk_id or not doc_id:
                warning_messages.append(f"chunk file {path} entry #{index} missing chunk_id/document_id")
                continue

            record = ChunkFileRecord(
                chunk_id=chunk_id,
                doc_id=doc_id,
                chunk_index=_coerce_int(item.get("chunk_index")),
                text=None if item.get("text") is None else str(item.get("text")),
                char_start=_coerce_int(item.get("char_start")),
                char_end=_coerce_int(item.get("char_end")),
                page_no=_coerce_int(item.get("page_no") or item.get("page")),
            )

            if chunk_id in chunk_by_id and chunk_by_id[chunk_id] != record:
                warning_messages.append(f"duplicate chunk_id in chunk files: {chunk_id}, latest file wins")
            chunk_by_id[chunk_id] = record
            chunk_count_by_doc[doc_id] += 1

    return chunk_by_id, chunk_count_by_doc, files_scanned, warning_messages


def _load_qdrant_chunk_records(
    *,
    qdrant_url: str,
    qdrant_collection: str,
    batch_size: int,
) -> tuple[dict[str, QdrantChunkRecord], Counter[str], dict[str, dict[str, Any]], list[str], int]:
    warning_messages: list[str] = []
    records_by_chunk_id: dict[str, QdrantChunkRecord] = {}
    vector_count_by_doc: Counter[str] = Counter()
    doc_hint_by_doc_id: dict[str, dict[str, Any]] = {}

    client = QdrantClient(url=qdrant_url, trust_env=False, check_compatibility=False)
    collection_names = {item.name for item in client.get_collections().collections}
    if qdrant_collection not in collection_names:
        raise RuntimeError(
            f"Qdrant collection not found: {qdrant_collection}. Available={sorted(collection_names)}"
        )

    fetched_points = 0
    offset: Any = None
    while True:
        points, offset = client.scroll(
            collection_name=qdrant_collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break

        for point in points:
            fetched_points += 1
            payload = point.payload or {}
            chunk_id = str(payload.get("chunk_id") or point.id or "").strip()
            doc_id = str(payload.get("document_id") or "").strip()
            if not chunk_id:
                warning_messages.append(f"qdrant point {point.id} missing chunk_id")
                continue
            if not doc_id:
                warning_messages.append(f"qdrant point {point.id} missing document_id")
                continue

            vector = _extract_vector(point.vector)
            record = QdrantChunkRecord(
                chunk_id=chunk_id,
                doc_id=doc_id,
                chunk_index=_coerce_int(payload.get("chunk_index")),
                text=None if payload.get("text") is None else str(payload.get("text")),
                source_path=None if payload.get("source_path") is None else str(payload.get("source_path")),
                parsed_path=None if payload.get("parsed_path") is None else str(payload.get("parsed_path")),
                char_start=_coerce_int(payload.get("char_start")),
                char_end=_coerce_int(payload.get("char_end")),
                page_no=_coerce_int(payload.get("page_no") or payload.get("page")),
                vector=vector,
                point_id=str(point.id),
                payload=dict(payload),
            )

            if chunk_id in records_by_chunk_id and records_by_chunk_id[chunk_id] != record:
                warning_messages.append(f"duplicate chunk_id in qdrant: {chunk_id}, latest point wins")
            records_by_chunk_id[chunk_id] = record
            vector_count_by_doc[doc_id] += 1
            if doc_id not in doc_hint_by_doc_id:
                doc_hint_by_doc_id[doc_id] = dict(payload)

        if offset is None:
            break

    return records_by_chunk_id, vector_count_by_doc, doc_hint_by_doc_id, warning_messages, fetched_points


def _ensure_required_tables(conn: psycopg.Connection[Any]) -> None:
    missing: list[str] = []
    with conn.cursor() as cur:
        for table in REQUIRED_TABLES:
            cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
            row = cur.fetchone()
            if row is None or row[0] is None:
                missing.append(table)
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"PostgreSQL target tables are missing: {joined}. "
            "Run `npx prisma db push --schema prisma/schema.prisma` first."
        )


def _prepare_import_rows(
    *,
    document_records: list[DocumentRecord],
    job_records: list[IngestJobRecord],
    chunk_file_records: dict[str, ChunkFileRecord],
    chunk_count_by_doc: Counter[str],
    qdrant_chunk_records: dict[str, QdrantChunkRecord],
    qdrant_vector_count_by_doc: Counter[str],
    qdrant_doc_hints: dict[str, dict[str, Any]],
    missing_doc_strategy: str,
    default_tenant_id: str,
    namespace: str,
    embedding_model: str,
    parsed_dir: Path,
    chunk_dir: Path,
    vector_dim: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], BuildSummary, list[str]]:
    warnings: list[str] = []
    docs_by_id: dict[str, DocumentRecord] = {record.doc_id: record for record in document_records}

    referenced_doc_ids: set[str] = set()
    referenced_doc_ids.update(job.doc_id for job in job_records)
    referenced_doc_ids.update(record.doc_id for record in chunk_file_records.values())
    referenced_doc_ids.update(record.doc_id for record in qdrant_chunk_records.values())

    placeholder_docs_created = 0
    for doc_id in sorted(referenced_doc_ids):
        if doc_id in docs_by_id:
            continue

        if missing_doc_strategy == "error":
            raise RuntimeError(
                f"doc_id={doc_id} is referenced by job/chunk/qdrant but missing in data/documents. "
                "Use --missing-doc-strategy=create or skip."
            )

        if missing_doc_strategy == "skip":
            continue

        hint = qdrant_doc_hints.get(doc_id, {})
        placeholder = _build_placeholder_document(
            doc_id,
            default_tenant_id=default_tenant_id,
            source_path=None if hint.get("source_path") is None else str(hint.get("source_path")),
            document_name=None if hint.get("document_name") is None else str(hint.get("document_name")),
            source_system="qdrant_import",
        )
        docs_by_id[doc_id] = placeholder
        placeholder_docs_created += 1

    skipped_jobs = 0
    prepared_jobs: list[dict[str, Any]] = []
    for record in sorted(job_records, key=lambda item: item.job_id):
        if record.doc_id not in docs_by_id:
            skipped_jobs += 1
            warnings.append(f"skip job={record.job_id}, doc_id={record.doc_id} is missing")
            continue

        normalized_status = _normalize_enum(record.status, JOB_STATUS_ALLOWED, "failed")
        prepared_jobs.append(
            {
                "job_id": record.job_id,
                "doc_id": record.doc_id,
                "version": record.version,
                "file_name": record.file_name,
                "status": normalized_status,
                "stage": record.stage,
                "progress": record.progress,
                "retry_count": record.retry_count,
                "error_code": record.error_code,
                "error_message": record.error_message,
                "metadata": None,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    max_job_version_by_doc: dict[str, int] = {}
    latest_job_id_by_doc: dict[str, str] = {}
    latest_job_time_by_doc: dict[str, datetime] = {}
    for record in job_records:
        if record.doc_id not in docs_by_id:
            continue
        previous_version = max_job_version_by_doc.get(record.doc_id, 0)
        if record.version > previous_version:
            max_job_version_by_doc[record.doc_id] = record.version

        previous_time = latest_job_time_by_doc.get(record.doc_id)
        if previous_time is None or record.updated_at >= previous_time:
            latest_job_time_by_doc[record.doc_id] = record.updated_at
            latest_job_id_by_doc[record.doc_id] = record.job_id

    prepared_docs: list[dict[str, Any]] = []
    prepared_versions: list[dict[str, Any]] = []

    for doc_id in sorted(docs_by_id.keys()):
        record = docs_by_id[doc_id]
        normalized_visibility = _normalize_enum(record.visibility, VISIBILITY_ALLOWED, "private")
        normalized_classification = _normalize_enum(record.classification, CLASSIFICATION_ALLOWED, "internal")
        normalized_status = _normalize_enum(record.status, DOC_STATUS_ALLOWED, "active")
        current_version = max(record.current_version, max_job_version_by_doc.get(doc_id, 1))

        latest_job_id = latest_job_id_by_doc.get(doc_id) or (record.latest_job_id.strip() if record.latest_job_id else "")
        latest_job_value = latest_job_id or None

        prepared_docs.append(
            {
                "doc_id": record.doc_id,
                "tenant_id": record.tenant_id,
                "file_name": record.file_name,
                "file_hash": record.file_hash,
                "source_type": record.source_type,
                "source_system": record.source_system,
                "created_by": record.created_by,
                "owner_id": record.owner_id,
                "visibility": normalized_visibility,
                "classification": normalized_classification,
                "department_ids": record.department_ids,
                "role_ids": record.role_ids,
                "tags": record.tags,
                "namespace": namespace,
                "status": normalized_status,
                "current_version": current_version,
                "latest_job_id": latest_job_value,
                "storage_path": record.storage_path,
                "metadata": None,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

        parsed_path_from_qdrant = None
        if doc_id in qdrant_doc_hints:
            hint = qdrant_doc_hints[doc_id]
            if hint.get("parsed_path") is not None:
                parsed_path_from_qdrant = str(hint.get("parsed_path"))

        parsed_candidate = parsed_dir / f"{doc_id}.txt"
        parsed_path = str(parsed_candidate) if parsed_candidate.exists() else parsed_path_from_qdrant

        chunk_candidate = chunk_dir / f"{doc_id}.json"
        chunk_path = str(chunk_candidate) if chunk_candidate.exists() else None

        chunk_count = chunk_count_by_doc.get(doc_id, 0)
        vector_count = qdrant_vector_count_by_doc.get(doc_id, 0)
        if chunk_count == 0 and vector_count > 0:
            chunk_count = vector_count

        prepared_versions.append(
            {
                "doc_id": doc_id,
                "version": current_version,
                "storage_path": record.storage_path,
                "parsed_path": parsed_path,
                "chunk_path": chunk_path,
                "chunk_count": int(chunk_count),
                "vector_count": int(vector_count),
                "index_version": None,
                "is_current": True,
                "status": normalized_status,
                "metadata": _safe_json(
                    {
                        "import_source": "data+qdrant",
                        "qdrant_vector_count": int(vector_count),
                    }
                ),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    skipped_chunks = 0
    chunks_without_embedding = 0
    prepared_chunks: list[dict[str, Any]] = []
    skipped_chunk_doc_counter: Counter[str] = Counter()

    for chunk_id in sorted(set(chunk_file_records.keys()) | set(qdrant_chunk_records.keys())):
        from_file = chunk_file_records.get(chunk_id)
        from_qdrant = qdrant_chunk_records.get(chunk_id)

        doc_id = ""
        if from_file is not None:
            doc_id = from_file.doc_id
        elif from_qdrant is not None:
            doc_id = from_qdrant.doc_id

        if from_file is not None and from_qdrant is not None and from_file.doc_id != from_qdrant.doc_id:
            warnings.append(
                "chunk_id=%s doc_id mismatch: file=%s qdrant=%s, file value wins"
                % (chunk_id, from_file.doc_id, from_qdrant.doc_id)
            )

        if not doc_id or doc_id not in docs_by_id:
            skipped_chunks += 1
            skipped_chunk_doc_counter[doc_id or "<empty>"] += 1
            continue

        document = docs_by_id[doc_id]
        chunk_index = None
        if from_file is not None:
            chunk_index = from_file.chunk_index
        if chunk_index is None and from_qdrant is not None:
            chunk_index = from_qdrant.chunk_index
        if chunk_index is None:
            chunk_index = 0

        content: str | None = None
        if from_file is not None and from_file.text is not None:
            content = from_file.text
        if (content is None or content == "") and from_qdrant is not None and from_qdrant.text is not None:
            content = from_qdrant.text
        if content is None:
            content = ""

        char_start = from_file.char_start if from_file is not None else None
        if char_start is None and from_qdrant is not None:
            char_start = from_qdrant.char_start

        char_end = from_file.char_end if from_file is not None else None
        if char_end is None and from_qdrant is not None:
            char_end = from_qdrant.char_end

        page_no = from_file.page_no if from_file is not None else None
        if page_no is None and from_qdrant is not None:
            page_no = from_qdrant.page_no

        source_path = None
        parsed_path = None
        if from_qdrant is not None:
            source_path = from_qdrant.source_path
            parsed_path = from_qdrant.parsed_path
        if source_path is None:
            source_path = document.storage_path
        if parsed_path is None:
            parsed_candidate = parsed_dir / f"{doc_id}.txt"
            if parsed_candidate.exists():
                parsed_path = str(parsed_candidate)

        embedding = from_qdrant.vector if from_qdrant is not None else None
        if embedding is None:
            chunks_without_embedding += 1
        elif vector_dim > 0 and len(embedding) != vector_dim:
            skipped_chunks += 1
            warnings.append(
                f"skip chunk={chunk_id}, vector_dim={len(embedding)} does not match expected {vector_dim}"
            )
            continue

        normalized_visibility = _normalize_enum(document.visibility, VISIBILITY_ALLOWED, "private")
        normalized_classification = _normalize_enum(document.classification, CLASSIFICATION_ALLOWED, "internal")

        metadata_payload: dict[str, Any] = {
            "from_data_chunk": from_file is not None,
            "from_qdrant": from_qdrant is not None,
        }
        if from_qdrant is not None:
            metadata_payload["qdrant_point_id"] = from_qdrant.point_id
            if from_qdrant.payload.get("document_name") is not None:
                metadata_payload["document_name"] = str(from_qdrant.payload.get("document_name"))

        prepared_chunks.append(
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "version": max(document.current_version, max_job_version_by_doc.get(doc_id, 1)),
                "tenant_id": document.tenant_id,
                "namespace": namespace,
                "chunk_index": int(chunk_index),
                "content": content,
                "embedding_model": embedding_model,
                "embedding": _vector_to_pg_literal(embedding),
                "source_path": source_path,
                "parsed_path": parsed_path,
                "char_start": char_start,
                "char_end": char_end,
                "page_no": page_no,
                "owner_id": document.owner_id,
                "visibility": normalized_visibility,
                "classification": normalized_classification,
                "department_ids": document.department_ids,
                "role_ids": document.role_ids,
                "metadata": _safe_json(metadata_payload),
                "created_at": document.created_at,
                "updated_at": document.updated_at,
            }
        )

    for missing_doc_id, count in sorted(skipped_chunk_doc_counter.items()):
        warnings.append(f"skip {count} chunk(s) because doc_id={missing_doc_id} is missing")

    summary = BuildSummary(
        placeholder_documents_created=placeholder_docs_created,
        skipped_jobs=skipped_jobs,
        skipped_chunks=skipped_chunks,
        chunks_without_embedding=chunks_without_embedding,
    )

    return prepared_docs, prepared_versions, prepared_jobs, prepared_chunks, summary, warnings


def _write_documents(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.rag_source_documents (
                "docId", "tenantId", "fileName", "fileHash", "sourceType",
                "sourceSystem", "createdBy", "ownerId", "visibility", "classification",
                "departmentIds", "roleIds", "tags", "namespace", "status",
                "currentVersion", "latestJobId", "storagePath", "metadata",
                "createdAt", "updatedAt"
            ) VALUES (
                %(doc_id)s, %(tenant_id)s, %(file_name)s, %(file_hash)s, %(source_type)s,
                %(source_system)s, %(created_by)s, %(owner_id)s, %(visibility)s, %(classification)s,
                %(department_ids)s, %(role_ids)s, %(tags)s, %(namespace)s, %(status)s,
                %(current_version)s, %(latest_job_id)s, %(storage_path)s, %(metadata)s,
                %(created_at)s, %(updated_at)s
            )
            ON CONFLICT ("docId") DO UPDATE SET
                "tenantId" = EXCLUDED."tenantId",
                "fileName" = EXCLUDED."fileName",
                "fileHash" = EXCLUDED."fileHash",
                "sourceType" = EXCLUDED."sourceType",
                "sourceSystem" = EXCLUDED."sourceSystem",
                "createdBy" = EXCLUDED."createdBy",
                "ownerId" = EXCLUDED."ownerId",
                "visibility" = EXCLUDED."visibility",
                "classification" = EXCLUDED."classification",
                "departmentIds" = EXCLUDED."departmentIds",
                "roleIds" = EXCLUDED."roleIds",
                "tags" = EXCLUDED."tags",
                "namespace" = EXCLUDED."namespace",
                "status" = EXCLUDED."status",
                "currentVersion" = EXCLUDED."currentVersion",
                "latestJobId" = EXCLUDED."latestJobId",
                "storagePath" = EXCLUDED."storagePath",
                "metadata" = EXCLUDED."metadata",
                "updatedAt" = EXCLUDED."updatedAt"
            """,
            rows,
        )


def _write_versions(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.rag_document_versions (
                "docId", "version", "storagePath", "parsedPath", "chunkPath",
                "chunkCount", "vectorCount", "indexVersion", "isCurrent", "status",
                "metadata", "createdAt", "updatedAt"
            ) VALUES (
                %(doc_id)s, %(version)s, %(storage_path)s, %(parsed_path)s, %(chunk_path)s,
                %(chunk_count)s, %(vector_count)s, %(index_version)s, %(is_current)s, %(status)s,
                %(metadata)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT ("docId", "version") DO UPDATE SET
                "storagePath" = EXCLUDED."storagePath",
                "parsedPath" = EXCLUDED."parsedPath",
                "chunkPath" = EXCLUDED."chunkPath",
                "chunkCount" = EXCLUDED."chunkCount",
                "vectorCount" = EXCLUDED."vectorCount",
                "indexVersion" = EXCLUDED."indexVersion",
                "isCurrent" = EXCLUDED."isCurrent",
                "status" = EXCLUDED."status",
                "metadata" = EXCLUDED."metadata",
                "updatedAt" = EXCLUDED."updatedAt"
            """,
            rows,
        )


def _write_jobs(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.rag_ingest_jobs (
                "jobId", "docId", "version", "fileName", "status", "stage",
                "progress", "retryCount", "errorCode", "errorMessage", "metadata",
                "createdAt", "updatedAt"
            ) VALUES (
                %(job_id)s, %(doc_id)s, %(version)s, %(file_name)s, %(status)s, %(stage)s,
                %(progress)s, %(retry_count)s, %(error_code)s, %(error_message)s, %(metadata)s,
                %(created_at)s, %(updated_at)s
            )
            ON CONFLICT ("jobId") DO UPDATE SET
                "docId" = EXCLUDED."docId",
                "version" = EXCLUDED."version",
                "fileName" = EXCLUDED."fileName",
                "status" = EXCLUDED."status",
                "stage" = EXCLUDED."stage",
                "progress" = EXCLUDED."progress",
                "retryCount" = EXCLUDED."retryCount",
                "errorCode" = EXCLUDED."errorCode",
                "errorMessage" = EXCLUDED."errorMessage",
                "metadata" = EXCLUDED."metadata",
                "updatedAt" = EXCLUDED."updatedAt"
            """,
            rows,
        )


def _write_chunks(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.rag_knowledge_chunks (
                "chunkId", "docId", "version", "tenantId", "namespace",
                "chunkIndex", "content", "embeddingModel", "embedding",
                "sourcePath", "parsedPath", "charStart", "charEnd", "pageNo",
                "ownerId", "visibility", "classification", "departmentIds", "roleIds",
                "metadata", "createdAt", "updatedAt"
            ) VALUES (
                %(chunk_id)s, %(doc_id)s, %(version)s, %(tenant_id)s, %(namespace)s,
                %(chunk_index)s, %(content)s, %(embedding_model)s, %(embedding)s::vector,
                %(source_path)s, %(parsed_path)s, %(char_start)s, %(char_end)s, %(page_no)s,
                %(owner_id)s, %(visibility)s, %(classification)s, %(department_ids)s, %(role_ids)s,
                %(metadata)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT ("chunkId") DO UPDATE SET
                "docId" = EXCLUDED."docId",
                "version" = EXCLUDED."version",
                "tenantId" = EXCLUDED."tenantId",
                "namespace" = EXCLUDED."namespace",
                "chunkIndex" = EXCLUDED."chunkIndex",
                "content" = EXCLUDED."content",
                "embeddingModel" = EXCLUDED."embeddingModel",
                "embedding" = EXCLUDED."embedding",
                "sourcePath" = EXCLUDED."sourcePath",
                "parsedPath" = EXCLUDED."parsedPath",
                "charStart" = EXCLUDED."charStart",
                "charEnd" = EXCLUDED."charEnd",
                "pageNo" = EXCLUDED."pageNo",
                "ownerId" = EXCLUDED."ownerId",
                "visibility" = EXCLUDED."visibility",
                "classification" = EXCLUDED."classification",
                "departmentIds" = EXCLUDED."departmentIds",
                "roleIds" = EXCLUDED."roleIds",
                "metadata" = EXCLUDED."metadata",
                "updatedAt" = EXCLUDED."updatedAt"
            """,
            rows,
        )


def main() -> int:
    args = parse_args()
    settings = Settings()

    dsn = (args.dsn or "").strip() or get_postgres_metadata_dsn(settings)
    normalized_dsn = dsn
    mapped_schema: str | None = None
    if dsn:
        normalized_dsn, mapped_schema = _normalize_postgres_dsn_for_psycopg(dsn)
        if mapped_schema:
            print(f"[info] mapped Prisma-style schema={mapped_schema} to libpq options(search_path)")
    qdrant_url = (args.qdrant_url or "").strip() or settings.qdrant_url
    qdrant_collection = (args.qdrant_collection or "").strip() or settings.qdrant_collection
    embedding_model = (args.embedding_model or "").strip() or settings.embedding_model

    document_dir = Path(args.document_dir)
    job_dir = Path(args.job_dir)
    chunk_dir = Path(args.chunk_dir)
    parsed_dir = Path(args.parsed_dir)

    document_records, document_failures = load_document_records(document_dir)
    job_records, job_failures = load_job_records(job_dir)
    chunk_file_records, chunk_count_by_doc, chunk_files_scanned, chunk_file_warnings = _load_chunk_file_records(chunk_dir)

    qdrant_chunk_records, qdrant_vector_count_by_doc, qdrant_doc_hints, qdrant_warnings, qdrant_point_count = (
        _load_qdrant_chunk_records(
            qdrant_url=qdrant_url,
            qdrant_collection=qdrant_collection,
            batch_size=max(1, args.batch_size),
        )
    )

    all_warnings: list[str] = []
    all_warnings.extend(f"document parse failure: {item.path}: {item.reason}" for item in document_failures)
    all_warnings.extend(f"job parse failure: {item.path}: {item.reason}" for item in job_failures)
    all_warnings.extend(chunk_file_warnings)
    all_warnings.extend(qdrant_warnings)

    scan_summary = ScanSummary(
        document_valid=len(document_records),
        document_invalid=len(document_failures),
        job_valid=len(job_records),
        job_invalid=len(job_failures),
        chunk_files=chunk_files_scanned,
        chunk_file_records=len(chunk_file_records),
        qdrant_points=qdrant_point_count,
    )

    docs, versions, jobs, chunks, build_summary, prepare_warnings = _prepare_import_rows(
        document_records=document_records,
        job_records=job_records,
        chunk_file_records=chunk_file_records,
        chunk_count_by_doc=chunk_count_by_doc,
        qdrant_chunk_records=qdrant_chunk_records,
        qdrant_vector_count_by_doc=qdrant_vector_count_by_doc,
        qdrant_doc_hints=qdrant_doc_hints,
        missing_doc_strategy=args.missing_doc_strategy,
        default_tenant_id=args.default_tenant_id,
        namespace=args.namespace,
        embedding_model=embedding_model,
        parsed_dir=parsed_dir,
        chunk_dir=chunk_dir,
        vector_dim=max(0, args.vector_dim),
    )
    all_warnings.extend(prepare_warnings)

    print(
        "[scan] "
        f"documents={scan_summary.document_valid} valid/{scan_summary.document_invalid} invalid, "
        f"jobs={scan_summary.job_valid} valid/{scan_summary.job_invalid} invalid, "
        f"chunk_files={scan_summary.chunk_files}, chunk_records={scan_summary.chunk_file_records}, "
        f"qdrant_points={scan_summary.qdrant_points}"
    )
    print(
        "[build] "
        f"docs={len(docs)}, versions={len(versions)}, jobs={len(jobs)}, chunks={len(chunks)}, "
        f"placeholder_docs={build_summary.placeholder_documents_created}, "
        f"skipped_jobs={build_summary.skipped_jobs}, skipped_chunks={build_summary.skipped_chunks}, "
        f"chunks_without_embedding={build_summary.chunks_without_embedding}"
    )

    if args.dry_run:
        print("[done] mode=dry-run (no PostgreSQL write)")
        if all_warnings:
            print(f"[warn] total={len(all_warnings)} (showing first 50)")
            for message in all_warnings[:50]:
                print(f"[warn] {message}")
        return 0 if not document_failures and not job_failures else 1

    if not dsn:
        print("ERROR: PostgreSQL DSN is empty. Set --dsn or env RAG_POSTGRES_METADATA_DSN / DATABASE_URL.")
        return 2

    with psycopg.connect(normalized_dsn) as conn:
        _ensure_required_tables(conn)
        _write_documents(conn, docs)
        _write_versions(conn, versions)
        _write_jobs(conn, jobs)
        _write_chunks(conn, chunks)

    print(
        "[done] mode=write "
        f"documents={len(docs)}, versions={len(versions)}, jobs={len(jobs)}, chunks={len(chunks)}"
    )

    if all_warnings:
        print(f"[warn] total={len(all_warnings)} (showing first 50)")
        for message in all_warnings[:50]:
            print(f"[warn] {message}")

    if document_failures or job_failures:
        print("ERROR: Some metadata JSON files are invalid. Fix them and rerun.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
