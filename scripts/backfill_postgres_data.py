#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings, get_postgres_metadata_dsn
from backend.app.db.postgres_metadata_store import PostgresMetadataStore
from backend.app.tools.postgres_data_backfill import backfill_all_data, load_all_data_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill the whole data/ directory into PostgreSQL.")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Fallback: RAG_POSTGRES_METADATA_DSN -> DATABASE_URL.")
    parser.add_argument("--data-dir", default="data", help="Project data directory to import.")
    parser.add_argument("--row-batch-size", type=int, default=500, help="Batch size for version/chunk upsert.")
    parser.add_argument("--asset-batch-size", type=int, default=32, help="Batch size for data asset upsert.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and count only; do not write into PostgreSQL.")
    return parser.parse_args()


def ensure_data_tables_exist(store: PostgresMetadataStore) -> None:
    required_tables = (
        "rag_source_documents",
        "rag_ingest_jobs",
        "rag_document_versions",
        "rag_knowledge_chunks",
        "rag_data_assets",
    )
    missing: list[str] = []
    with psycopg.connect(store.psycopg_dsn) as conn:
        with conn.cursor() as cur:
            for table in required_tables:
                cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                row = cur.fetchone()
                if row is None or row[0] is None:
                    missing.append(table)
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"PostgreSQL tables are missing: {joined}. "
            "Run `npx prisma@6.19.0 db push --schema prisma/schema.prisma` first."
        )


def main() -> int:
    args = parse_args()
    settings = Settings()
    dsn = (args.dsn or "").strip() or get_postgres_metadata_dsn(settings)
    if not dsn:
        print("ERROR: PostgreSQL DSN is empty. Set --dsn or env RAG_POSTGRES_METADATA_DSN / DATABASE_URL.")
        return 2

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: data directory not found: {data_dir}")
        return 2

    document_records, job_records, failures = load_all_data_records(data_dir)
    print(f"[scan] documents={len(document_records)} jobs={len(job_records)} failures={len(failures)} data_dir={data_dir}")
    for failure in failures:
        print(f"[warn] {failure.path}: {failure.reason}")

    store = PostgresMetadataStore(dsn)
    store.ping()
    ensure_data_tables_exist(store)

    report = backfill_all_data(
        store=store,
        data_dir=data_dir,
        dry_run=args.dry_run,
        row_batch_size=max(1, args.row_batch_size),
        asset_batch_size=max(1, args.asset_batch_size),
        asset_store_binary_enabled=settings.data_asset_store_binary_enabled,
        asset_binary_max_bytes=max(0, settings.data_asset_binary_max_bytes),
    )
    mode = "dry-run" if report.dry_run else "write"
    print(
        "[done] "
        f"mode={mode} "
        f"documents={report.document_saved}/{report.document_total} "
        f"jobs={report.job_saved}/{report.job_total} "
        f"versions={report.version_saved}/{report.version_total} "
        f"chunks={report.chunk_saved}/{report.chunk_total} "
        f"assets={report.asset_saved}/{report.asset_total}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
