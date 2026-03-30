import json
from pathlib import Path

from backend.app.services.retrieval_query_router import RetrievalQueryRouter
from scripts.eval_hybrid_query_router import build_calibration_settings, evaluate_samples, load_sample_specs


SAMPLES_PATH = Path(__file__).resolve().parent / "fixtures" / "hybrid_query_router_samples.jsonl"


def test_hybrid_query_router_curated_samples_match_expected_types_and_weights() -> None:
    samples = load_sample_specs(SAMPLES_PATH)
    evaluations = evaluate_samples(
        samples=samples,
        settings=build_calibration_settings(),
    )

    mismatches = [item for item in evaluations if not item["matched"]]

    assert mismatches == []


def test_hybrid_query_router_sample_file_is_valid_jsonl() -> None:
    lines = SAMPLES_PATH.read_text(encoding="utf-8").splitlines()
    assert lines

    for index, line in enumerate(lines, start=1):
        payload = json.loads(line)
        assert set(payload.keys()) == {
            "query",
            "expected_query_type",
            "expected_vector_weight",
            "expected_lexical_weight",
            "note",
        }, index
        assert payload["expected_query_type"] in {"exact", "semantic", "mixed"}


def test_hybrid_query_router_curated_samples_keep_dynamic_weighting_enabled() -> None:
    router = RetrievalQueryRouter(build_calibration_settings())
    for sample in load_sample_specs(SAMPLES_PATH):
        weights = router.resolve_branch_weights(str(sample["query"]))
        assert weights.dynamic_enabled is True
