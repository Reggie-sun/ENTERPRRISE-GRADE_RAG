#!/usr/bin/env python3
"""Compare two retrieval evaluation result files and print a diff summary.

Usage:
    python scripts/compare_eval_results.py before.json after.json
    python scripts/compare_eval_results.py eval/results/eval_*.json  # auto-pick latest two
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two retrieval eval result files.")
    parser.add_argument("files", nargs=2, type=Path, help="Two eval result JSON files to compare")
    return parser.parse_args()


def load_eval(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2%}"


def fmt_delta(old: float | None, new: float | None) -> str:
    if old is None or new is None:
        return ""
    delta = new - old
    sign = "+" if delta >= 0 else ""
    return f"  ({sign}{delta:+.2%})"


def compare(before: dict, after: dict) -> None:
    bm = before.get("summary", {}).get("metrics", {})
    am = after.get("summary", {}).get("metrics", {})

    print("=" * 70)
    print("EVAL COMPARISON")
    print("=" * 70)

    before_label = before.get("config", {}).get("samples_path", "before")
    after_label = after.get("config", {}).get("samples_path", "after")
    before_time = before.get("summary", {}).get("evaluated_at", "?")
    after_time = after.get("summary", {}).get("evaluated_at", "?")
    print(f"  Before: {before_label}  ({before_time})")
    print(f"  After:  {after_label}  ({after_time})")
    print()

    metrics = [
        ("top1_accuracy", "Top-1 Accuracy"),
        ("top1_partial_hit_rate", "Top-1 Partial Hit Rate"),
        ("topk_recall", "Top-K Recall"),
        ("expected_doc_coverage_avg", "Doc Coverage Avg"),
        ("term_coverage_avg", "Term Coverage Avg"),
        ("supplemental_precision", "Supplemental Precision"),
        ("supplemental_recall", "Supplemental Recall"),
        ("heuristic_chunk_type_full_match_rate", "Chunk Type Full Match (heuristic)"),
        ("heuristic_chunk_type_partial_match_rate", "Chunk Type Partial Match (heuristic)"),
    ]

    print(f"  {'Metric':<40} {'Before':>8} {'After':>8}  {'Delta':>10}")
    print("  " + "-" * 66)

    for key, label in metrics:
        bv = bm.get(key)
        av = am.get(key)
        delta_str = fmt_delta(bv, av)
        # Mark significant changes
        marker = ""
        if bv is not None and av is not None:
            if av < bv - 0.02:
                marker = " <<<"
            elif av > bv + 0.02:
                marker = " >>>"
        print(f"  {label:<40} {fmt_pct(bv):>8} {fmt_pct(av):>8}{delta_str:>10}{marker}")

    # Conservative trigger count
    btc = bm.get("conservative_trigger_count", "?")
    atc = am.get("conservative_trigger_count", "?")
    print(f"  {'Conservative Trigger Count':<40} {str(btc):>8} {str(atc):>8}")

    # Per-sample diff (regressions only)
    before_scores = {s["sample_id"]: s for s in before.get("scores", [])}
    after_scores = {s["sample_id"]: s for s in after.get("scores", [])}

    regressions = []
    for sid, bs in before_scores.items():
        a_s = after_scores.get(sid)
        if not a_s:
            continue
        if bs.get("top1_accuracy", 0) == 1.0 and a_s.get("top1_accuracy", 0) == 0.0:
            regressions.append((sid, bs, a_s))
        if bs.get("topk_recall", 0) == 1.0 and a_s.get("topk_recall", 0) == 0.0:
            regressions.append((sid, bs, a_s))

    if regressions:
        print(f"\n  REGRESSIONS ({len(regressions)} samples):")
        for sid, bs, a_s in regressions:
            print(f"    [{sid}] {a_s.get('query', '')[:60]}")
            print(f"      top1: {bs.get('top1_doc_id', '?')} → {a_s.get('top1_doc_id', '?')}")

    improvements = []
    for sid, bs in before_scores.items():
        a_s = after_scores.get(sid)
        if not a_s:
            continue
        if bs.get("top1_accuracy", 0) == 0.0 and a_s.get("top1_accuracy", 0) == 1.0:
            improvements.append((sid, bs, a_s))

    if improvements:
        print(f"\n  IMPROVEMENTS ({len(improvements)} samples):")
        for sid, bs, a_s in improvements:
            print(f"    [{sid}] {a_s.get('query', '')[:60]}")

    # Verdict
    print("\n  VERDICT:")
    old_recall = bm.get("topk_recall", 0)
    new_recall = am.get("topk_recall", 0)
    old_top1 = bm.get("top1_accuracy", 0)
    new_top1 = am.get("top1_accuracy", 0)

    if new_recall >= old_recall and new_top1 >= old_top1:
        print("    PASS: No regression in top1_accuracy or topk_recall.")
    else:
        print("    REGRESSION DETECTED: Consider rollback.")
        if new_top1 < old_top1:
            print(f"    top1_accuracy dropped from {fmt_pct(old_top1)} to {fmt_pct(new_top1)}")
        if new_recall < old_recall:
            print(f"    topk_recall dropped from {fmt_pct(old_recall)} to {fmt_pct(new_recall)}")


def main() -> int:
    args = parse_args()
    before = load_eval(args.files[0])
    after = load_eval(args.files[1])
    compare(before, after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
