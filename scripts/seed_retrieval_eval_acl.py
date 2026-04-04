#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings, get_postgres_metadata_dsn
from backend.app.db.postgres_metadata_store import PostgresMetadataStore
from backend.app.schemas.document import DocumentRecord

DEFAULT_SEED_PATH = PROJECT_ROOT / "eval" / "retrieval_document_acl_seed.yaml"
DEFAULT_DOCUMENT_DIR = PROJECT_ROOT / "data" / "documents"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed retrieval-eval ACL metadata so department-scoped supplemental evaluation becomes calibratable."
    )
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH, help="Path to retrieval eval ACL seed YAML.")
    parser.add_argument("--document-dir", type=Path, default=DEFAULT_DOCUMENT_DIR, help="Local document metadata directory.")
    parser.add_argument("--upload-dir", type=Path, default=DEFAULT_UPLOAD_DIR, help="Upload asset directory for local JSON stub creation.")
    parser.add_argument("--tenant-id", default="wl", help="Tenant ID used when creating local JSON stubs.")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN. Fallback: RAG_POSTGRES_METADATA_DSN -> DATABASE_URL.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not write changes.")
    parser.add_argument("--apply-local-json", action="store_true", help="Apply ACL seed to data/documents/*.json records.")
    parser.add_argument(
        "--create-missing-local-json",
        action="store_true",
        help="When applying local JSON, create missing DocumentRecord JSON from upload assets if needed.",
    )
    parser.add_argument("--apply-postgres", action="store_true", help="Apply ACL seed to PostgreSQL metadata store.")
    return parser.parse_args()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        item = (value or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def load_acl_seed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"ACL seed file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_documents = data.get("documents") or []
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError(f"ACL seed must contain a non-empty 'documents' list: {path}")

    seeds: dict[str, dict[str, Any]] = {}
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise ValueError("Each ACL seed entry must be a mapping")
        doc_id = str(raw.get("doc_id") or "").strip()
        department_id = str(raw.get("department_id") or "").strip()
        visibility = str(raw.get("visibility") or "private").strip()
        retrieval_department_ids = _dedupe(raw.get("retrieval_department_ids") or [])
        if not doc_id or not department_id:
            raise ValueError(f"ACL seed entry must include non-empty doc_id and department_id: {raw!r}")
        seeds[doc_id] = {
            "doc_id": doc_id,
            "department_id": department_id,
            "department_ids": [department_id],
            "retrieval_department_ids": retrieval_department_ids,
            "visibility": visibility,
            "file_name_hint": str(raw.get("file_name_hint") or "").strip() or None,
            "note": str(raw.get("note") or "").strip() or None,
        }
    return seeds


def apply_acl_to_record(record: DocumentRecord, seed_entry: dict[str, Any]) -> DocumentRecord:
    updated = record.model_copy(deep=True)
    updated.department_id = seed_entry["department_id"]
    updated.department_ids = _dedupe(seed_entry.get("department_ids") or [seed_entry["department_id"]])
    updated.retrieval_department_ids = _dedupe(seed_entry.get("retrieval_department_ids") or [])
    updated.visibility = seed_entry.get("visibility", updated.visibility)
    updated.updated_at = _now_utc()
    return updated


def _find_upload_path(doc_id: str, upload_dir: Path) -> Path:
    matches = sorted(upload_dir.glob(f"{doc_id}__*"))
    if not matches:
        raise FileNotFoundError(f"Upload asset not found for {doc_id} in {upload_dir}")
    return matches[0]


def build_local_stub_record(
    *,
    doc_id: str,
    seed_entry: dict[str, Any],
    tenant_id: str,
    upload_dir: Path,
) -> DocumentRecord:
    upload_path = _find_upload_path(doc_id, upload_dir)
    file_name = upload_path.name.split("__", 1)[1] if "__" in upload_path.name else upload_path.name
    file_hash = hashlib.sha256(upload_path.read_bytes()).hexdigest()
    timestamp = datetime.fromtimestamp(upload_path.stat().st_mtime, tz=timezone.utc)
    suffix = upload_path.suffix.lower().lstrip(".") or "unknown"
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id=tenant_id,
        file_name=file_name,
        file_hash=file_hash,
        source_type=suffix,
        department_id=seed_entry["department_id"],
        department_ids=_dedupe(seed_entry.get("department_ids") or [seed_entry["department_id"]]),
        retrieval_department_ids=_dedupe(seed_entry.get("retrieval_department_ids") or []),
        role_ids=[],
        owner_id=None,
        visibility=seed_entry.get("visibility", "private"),
        classification="internal",
        tags=["retrieval_eval_acl_seed"],
        source_system="retrieval_eval_acl_seed",
        status="active",
        current_version=1,
        latest_job_id=f"job_eval_acl_seed_{doc_id[-8:]}",
        storage_path=str(upload_path.resolve()),
        uploaded_by="retrieval_eval_acl_seed",
        created_by="retrieval_eval_acl_seed",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _write_local_record(path: Path, record: DocumentRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")


def _load_local_record(path: Path) -> DocumentRecord | None:
    if not path.exists():
        return None
    return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _print_entry(prefix: str, doc_id: str, detail: str) -> None:
    print(f"[{prefix}] {doc_id}: {detail}")


def _apply_local_json(
    *,
    seeds: dict[str, dict[str, Any]],
    document_dir: Path,
    upload_dir: Path,
    tenant_id: str,
    write_changes: bool,
    create_missing_local_json: bool,
) -> tuple[int, int]:
    changed = 0
    missing = 0
    for doc_id, seed_entry in seeds.items():
        path = document_dir / f"{doc_id}.json"
        existing = _load_local_record(path)
        action = "update-local-json"
        if existing is None:
            if not create_missing_local_json:
                missing += 1
                _print_entry("warn", doc_id, f"missing local JSON metadata ({path}); rerun with --create-missing-local-json")
                continue
            existing = build_local_stub_record(
                doc_id=doc_id,
                seed_entry=seed_entry,
                tenant_id=tenant_id,
                upload_dir=upload_dir,
            )
            action = "create-local-json"
        updated = apply_acl_to_record(existing, seed_entry)
        _print_entry(action, doc_id, f"department_id={updated.department_id}, retrieval_department_ids={updated.retrieval_department_ids}")
        if write_changes:
            _write_local_record(path, updated)
        changed += 1
    return changed, missing


def _apply_postgres(
    *,
    seeds: dict[str, dict[str, Any]],
    dsn: str,
    write_changes: bool,
) -> tuple[int, int]:
    store = PostgresMetadataStore(dsn)
    store.ping()
    store.ensure_required_tables()

    changed = 0
    missing = 0
    for doc_id, seed_entry in seeds.items():
        existing = store.load_document(doc_id)
        if existing is None:
            missing += 1
            _print_entry("warn", doc_id, "missing PostgreSQL metadata record; cannot apply ACL seed")
            continue
        updated = apply_acl_to_record(existing, seed_entry)
        _print_entry("update-postgres", doc_id, f"department_id={updated.department_id}, retrieval_department_ids={updated.retrieval_department_ids}")
        if write_changes:
            store.save_document(updated)
        changed += 1
    return changed, missing


def main() -> int:
    args = parse_args()
    seeds = load_acl_seed(args.seed)

    write_changes = (args.apply_local_json or args.apply_postgres) and not args.dry_run
    mode = "write" if write_changes else "dry-run"
    print(f"[mode] {mode}")
    print(f"[seed] loaded {len(seeds)} document ACL entries from {args.seed}")

    local_changed = 0
    local_missing = 0
    postgres_changed = 0
    postgres_missing = 0

    if args.apply_local_json or not (args.apply_local_json or args.apply_postgres):
        local_changed, local_missing = _apply_local_json(
            seeds=seeds,
            document_dir=args.document_dir,
            upload_dir=args.upload_dir,
            tenant_id=args.tenant_id,
            write_changes=write_changes and args.apply_local_json,
            create_missing_local_json=args.create_missing_local_json,
        )

    if args.apply_postgres:
        settings = Settings()
        dsn = (args.dsn or "").strip() or get_postgres_metadata_dsn(settings)
        if not dsn:
            print("ERROR: PostgreSQL DSN is empty. Set --dsn or env RAG_POSTGRES_METADATA_DSN / DATABASE_URL.")
            return 2
        postgres_changed, postgres_missing = _apply_postgres(
            seeds=seeds,
            dsn=dsn,
            write_changes=write_changes,
        )

    print(
        "[summary] "
        f"local_changed={local_changed}, local_missing={local_missing}, "
        f"postgres_changed={postgres_changed}, postgres_missing={postgres_missing}"
    )
    if not args.apply_local_json and not args.apply_postgres:
        print("[note] No apply flags provided; dry-run planned local JSON changes only.")
    if args.dry_run and (args.apply_local_json or args.apply_postgres):
        print("[note] --dry-run active; no metadata was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
