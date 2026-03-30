#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES_PATH = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "hybrid_query_router_samples.jsonl"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings
from backend.app.services.retrieval_query_router import RetrievalQueryRouter


def build_calibration_settings() -> Settings:
    return Settings(
        _env_file=None,
        retrieval_dynamic_weighting_enabled=True,
        retrieval_hybrid_exact_vector_weight=0.3,
        retrieval_hybrid_exact_lexical_weight=0.7,
        retrieval_hybrid_semantic_vector_weight=0.7,
        retrieval_hybrid_semantic_lexical_weight=0.3,
        retrieval_hybrid_mixed_vector_weight=0.5,
        retrieval_hybrid_mixed_lexical_weight=0.5,
        retrieval_query_classifier_exact_signal_threshold=2,
        retrieval_query_classifier_semantic_signal_threshold=2,
    )


def load_sample_specs(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        payload["_line_number"] = line_number
        samples.append(payload)
    return samples


def evaluate_samples(
    *,
    samples: list[dict[str, Any]],
    settings: Settings,
) -> list[dict[str, Any]]:
    router = RetrievalQueryRouter(settings)
    evaluations: list[dict[str, Any]] = []
    for sample in samples:
        classification = router.classify(str(sample["query"]))
        weights = router.resolve_branch_weights(str(sample["query"]))
        expected_type = str(sample["expected_query_type"])
        expected_vector_weight = float(sample["expected_vector_weight"])
        expected_lexical_weight = float(sample["expected_lexical_weight"])
        evaluations.append(
            {
                "query": sample["query"],
                "expected_query_type": expected_type,
                "actual_query_type": classification.query_type,
                "expected_vector_weight": expected_vector_weight,
                "actual_vector_weight": weights.vector_weight,
                "expected_lexical_weight": expected_lexical_weight,
                "actual_lexical_weight": weights.lexical_weight,
                "exact_signals": classification.exact_signals,
                "semantic_signals": classification.semantic_signals,
                "matched": (
                    classification.query_type == expected_type
                    and abs(weights.vector_weight - expected_vector_weight) < 1e-9
                    and abs(weights.lexical_weight - expected_lexical_weight) < 1e-9
                ),
                "note": sample.get("note"),
                "line_number": sample.get("_line_number"),
            }
        )
    return evaluations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate curated hybrid query router samples against the current rule-based classifier."
    )
    parser.add_argument(
        "--samples",
        type=Path,
        default=DEFAULT_SAMPLES_PATH,
        help=f"Path to the JSONL sample file. Default: {DEFAULT_SAMPLES_PATH}",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when any sample no longer matches its expected query type or weights.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = load_sample_specs(args.samples)
    settings = build_calibration_settings()
    evaluations = evaluate_samples(samples=samples, settings=settings)

    mismatches = [item for item in evaluations if not item["matched"]]
    for item in evaluations:
        print(
            " | ".join(
                [
                    f"query={item['query']}",
                    f"expected={item['expected_query_type']}",
                    f"actual={item['actual_query_type']}",
                    f"weights={item['actual_vector_weight']:.2f}/{item['actual_lexical_weight']:.2f}",
                    f"signals={item['exact_signals']}/{item['semantic_signals']}",
                    f"matched={item['matched']}",
                ]
            )
        )

    print(
        f"\nsummary: total={len(evaluations)} matched={len(evaluations) - len(mismatches)} mismatched={len(mismatches)}"
    )
    if args.strict and mismatches:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
