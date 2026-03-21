from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..db.postgres_metadata_store import PostgresMetadataStore
from ..schemas.document import DocumentRecord, IngestJobRecord


@dataclass(slots=True)
class ParseFailure:
    path: Path
    reason: str


@dataclass(slots=True)
class BackfillReport:
    document_total: int
    document_saved: int
    job_total: int
    job_saved: int
    dry_run: bool


def load_document_records(document_dir: Path) -> tuple[list[DocumentRecord], list[ParseFailure]]:
    return _load_records(document_dir, DocumentRecord, "document")


def load_job_records(job_dir: Path) -> tuple[list[IngestJobRecord], list[ParseFailure]]:
    return _load_records(job_dir, IngestJobRecord, "job")


def backfill_records(
    store: PostgresMetadataStore,
    document_records: list[DocumentRecord],
    job_records: list[IngestJobRecord],
    *,
    dry_run: bool,
) -> BackfillReport:
    if dry_run:
        return BackfillReport(
            document_total=len(document_records),
            document_saved=0,
            job_total=len(job_records),
            job_saved=0,
            dry_run=True,
        )

    document_saved = 0
    for record in document_records:
        store.save_document(record)
        document_saved += 1

    job_saved = 0
    for record in job_records:
        store.save_job(record)
        job_saved += 1

    return BackfillReport(
        document_total=len(document_records),
        document_saved=document_saved,
        job_total=len(job_records),
        job_saved=job_saved,
        dry_run=False,
    )


def _load_records(
    source_dir: Path,
    model_cls: type[DocumentRecord] | type[IngestJobRecord],
    label: str,
) -> tuple[list[DocumentRecord] | list[IngestJobRecord], list[ParseFailure]]:
    records: list[DocumentRecord] | list[IngestJobRecord] = []
    failures: list[ParseFailure] = []
    if not source_dir.exists():
        return records, failures

    for path in sorted(source_dir.glob("*.json")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            records.append(model_cls.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - 运维回填脚本需要完整收集坏文件，不中断全流程。
            failures.append(ParseFailure(path=path, reason=f"Invalid {label} json: {exc}"))
    return records, failures

