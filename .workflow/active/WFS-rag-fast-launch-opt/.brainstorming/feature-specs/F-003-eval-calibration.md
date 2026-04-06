# Feature Spec: F-003 - Eval Calibration

**Priority**: High
**Contributing Roles**: test-strategist (lead), data-architect, system-architect
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL extend the existing evaluation dataset from 43 samples to 60-80 samples with balanced type coverage, run calibration against the frozen bundle (F-002), produce a score distribution report for evidence gate threshold calibration (F-001), and output eval results bound to the bundle_id.

- The expanded dataset MUST achieve minimum coverage: exact >=15, fine >=10, semantic >=15, coarse >=10, permission >=5.
- Every new sample MUST have `expected_doc_ids` pointing to real documents in the current index, EXCEPT anti-pattern samples which MUST have `expected_doc_ids: []` and `should_refuse: true`.
- The eval runner MUST verify bundle integrity (point count, config hash, embedding model) before executing.
- Every eval result MUST include `bundle_id`, per-sample `top1_score`, `top5_scores`, and `expected_doc_scores`.
- The score distribution report MUST provide threshold candidates: `conservative_95`, `balanced_90`, `aggressive_80`.
- The recommended initial threshold is `conservative_95` (95% of correct hits score above this value).
- The eval MUST abort if bundle verification fails at any point.

## 2. Design Decisions

### 2.1 Sample Type Coverage Targets

**Decision**: Target 65-75 samples (not the full 80), with new additions prioritizing semantic/coarse queries and anti-pattern samples.

**Current gaps addressed**:
- Semantic/coarse queries: 19 existing, target 25-30. Adding 6-11 new semantic samples.
- Coarse-type queries: 0 existing dedicated coarse samples. Adding 3-5 new coarse samples.
- Anti-pattern (out-of-scope) queries: 0 existing. Adding 3-5 with `expected_doc_ids: []`.
- Department parity: each of 3 departments MUST have >=15 samples.

**Rationale for anti-pattern samples**: The evidence gate (F-001) needs negative examples -- queries where the system SHOULD NOT find a relevant document. Without these, threshold specificity cannot be calibrated.

**New sample categories**:
| Category | Count | Description |
|----------|-------|-------------|
| A: Semantic rephrasings | 10-12 | Existing exact queries rewritten in natural language |
| B: Coarse summary queries | 6-8 | Document-level structure questions |
| C: Anti-pattern / out-of-scope | 3-5 | Queries about topics not in corpus |
| D: Cross-department parity | 3-5 | Fill department coverage gaps |

**Source roles**: test-strategist (target dataset design, sample priority), data-architect (sample type coverage requirements).

### 2.2 Anti-Pattern expected_doc_ids Handling (RESOLVED)

**Decision**: Anti-pattern samples (Category C) MUST have `expected_doc_ids: []` and `should_refuse: true`. The eval runner MUST exempt these samples from the `expected_doc_ids` non-empty validation rule.

**Conflict history**: The original eval framework assumed `expected_doc_ids` is always non-empty. Anti-pattern samples break this assumption. Resolution: the eval runner skips `expected_doc_ids` validation when `should_refuse=true`, treating an empty result list as a correct outcome.

**Source roles**: data-architect (sample schema evolution), test-strategist (anti-pattern sample design).

### 2.3 Per-Sample Score Capture for Threshold Calibration

**Decision**: Every eval result MUST capture `top1_score`, `top5_scores`, `expected_doc_scores`, and `score_gap` per sample. These feed into an aggregate `score_distributions` section with threshold candidates.

**Data model extension**: New fields added to eval results JSON:
- `top1_score` (float or null): Score of top-1 result
- `top5_scores` (list[float]): Scores of all returned results
- `expected_doc_scores` (dict[str, float or null]): Score of each expected document
- `score_gap` (float or null): top1_score minus first_expected_doc_score; null if hit_at_1 is true

**Aggregate output**: `score_distributions` section with `overall`, `by_type`, and `threshold_candidates` subsections.

**Source roles**: data-architect (per-sample score capture, score distribution export), test-strategist (threshold calibration support).

### 2.4 Eval-Bundle Binding via bundle_id

**Decision**: Every eval result file MUST include `bundle_id` at the top level. The eval runner MUST verify the bundle before executing (point count, config hash, embedding model, collection name).

**Pre-run verification steps**:
1. Read frozen `launch-bundle.json`
2. Verify `bundle_id` is present and well-formed
3. Verify `index.point_count` matches current Qdrant state
4. Verify `index.embedding_model` matches `Settings.embedding_model`
5. Verify `config.system_config_hash` matches current system_config.json hash
6. Abort if any verification fails

**Post-run output**: Every eval result includes `bundle_id`, `eval_run_at`, `corpus_verified`, `config_verified`.

**Rationale**: Running eval against a different corpus/index/config than what was frozen produces misleading results that cannot serve as launch evidence.

**Source roles**: data-architect (eval-bundle binding, pre-run verification), system-architect (bundle freeze contract).

## 3. Interface Contract

### 3.1 Eval Dataset Schema Extension (YAML)

New optional fields (backward-compatible):

```yaml
- id: semantic-020
  query: "..."
  query_type: semantic
  expected_granularity: coarse
  expected_doc_ids: ["doc_..."]
  expected_chunk_type: procedure
  expected_terms: ["..."]
  supplemental_expected: false
  requester_department_id: "dept_..."
  status: verified
  source: synthetic
  note: "..."
  difficulty: medium          # NEW: easy/medium/hard
  query_language: chinese     # NEW: chinese/english/mixed
  expected_min_score: 0.65    # NEW: minimum acceptable top-1 score
```

### 3.2 Eval Results Schema Extension (JSON)

```json
{
  "bundle_id": "bundle-20260406-a1b2c3d4",
  "eval_run_at": "2026-04-06T14:00:00Z",
  "corpus_verified": true,
  "config_verified": true,
  "total_samples": 72,
  "summary": { "metrics": {} },
  "results": [{
    "sample_id": "exact-001",
    "top1_score": 0.98,
    "top5_scores": [0.98, 0.85, 0.72, 0.65, 0.58],
    "expected_doc_scores": {"doc_...": 0.98},
    "score_gap": null,
    "should_refuse": false
  }],
  "score_distributions": {
    "overall": { "top1_mean": 0.72, "top1_median": 0.75 },
    "by_type": { "exact": {}, "semantic": {}, "coarse": {} },
    "threshold_candidates": {
      "conservative_95": 0.50,
      "balanced_90": 0.45,
      "aggressive_80": 0.38
    }
  }
}
```

### 3.3 Deliverables

| Deliverable | Format | Consumer |
|------------|--------|----------|
| Expanded eval dataset | `eval/retrieval_samples.yaml` (updated) | F-001, F-004 |
| Calibration results | `eval/results/eval_YYYYMMDD_calibration.json` | F-001, go/no-go |
| Score distribution report | Section in calibration results JSON | F-001 threshold calibration |
| Per-sample audit | `eval/results/audit_YYYYMMDD.csv` | F-004 sample selection |

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| Bundle dependency | F-002 MUST complete before F-003 can run |
| 1-day timeline | Sample creation + calibration must complete in 1 day |
| No production logs | System is not yet in production; samples are synthetic |
| Statistical power | 60-80 samples gives CI width ~0.07-0.10; adequate for go/no-go but not for detecting small differences |

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Near-100% top1 accuracy yields insufficient negatives | High | Medium | Synthesize negative samples: pair real queries with unrelated documents |
| New samples too easy (selection bias) | Medium | Medium | Audit new samples for representativeness; compare score distributions |
| Department imbalance | Low | Low | Minimum 15 samples per department enforced |
| Bundle changes during eval | Low | Critical | Eval runner verifies bundle hash at start and end |

## 5. Acceptance Criteria

1. **Sample count**: Total samples >= 60, target 65-75.
2. **Type coverage**: exact >=15, semantic >=15, coarse >=10, permission >=5.
3. **Department parity**: Each of 3 departments has >=15 samples.
4. **Anti-pattern samples**: At least 3 samples with `should_refuse: true` and `expected_doc_ids: []`.
5. **All samples verified**: Every new sample transitions from `unverified` to `verified` against live retrieval endpoint.
6. **Bundle binding**: Eval results include `bundle_id` matching the frozen bundle.
7. **Score distribution**: Results include `score_distributions` with `threshold_candidates`.
8. **Baseline comparison**: No metric degrades more than 5 percentage points from baseline (top1_accuracy, topk_recall).
9. **Per-sample audit**: Every sample where `hit_at_1 = false` is individually reviewed.
10. **Confidence intervals**: Eval report includes 95% CIs for all reported proportions.

## 6. Detailed Analysis References

- @test-strategist/analysis-F-003-eval-calibration.md -- Target dataset design, sample categories, baseline comparison methodology, statistical significance, execution plan
- @test-strategist/analysis-cross-cutting.md -- Score distribution analysis, threshold calibration methodology, go/no-go framework
- @data-architect/analysis-F-003-eval-calibration.md -- Dataset schema evolution, sample type coverage requirements, score distribution tracking, eval-bundle binding
- @data-architect/analysis-cross-cutting.md -- Bundle identity propagation, hash standards, validation framework
- @system-architect/analysis-cross-cutting.md -- Bundle freeze contract, dependency sequencing

## 7. Cross-Feature Dependencies

**Depends on**:
- F-002 (bundle-freeze): MUST run against frozen bundle; `bundle_id` verification is mandatory before eval execution.

**Required by**:
- F-001 (evidence-gate): Score distribution and threshold candidates are the primary input for threshold calibration.
- F-004 (human-review): Per-sample results and score distributions feed sample selection for human review.

**Shared patterns**:
- Bundle identity: `bundle_id` propagates from F-002 through F-003 results to F-004 and F-008.
- SHA-256 content hashes: Corpus spot-check during eval uses same hash standard as bundle freeze.

**Integration points**:
- `eval/retrieval_samples.yaml` -- shared dataset between eval runner and human review
- `launch-bundle.json` -- eval reads bundle for verification; eval results reference bundle_id
- Score distribution report consumed by F-001 threshold calibration
