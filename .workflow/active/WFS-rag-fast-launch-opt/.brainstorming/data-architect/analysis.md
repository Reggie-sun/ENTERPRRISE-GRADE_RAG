# Data-Architect Analysis: RAG Fast Launch Optimization

**Role**: Data-Architect
**Date**: 2026-04-06
**Scope**: Data integrity across bundle freeze, eval calibration, and monitoring pipeline
**Bundle Context**: 1-week full launch, evidence-grounded Q&A system

## Role Perspective

The data-architect's mandate for this fast launch is ensuring **data determinism from freeze through deploy to post-launch observation**. The system MUST guarantee that what was tested is exactly what ships, and that post-launch drift is detectable without new infrastructure.

The existing codebase provides concrete data foundations to build on:

- **Qdrant payloads** carry 10+ fields per point (`chunk_id`, `document_id`, `document_name`, `chunk_index`, `text`, `source_path`, `parsed_path`, `char_start`, `char_end`), with collection names `enterprise_rag_v1` (mock, 32-dim) and `enterprise_rag_v1_local_bge_m3` (production, 1024-dim)
- **Event logs** and **request traces** are JSONL-per-day files under `data/event_logs/` and `data/request_traces/`, each record containing 30+ fields including `trace_id`, `category`, `action`, `outcome`, `mode`, `top_k`, `details` with nested retrieval diagnostics (recall counts, filter counts, stage durations, branch weights, quality thresholds)
- **Identity bootstrap** (`identity_bootstrap.json`) defines roles, departments, and user-department mappings; the ACL seed YAML at `eval/retrieval_document_acl_seed.yaml` already maps documents to departments with `retrieval_department_ids` for supplemental access
- **System config** (`data/system_config.json`) stores runtime controls: query profiles, model routing, reranker config, degrade controls, concurrency, prompt budget, and supplemental quality thresholds
- **Eval samples** (`eval/retrieval_samples.yaml`) currently 43 samples with `id`, `query`, `query_type`, `expected_doc_ids`, `expected_chunk_type`, `supplemental_expected`, `requester_department_id`, verified against live index
- **Eval results** are JSON with `summary.total_samples`, `summary.metrics` (top1_accuracy, topk_recall, supplemental precision/recall, heuristic chunk type match rates, term coverage), and `by_query_type` / `by_department` breakdowns

The data-architect defines how these structures feed into the freeze mechanism, what additional exports are required, and what validation rules MUST hold at each pipeline stage.

## Feature Point Index

| Feature | Document | Data-Architect Focus |
|---------|----------|---------------------|
| F-002 | @analysis-F-002-bundle-freeze.md | Corpus manifest schema from Qdrant scroll, ACL seed from identity bootstrap + document metadata join, index version from collection config + embedding settings, config snapshot from system_config.json, validation rules |
| F-003 | @analysis-F-003-eval-calibration.md | Eval dataset schema evolution (YAML to extended YAML), sample type coverage targets, per-sample score capture, score distribution export, eval-bundle binding via bundle_id |
| F-008 | @analysis-F-008-monitoring-dashboard.md | JSONL parsing of event_logs and request_traces, metric extraction (score distribution, mode distribution, evidence gate trigger rate), bundle drift detection against launch-bundle.json |
| Cross-cutting | @analysis-cross-cutting.md | Shared hash standards, bundle identity convention, validation framework, post-launch data migration path, data size estimates |

## Cross-Feature Summary

The three features share one invariant: **every data artifact MUST reference the same bundle_id**. The bundle freeze (F-002) defines what gets frozen. The eval calibration (F-003) runs against that frozen state and records the bundle_id in results. The monitoring dashboard (F-008) compares live production signals against the frozen baseline. If any link breaks -- eval runs against a different corpus, or monitoring cannot detect that production drifted from the frozen bundle -- the evidence chain is invalid.

Key shared decisions: SHA-256 for all content hashes, ISO 8601 UTC for all timestamps, `bundle-{YYYYMMDD}-{short_hash}` for bundle identity, and fail-fast validation with `bundle-validation.json` output. The post-launch optimization path (supplemental -> chunk -> router -> rerank) is preserved because each phase change triggers a new bundle freeze, leaving the old bundle archived for baseline comparison.

## Critical Data Integrity Risks

1. **Corpus drift between freeze and eval**: If documents are re-ingested or chunks are modified after freeze but before eval, results are meaningless. The eval runner MUST verify point count and content hashes match the bundle before proceeding.

2. **ACL mismatch**: The ACL seed at `eval/retrieval_document_acl_seed.yaml` already shows complex cross-department visibility. If eval runs with a different ACL assumption than production, supplemental recall behavior diverges. Both MUST use the same frozen ACL snapshot.

3. **Config non-determinism**: `data/system_config.json` has an `updated_at` field. If config changes between freeze and eval, quality thresholds change. The bundle MUST capture the config hash, and the eval runner MUST verify it matches.

4. **Trace data completeness**: Event logs and request traces are append-only JSONL. The monitoring script MUST handle partial lines (crash during write) and MUST support incremental analysis without re-processing historical data.
