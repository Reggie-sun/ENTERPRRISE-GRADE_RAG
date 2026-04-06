# F-003: Eval Calibration -- Data Architecture

**Feature**: Eval Calibration (extend to 60-80 samples)
**Priority**: High
**Data-Architect Role**: Define eval dataset schema evolution, sample coverage requirements, score distribution tracking, eval-bundle binding

## 1. Overview

The eval calibration extends the existing evaluation framework from 43 samples to 60-80 samples, with emphasis on adding semantic and coarse query types. From the data-architect perspective, this requires: schema evolution rules for the eval dataset, coverage validation for balanced query type representation, per-sample score capture for evidence gate calibration, and strict binding between eval results and the frozen bundle.

## 2. Current Eval Dataset Analysis

### 2.1 Existing Schema (YAML)

The current `eval/retrieval_samples.yaml` defines each sample with:

```yaml
- id: exact-001
  query: "700000 面板急停报警 现场先查什么"
  query_type: exact
  expected_granularity: fine
  expected_doc_ids: ["doc_20260321070337_445684f4"]
  expected_chunk_type: clause
  expected_terms: ["700000", "面板急停报警", "现场先查什么"]
  supplemental_expected: false
  requester_department_id: "dept_after_sales"
  status: verified
  source: synthetic
  note: "已按当前索引验证：123.txt 中 700000 面板急停报警条目"
```

### 2.2 Existing Results Schema (JSON)

The current eval results at `eval/results/eval_*.json` contain:

```json
{
  "summary": {
    "total_samples": 43,
    "evaluated_at": "2026-04-06T03:28:40.280581+00:00",
    "metrics": {
      "top1_accuracy": 0.977,
      "topk_recall": 1.0,
      "supplemental_precision": 0.793,
      "supplemental_recall": 1.0,
      "conservative_trigger_count": 6,
      "heuristic_chunk_type_full_match_rate": 0.442,
      "heuristic_chunk_type_partial_match_rate": 0.558,
      "term_coverage_avg": 0.874
    },
    "by_query_type": {
      "exact": { "count": 24, "top1_accuracy": 1.0, "topk_recall": 1.0 },
      "semantic": { "count": 19, "top1_accuracy": 0.947, "topk_recall": 1.0 }
    },
    "by_department": {
      "dept_after_sales": { "count": 13, "top1_accuracy": 1.0 },
      "dept_assembly": { "count": 16, "top1_accuracy": 0.9375 },
      "dept_digitalization": { "count": 14, "top1_accuracy": 1.0 }
    }
  }
}
```

### 2.3 Gaps to Address

1. **No score distribution tracking**: The current eval records hit/miss but not actual scores. The evidence gate (F-001) needs score thresholds calibrated from actual score distributions. The request traces show `top1_score` and `avg_top_n_score` are available at retrieval time but not persisted in eval results.

2. **No per-sample diagnostic capture**: When a sample fails, there is no structured way to see what scores the expected documents received versus what actually ranked above them.

3. **Unbalanced query type coverage**: The existing 43 samples contain 24 exact and 19 semantic, with zero dedicated coarse-type samples. The eval note explicitly states this is "threshold experiment, not final calibration."

4. **No bundle binding**: Current eval results have no `bundle_id` field, making it impossible to trace which corpus/config state produced the results.

## 3. Dataset Schema Evolution

### 3.1 New Fields for Samples

The eval dataset YAML MUST be extended with optional fields that are backward-compatible:

```yaml
- id: semantic-020
  query: "新员工入职需要注意什么安全事项"
  query_type: semantic
  expected_granularity: coarse
  expected_doc_ids: ["doc_20260330055115_c20cfc5a", "doc_20260331021041_adff1740"]
  expected_chunk_type: procedure
  expected_terms: ["安全", "入职", "注意事项"]
  supplemental_expected: false
  requester_department_id: "dept_production_technology"
  status: verified
  source: synthetic
  note: "语义查询：描述性查询，不含精确文档代码"
  difficulty: medium
  query_language: chinese
  expected_min_score: 0.65
```

**New fields**:

| Field | Type | Required | Default | Purpose |
|-------|------|----------|---------|---------|
| `difficulty` | string | SHOULD | "medium" | easy/medium/hard; ensures balanced difficulty distribution |
| `query_language` | string | SHOULD | "chinese" | chinese/english/mixed; tracks language coverage |
| `expected_min_score` | float | SHOULD | null | Minimum acceptable top-1 score for evidence gate calibration |

Existing samples without these fields will use defaults. No migration of existing samples is required.

### 3.2 Sample Type Coverage Requirements

The expanded dataset (60-80 samples) MUST meet these minimum coverage targets:

| Type | Min Count | Max Count | Rationale | Source for New Samples |
|------|-----------|-----------|-----------|----------------------|
| exact | 15 | 20 | Core use case: fault codes, procedure names, clause numbers | Existing 24 + trim edge cases |
| fine | 10 | 15 | Abbreviated references, partial names, sub-component lookups | New samples from domain abbreviations |
| semantic | 15 | 20 | Descriptive queries without exact terms; weakest current area | Mostly new; describe procedures in natural language |
| coarse | 10 | 15 | Broad topic queries spanning multiple documents | All new; "安全生产", "设备维护" etc. |
| permission | 5 | 8 | Cross-department access boundary tests | New from ACL boundary analysis using existing acl-seed.yaml |

**Coverage validation**: The bundle freeze script MUST check eval dataset coverage. A WARNING is emitted if any type is below minimum. A CRITICAL failure is emitted if total sample count is below 60.

### 3.3 Department Coverage

The current eval shows 3 departments tested (after_sales, assembly, digitalization). The expanded dataset SHOULD cover all departments present in the ACL seed. At minimum, every department that owns documents in the corpus manifest MUST have at least 2 eval samples.

## 4. Score Distribution Tracking

### 4.1 Per-Sample Score Capture

The eval results MUST be extended to capture per-sample score information. Each sample result MUST include:

```json
{
  "sample_id": "exact-001",
  "sample_type": "exact",
  "query": "700000 面板急停报警 现场先查什么",
  "expected_doc_ids": ["doc_20260321070337_445684f4"],
  "returned_doc_ids": ["doc_20260321070337_445684f4"],
  "hit_at_1": true,
  "hit_at_3": true,
  "hit_at_5": true,
  "first_hit_rank": 1,
  "top1_score": 0.98,
  "top5_scores": [0.98, 0.85, 0.72, 0.65, 0.58],
  "expected_doc_scores": {
    "doc_20260321070337_445684f4": 0.98
  },
  "score_gap": null,
  "should_refuse": false,
  "result_count": 5,
  "elapsed_ms": 320.5
}
```

**New fields**:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `top1_score` | float or null | MUST | Score of the top-1 result; feeds evidence gate threshold |
| `top5_scores` | list[float] | MUST | Scores of all returned results |
| `expected_doc_scores` | dict[str, float or null] | MUST | Score of each expected document (null if not retrieved) |
| `score_gap` | float or null | SHOULD | top1_score minus first_expected_doc_score; null if hit_at_1 is true |

### 4.2 Score Distribution Export

The eval results MUST include an aggregate `score_distributions` section:

```json
{
  "score_distributions": {
    "overall": {
      "top1_mean": 0.72,
      "top1_median": 0.75,
      "top1_std": 0.12,
      "top1_min": 0.35,
      "top1_p10": 0.48,
      "top1_p25": 0.61,
      "top1_p75": 0.83,
      "top1_p90": 0.91,
      "top1_max": 0.99
    },
    "by_type": {
      "exact": { "top1_mean": 0.85, "top1_median": 0.88, "top1_min": 0.65 },
      "semantic": { "top1_mean": 0.62, "top1_median": 0.65, "top1_min": 0.35 },
      "coarse": { "top1_mean": 0.55, "top1_median": 0.58, "top1_min": 0.30 }
    },
    "threshold_candidates": {
      "conservative_95": 0.50,
      "balanced_90": 0.45,
      "aggressive_80": 0.38
    }
  }
}
```

### 4.3 Threshold Calibration Support

The `threshold_candidates` field provides pre-computed thresholds at different operating points for the evidence gate (F-001):

- **conservative_95**: 95% of correct hits score above this threshold. Low false positive rate, higher abstention rate. Recommended for launch.
- **balanced_90**: 90% of correct hits score above. Balanced operating point.
- **aggressive_80**: 80% of correct hits score above. More answers returned, more risk of incorrect responses.

For launch, the data-architect recommends using `conservative_95` as the initial evidence gate threshold, consistent with the product positioning of "prefer abstention over confident wrong answers."

## 5. Eval-Bundle Binding

### 5.1 Pre-Run Bundle Verification

Before running the eval, the runner MUST:

1. Read the frozen `launch-bundle.json`
2. Verify `bundle_id` is present and well-formed
3. Verify `index.point_count` matches current Qdrant state (`count_points()`)
4. Verify `index.collection_name` matches `Settings.qdrant_collection`
5. Verify `index.embedding_model` matches `Settings.embedding_model`
6. Verify `config.system_config_hash` matches current system_config.json hash
7. Record `bundle_id` in eval results output

If any verification fails, the eval MUST NOT proceed. Running eval against a different corpus/index/config than what was frozen produces misleading results that cannot serve as launch evidence.

### 5.2 Post-Run Bundle Reference

Every eval result file MUST include at the top level:

```json
{
  "bundle_id": "bundle-20260406-a1b2c3d4",
  "eval_run_at": "2026-04-06T14:00:00Z",
  "eval_runner_version": "1.0",
  "corpus_verified": true,
  "config_verified": true,
  "total_samples": 72,
  "results": { },
  "score_distributions": { }
}
```

This ensures that any future review can identify exactly which system state produced the results.

### 5.3 Corpus State Verification

In addition to point count verification, the eval runner SHOULD spot-check content integrity:
- Pick 3 random documents from the corpus manifest
- Re-compute their content hashes from current Qdrant points
- Compare against the manifest's `content_hash`
- If any mismatch, emit CRITICAL warning and halt

This prevents a subtle failure mode where point count is correct but chunk content was modified (e.g., re-ingestion with different parser settings).

## 6. Data Consistency Between Eval and Production

### 6.1 ACL Consistency

The eval runner and production system MUST use the same ACL seed. The eval currently uses `retrieval_document_acl_seed.yaml` which defines cross-department visibility. The bundle freeze exports this into `launch-bundle.json` under `acl.supplemental_access`. The eval runner MUST:
1. Load ACL from the bundle, not from the standalone YAML file
2. Verify that the bundle ACL matches the standalone YAML (WARNING if mismatch)
3. Use the bundle ACL for all permission-scoped queries

### 6.2 Config Consistency

The eval runner MUST use the same retrieval config that the bundle captures. Specifically:
- `supplemental_quality_thresholds` determine when supplemental recall triggers
- `query_profiles` determine top_k and rerank_top_n
- `reranker_routing` determines rerank strategy

If the eval runner uses different config (e.g., from a stale system_config.json), the eval results do not reflect production behavior. The runner MUST verify config hash matches the bundle.

### 6.3 Score Scale Consistency

The Qdrant Cosine similarity scores range from 0 to 1. The eval score tracking MUST use the raw scores from Qdrant without normalization. If the embedding model changes post-launch, the score scale MAY change, making pre-launch threshold calibrations invalid. This is why a new bundle and re-calibration are mandatory after any embedding model change.

## 7. Human Review Data Contract (F-004 Interface)

The eval results feed into human review (F-004). The data contract:

**Eval provides**: sample_id, query, returned chunks (top-1 to top-5), scores, hit/miss status, score_gap
**Human review adds**: 5-bucket classification (correct, abstained, unsupported-query, wrong-with-citation, permission-boundary-failure), reviewer notes, severity assessment

The human review input file MUST be a filtered subset of eval results (20-30 representative samples). The filtering criteria SHOULD select:
- All samples where `hit_at_1` is False (to verify misses are reasonable)
- A random sample of hits across all types
- All `should_refuse` samples
- Edge cases where `score_gap` is small (near-threshold decisions)

## 8. Sample Generation Guidance

### 8.1 Semantic Query Samples

Semantic queries describe information needs without using exact document terms. Each MUST be verified against the corpus to ensure at least one relevant document exists.

### 8.2 Coarse Query Samples

Coarse queries are broad topic queries that SHOULD return multiple relevant documents. `expected_doc_ids` SHOULD contain 3-5 documents. The test SHOULD use Hit@5 rather than Hit@1 as the primary metric.

### 8.3 Permission Boundary Samples

Permission samples test department isolation using the ACL seed's `supplemental_access` mappings. The existing `retrieval_document_acl_seed.yaml` provides the cross-department visibility data needed to construct these tests.
