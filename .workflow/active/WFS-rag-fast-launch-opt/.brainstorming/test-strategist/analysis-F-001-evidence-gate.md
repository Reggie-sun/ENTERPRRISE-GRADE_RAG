# F-001: Evidence Gate Test Strategy

**Feature**: Chat layer score threshold + citation validation
**Priority**: High
**Date**: 2026-04-06

## 1. Problem Statement

The RAG system retrieves documents and generates answers regardless of retrieval quality. When the best retrieved citation has a low relevance score, the LLM may still produce a confident but unfounded answer. The evidence gate MUST prevent this by checking the top-1 citation score against a calibrated threshold before allowing answer generation.

The test strategy for this feature addresses three questions:
1. What threshold value maximizes safety while minimizing false abstentions?
2. How to validate the threshold against existing and new eval results?
3. How to regression-test the gate so future changes do not silently degrade it?

## 2. Threshold Determination Method

### 2.1 Data Source

The threshold MUST be derived from the expanded eval dataset (F-003, 60-80 samples). Using only the current 43 samples is insufficient because:

- The score distribution has gaps (especially in semantic/coarse queries)
- No samples currently fail the top1 test (97.7% accuracy), leaving no data about the "wrong answer" score range
- The boundary samples (boundary-001 through boundary-005, lexical-001/002, hybrid-001/002) are designed to exercise threshold boundaries but are currently unverified

### 2.2 ROC Curve Construction

From the expanded eval, construct a binary classification per sample:

- **Positive class**: Correct retrieval (top1 doc matches expected_doc_ids)
- **Negative class**: Incorrect retrieval (top1 doc does not match)

For each candidate threshold value (stepping from 0.0 to 1.0 in 0.01 increments):
- **True Positive (TP)**: Correct retrieval with score >= threshold (gate allows, answer is correct)
- **False Positive (FP)**: Incorrect retrieval with score >= threshold (gate allows, answer is wrong)
- **True Negative (TN)**: Incorrect retrieval with score < threshold (gate blocks, abstention is correct)
- **False Negative (FN)**: Correct retrieval with score < threshold (gate blocks, unnecessary abstention)

Plot the ROC curve (TPR vs FPR) and calculate AUC.

### 2.3 Optimal Threshold Selection

Apply two criteria in order:

**Criterion 1: Zero tolerance for FP (wrong-with-citation)**

Find the highest threshold where FP = 0. This is the minimum safe threshold. If FP = 0 at threshold 0.0 (i.e., all incorrect retrievals have score 0.0), then the threshold can be set low. If FP > 0 at all thresholds below some value T, then T is the floor.

**Criterion 2: Minimize FN within the zero-FP constraint**

Among all thresholds that achieve FP = 0, select the one that minimizes FN (maximizes TPR). This is the threshold that allows the most correct answers while never allowing a wrong one.

**Criterion 3: Safety margin**

Add a margin of 0.03-0.05 above the selected threshold. This accounts for:
- Score variance not captured in 60-80 samples
- Production query distribution differing from eval
- Future model or index changes shifting score distributions

### 2.4 Fallback: Insufficient Negative Samples

If the expanded eval still shows near-100% top1 accuracy (likely given current trends), there will be very few negative samples. In this case:

1. Synthesize negative samples: take 10 real queries and pair them with documents they should NOT retrieve (different topic entirely). Run retrieval and record the scores of incorrect top-1 results.
2. Use the lowest score of correct retrievals as the "safe floor" and the highest score of synthetic negative retrievals as the "danger ceiling".
3. Set threshold at the midpoint between safe floor and danger ceiling, with safety margin toward the safe floor.

### 2.5 Threshold Ranges for Reference

Based on current threshold_matrix.yaml experiments:
- `top1_threshold`: 0.35 to 0.95 (experiment range); the current `current_defaults` uses 0.55
- `fine_query_top1_threshold`: 0.65 to 0.99 (experiment range); current is 0.85

The evidence gate threshold operates at a different level (citation score, not retrieval internal score), so it SHOULD be calibrated independently. However, if citation scores correlate with internal retrieval scores, the evidence gate threshold MAY be approximately:
- 0.55-0.65 for general queries (matching current top1_threshold range)
- 0.70-0.85 for fine-grained queries (matching fine_query_top1_threshold range)

These are starting hypotheses; the actual value MUST come from data.

## 3. Threshold Validation

### 3.1 Retrospective Validation Against Existing 43 Samples

Extract `top1_score` from the latest eval results (eval_20260406_113356.json). Apply the candidate threshold:

| Check | Expected Outcome | Action if Failed |
|-------|-----------------|------------------|
| No correct retrieval blocked (FN = 0) | All 42 correct top-1 results have score >= threshold | Lower threshold or investigate score anomalies |
| No incorrect retrieval allowed (FP = 0) | The 1 incorrect top-1 result (if any) has score < threshold | Raise threshold |
| Boundary samples near threshold | Count samples with score within 0.10 of threshold | Manual review each |

### 3.2 Prospective Validation Against New Samples

Run the 17-37 new samples from F-003 through the same pipeline:

- Record which samples would be blocked by the evidence gate
- Every blocked sample MUST be reviewed: is the block correct (bad retrieval) or incorrect (valid answer suppressed)?
- If any valid answer is suppressed, the threshold is too aggressive

### 3.3 Edge Case Catalog

The evidence gate MUST be specifically tested against these edge cases:

| Edge Case | Test Method | Expected Behavior |
|-----------|------------|-------------------|
| Score exactly at threshold | Craft or find a sample where top1_score equals the threshold | MUST be treated as "below threshold" (fail-closed) |
| Score within 0.01 of threshold | Run boundary samples; check behavior | SHOULD log as "near-miss" for monitoring |
| Empty citation list | Query that returns 0 results | MUST abstain (existing behavior; gate is redundant) |
| Multiple citations, top1 below threshold but top2 above | Craft multi-hit query with top1 weak | Gate checks top1 only; MUST abstain |
| Citation with null/missing score | Simulate citation without score field | MUST fail-open (allow generation); log warning |
| Score inflation from supplemental | Cross-dept query where supplemental boosts score | Verify that supplemental-boosted scores are calibrated |
| Rerank changes score ordering | Rerank promotes different doc to top1 | Gate MUST use post-rerank score |

### 3.4 Conflicting Citations

When the top-1 citation is from document A but the top-2 and top-3 are from document B (a different, potentially conflicting document):

- The evidence gate checks only the top-1 score. If top-1 passes the threshold, the answer proceeds.
- This is acceptable for launch because the LLM is instructed to cite sources; conflicting citations will surface in the answer.
- Post-launch enhancement: the gate MAY check citation coherence (all top-3 from the same document cluster).

## 4. Regression Testing Approach

### 4.1 Gate Regression Test Suite

Create a dedicated test file: `backend/tests/test_evidence_gate.py`

The test suite MUST include:

1. **Threshold boundary tests**: Synthetic citations with scores at threshold, threshold-0.01, threshold+0.01
2. **Empty input tests**: Empty citation list, None citations
3. **Config override tests**: Gate disabled in config, custom threshold in config
4. **Fail-open tests**: Simulate config read failure, malformed citation scores
5. **Integration test**: Full chat pipeline with a query that triggers the gate

### 4.2 Continuous Eval Hook

After implementation, the existing eval pipeline MUST be extended to:

1. Record `evidence_gate_would_trigger: bool` for every sample
2. Record `evidence_gate_top1_score: float` for every sample
3. Report a new metric: `evidence_gate_false_block_rate` (proportion of correct retrievals that would be blocked)
4. Alert if `evidence_gate_false_block_rate > 0.05` on any eval run

This ensures that future changes to the retrieval pipeline (chunk size, embedding model, rerank strategy) are automatically checked against the evidence gate.

### 4.3 Bundle Change Regression

If the launch bundle (F-002) is modified post-launch:

1. Re-run the full eval (60-80 samples) with evidence gate enabled
2. Compare `evidence_gate_false_block_rate` and `evidence_gate_trigger_rate` to launch baseline
3. Any increase in false block rate > 2 percentage points MUST be investigated before deploying the bundle change

## 5. Observability Requirements

### 5.1 Trace Fields

The evidence gate MUST write to the existing request_trace when triggered:

```json
{
  "evidence_gate_result": {
    "triggered": true,
    "top1_score": 0.45,
    "threshold": 0.60,
    "reason": "insufficient_score"
  }
}
```

### 5.2 Monitoring Queries

Post-launch, the monitoring dashboard (F-008) SHOULD support these queries:

- Gate trigger rate over time (hourly/daily)
- Top-1 score distribution histogram (for queries that pass vs. fail the gate)
- Average latency impact (gate evaluation time should be < 1ms)

## 6. Implementation Test Checklist

Before the evidence gate is considered "tested and ready":

- [ ] Threshold is calibrated against 60+ sample expanded eval
- [ ] Retrospective validation on original 43 samples shows 0 false blocks
- [ ] Prospective validation on new samples shows 0 false blocks
- [ ] All edge cases from Section 3.3 are tested
- [ ] `test_evidence_gate.py` has >= 10 test cases
- [ ] Integration test with full chat pipeline passes
- [ ] Fail-open behavior verified (config failure does not block all answers)
- [ ] Bundle integrity check passes (eval bundle matches deployment bundle)
