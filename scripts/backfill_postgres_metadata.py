#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings, get_postgres_metadata_dsn
from backend.app.db.postgres_metadata_store import PostgresMetadataStore
from backend.app.tools.postgres_metadata_backfill import backfill_records, load_document_records, load_job_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill local document/job metadata JSON files into PostgreSQL.")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Fallback: RAG_POSTGRES_METADATA_DSN -> DATABASE_URL.")
    parser.add_argument("--document-dir", default="data/documents", help="Directory for document metadata JSON files.")
    parser.add_argument("--job-dir", default="data/jobs", help="Directory for ingest job metadata JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Only parse and count records; do not write into PostgreSQL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings()
    dsn = (args.dsn or "").strip() or get_postgres_metadata_dsn(settings)
    if not dsn:
        print("ERROR: PostgreSQL DSN is empty. Set --dsn or env RAG_POSTGRES_METADATA_DSN / DATABASE_URL.")
        return 2

    document_dir = Path(args.document_dir)
    job_dir = Path(args.job_dir)
    document_records, document_failures = load_document_records(document_dir)
    job_records, job_failures = load_job_records(job_dir)

    print(f"[scan] documents: {len(document_records)} valid, {len(document_failures)} invalid, dir={document_dir}")
    print(f"[scan] jobs: {len(job_records)} valid, {len(job_failures)} invalid, dir={job_dir}")
    for failure in document_failures:
        print(f"[warn] {failure.path}: {failure.reason}")
    for failure in job_failures:
        print(f"[warn] {failure.path}: {failure.reason}")

    store = PostgresMetadataStore(dsn)
    store.ping()
    store.ensure_required_tables()
    report = backfill_records(
        store,
        document_records=document_records,
        job_records=job_records,
        dry_run=args.dry_run,
    )
    mode = "dry-run" if report.dry_run else "write"
    print(
        "[done] "
        f"mode={mode}, documents={report.document_saved}/{report.document_total}, "
        f"jobs={report.job_saved}/{report.job_total}"
    )

    if document_failures or job_failures:
        print("ERROR: Some JSON metadata files are invalid. Fix them and rerun.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
