#!/usr/bin/env python3
"""Retrieval evaluation script — calls the protected /retrieval/search endpoint and scores results against sample expectations.

Usage:
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --api-base http://localhost:8020 --samples eval/retrieval_samples.yaml
    python scripts/eval_retrieval.py --username admin --password secret
    python scripts/eval_retrieval.py --threshold-override top1_threshold=0.60,avg_top_n_threshold=0.50
    python scripts/eval_retrieval.py --threshold-matrix eval/threshold_matrix.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = "http://localhost:8020"
DEFAULT_SAMPLES = PROJECT_ROOT / "eval" / "retrieval_samples.yaml"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "eval" / "experiments"
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "eval" / "experiments"

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
    parser.add_argument("--threshold-override", type=str, default=None, help="Override internal thresholds (comma-separated key=value pairs)")
    parser.add_argument("--threshold-matrix", type=Path, default=None, help="Path to threshold matrix YAML for running multiple experiments")
    parser.add_argument("--experiment-name", type=str, default=None, help="Tag name for results file (e.g. 'before_change' → baseline_before_change.json). If omitted, uses timestamp.")
    return parser.parse_args()


# ── Threshold management ─────────────────────────────────

def parse_threshold_override(override_str: str) -> dict[str, float]:
    """Parse 'key1=val1,key2=val2' into a dict."""
    thresholds: dict[str, float] = {}
    for pair in override_str.split(","):
        pair = pair.strip()
        if "=" not in pair:
            print(f"ERROR: Invalid threshold override format: {pair!r}. Use key=value.", file=sys.stderr)
            sys.exit(1)
        key, val = pair.split("=", 1)
        try:
            thresholds[key.strip()] = float(val.strip())
        except ValueError:
            print(f"ERROR: Invalid threshold value: {val!r}. Must be a float.", file=sys.stderr)
            sys.exit(1)
    return thresholds


def read_current_system_config(api_base: str, token: str, timeout: int) -> dict[str, Any]:
    """Read current system config (requires sys_admin)."""
    url = f"{api_base}/api/v1/system-config"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to read system config (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


def write_internal_thresholds(api_base: str, token: str, thresholds: dict[str, float], timeout: int) -> None:
    """Write internal retrieval thresholds to system config.

    This writes the _internal_retrieval_controls key to system-config.
    Uses a two-step approach: read current config, merge internal controls, write back.
    """
    import subprocess

    system_config_path = _find_system_config_path(api_base, token, timeout)
    if system_config_path is None:
        print("WARNING: Could not determine system config file path; threshold override may not persist.", file=sys.stderr)
        print("  You can manually update the _internal_retrieval_controls in data/system_config.json", file=sys.stderr)
        return

    config_path = Path(system_config_path)
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        config_data = {}

    # Build nested structure
    internal_controls: dict[str, Any] = config_data.get("_internal_retrieval_controls", {})
    quality_thresholds = internal_controls.get("supplemental_quality_thresholds", {})
    quality_thresholds.update(thresholds)
    internal_controls["supplemental_quality_thresholds"] = quality_thresholds
    config_data["_internal_retrieval_controls"] = internal_controls

    config_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Written thresholds to {config_path}")


def _find_system_config_path(api_base: str, token: str, timeout: int) -> str | None:
    """Try to find the system config file path from the API health/config info."""
    try:
        health_url = f"{api_base}/api/v1/health"
        resp = requests.get(health_url, timeout=timeout)
        # Not reliable for finding file path, so use convention
    except Exception:
        pass
    # Convention: look for data/system_config.json relative to project root
    convention_paths = [
        PROJECT_ROOT / "data" / "system_config.json",
        Path.cwd() / "data" / "system_config.json",
    ]
    for p in convention_paths:
        if p.exists():
            return str(p)
    # Return the most likely path even if it doesn't exist yet
    return str(PROJECT_ROOT / "data" / "system_config.json")


def load_threshold_matrix(path: Path) -> list[dict[str, Any]]:
    """Load threshold matrix from YAML file.

    Expected format:
    experiments:
      - name: "default"
        thresholds:
          top1_threshold: 0.55
          avg_top_n_threshold: 0.45
      - name: "stricter"
        thresholds:
          top1_threshold: 0.65
          avg_top_n_threshold: 0.55
    """
    if not path.exists():
        print(f"ERROR: Threshold matrix file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    experiments = data.get("experiments", [])
    if not experiments:
        print(f"ERROR: No experiments found in {path}", file=sys.stderr)
        sys.exit(1)
    return experiments


def snapshot_current_thresholds(api_base: str, token: str, timeout: int) -> dict[str, float]:
    """Snapshot current thresholds from the system config file."""
    config_path = _find_system_config_path(api_base, token, timeout)
    if config_path is None:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        config_data = json.load(f)
    internal = config_data.get("_internal_retrieval_controls", {})
    quality = internal.get("supplemental_quality_thresholds", {})
    return {k: float(v) for k, v in quality.items() if isinstance(v, (int, float))}


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

    # Diagnostic quality fields (for threshold experiment analysis)
    primary_threshold = diagnostic.get("primary_threshold") if isinstance(diagnostic, dict) else None
    primary_top1_score = diagnostic.get("primary_top1_score") if isinstance(diagnostic, dict) else None
    primary_avg_top_n_score = diagnostic.get("primary_avg_top_n_score") if isinstance(diagnostic, dict) else None
    quality_top1_threshold = diagnostic.get("quality_top1_threshold") if isinstance(diagnostic, dict) else None
    quality_avg_threshold = diagnostic.get("quality_avg_threshold") if isinstance(diagnostic, dict) else None
    supplemental_trigger_basis = diagnostic.get("supplemental_trigger_basis") if isinstance(diagnostic, dict) else None

    # Also check structured diagnostic sub-stages
    primary_recall_stage = diagnostic.get("primary_recall_stage") if isinstance(diagnostic, dict) else None
    if primary_recall_stage and isinstance(primary_recall_stage, dict):
        primary_threshold = primary_recall_stage.get("threshold", primary_threshold)
        primary_top1_score = primary_recall_stage.get("top1_score", primary_top1_score)
        primary_avg_top_n_score = primary_recall_stage.get("avg_top_n_score", primary_avg_top_n_score)
        quality_top1_threshold = primary_recall_stage.get("quality_top1_threshold", quality_top1_threshold)
        quality_avg_threshold = primary_recall_stage.get("quality_avg_threshold", quality_avg_threshold)

    supplemental_recall_stage = diagnostic.get("supplemental_recall_stage") if isinstance(diagnostic, dict) else None
    if supplemental_recall_stage and isinstance(supplemental_recall_stage, dict):
        supplemental_trigger_basis = supplemental_recall_stage.get("trigger_basis", supplemental_trigger_basis)

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
        # Diagnostic quality fields (for threshold experiment analysis)
        "diagnostic_primary_threshold": primary_threshold,
        "diagnostic_primary_top1_score": primary_top1_score,
        "diagnostic_primary_avg_top_n_score": primary_avg_top_n_score,
        "diagnostic_quality_top1_threshold": quality_top1_threshold,
        "diagnostic_quality_avg_threshold": quality_avg_threshold,
        "diagnostic_trigger_basis": supplemental_trigger_basis,
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


# ── Run single evaluation pass ───────────────────────────

def run_evaluation(
    *,
    samples: list[dict[str, Any]],
    api_base: str,
    token: str,
    top_k: int,
    timeout: int,
    threshold_name: str | None = None,
    thresholds_applied: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one evaluation pass and return (summary, scores, errors)."""
    scores: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, sample in enumerate(samples, 1):
        sid = sample["id"]
        query = sample["query"]
        dept = sample.get("requester_department_id")
        label = f"[{i}/{len(samples)}] {sid}: {query[:50]}{'...' if len(query) > 50 else ''}"
        print(f"  {label}", end="", flush=True)
        try:
            start = time.monotonic()
            result = call_retrieval(
                api_base, token, query, top_k,
                department_id=dept, timeout=timeout,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            score = score_sample(sample, result)
            score["latency_ms"] = elapsed_ms
            scores.append(score)
            tag = "OK" if score["topk_recall"] == 1.0 else "MISS"
            sup_tag = ""
            if score["supplemental_triggered"]:
                sup_tag = " [SUPP]"
            print(f"  ({elapsed_ms}ms) [{tag}]{sup_tag}")
        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append({"sample_id": sid, "query": query, "error": str(e)})

    summary = aggregate(scores)

    # Attach threshold metadata
    summary["threshold_experiment"] = {
        "name": threshold_name,
        "thresholds_applied": thresholds_applied,
        "note": "This is a threshold experiment, not a final calibration.",
    }

    return summary, scores, errors


def print_human_summary(summary: dict[str, Any], errors: list[dict[str, Any]], threshold_name: str | None = None) -> None:
    """Print a human-readable evaluation summary."""
    print("\n" + "=" * 60)
    if threshold_name:
        print(f"EVALUATION SUMMARY — threshold: {threshold_name}")
    else:
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

    # Determine experiment mode
    if args.threshold_matrix:
        return _run_threshold_matrix(args, samples, token)
    elif args.threshold_override:
        return _run_single_threshold_override(args, samples, token)

    # 3. Run single evaluation (no threshold changes)
    summary, scores, errors = run_evaluation(
        samples=samples,
        api_base=args.api_base,
        token=token,
        top_k=args.top_k,
        timeout=args.timeout,
    )

    # 4. Output JSON report
    args.results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Use experiment-name for tagged baseline if provided
    if args.experiment_name:
        report_path = args.results_dir / f"baseline_{args.experiment_name}.json"
    else:
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

    # 5. Print human-readable summary
    print_human_summary(summary, errors)

    return 0 if not errors else 1


def _run_single_threshold_override(args: argparse.Namespace, samples: list[dict[str, Any]], token: str) -> int:
    """Run evaluation with a single threshold override."""
    thresholds = parse_threshold_override(args.threshold_override)
    exp_name = args.experiment_name or ",".join(f"{k}={v}" for k, v in thresholds.items())

    # Snapshot current thresholds before override
    original_thresholds = snapshot_current_thresholds(args.api_base, token, args.timeout)
    print(f"Original thresholds: {original_thresholds}")
    print(f"Applying override: {thresholds}")

    try:
        write_internal_thresholds(args.api_base, token, thresholds, args.timeout)
        print("Thresholds written. Waiting 1s for backend to pick up changes...")
        time.sleep(1)

        summary, scores, errors = run_evaluation(
            samples=samples,
            api_base=args.api_base,
            token=token,
            top_k=args.top_k,
            timeout=args.timeout,
            threshold_name=exp_name,
            thresholds_applied=thresholds,
        )
    finally:
        # Restore original thresholds
        if original_thresholds:
            print(f"\nRestoring original thresholds: {original_thresholds}")
            write_internal_thresholds(args.api_base, token, original_thresholds, args.timeout)
            time.sleep(0.5)

    # Output
    args.results_dir.mkdir(parents=True, exist_ok=True)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    DEFAULT_EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DEFAULT_EXPERIMENTS_DIR / f"threshold_{exp_name}_{timestamp}.json"
    report = {
        "summary": summary,
        "scores": scores,
        "errors": errors,
        "config": {
            "api_base": args.api_base,
            "samples_path": str(args.samples),
            "top_k": args.top_k,
        },
        "threshold_experiment": {
            "name": exp_name,
            "applied": thresholds,
            "restored": original_thresholds,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}")

    print_human_summary(summary, errors, threshold_name=exp_name)

    return 0 if not errors else 1


def _run_threshold_matrix(args: argparse.Namespace, samples: list[dict[str, Any]], token: str) -> int:
    """Run evaluation across a matrix of threshold combinations."""
    experiments = load_threshold_matrix(args.threshold_matrix)
    original_thresholds = snapshot_current_thresholds(args.api_base, token, args.timeout)
    print(f"Original thresholds: {original_thresholds}")
    print(f"Running {len(experiments)} threshold experiments...")

    DEFAULT_EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results: list[dict[str, Any]] = []

    try:
        for exp_idx, experiment in enumerate(experiments, 1):
            name = experiment.get("name", f"experiment_{exp_idx}")
            thresholds = experiment.get("thresholds", {})

            if not thresholds:
                print(f"\n  [{exp_idx}/{len(experiments)}] {name}: SKIP (no thresholds defined)")
                continue

            print(f"\n  [{exp_idx}/{len(experiments)}] {name}: {thresholds}")

            try:
                write_internal_thresholds(args.api_base, token, thresholds, args.timeout)
                time.sleep(1)

                summary, scores, errors = run_evaluation(
                    samples=samples,
                    api_base=args.api_base,
                    token=token,
                    top_k=args.top_k,
                    timeout=args.timeout,
                    threshold_name=name,
                    thresholds_applied=thresholds,
                )

                all_results.append({
                    "experiment_name": name,
                    "thresholds": thresholds,
                    "summary": summary,
                    "error_count": len(errors),
                    "scores": scores,
                    "errors": errors,
                })
            except Exception as e:
                print(f"    ERROR: {e}")
                all_results.append({
                    "experiment_name": name,
                    "thresholds": thresholds,
                    "error": str(e),
                })
    finally:
        if original_thresholds:
            print(f"\nRestoring original thresholds: {original_thresholds}")
            write_internal_thresholds(args.api_base, token, original_thresholds, args.timeout)
            time.sleep(0.5)

    # Write combined matrix report
    matrix_report_path = DEFAULT_EXPERIMENTS_DIR / f"matrix_{timestamp}.json"
    matrix_report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_experiments": len(all_results),
        "original_thresholds": original_thresholds,
        "samples_path": str(args.samples),
        "sample_count": len(samples),
        "top_k": args.top_k,
        "api_base": args.api_base,
        "note": (
            "PROVISIONAL — Eval runs with sys_admin (data_scope=global), so department-priority retrieval "
            "and supplemental trigger logic are bypassed. Supplemental precision/recall are not meaningful "
            "until department-scoped auth and document department_id metadata are in place. "
            "BLOCKER STATUS (2026-04-02 audit): "
            "(1) Document metadata: sampled doc has department_ids=[], visibility=private — not fully verified for all docs. "
            "(2) Identity: dept_after_sales/dept_assembly NOT in production identity_bootstrap.json. "
            "(3) Eval harness: sys_admin auth means data_scope=global, so _should_use_department_priority_routes() returns False; "
            "RetrievalRequest has no department_id field (department context comes from auth_context, not request body). "
            "(4) Diagnostics tests: 4 failed (401), 6 passed — not usable as regression verification until auth mock added. "
            "See RETRIEVAL_PHASE1B_GLM_PROMPT.md for details."
        ),
        "experiments": all_results,
        "comparison": _build_comparison_table(all_results),
    }
    matrix_report_path.write_text(json.dumps(matrix_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMatrix report written to {matrix_report_path}")

    # Print comparison table
    _print_comparison_table(all_results)

    return 0


def _build_comparison_table(all_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a comparison table across experiments."""
    rows = []
    for r in all_results:
        if "error" in r:
            rows.append({
                "experiment_name": r["experiment_name"],
                "thresholds": r["thresholds"],
                "error": r["error"],
            })
            continue
        m = r["summary"]["metrics"]
        rows.append({
            "experiment_name": r["experiment_name"],
            "thresholds": r["thresholds"],
            "top1_accuracy": m["top1_accuracy"],
            "topk_recall": m["topk_recall"],
            "doc_coverage_avg": m["expected_doc_coverage_avg"],
            "conservative_trigger_count": m["conservative_trigger_count"],
            "supplemental_triggered_count": sum(1 for s in r["scores"] if s["supplemental_triggered"]),
            "avg_primary_top1_score": _safe_avg([s["diagnostic_primary_top1_score"] for s in r["scores"] if s["diagnostic_primary_top1_score"] is not None]),
        })
    return {"rows": rows}


def _safe_avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _print_comparison_table(all_results: list[dict[str, Any]]) -> None:
    """Print a comparison table across experiments."""
    print("\n" + "=" * 80)
    print("THRESHOLD MATRIX COMPARISON (PROVISIONAL)")
    print("=" * 80)
    print(f"  {'Experiment':<20} {'top1':>6} {'recall':>7} {'cov':>6} {'conservative':>12} {'supp_trig':>9} {'avg_top1':>8}")
    print("  " + "-" * 76)

    for r in all_results:
        if "error" in r:
            print(f"  {r['experiment_name']:<20} ERROR: {r['error'][:50]}")
            continue
        m = r["summary"]["metrics"]
        comp = _build_comparison_table(all_results)["rows"]
        row = next(x for x in comp if x["experiment_name"] == r["experiment_name"])
        avg_top1 = f"{row['avg_primary_top1_score']:.4f}" if row.get("avg_primary_top1_score") is not None else "N/A"
        print(
            f"  {r['experiment_name']:<20} "
            f"{m['top1_accuracy']:>5.1%} "
            f"{m['topk_recall']:>6.1%} "
            f"{m['expected_doc_coverage_avg']:>5.1%} "
            f"{m['conservative_trigger_count']:>12} "
            f"{row['supplemental_triggered_count']:>9} "
            f"{avg_top1:>8}"
        )

    print("\n  NOTE: Results are PROVISIONAL. Current eval runs as sys_admin (data_scope=global),")
    print("  which bypasses department-priority retrieval and supplemental trigger logic.")
    print("  Supplemental metrics are not meaningful until department-scoped auth is used.")
    print("  BLOCKER STATUS (2026-04-02): (1) doc metadata - department_ids empty in sampled docs;")
    print("  (2) identity - dept_after_sales/dept_assembly NOT in production bootstrap;")
    print("  (3) harness - sys_admin auth => data_scope=global => department_priority disabled;")
    print("  RetrievalRequest has no department_id field (dept context from auth_context, not request body).")
    print("  (4) tests - 4 failed (401), 6 passed.")
    print("  See RETRIEVAL_PHASE1B_GLM_PROMPT.md for blocker details.")


if __name__ == "__main__":
    raise SystemExit(main())
