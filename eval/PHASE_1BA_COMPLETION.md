# Retrieval Phase 1B-A Completion Report

**Status:** COMPLETED (with boundaries)
**Date:** 2026-04-02
**Scope:** Experiment infrastructure, diagnostics consistency, regression tests
**NOT Completed:** Final supplemental threshold calibration (blocked by sample availability)

---

## 1. What Was Completed

### 1.1 Threshold Experiment Infrastructure

**Files Modified:**
- [scripts/eval_retrieval.py](scripts/eval_retrieval.py) — Added threshold matrix experiment capability

**New Features:**
- `--threshold-override` flag for single threshold experiments
- `--threshold-matrix` flag for running multiple experiments from YAML
- `--experiment-name` flag for naming experiment results
- Automatic snapshot/restore of original thresholds
- Comparison table output across experiments

**Usage Examples:**
```bash
# Single threshold override
python scripts/eval_retrieval.py --threshold-override top1_threshold=0.60,avg_top_n_threshold=0.50

# Matrix experiment
python scripts/eval_retrieval.py --threshold-matrix eval/threshold_matrix.yaml
```

### 1.2 Experiment Templates

**New Files:**
- [eval/experiments/](eval/experiments/) — Directory for experiment results
- [eval/threshold_matrix.yaml](eval/threshold_matrix.yaml) — Sample threshold matrix with 5 experiment configurations

### 1.3 Diagnostic Consistency Tests

**Files Modified:**
- [backend/tests/test_retrieval_chat.py](backend/tests/test_retrieval_chat.py) — Added 7 new regression tests

**New Tests:**
1. `test_supplemental_diagnostics_department_sufficient_populates_all_quality_fields`
   - Verifies all diagnostic fields populated when department is sufficient
   - Checks `primary_threshold`, `primary_top1_score`, `primary_avg_top_n_score`
   - Checks `quality_top1_threshold`, `quality_avg_threshold`

2. `test_supplemental_diagnostics_department_insufficient_populates_trigger_basis`
   - Verifies `trigger_basis == "department_insufficient"` when count < threshold

3. `test_supplemental_diagnostics_department_low_quality_populates_quality_fields`
   - Verifies `trigger_basis == "department_low_quality"` when quality < threshold
   - Verifies quality scores vs thresholds in diagnostics

4. `test_supplemental_diagnostics_fine_query_uses_stricter_thresholds`
   - Verifies fine-grained queries use `fine_query_*_threshold` values
   - Verifies supplemental triggered due to stricter thresholds

5. `test_supplemental_diagnostics_truncate_to_top_k_false_uses_rerank_top_n_threshold`
   - Verifies `truncate_to_top_k=False` uses `rerank_top_n` as threshold window
   - Important for chat/SOP pipeline that needs larger candidate pools

6. `test_supplemental_diagnostics_quality_thresholds_from_system_config_override_defaults`
   - Verifies `_internal_retrieval_controls` from system config override Settings defaults

7. `test_supplemental_diagnostics_consistent_across_structured_diagnostic_and_raw`
   - Verifies `RetrievalDiagnostic` structured fields match raw dict values
   - Ensures no drift between diagnostic layers

---

## 2. Current Baseline State

### 2.1 Verified Sample Set

**Location:** [eval/retrieval_samples.yaml](eval/retrieval_samples.yaml)
**Total Samples:** 19 verified
**Distribution:**
- `exact` queries: 12
- `semantic` queries: 7
- Departments: `dept_after_sales` (3), `dept_assembly` (10), `dept_digitalization` (6)

### 2.2 Critical Limitation

**`supplemental_expected=true` count: 0**

All 19 verified samples have `supplemental_expected: false`. This means:
- Cannot evaluate `supplemental_precision` (denominator = 0)
- Cannot evaluate `supplemental_recall` (no positive cases)
- Cannot validate threshold calibration against ground truth

### 2.3 Latest Evaluation Results

**Location:** [eval/results/eval_20260402_140610.json](eval/results/eval_20260402_140610.json)

| Metric | Value |
|--------|-------|
| `top1_accuracy` | 100% |
| `topk_recall` | 100% |
| `expected_doc_coverage_avg` | 100% |
| `supplemental_precision` | N/A (no `supplemental_expected=true` samples) |
| `supplemental_recall` | N/A (no `supplemental_expected=true` samples) |
| `conservative_trigger_count` | 0 |

**Interpretation:** The current verified sample set only covers cases where:
- The correct document is within the requester's department
- No cross-department supplemental is expected

---

## 3. What Was NOT Completed (and Why)

### 3.1 Final Supplemental Threshold Calibration

**Status:** BLOCKED

**Reason:** No `supplemental_expected=true` verified samples exist in the current set.

**What's Needed for 1B-B:**
1. Identify queries where the answer requires cross-department knowledge
2. Verify expected document IDs against the indexed corpus
3. Mark `supplemental_expected: true` in samples
4. Run threshold matrix experiments to calibrate

### 3.2 Provisional Threshold Recommendations

**NOT RECOMMENDED to change defaults at this time.**

Current defaults in Settings:
- `top1_threshold`: 0.55
- `avg_top_n_threshold`: 0.45
- `fine_query_top1_threshold`: 0.85
- `fine_query_avg_top_n_threshold`: 0.60

**Why not change:**
- No positive supplemental cases to validate against
- Changing thresholds without ground truth is speculation
- Current settings are conservative (prefer precision over recall)

---

## 4. Public Contract Compliance

### 4.1 No Public Field Expansion

**Verified:**
- No new fields added to `system-config` public response
- `_internal_retrieval_controls` remains internal-only
- No new `retrieval/search` or `chat/ask` request/response fields

### 4.2 Consistent Supplemental Logic

**Verified:**
- `retrieval/search`, `chat/ask`, and SOP generation all use the same `RetrievalService.search_candidates()` path
- Supplemental quality threshold evaluation is centralized in `_collect_department_priority_candidates()`
- No endpoint-specific threshold overrides

---

## 5. Test Results Summary

```
backend/tests/test_retrieval_chat.py ........ 54 passed
backend/tests/test_system_config_service.py ... 16 passed
backend/tests/test_system_config_endpoints.py . 10 passed
```

All existing tests continue to pass.

---

## 6. Next Steps for Phase 1B-B

### 6.1 Sample Collection

**Priority: P0**

Need to add at least 10-15 samples with `supplemental_expected: true`:
- Cross-department policy queries
- Cross-department safety procedures
- Cross-department technical references

### 6.2 Sample Verification Process

1. Identify candidate query
2. Run retrieval with `sys_admin` to see all documents
3. Confirm expected document is in different department than requester
4. Add to `retrieval_samples.yaml` with `supplemental_expected: true`

### 6.3 Threshold Calibration

Once samples are ready:
```bash
python scripts/eval_retrieval.py --threshold-matrix eval/threshold_matrix.yaml
```

Then analyze:
- `supplemental_precision` (TP / (TP + conservative))
- `supplemental_recall` (TP / (TP + FN))
- Per-threshold comparison table

---

## 7. Modified Files Summary

| File | Change Type |
|------|-------------|
| `scripts/eval_retrieval.py` | Modified (added threshold experiment features) |
| `backend/tests/test_retrieval_chat.py` | Modified (added 7 regression tests) |
| `eval/experiments/` | Created (directory) |
| `eval/threshold_matrix.yaml` | Created (experiment template) |

---

## 8. Conclusion

Phase 1B-A is complete for infrastructure and diagnostics. The experiment pipeline is ready, regression tests are in place, and diagnostic fields are consistent.

However, **Phase 1B-B (actual threshold calibration) cannot proceed** until verified samples with `supplemental_expected=true` are added to the sample set. Without positive supplemental cases, any threshold changes would be uninformed speculation.

**Recommendation:** Prioritize cross-department sample collection before attempting threshold calibration.
