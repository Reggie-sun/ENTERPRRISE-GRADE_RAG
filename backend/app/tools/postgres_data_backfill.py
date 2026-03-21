from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator

import psycopg
from psycopg.types.json import Jsonb

from ..db.postgres_metadata_store import PostgresMetadataStore
from ..schemas.document import DocumentRecord, IngestJobRecord
from .postgres_metadata_backfill import ParseFailure, load_document_records, load_job_records


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".log", ".csv", ".yaml", ".yml"}
DEFAULT_ROW_BATCH_SIZE = 500
DEFAULT_ASSET_BATCH_SIZE = 32


@dataclass(slots=True)
class DataBackfillReport:
    document_total: int
    document_saved: int
    job_total: int
    job_saved: int
    version_total: int
    version_saved: int
    chunk_total: int
    chunk_saved: int
    asset_total: int
    asset_saved: int
    dry_run: bool


@dataclass(slots=True)
class AssetRow:
    asset_key: str
    doc_id: str | None
    job_id: str | None
    kind: str
    relative_path: str
    file_name: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    text_content: str | None
    binary_content: bytes | None
    metadata: dict[str, object]


def load_all_data_records(
    data_dir: Path,
) -> tuple[list[DocumentRecord], list[IngestJobRecord], list[ParseFailure]]:
    document_records, document_failures = load_document_records(data_dir / "documents")
    job_records, job_failures = load_job_records(data_dir / "jobs")
    return document_records, job_records, [*document_failures, *job_failures]


def backfill_all_data(
    *,
    store: PostgresMetadataStore,
    data_dir: Path,
    dry_run: bool,
    row_batch_size: int = DEFAULT_ROW_BATCH_SIZE,
    asset_batch_size: int = DEFAULT_ASSET_BATCH_SIZE,
    asset_store_binary_enabled: bool = True,
    asset_binary_max_bytes: int = 1 * 1024 * 1024,
) -> DataBackfillReport:
    document_records, job_records, failures = load_all_data_records(data_dir)
    if failures:
        raise RuntimeError(f"Invalid metadata JSON detected: {failures[0].path} -> {failures[0].reason}")

    documents_by_id = {record.doc_id: record for record in document_records}
    jobs_by_id = {record.job_id: record for record in job_records}

    version_rows = build_document_version_rows(data_dir, document_records)
    chunk_rows = build_chunk_rows(data_dir, documents_by_id)
    normalized_row_batch_size = max(1, row_batch_size)
    normalized_asset_batch_size = max(1, asset_batch_size)
    normalized_asset_binary_max_bytes = max(0, asset_binary_max_bytes)

    if dry_run:
        asset_total = sum(
            1
            for _ in iter_asset_rows(
                data_dir,
                documents_by_id,
                jobs_by_id,
                store_binary_enabled=asset_store_binary_enabled,
                binary_max_bytes=normalized_asset_binary_max_bytes,
            )
        )
        return DataBackfillReport(
            document_total=len(document_records),
            document_saved=0,
            job_total=len(job_records),
            job_saved=0,
            version_total=len(version_rows),
            version_saved=0,
            chunk_total=len(chunk_rows),
            chunk_saved=0,
            asset_total=asset_total,
            asset_saved=0,
            dry_run=True,
        )

    for record in document_records:
        store.save_document(record)
    for record in job_records:
        store.save_job(record)

    version_saved = _upsert_versions(store.psycopg_dsn, version_rows, batch_size=normalized_row_batch_size)
    chunk_saved = _upsert_chunks(store.psycopg_dsn, chunk_rows, batch_size=normalized_row_batch_size)
    asset_total, asset_saved = _upsert_assets(
        store.psycopg_dsn,
        iter_asset_rows(
            data_dir,
            documents_by_id,
            jobs_by_id,
            store_binary_enabled=asset_store_binary_enabled,
            binary_max_bytes=normalized_asset_binary_max_bytes,
        ),
        batch_size=normalized_asset_batch_size,
    )

    return DataBackfillReport(
        document_total=len(document_records),
        document_saved=len(document_records),
        job_total=len(job_records),
        job_saved=len(job_records),
        version_total=len(version_rows),
        version_saved=version_saved,
        chunk_total=len(chunk_rows),
        chunk_saved=chunk_saved,
        asset_total=asset_total,
        asset_saved=asset_saved,
        dry_run=False,
    )


def build_document_version_rows(data_dir: Path, document_records: list[DocumentRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in document_records:
        parsed_path = data_dir / "parsed" / f"{record.doc_id}.txt"
        chunk_path = data_dir / "chunks" / f"{record.doc_id}.json"
        chunk_count = _count_chunk_file(chunk_path)
        rows.append(
            {
                "id": PostgresMetadataStore._stable_uuid("rag-document-version", f"{record.doc_id}:v{record.current_version}"),
                "doc_id": record.doc_id,
                "version": record.current_version,
                "storage_path": record.storage_path,
                "parsed_path": str(parsed_path) if parsed_path.exists() else None,
                "chunk_path": str(chunk_path) if chunk_path.exists() else None,
                "chunk_count": chunk_count,
                "vector_count": 0,
                "index_version": None,
                "is_current": True,
                "status": record.status,
                "metadata": {
                    "source_type": record.source_type,
                    "file_name": record.file_name,
                },
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )
    return rows


def build_chunk_rows(data_dir: Path, documents_by_id: dict[str, DocumentRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((data_dir / "chunks").glob("*.json")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("document_id") or "")
            record = documents_by_id.get(doc_id)
            if record is None:
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            rows.append(
                {
                    "id": PostgresMetadataStore._stable_uuid("rag-knowledge-chunk", chunk_id),
                    "chunk_id": chunk_id,
                    "doc_id": record.doc_id,
                    "version": record.current_version,
                    "tenant_id": record.tenant_id,
                    "namespace": "default",
                    "chunk_index": int(item.get("chunk_index") or 0),
                    "content": str(item.get("text") or ""),
                    "embedding_model": "BAAI/bge-m3",
                    "source_path": record.storage_path,
                    "parsed_path": str(data_dir / "parsed" / f"{record.doc_id}.txt") if (data_dir / "parsed" / f"{record.doc_id}.txt").exists() else None,
                    "char_start": item.get("char_start"),
                    "char_end": item.get("char_end"),
                    "page_no": item.get("page_no"),
                    "owner_id": record.owner_id,
                    "visibility": record.visibility,
                    "classification": record.classification,
                    "department_ids": record.department_ids,
                    "role_ids": record.role_ids,
                    "metadata": {
                        key: value
                        for key, value in item.items()
                        if key not in {"chunk_id", "document_id", "chunk_index", "text", "char_start", "char_end", "page_no"}
                    },
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
            )
    return rows


def iter_asset_rows(
    data_dir: Path,
    documents_by_id: dict[str, DocumentRecord],
    jobs_by_id: dict[str, IngestJobRecord],
    *,
    store_binary_enabled: bool = True,
    binary_max_bytes: int = 1 * 1024 * 1024,
) -> Iterator[AssetRow]:
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative_path = path.relative_to(data_dir).as_posix()
        size_bytes = path.stat().st_size
        sha256 = _hash_file(path)
        kind, doc_id, job_id = _classify_asset(path, documents_by_id, jobs_by_id)
        mime_type = mimetypes.guess_type(path.name)[0]
        max_bytes = max(0, binary_max_bytes)
        should_store_binary = store_binary_enabled and size_bytes <= max_bytes
        should_store_text = size_bytes <= max_bytes

        # 只在需要时读取文件内容，避免大文件整块进入内存。
        content: bytes | None = None
        if should_store_binary or should_store_text:
            content = path.read_bytes()

        text_content = _decode_text_content(path, content) if should_store_text and content is not None else None
        binary_skip_reason: str | None = None
        if not should_store_binary:
            binary_skip_reason = "disabled" if not store_binary_enabled else "size_limit"
        text_skip_reason: str | None = None
        if not should_store_text:
            text_skip_reason = "size_limit"
        yield AssetRow(
            asset_key=relative_path,
            doc_id=doc_id,
            job_id=job_id,
            kind=kind,
            relative_path=relative_path,
            file_name=path.name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            text_content=text_content,
            binary_content=content if should_store_binary else None,
            metadata={
                "top_dir": relative_path.split("/", 1)[0] if "/" in relative_path else relative_path,
                "suffix": path.suffix.lower(),
                "binary_stored": should_store_binary,
                "binary_skip_reason": binary_skip_reason,
                "text_stored": should_store_text and text_content is not None,
                "text_skip_reason": text_skip_reason,
            },
        )


def build_asset_rows(
    data_dir: Path,
    documents_by_id: dict[str, DocumentRecord],
    jobs_by_id: dict[str, IngestJobRecord],
    *,
    store_binary_enabled: bool = True,
    binary_max_bytes: int = 1 * 1024 * 1024,
) -> list[AssetRow]:
    return list(
        iter_asset_rows(
            data_dir,
            documents_by_id,
            jobs_by_id,
            store_binary_enabled=store_binary_enabled,
            binary_max_bytes=binary_max_bytes,
        )
    )


def _count_chunk_file(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _decode_text_content(path: Path, content: bytes) -> str | None:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        if path.parent.name not in {"parsed", "chunks", "documents", "jobs"}:
            return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _with_jsonb(row: dict[str, object], *keys: str) -> dict[str, object]:
    normalized = dict(row)
    for key in keys:
        value = normalized.get(key)
        if value is not None:
            normalized[key] = Jsonb(value)
    return normalized


def _upsert_versions(psycopg_dsn: str, rows: list[dict[str, object]], *, batch_size: int) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO public.rag_document_versions (
            "id", "docId", "version", "storagePath", "parsedPath", "chunkPath",
            "chunkCount", "vectorCount", "indexVersion", "isCurrent", "status",
            "metadata", "createdAt", "updatedAt"
        ) VALUES (
            %(id)s, %(doc_id)s, %(version)s, %(storage_path)s, %(parsed_path)s, %(chunk_path)s,
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
    """
    saved = 0
    for batch in _iter_batches(rows, batch_size):
        prepared = [_with_jsonb(row, "metadata") for row in batch]
        with psycopg.connect(psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, prepared)
            conn.commit()
        saved += len(batch)
    return saved


def _upsert_chunks(psycopg_dsn: str, rows: list[dict[str, object]], *, batch_size: int) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO public.rag_knowledge_chunks (
            "id", "chunkId", "docId", "version", "tenantId", "namespace", "chunkIndex",
            "content", "embeddingModel", "embedding", "sourcePath", "parsedPath", "charStart",
            "charEnd", "pageNo", "ownerId", "visibility", "classification",
            "departmentIds", "roleIds", "metadata", "createdAt", "updatedAt"
        ) VALUES (
            %(id)s, %(chunk_id)s, %(doc_id)s, %(version)s, %(tenant_id)s, %(namespace)s, %(chunk_index)s,
            %(content)s, %(embedding_model)s, NULL, %(source_path)s, %(parsed_path)s, %(char_start)s,
            %(char_end)s, %(page_no)s, %(owner_id)s, %(visibility)s, %(classification)s,
            %(department_ids)s, %(role_ids)s, %(metadata)s, %(created_at)s, %(updated_at)s
        )
        ON CONFLICT ("chunkId") DO UPDATE SET
            "docId" = EXCLUDED."docId",
            "version" = EXCLUDED."version",
            "tenantId" = EXCLUDED."tenantId",
            "namespace" = EXCLUDED."namespace",
            "chunkIndex" = EXCLUDED."chunkIndex",
            "content" = EXCLUDED."content",
            "embeddingModel" = EXCLUDED."embeddingModel",
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
    """
    saved = 0
    for batch in _iter_batches(rows, batch_size):
        prepared = [_with_jsonb(row, "metadata") for row in batch]
        with psycopg.connect(psycopg_dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, prepared)
            conn.commit()
        saved += len(batch)
    return saved


def _upsert_assets(psycopg_dsn: str, asset_rows: Iterable[AssetRow], *, batch_size: int) -> tuple[int, int]:
    sql = """
        INSERT INTO public.rag_data_assets (
            "id", "assetKey", "docId", "jobId", "kind", "relativePath", "fileName", "mimeType",
            "sizeBytes", "sha256", "textContent", "binaryContent", "metadata", "createdAt", "updatedAt"
        ) VALUES (
            %(id)s, %(asset_key)s, %(doc_id)s, %(job_id)s, %(kind)s, %(relative_path)s, %(file_name)s, %(mime_type)s,
            %(size_bytes)s, %(sha256)s, %(text_content)s, %(binary_content)s, %(metadata)s, NOW(), NOW()
        )
        ON CONFLICT ("assetKey") DO UPDATE SET
            "docId" = EXCLUDED."docId",
            "jobId" = EXCLUDED."jobId",
            "kind" = EXCLUDED."kind",
            "relativePath" = EXCLUDED."relativePath",
            "fileName" = EXCLUDED."fileName",
            "mimeType" = EXCLUDED."mimeType",
            "sizeBytes" = EXCLUDED."sizeBytes",
            "sha256" = EXCLUDED."sha256",
            "textContent" = EXCLUDED."textContent",
            "binaryContent" = EXCLUDED."binaryContent",
            "metadata" = EXCLUDED."metadata",
            "updatedAt" = NOW()
    """

    total = 0
    saved = 0
    buffer: list[AssetRow] = []

    for row in asset_rows:
        total += 1
        buffer.append(row)
        if len(buffer) >= batch_size:
            _flush_asset_batch(psycopg_dsn, sql, buffer)
            saved += len(buffer)
            buffer.clear()

    if buffer:
        _flush_asset_batch(psycopg_dsn, sql, buffer)
        saved += len(buffer)

    return total, saved


def _flush_asset_batch(psycopg_dsn: str, sql: str, batch: list[AssetRow]) -> None:
    prepared = [
        _with_jsonb(
            {
                "id": PostgresMetadataStore._stable_uuid("rag-data-asset", row.asset_key),
                "asset_key": row.asset_key,
                "doc_id": row.doc_id,
                "job_id": row.job_id,
                "kind": row.kind,
                "relative_path": row.relative_path,
                "file_name": row.file_name,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "text_content": row.text_content,
                "binary_content": row.binary_content,
                "metadata": row.metadata,
            },
            "metadata",
        )
        for row in batch
    ]

    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, prepared)
        conn.commit()


def _iter_batches(rows: list[dict[str, object]], batch_size: int) -> Iterator[list[dict[str, object]]]:
    iterator = iter(rows)
    while True:
        batch = list(islice(iterator, max(1, batch_size)))
        if not batch:
            break
        yield batch


def _classify_asset(
    path: Path,
    documents_by_id: dict[str, DocumentRecord],
    jobs_by_id: dict[str, IngestJobRecord],
) -> tuple[str, str | None, str | None]:
    top_dir = path.parent.name
    stem = path.stem
    if top_dir == "documents":
        doc_id = _extract_doc_id_from_json(path)
        return "document_json", doc_id if doc_id in documents_by_id else None, None
    if top_dir == "jobs":
        job_id, doc_id = _extract_job_and_doc_id_from_json(path)
        valid_job_id = job_id if job_id in jobs_by_id else None
        valid_doc_id = doc_id if doc_id in documents_by_id else None
        return "job_json", valid_doc_id, valid_job_id
    if top_dir == "parsed":
        return "parsed_text", stem if stem in documents_by_id else None, None
    if top_dir == "chunks":
        doc_id = _extract_doc_id_from_chunk_file(path)
        return "chunk_json", doc_id if doc_id in documents_by_id else None, None
    if top_dir == "uploads":
        doc_id = None
        if "__" in path.name:
            maybe_doc_id = path.name.split("__", 1)[0]
            if maybe_doc_id in documents_by_id:
                doc_id = maybe_doc_id
        return "upload_file", doc_id, None
    return "file", None, None


def _extract_doc_id_from_json(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        value = payload.get("doc_id")
        return str(value) if value else None
    return None


def _extract_job_and_doc_id_from_json(path: Path) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    if isinstance(payload, dict):
        job_id = payload.get("job_id")
        doc_id = payload.get("doc_id")
        return (str(job_id) if job_id else None, str(doc_id) if doc_id else None)
    return None, None


def _extract_doc_id_from_chunk_file(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        value = payload[0].get("document_id")
        return str(value) if value else None
    return None
