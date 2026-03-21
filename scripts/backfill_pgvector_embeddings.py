#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings, get_postgres_metadata_dsn
from backend.app.tools.pgvector_backfill import (
    backfill_pgvector,
    ensure_pgvector_ann_index,
    ensure_pgvector_target_table,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill rag_knowledge_chunks.embedding from Qdrant and/or re-embedding."
    )
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Fallback: RAG_POSTGRES_METADATA_DSN -> DATABASE_URL.")
    parser.add_argument(
        "--mode",
        choices=("qdrant", "reembed", "hybrid"),
        default="hybrid",
        help="qdrant=direct copy vectors from Qdrant, reembed=recompute embeddings, hybrid=Qdrant first then reembed missing.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing pgvector values. Default only fills rows where embedding IS NULL.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build the migration plan only; do not write into PostgreSQL.")
    parser.add_argument("--vector-dim", type=int, default=1024, help="Expected vector dimension. Set 0 to disable validation.")
    parser.add_argument("--qdrant-url", default="", help="Override Qdrant URL. Fallback: RAG_QDRANT_URL.")
    parser.add_argument("--qdrant-collection", default="", help="Override Qdrant collection. Fallback: RAG_QDRANT_COLLECTION.")
    parser.add_argument("--qdrant-batch-size", type=int, default=256, help="Qdrant scroll batch size.")
    parser.add_argument("--embedding-provider", default="", help="Override embedding provider. Fallback: .env")
    parser.add_argument("--embedding-base-url", default="", help="Override embedding base URL. Fallback: .env")
    parser.add_argument("--embedding-model", default="", help="Override embedding model name. Fallback: .env")
    parser.add_argument("--embedding-api-key", default="", help="Override embedding API key. Fallback: .env")
    parser.add_argument("--embedding-batch-size", type=int, default=0, help="Override embedding batch size. Fallback: .env")
    parser.add_argument(
        "--allow-qdrant-fallback",
        action="store_true",
        help="Allow hybrid mode to continue with re-embedding when Qdrant copy fails. Default: fail-fast.",
    )
    parser.add_argument(
        "--ann-method",
        choices=("none", "auto", "hnsw", "ivfflat"),
        default="auto",
        help="Create pgvector ANN index before backfill. Default auto (prefer hnsw, fallback ivfflat).",
    )
    parser.add_argument("--ivfflat-lists", type=int, default=100, help="ivfflat lists parameter when ann-method uses ivfflat.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings()

    overrides: dict[str, object] = {}
    if args.qdrant_url.strip():
        overrides["qdrant_url"] = args.qdrant_url.strip()
    if args.qdrant_collection.strip():
        overrides["qdrant_collection"] = args.qdrant_collection.strip()
    if args.embedding_provider.strip():
        overrides["embedding_provider"] = args.embedding_provider.strip()
    if args.embedding_base_url.strip():
        overrides["embedding_base_url"] = args.embedding_base_url.strip()
    if args.embedding_model.strip():
        overrides["embedding_model"] = args.embedding_model.strip()
    if args.embedding_api_key.strip():
        overrides["embedding_api_key"] = args.embedding_api_key
    if args.embedding_batch_size > 0:
        overrides["embedding_batch_size"] = args.embedding_batch_size
    if overrides:
        settings = settings.model_copy(update=overrides)

    dsn = (args.dsn or "").strip() or get_postgres_metadata_dsn(settings)
    if not dsn:
        print("ERROR: PostgreSQL DSN is empty. Set --dsn or env RAG_POSTGRES_METADATA_DSN / DATABASE_URL.")
        return 2

    ensure_pgvector_target_table(dsn)
    ann_method = None
    if not args.dry_run:
        ann_method = ensure_pgvector_ann_index(dsn, method=args.ann_method, ivfflat_lists=args.ivfflat_lists)
    report = backfill_pgvector(
        dsn=dsn,
        settings=settings,
        mode=args.mode,
        only_missing=not args.overwrite,
        vector_dim=max(0, args.vector_dim),
        qdrant_batch_size=max(1, args.qdrant_batch_size),
        allow_qdrant_fallback=args.allow_qdrant_fallback,
        dry_run=args.dry_run,
    )
    report.ann_index_method = ann_method

    print(
        "[done] "
        f"mode={report.mode} "
        f"ann_index={report.ann_index_method or 'none'} "
        f"dry_run={str(report.dry_run).lower()} "
        f"only_missing={str(report.only_missing).lower()} "
        f"target_chunks={report.target_chunks} "
        f"qdrant_points_scanned={report.qdrant_points_scanned} "
        f"qdrant_matches={report.qdrant_matches} "
        f"qdrant_written={report.qdrant_written} "
        f"reembed_candidates={report.reembed_candidates} "
        f"reembedded={report.reembedded} "
        f"skipped_empty_content={report.skipped_empty_content} "
        f"skipped_vector_dim={report.skipped_vector_dim} "
        f"version_counts_synced={report.version_counts_synced} "
        f"remaining_without_embedding={report.remaining_without_embedding}"
    )
    if report.warnings:
        print(f"[warn] total={len(report.warnings)}")
        for message in report.warnings[:50]:
            print(f"[warn] {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
