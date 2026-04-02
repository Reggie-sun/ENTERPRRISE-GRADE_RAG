#!/usr/bin/env python3
"""Batch document rebuild orchestration script.

Orchestrates rebuilding vector indexes for multiple documents by calling
the existing POST /api/v1/documents/{doc_id}/rebuild endpoint.

Usage:
    python scripts/rebuild_documents.py --help
    python scripts/rebuild_documents.py --document-list doc_ids.txt
    python scripts/rebuild_documents.py --status
    python scripts/rebuild_documents.py --wait
    python scripts/rebuild_documents.py --dry-run --document-list doc_ids.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = "http://localhost:8020"
DEFAULT_USERNAME = "sys.admin.demo"
DEFAULT_PASSWORD = "sys-admin-demo-pass"
DEFAULT_STATUS_FILE = PROJECT_ROOT / "eval" / "rebuild_status.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch document rebuild orchestration.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="API base URL")
    parser.add_argument("--username", default=os.environ.get("AUTH_USERNAME", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.environ.get("AUTH_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--timeout", type=int, default=30, help="HTTP request timeout")
    parser.add_argument("--poll-interval", type=int, default=5, help="Job status poll interval (seconds)")
    parser.add_argument("--max-poll-attempts", type=int, default=120, help="Max poll attempts before giving up")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS_FILE, help="Status tracking file")
    parser.add_argument("--document-list", type=Path, help="File with one document_id per line")
    parser.add_argument("--doc-ids", nargs="*", help="Document IDs as CLI arguments")
    parser.add_argument("--status", action="store_true", help="Check status of tracked rebuild jobs")
    parser.add_argument("--wait", action="store_true", help="Wait for all in-flight jobs to finish")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    return parser.parse_args()


def login(api_base: str, username: str, password: str, timeout: int) -> str:
    url = f"{api_base}/api/v1/auth/login"
    try:
        resp = requests.post(url, json={"username": username, "password": password}, timeout=timeout)
    except requests.ConnectionError:
        print(f"ERROR: Cannot connect to API at {url}", file=sys.stderr)
        print("  Make sure the backend is running. Try:  make dev-api", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"ERROR: Login failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json().get("access_token")


def load_status(status_file: Path) -> dict:
    if not status_file.exists():
        return {"jobs": [], "created_at": None}
    with open(status_file, encoding="utf-8") as f:
        return json.load(f)


def save_status(status_file: Path, data: dict) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def trigger_rebuild(api_base: str, token: str, doc_id: str, timeout: int) -> dict:
    url = f"{api_base}/api/v1/documents/{doc_id}/rebuild"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(url, headers=headers, timeout=timeout)
    if resp.status_code == 409:
        return {"error": f"Conflict: {resp.json().get('detail', 'unknown')}"}
    if resp.status_code != 202:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    return resp.json()


def check_job_status(api_base: str, token: str, job_id: str, timeout: int) -> dict:
    url = f"{api_base}/api/v1/ingest/jobs/{job_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    return resp.json()


def run_rebuild(args: argparse.Namespace, token: str) -> int:
    # Collect target document IDs
    doc_ids = []
    if args.doc_ids:
        doc_ids.extend(args.doc_ids)
    if args.document_list:
        if not args.document_list.exists():
            print(f"ERROR: Document list file not found: {args.document_list}", file=sys.stderr)
            return 1
        with open(args.document_list, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    doc_ids.append(line)

    if not doc_ids:
        print("ERROR: No document IDs provided. Use --document-list or --doc-ids.", file=sys.stderr)
        return 1

    print(f"Target documents: {len(doc_ids)}")
    if args.dry_run:
        print("DRY RUN — would trigger rebuild for:")
        for doc_id in doc_ids:
            print(f"  POST /api/v1/documents/{doc_id}/rebuild")
        return 0

    status = load_status(args.status_file)
    new_jobs = []

    for i, doc_id in enumerate(doc_ids, 1):
        print(f"[{i}/{len(doc_ids)}] Rebuilding {doc_id}...", end="", flush=True)
        result = trigger_rebuild(args.api_base, token, doc_id, args.timeout)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            status["jobs"].append({
                "doc_id": doc_id,
                "job_id": None,
                "status": "error",
                "error": result["error"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            job_id = result.get("job_id")
            print(f"  job={job_id} removed={result.get('previous_vector_points_removed', 0)}")
            status["jobs"].append({
                "doc_id": doc_id,
                "job_id": job_id,
                "status": "queued",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            new_jobs.append(job_id)
        save_status(args.status_file, status)

    print(f"\nTriggered {len(new_jobs)} rebuild jobs. Status file: {args.status_file}")
    print(f"Check status: python scripts/rebuild_documents.py --status")
    print(f"Wait for completion: python scripts/rebuild_documents.py --wait")
    return 0


def run_status(args: argparse.Namespace, token: str) -> int:
    status = load_status(args.status_file)
    jobs = status.get("jobs", [])
    if not jobs:
        print("No rebuild jobs tracked. Run rebuild first.")
        return 0

    print(f"Tracked rebuild jobs: {len(jobs)}\n")

    by_status: dict[str, list[dict]] = {}
    for job in jobs:
        s = job.get("status", "unknown")
        by_status.setdefault(s, []).append(job)

    terminal = {"completed", "partial_failed", "dead_letter", "error"}
    in_flight = {"queued", "pending", "parsing", "ocr_processing", "chunking", "embedding", "indexing"}

    for status_name in sorted(in_flight | terminal):
        items = by_status.get(status_name, [])
        if not items:
            continue
        print(f"  {status_name}: {len(items)}")
        for item in items:
            job_id = item.get("job_id", "N/A")
            doc_id = item.get("doc_id", "N/A")
            if status_name in in_flight and job_id and job_id != "N/A":
                live = check_job_status(args.api_base, token, job_id, args.timeout)
                live_stage = live.get("stage", "?")
                live_progress = live.get("progress", "?")
                print(f"    {doc_id} → {job_id} [{live_stage}] {live_progress}%")
            elif status_name == "error":
                print(f"    {doc_id} → {item.get('error', 'unknown error')}")
            else:
                print(f"    {doc_id} → {job_id}")

    in_flight_count = sum(len(by_status.get(s, [])) for s in in_flight)
    completed_count = sum(len(by_status.get(s, [])) for s in terminal if s != "error")
    error_count = len(by_status.get("error", []))
    print(f"\n  Summary: {in_flight_count} in-flight, {completed_count} completed, {error_count} errors")
    return 0


def run_wait(args: argparse.Namespace, token: str) -> int:
    status = load_status(args.status_file)
    jobs = [j for j in status.get("jobs", []) if j.get("job_id") and j.get("status") not in ("completed", "partial_failed", "dead_letter", "error")]

    if not jobs:
        print("No in-flight jobs to wait for.")
        return 0

    print(f"Waiting for {len(jobs)} in-flight jobs (poll every {args.poll_interval}s, max {args.max_poll_attempts} attempts)...")

    for attempt in range(1, args.max_poll_attempts + 1):
        still_running = 0
        for job in jobs:
            if job.get("status") in ("completed", "partial_failed", "dead_letter", "error"):
                continue
            job_id = job["job_id"]
            live = check_job_status(args.api_base, token, job_id, args.timeout)
            if "error" in live:
                job["status"] = "error"
                job["error"] = live["error"]
                print(f"  [{attempt}] {job['doc_id']} → ERROR")
            else:
                new_status = live.get("status", "unknown")
                if new_status in ("completed", "partial_failed", "dead_letter"):
                    job["status"] = new_status
                    print(f"  [{attempt}] {job['doc_id']} → {new_status}")
                else:
                    still_running += 1

        save_status(args.status_file, status)

        if still_running == 0:
            print(f"\nAll jobs finished after {attempt} polls.")
            return 0

        time.sleep(args.poll_interval)

    print(f"\nTIMEOUT: {still_running} jobs still running after {args.max_poll_attempts} polls.", file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()

    if not args.status and not args.wait and not args.dry_run:
        # Need login for real operations
        print(f"Logging in to {args.api_base} ...")
        token = login(args.api_base, args.username, args.password, args.timeout)
        print("Login OK.")
    else:
        # Status/wait also need token for live checks
        token = None
        try:
            token = login(args.api_base, args.username, args.password, args.timeout)
        except Exception:
            pass

    if args.status:
        return run_status(args, token) if token else 1
    if args.wait:
        return run_wait(args, token) if token else 1

    return run_rebuild(args, token)


if __name__ == "__main__":
    raise SystemExit(main())
