"""
离线检索评测脚本 — 读取 eval dataset，调用 RetrievalService.search，统计命中率和排名指标。

用法：
    # 用 mock embedding + 内存 Qdrant，在临时目录跑离线评测
    python -m backend.eval.run_retrieval_eval

    # 指定评测集文件
    python -m backend.eval.run_retrieval_eval --dataset backend/eval/retrieval_eval_dataset.json

    # 输出 JSON 结果到文件
    python -m backend.eval.run_retrieval_eval --output backend/eval/results/latest.json

指标：
    - Hit@K: 前 K 条结果中至少命中一个 expected document 的比例
    - MRR: Mean Reciprocal Rank，第一个命中结果的排名倒数的均值
    - Dept-first 优先命中: department_private 类 query 中，本部门文档排在第一位的情况
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, ensure_data_directories
from backend.app.schemas.retrieval import RetrievalRequest
from backend.app.services.document_service import DocumentService
from backend.app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Eval sample model
# ---------------------------------------------------------------------------

@dataclass
class EvalSample:
    id: str
    type: str
    query: str
    expected_document_ids: list[str]
    scope_expectation: str
    should_refuse: bool
    expected_top1_hit: bool
    notes: str
    accessible_departments: list[str] = field(default_factory=list)
    inaccessible_departments: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    sample_id: str
    sample_type: str
    query: str
    expected_document_ids: list[str]
    returned_document_ids: list[str]
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    first_hit_rank: int | None  # None = no hit
    should_refuse: bool
    result_count: int
    elapsed_ms: float


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------

def load_dataset(path: str | Path) -> list[EvalSample]:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: dataset not found: {p}", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    samples: list[EvalSample] = []
    for s in data["samples"]:
        samples.append(EvalSample(
            id=s["id"],
            type=s["type"],
            query=s["query"],
            expected_document_ids=s.get("expected_document_ids", []),
            scope_expectation=s.get("scope_expectation", "global"),
            should_refuse=s.get("should_refuse", False),
            expected_top1_hit=s.get("expected_top1_hit", False),
            notes=s.get("notes", ""),
            accessible_departments=s.get("accessible_departments", []),
            inaccessible_departments=s.get("inaccessible_departments", []),
        ))
    return samples


# ---------------------------------------------------------------------------
# Settings builder (offline, no external dependencies)
# ---------------------------------------------------------------------------

def build_eval_settings(tmp_dir: Path) -> Settings:
    data_dir = tmp_dir / "data"
    return Settings(
        _env_file=None,
        app_name="Retrieval Eval Runner",
        app_env="test",
        debug=False,
        qdrant_url=":memory:",
        qdrant_collection="retrieval_eval",
        postgres_metadata_enabled=False,
        postgres_metadata_dsn=None,
        database_url=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        llm_provider="mock",
        llm_base_url="http://llm.test/v1",
        llm_model="Qwen/Qwen2.5-7B-Instruct",
        ollama_base_url="http://embedding.test",
        reranker_provider="heuristic",
        embedding_provider="mock",
        embedding_base_url="http://embedding.test",
        embedding_model="BAAI/bge-m3",
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=data_dir / "parsed",
        chunk_dir=data_dir / "chunks",
        ocr_artifact_dir=data_dir / "ocr_artifacts",
        document_dir=data_dir / "documents",
        job_dir=data_dir / "jobs",
        event_log_dir=data_dir / "event_logs",
        request_trace_dir=data_dir / "request_traces",
        request_snapshot_dir=data_dir / "request_snapshots",
        system_config_path=data_dir / "system_config.json",
    )


# ---------------------------------------------------------------------------
# Seed documents via upload API (same path as real users)
# ---------------------------------------------------------------------------

def seed_documents_via_api(
    client: TestClient,
    samples: list[EvalSample],
) -> dict[str, str]:
    """Seed unique documents from expected_document_ids via the upload endpoint.

    Returns a mapping of placeholder_id → actual doc_id.
    """
    unique_doc_ids: set[str] = set()
    for s in samples:
        for doc_id in s.expected_document_ids:
            unique_doc_ids.add(doc_id)

    id_mapping: dict[str, str] = {}
    for placeholder_id in sorted(unique_doc_ids):
        content = (
            f"Eval document: {placeholder_id}.\n"
            f"This document covers alarm handling, troubleshooting, "
            f"inspection procedures, and equipment maintenance for {placeholder_id}."
        )
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": (f"{placeholder_id}.txt", content.encode("utf-8"), "text/plain")},
        )
        if resp.status_code != 201:
            logger.warning("seed failed for %s: %s %s", placeholder_id, resp.status_code, resp.text)
            continue
        actual_id = resp.json()["document_id"]
        id_mapping[placeholder_id] = actual_id
        logger.info("seeded %s → %s", placeholder_id, actual_id)

    return id_mapping


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def run_eval(
    dataset_path: str | Path,
    output_path: str | None = None,
) -> dict[str, Any]:
    import tempfile

    from fastapi.testclient import TestClient

    from backend.app.main import app
    from backend.app.services.document_service import get_document_service
    from backend.app.services.retrieval_service import get_retrieval_service

    with tempfile.TemporaryDirectory(prefix="rag_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        settings = build_eval_settings(tmp_path)
        ensure_data_directories(settings)

        document_service = DocumentService(settings)
        retrieval_service = RetrievalService(settings, document_service=document_service)

        # Override FastAPI dependencies so TestClient hits our eval services
        app.dependency_overrides[get_document_service] = lambda: document_service
        app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service
        client = TestClient(app)

        samples = load_dataset(dataset_path)
        print(f"\n{'='*60}")
        print(f"Retrieval Eval — {len(samples)} samples")
        print(f"{'='*60}\n")

        # Seed documents via upload API (same path as real users)
        id_mapping = seed_documents_via_api(client, samples)

        results: list[EvalResult] = []

        for sample in samples:
            # Remap expected IDs using the seeding mapping
            mapped_expected = [id_mapping.get(d, d) for d in sample.expected_document_ids]

            t0 = time.perf_counter()
            response = retrieval_service.search(
                RetrievalRequest(query=sample.query, top_k=5),
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            returned_ids = [r.document_id for r in response.results]

            # Hit@K calculation
            expected_set = set(mapped_expected)
            hit_at_1 = bool(expected_set) and bool(expected_set.intersection(returned_ids[:1]))
            hit_at_3 = bool(expected_set) and bool(expected_set.intersection(returned_ids[:3]))
            hit_at_5 = bool(expected_set) and bool(expected_set.intersection(returned_ids[:5]))

            # First hit rank
            first_hit_rank: int | None = None
            for rank, doc_id in enumerate(returned_ids, start=1):
                if doc_id in expected_set:
                    first_hit_rank = rank
                    break

            results.append(EvalResult(
                sample_id=sample.id,
                sample_type=sample.type,
                query=sample.query,
                expected_document_ids=mapped_expected,
                returned_document_ids=returned_ids,
                hit_at_1=hit_at_1,
                hit_at_3=hit_at_3,
                hit_at_5=hit_at_5,
                first_hit_rank=first_hit_rank,
                should_refuse=sample.should_refuse,
                result_count=len(returned_ids),
                elapsed_ms=elapsed_ms,
            ))

            status = "HIT" if hit_at_1 else ("miss" if expected_set else "skip")
            print(f"  {sample.id:10s} [{sample.type:22s}] {status:4s}  rank={first_hit_rank or '-':>3s}  {sample.query[:50]}")

        # Cleanup FastAPI dependency overrides
        app.dependency_overrides.clear()

    # -----------------------------------------------------------------------
    # Compute metrics
    # -----------------------------------------------------------------------
    n = len(results)
    evaluable = [r for r in results if r.expected_document_ids]
    n_evaluable = len(evaluable)

    hit_at_1_count = sum(1 for r in evaluable if r.hit_at_1)
    hit_at_3_count = sum(1 for r in evaluable if r.hit_at_3)
    hit_at_5_count = sum(1 for r in evaluable if r.hit_at_5)

    hit_at_1_rate = hit_at_1_count / n_evaluable if n_evaluable else 0
    hit_at_3_rate = hit_at_3_count / n_evaluable if n_evaluable else 0
    hit_at_5_rate = hit_at_5_count / n_evaluable if n_evaluable else 0

    # MRR
    reciprocal_ranks = []
    for r in evaluable:
        if r.first_hit_rank is not None:
            reciprocal_ranks.append(1.0 / r.first_hit_rank)
        else:
            reciprocal_ranks.append(0.0)
    mrr = sum(reciprocal_ranks) / n_evaluable if n_evaluable else 0

    # Per-type breakdown
    type_metrics: dict[str, dict[str, Any]] = {}
    by_type: dict[str, list[EvalResult]] = {}
    for r in evaluable:
        by_type.setdefault(r.sample_type, []).append(r)

    for sample_type, type_results in sorted(by_type.items()):
        tn = len(type_results)
        type_metrics[sample_type] = {
            "count": tn,
            "hit_at_1": sum(1 for r in type_results if r.hit_at_1) / tn,
            "hit_at_3": sum(1 for r in type_results if r.hit_at_3) / tn,
            "hit_at_5": sum(1 for r in type_results if r.hit_at_5) / tn,
            "mrr": sum(1.0 / r.first_hit_rank if r.first_hit_rank else 0.0 for r in type_results) / tn,
        }

    # Department-first priority hit
    dept_first_results = [r for r in results if r.sample_type == "department_private" and r.expected_document_ids]
    dept_first_n = len(dept_first_results)
    dept_first_hit = sum(1 for r in dept_first_results if r.hit_at_1)
    dept_first_rate = dept_first_hit / dept_first_n if dept_first_n else 0

    # Refuse correctness
    refuse_results = [r for r in results if r.should_refuse]
    refuse_correct = sum(1 for r in refuse_results if r.result_count == 0)

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------
    summary = {
        "total_samples": n,
        "evaluable_samples": n_evaluable,
        "overall": {
            "hit_at_1": round(hit_at_1_rate, 4),
            "hit_at_3": round(hit_at_3_rate, 4),
            "hit_at_5": round(hit_at_5_rate, 4),
            "mrr": round(mrr, 4),
        },
        "department_first": {
            "total": dept_first_n,
            "hit_at_1": dept_first_hit,
            "rate": round(dept_first_rate, 4),
        },
        "refuse_correctness": {
            "total": len(refuse_results),
            "correct_no_result": refuse_correct,
        },
        "per_type": type_metrics,
        "sample_results": [
            {
                "id": r.sample_id,
                "type": r.sample_type,
                "query": r.query,
                "hit_at_1": r.hit_at_1,
                "hit_at_3": r.hit_at_3,
                "hit_at_5": r.hit_at_5,
                "first_hit_rank": r.first_hit_rank,
                "result_count": r.result_count,
                "elapsed_ms": round(r.elapsed_ms, 1),
            }
            for r in results
        ],
    }

    # Terminal summary
    print(f"\n{'='*60}")
    print(f"  Eval Results ({n_evaluable} evaluable / {n} total)")
    print(f"{'='*60}")
    print(f"  Hit@1:  {hit_at_1_rate:.1%}  ({hit_at_1_count}/{n_evaluable})")
    print(f"  Hit@3:  {hit_at_3_rate:.1%}  ({hit_at_3_count}/{n_evaluable})")
    print(f"  Hit@5:  {hit_at_5_rate:.1%}  ({hit_at_5_count}/{n_evaluable})")
    print(f"  MRR:    {mrr:.4f}")
    print(f"")
    print(f"  Dept-first priority ({dept_first_n} samples):")
    print(f"    Hit@1 rate: {dept_first_rate:.1%}  ({dept_first_hit}/{dept_first_n})")
    print(f"")
    print(f"  Refuse correctness ({len(refuse_results)} samples):")
    print(f"    Correct no-result: {refuse_correct}/{len(refuse_results)}")
    print(f"")

    if type_metrics:
        print(f"  Per-type breakdown:")
        print(f"  {'Type':<25s} {'Count':>5s} {'H@1':>7s} {'H@3':>7s} {'H@5':>7s} {'MRR':>7s}")
        print(f"  {'-'*58}")
        for stype, sm in sorted(type_metrics.items()):
            print(f"  {stype:<25s} {sm['count']:>5d} {sm['hit_at_1']:>6.1%} {sm['hit_at_3']:>6.1%} {sm['hit_at_5']:>6.1%} {sm['mrr']:>7.4f}")
    print(f"{'='*60}\n")

    # Write JSON output
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Results written to: {out}")

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run offline retrieval evaluation")
    parser.add_argument(
        "--dataset",
        default="backend/eval/retrieval_eval_dataset.json",
        help="Path to eval dataset JSON (default: backend/eval/retrieval_eval_dataset.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results file (e.g. backend/eval/results/latest.json)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    run_eval(dataset_path=args.dataset, output_path=args.output)


if __name__ == "__main__":
    main()
