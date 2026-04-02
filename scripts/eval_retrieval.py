#!/usr/bin/env python3
"""Retrieval evaluation script — calls the protected /retrieval/search endpoint and scores results against sample expectations.

Usage:
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --api-base http://localhost:8020 --samples eval/retrieval_samples.yaml
    python scripts/eval_retrieval.py --username admin --password secret
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = "http://localhost:8020"
DEFAULT_SAMPLES = PROJECT_ROOT / "eval" / "retrieval_samples.yaml"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "eval" / "results"

# Default credentials aligned with LOCAL_DEV_RUNBOOK.md
DEFAULT_USERNAME = "sys.admin.demo"
DEFAULT_PASSWORD = "sys-admin-demo-pass"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against curated samples.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="API base URL (default: %(default)s)")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES, help="Path to samples YAML")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Output directory for results")
    parser.add_argument("--username", default=os.environ.get("AUTH_USERNAME", DEFAULT_USERNAME), help="Login username (or set AUTH_USERNAME env var)")
    parser.add_argument("--password", default=os.environ.get("AUTH_PASSWORD", DEFAULT_PASSWORD), help="Login password (or set AUTH_PASSWORD env var)")
    parser.add_argument("--top-k", type=int, default=5, help="top_k to send with each retrieval request")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP request timeout in seconds")
    return parser.parse_args()


# ── Login ────────────────────────────────────────────────

def login(api_base: str, username: str, password: str, timeout: int) -> str:
    """Login and return Bearer token. Raises on failure."""
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
    data = resp.json()
    token = data.get("access_token")
    if not token:
        print(f"ERROR: Login response missing access_token: {data}", file=sys.stderr)
        sys.exit(1)
    return token


# ── Load samples ─────────────────────────────────────────

def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        print(f"ERROR: Samples file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    samples = data.get("samples", [])
    if not samples:
        print(f"ERROR: No samples found in {path}", file=sys.stderr)
        sys.exit(1)
    return samples


# ── Call retrieval ───────────────────────────────────────

def call_retrieval(
    api_base: str,
    token: str,
    query: str,
    top_k: int,
    department_id: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Call POST /api/v1/retrieval/search and return response JSON."""
    url = f"{api_base}/api/v1/retrieval/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"query": query, "top_k": top_k}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Retrieval failed (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


# ── Scoring ──────────────────────────────────────────────

def score_sample(sample: dict[str, Any], retrieval_result: dict[str, Any]) -> dict[str, Any]:
    """Score a single sample against retrieval results."""
    expected_doc_ids = sample.get("expected_doc_ids", [])
    expected_first_doc = expected_doc_ids[0] if expected_doc_ids else None
    expected_chunk_type = sample.get("expected_chunk_type")
    supplemental_expected = sample.get("supplemental_expected", False)

    results = retrieval_result.get("results", [])
    top1 = results[0] if results else None
    top1_doc_id = top1.get("document_id") if top1 else None

    # top1_accuracy: strict match against expected_doc_ids[0]
    top1_accuracy = 1.0 if (top1_doc_id and top1_doc_id == expected_first_doc) else 0.0

    # top1_partial_hit: top1 hits any expected doc but not the first
    top1_partial_hit = 0.0
    if top1_doc_id and top1_doc_id in expected_doc_ids and top1_doc_id != expected_first_doc:
        top1_partial_hit = 1.0

    # topk_recall: any result matches any expected doc
    hit_doc_ids = {r.get("document_id") for r in results}
    topk_recall = 1.0 if hit_doc_ids & set(expected_doc_ids) else 0.0

    # expected_doc_coverage
    doc_coverage = 0.0
    if expected_doc_ids:
        doc_coverage = len(hit_doc_ids & set(expected_doc_ids)) / len(expected_doc_ids)

    # chunk_type matching (top1) — HEURISTIC ONLY
    # This score is inferred from retrieval_strategy/source_scope/text-length,
    # NOT from a ground-truth chunk_type label. Do not treat as formal evaluation.
    chunk_type_score = None
    if top1 and expected_chunk_type:
        actual_chunk_type = _infer_chunk_type(top1)
        chunk_type_score = _score_chunk_type(expected_chunk_type, actual_chunk_type)

    # supplemental trigger
    diagnostic = retrieval_result.get("diagnostic") or {}
    supplemental_triggered = diagnostic.get("supplemental_triggered", False)

    supplemental_tp = supplemental_expected and supplemental_triggered
    supplemental_tn = (not supplemental_expected) and (not supplemental_triggered)
    conservative_trigger = (not supplemental_expected) and supplemental_triggered

    # expected_terms coverage
    expected_terms = sample.get("expected_terms", [])
    if expected_terms:
        all_text = " ".join(r.get("text", "") for r in results).lower()
        terms_hit = sum(1 for t in expected_terms if t.lower() in all_text)
        term_coverage = terms_hit / len(expected_terms)
    else:
        term_coverage = None

    return {
        "sample_id": sample["id"],
        "query": sample["query"],
        "query_type": sample.get("query_type"),
        "expected_granularity": sample.get("expected_granularity"),
        "top1_accuracy": top1_accuracy,
        "top1_partial_hit": top1_partial_hit,
        "topk_recall": topk_recall,
        "expected_doc_coverage": doc_coverage,
        "expected_doc_ids": expected_doc_ids,
        "hit_doc_ids": sorted(hit_doc_ids),
        "chunk_type_expected": expected_chunk_type,
        # Mark as heuristic — NOT a formal evaluation metric
        "heuristic_chunk_type_score": chunk_type_score,
        "supplemental_expected": supplemental_expected,
        "supplemental_triggered": supplemental_triggered,
        "supplemental_tp": supplemental_tp,
        "supplemental_tn": supplemental_tn,
        "conservative_trigger": conservative_trigger,
        "term_coverage": term_coverage,
        "requester_department_id": sample.get("requester_department_id"),
        "top1_doc_id": top1_doc_id,
        "top1_score": top1.get("score") if top1 else None,
        "result_count": len(results),
        # Prefer supplemental_recall_stage.trigger_basis; fall back to supplemental_reason
        "diagnostic_trigger_basis": (
            diagnostic.get("supplemental_recall_stage", {}).get("trigger_basis")
            or diagnostic.get("supplemental_reason")
        ),
        # requester_department_id is a sample label only — NOT a real auth context simulation
        "_department_auth_simulated": False,
    }


def _infer_chunk_type(result: dict[str, Any]) -> str | None:
    """Infer chunk type from result metadata. This is a best-effort heuristic."""
    # If source_scope indicates document_preview, it's likely doc_summary
    source_scope = result.get("source_scope", "")
    strategy = result.get("retrieval_strategy", "")
    text = result.get("text", "")
    if source_scope == "document_preview" or "doc_summary" in strategy:
        return "doc_summary"
    # Use text length as a rough heuristic
    if len(text) > 600:
        return "section_summary"
    if len(text) <= 300:
        return "clause"
    return "section_summary"


def _score_chunk_type(expected: str, actual: str | None) -> dict[str, Any] | None:
    """Score chunk type match. Returns dict with 'full_match' and 'partial_match' booleans."""
    if actual is None:
        return None
    full = expected == actual
    partial_rules = {
        ("clause", "section_summary"): True,
        ("section_summary", "doc_summary"): True,
    }
    partial = partial_rules.get((expected, actual), False)
    return {"expected": expected, "actual": actual, "full_match": full, "partial_match": partial}


# ── Aggregation ──────────────────────────────────────────

def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-sample scores into summary metrics."""
    n = len(scores)
    if n == 0:
        return {"error": "no samples scored"}

    summary: dict[str, Any] = {
        "total_samples": n,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "top1_accuracy": sum(s["top1_accuracy"] for s in scores) / n,
            "top1_partial_hit_rate": sum(s["top1_partial_hit"] for s in scores) / n,
            "topk_recall": sum(s["topk_recall"] for s in scores) / n,
            "expected_doc_coverage_avg": sum(s["expected_doc_coverage"] for s in scores) / n,
        },
    }

    # Supplemental metrics
    tp = sum(1 for s in scores if s["supplemental_tp"])
    fn = sum(1 for s in scores if s["supplemental_expected"] and not s["supplemental_triggered"])
    tn = sum(1 for s in scores if s["supplemental_tn"])
    conservative = sum(1 for s in scores if s["conservative_trigger"])

    summary["metrics"]["supplemental_precision"] = tp / (tp + conservative) if (tp + conservative) > 0 else None
    summary["metrics"]["supplemental_recall"] = tp / (tp + fn) if (tp + fn) > 0 else None
    summary["metrics"]["conservative_trigger_count"] = conservative
    summary["metrics"]["supplemental_true_negatives"] = tn

    # Chunk type stats (heuristic only — not a formal metric)
    chunk_scores = [s["heuristic_chunk_type_score"] for s in scores if s["heuristic_chunk_type_score"] is not None]
    if chunk_scores:
        full_match_count = sum(1 for c in chunk_scores if c["full_match"])
        partial_match_count = sum(1 for c in chunk_scores if c["partial_match"])
        summary["metrics"]["heuristic_chunk_type_full_match_rate"] = full_match_count / len(chunk_scores)
        summary["metrics"]["heuristic_chunk_type_partial_match_rate"] = partial_match_count / len(chunk_scores)

    # Term coverage
    term_coverages = [s["term_coverage"] for s in scores if s["term_coverage"] is not None]
    if term_coverages:
        summary["metrics"]["term_coverage_avg"] = sum(term_coverages) / len(term_coverages)

    # Group by query_type
    summary["by_query_type"] = _group_metrics(scores, "query_type")
    # Group by department
    summary["by_department"] = _group_metrics(scores, "requester_department_id")
    # Group by granularity
    summary["by_granularity"] = _group_metrics(scores, "expected_granularity")
    # Group by supplemental_expected
    summary["by_supplemental_expected"] = _group_metrics(scores, "supplemental_expected")

    return summary


def _group_metrics(scores: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in scores:
        k = str(s.get(key, "unknown"))
        groups.setdefault(k, []).append(s)
    result = {}
    for k, group in groups.items():
        n = len(group)
        result[k] = {
            "count": n,
            "top1_accuracy": sum(s["top1_accuracy"] for s in group) / n,
            "topk_recall": sum(s["topk_recall"] for s in group) / n,
            "expected_doc_coverage_avg": sum(s["expected_doc_coverage"] for s in group) / n,
        }
    return result


# ── Main ─────────────────────────────────────────────────

def main() -> int:
    args = parse_args()

    # 1. Load samples
    samples = load_samples(args.samples)
    print(f"Loaded {len(samples)} samples from {args.samples}")

    # 2. Login
    print(f"Logging in to {args.api_base} ...")
    token = login(args.api_base, args.username, args.password, args.timeout)
    print("Login OK.")

    # 3. Run evaluation
    scores: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, sample in enumerate(samples, 1):
        sid = sample["id"]
        query = sample["query"]
        dept = sample.get("requester_department_id")
        print(f"  [{i}/{len(samples)}] {sid}: {query[:50]}{'...' if len(query) > 50 else ''}", end="", flush=True)
        try:
            start = time.monotonic()
            result = call_retrieval(
                args.api_base, token, query, args.top_k,
                department_id=dept, timeout=args.timeout,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            score = score_sample(sample, result)
            score["latency_ms"] = elapsed_ms
            scores.append(score)
            tag = "OK" if score["topk_recall"] == 1.0 else "MISS"
            print(f"  ({elapsed_ms}ms) [{tag}]")
        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append({"sample_id": sid, "query": query, "error": str(e)})

    # 4. Aggregate
    summary = aggregate(scores)

    # 5. Output JSON report
    args.results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.results_dir / f"eval_{timestamp}.json"
    report = {
        "summary": summary,
        "scores": scores,
        "errors": errors,
        "config": {
            "api_base": args.api_base,
            "samples_path": str(args.samples),
            "top_k": args.top_k,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}")

    # 6. Print human-readable summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    m = summary["metrics"]
    print(f"  Total samples:    {summary['total_samples']}")
    print(f"  Errors:           {len(errors)}")
    print(f"  top1_accuracy:    {m['top1_accuracy']:.2%}")
    print(f"  top1_partial:     {m['top1_partial_hit_rate']:.2%}")
    print(f"  topk_recall:      {m['topk_recall']:.2%}")
    print(f"  doc_coverage:     {m['expected_doc_coverage_avg']:.2%}")
    if m.get("term_coverage_avg") is not None:
        print(f"  term_coverage:    {m['term_coverage_avg']:.2%}")
    if m.get("heuristic_chunk_type_full_match_rate") is not None:
        print(f"  chunk_full_match: {m['heuristic_chunk_type_full_match_rate']:.2%}  (heuristic)")
    if m.get("heuristic_chunk_type_partial_match_rate") is not None:
        print(f"  chunk_partial:    {m['heuristic_chunk_type_partial_match_rate']:.2%}  (heuristic)")
    print(f"  sup_precision:    {m.get('supplemental_precision', 'N/A')}")
    print(f"  sup_recall:       {m.get('supplemental_recall', 'N/A')}")
    print(f"  conservative_trig:{m['conservative_trigger_count']}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    [{e['sample_id']}] {e['query'][:60]} → {e['error']}")

    # Print by_query_type breakdown
    print("\n  BY QUERY TYPE:")
    for qt, metrics in summary.get("by_query_type", {}).items():
        print(f"    {qt}: n={metrics['count']}  top1={metrics['top1_accuracy']:.2%}  recall={metrics['topk_recall']:.2%}  coverage={metrics['expected_doc_coverage_avg']:.2%}")

    print("\n  BY DEPARTMENT (label-based grouping, NOT real permission simulation):")
    for dept, metrics in summary.get("by_department", {}).items():
        print(f"    {dept}: n={metrics['count']}  top1={metrics['top1_accuracy']:.2%}  recall={metrics['topk_recall']:.2%}  coverage={metrics['expected_doc_coverage_avg']:.2%}")

    # Print limitations notice
    print("\n  LIMITATIONS:")
    print("    - by_department grouping is based on sample labels, NOT real auth context simulation")
    print("    - chunk_type scores are heuristic (inferred from strategy/scope/text-length), NOT ground-truth")
    print("    - cross-dept supplemental results should be considered provisional")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
