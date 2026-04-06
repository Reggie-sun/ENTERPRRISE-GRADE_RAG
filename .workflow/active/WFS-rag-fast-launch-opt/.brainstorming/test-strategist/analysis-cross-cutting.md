# Cross-Cutting Test Strategy: RAG Fast Launch

**Role**: Test Strategist
**Date**: 2026-04-06
**Scope**: Decisions spanning F-001, F-003, F-004

## 1. Score Threshold Calibration Methodology

### 1.1 Score Distribution Analysis

The evidence gate threshold MUST be derived from the actual score distribution of the expanded eval dataset (F-003). The calibration method:

1. Run the full 60-80 sample eval against the frozen bundle
2. Extract `top1_score` for every sample, grouped by:
   - query_type (exact vs semantic)
   - expected_granularity (fine vs coarse)
   - supplemental_expected (true vs false)
3. Identify the score floor of correct retrievals and the score ceiling of incorrect retrievals

### 1.2 Separation Analysis

The threshold MUST be placed in the gap between the lowest correct score and the highest incorrect score. If no clean gap exists (which is likely given current data):

- Calculate the score at which Youden's J statistic (sensitivity + specificity - 1) is maximized on the ROC curve
- Apply a safety margin of 0.05 above the optimal point (favoring abstention over wrong answer)
- The safety margin is justified because the product principle is "wrong abstention is better than wrong answer"

### 1.3 Stratified Threshold Consideration

Current data shows score distributions differ by query type:
- exact/fine queries: scores tend to cluster high (0.80-1.00)
- semantic/coarse queries: scores are more dispersed

The evidence gate MAY use a single threshold or a stratified threshold (one for exact/fine, one for semantic/coarse). Decision criteria:
- If the ROC curves for the two groups are similar (AUC difference < 0.05), use a single threshold
- If the ROC curves diverge significantly, use stratified thresholds

### 1.4 Threshold Validation Protocol

After selecting a candidate threshold:

1. **Retrospective validation**: Apply the threshold to the existing 43-sample results. Count:
   - True abstentions (correctly blocked): should be 0 given current 97.7% top1 accuracy
   - False abstentions (wrongly blocked): count and list these
   - False passes (wrongly allowed): must be 0
2. **Prospective validation**: Run the threshold against the new 17-37 samples (F-003 additions). Same counts.
3. **Edge case analysis**: Manually review any sample within 0.10 of the threshold

## 2. Extended Eval Dataset Design (60-80 Samples)

### 2.1 Target Distribution

The expanded dataset MUST achieve balanced coverage across four dimensions:

| Dimension | Current (43) | Target (60-80) | Rationale |
|-----------|-------------|-----------------|-----------|
| query_type: exact | 24 (56%) | 30-35 (45-50%) | Slight reduction in proportion; still dominant type |
| query_type: semantic | 19 (44%) | 25-35 (40-50%) | Significant absolute increase; weakest area |
| granularity: fine | 24 (56%) | 32-38 (50-55%) | Maintain absolute count |
| granularity: coarse | 19 (44%) | 28-38 (45-50%) | Significant absolute increase |
| supplemental: false | 20 (47%) | 26-32 (40-45%) | Same-department queries |
| supplemental: true | 23 (53%) | 30-40 (50-55%) | Cross-department queries |

### 2.2 New Sample Priority

Given that semantic/coarse queries are the weakest area, new samples MUST prioritize:

1. **Semantic queries over existing documents**: Rephrase existing exact queries using synonyms, broader descriptions, or natural language without specific codes. Target: 10-15 new semantic samples.

2. **Coarse-grained queries**: Ask about document-level summaries, process overviews, or cross-section comparisons rather than specific parameter values. Target: 8-12 new coarse samples.

3. **Cross-department coverage parity**: Ensure each of the 3 departments (after_sales, assembly, digitalization) has at least 15 samples as requester. Current counts (13/16/14) are close but MUST reach parity in the expanded set.

4. **Boundary-adjacent queries**: Queries where the system might reasonably retrieve a partially-relevant document. These stress-test the evidence gate. Target: 5-8 samples.

### 2.3 Sample Sourcing

New samples SHOULD come from:

- **Curated rephrasing**: Take existing exact queries and rewrite them in natural language without codes/identifiers (simulates how a non-expert user would ask)
- **Document-guided creation**: Read the indexed documents and create questions that ask about document content at the section/chapter level
- **Anti-pattern queries**: Craft queries that are tangentially related but should NOT retrieve specific documents (tests false positive detection)
- **NOT from production logs**: The system is not yet in production; do not fabricate production-like logs

### 2.4 Sample Quality Gates

Every new sample MUST satisfy:

- `expected_doc_ids` is a non-empty list of real document IDs in the current index
- The query can be verified against the live `/api/v1/retrieval/search` endpoint (status transitions from `unverified` to `verified`)
- At least one domain expert confirms the expected_doc_ids are correct for the query
- The sample has a clear `query_type` and `expected_granularity` classification

## 3. Human Review Selection Criteria

### 3.1 Sample Selection from Eval Results

The 20-30 human review samples MUST be selected to cover all five buckets. Selection strategy:

1. **Stratified random sampling**: Divide the eval results into strata by query_type x granularity, then randomly select from each stratum
2. **Deliberate boundary inclusion**: Include all samples where the top1_score is within 0.15 of the evidence gate threshold (these are the most ambiguous cases)
3. **Error focus**: Include ALL samples where automated metrics show failure (top1 miss, wrong chunk type)
4. **Supplemental trigger coverage**: Include at least 5 samples where supplemental was triggered and 5 where it was not

### 3.2 Bucket Allocation Guidance

| Bucket | Target Count | Selection Priority |
|--------|-------------|-------------------|
| correct | 12-15 | Random from high-confidence results |
| abstained | 3-5 | All evidence-gate-triggered samples (if any) |
| unsupported-query | 2-3 | Queries about topics not in the corpus |
| wrong-with-citation | 0-2 | All top1 misses MUST be included |
| permission-boundary-failure | 2-3 | Cross-department queries where auth might fail |

### 3.3 Reviewer Qualification

Reviewers MUST:
- Have domain knowledge of at least one department (after_sales, assembly, or digitalization)
- Understand the system's positioning as an evidence-grounded Q&A system
- Be different from the person who created the eval samples (avoid confirmation bias)

Reviewers SHOULD NOT need technical knowledge of the retrieval pipeline.

## 4. Go/No-Go Decision Framework

### 4.1 Hard Gates (ALL must pass)

| Gate ID | Condition | Measurement | Failure Action |
|---------|-----------|-------------|----------------|
| G-1 | permission-boundary-failure = 0 | Human review bucket count | Block launch; fix ACL |
| G-2 | citation presence = 100% | Automated eval metric | Block launch; fix citation pipeline |
| G-3 | wrong-with-citation = 0 | Human review bucket count | Block launch; lower threshold |

### 4.2 Soft Gates (SHOULD pass; require explicit sign-off to override)

| Gate ID | Condition | Measurement | Override Authority |
|---------|-----------|-------------|-------------------|
| S-1 | top1_accuracy >= 0.90 | Automated eval | Product owner + test lead |
| S-2 | human correct bucket >= 80% | Human review | Product owner |
| S-3 | evidence gate trigger rate 5-20% | Production monitoring (Day 1) | System architect |
| S-4 | semantic query top1 >= 0.85 | Automated eval | Test lead |

### 4.3 Decision Process

1. After F-003 completes: compile automated metrics, check S-1 and S-4
2. After F-001 calibration: record threshold, check trigger rate against historical data
3. After F-004 completes: check all hard gates (G-1, G-2, G-3) and soft gate S-2
4. Convene go/no-go meeting (30 minutes): test-strategist presents evidence, product-owner makes final call

## 5. Post-Launch Monitoring Test Strategy

### 5.1 Day-1 Smoke Test

Within the first 4 hours of launch, the test-strategist (or designated person) MUST run a 10-sample smoke test against production:

- 5 high-confidence queries from the eval set (should all pass)
- 3 boundary queries near the evidence gate threshold
- 1 out-of-scope query (should abstain)
- 1 cross-department query (should respect ACL)

### 5.2 First-Week Metrics Watch

Daily review of:

- Evidence gate trigger rate (from event_log response_mode="evidence_gate_abstain")
- Average top1_score distribution (from request_traces)
- Citation count per response (should be > 0 for all non-abstain responses)
- Latency percentiles (p50, p95, p99) to catch evidence gate overhead

### 5.3 Regression Trigger

Any of the following MUST trigger a regression investigation:

- Evidence gate trigger rate changes by more than 10 percentage points from Day-1 baseline
- Any user report of a "confident wrong answer" (this is G-3 violation in production)
- Any user report of accessing documents outside their department (this is G-1 violation)

## 6. Statistical Significance Considerations

### 6.1 Sample Size Adequacy

With 60-80 samples, the 95% confidence interval for a proportion p is approximately:

- At p=0.95: CI is +/- 0.054 (60 samples) to +/- 0.047 (80 samples)
- At p=0.90: CI is +/- 0.076 (60 samples) to +/- 0.066 (80 samples)

This means:
- A measured top1_accuracy of 0.95 with 80 samples gives CI [0.903, 0.997]
- We can distinguish "great" (>=0.95) from "acceptable" (>=0.90) but not with high precision
- This is adequate for a launch decision but MUST be noted in the evidence package

### 6.2 Human Review Inter-Rater Reliability

With 20-30 samples and 2 reviewers:
- Cohen's kappa SHOULD be calculated for the 5-bucket classification
- If kappa < 0.60, a third reviewer MUST adjudicate disagreements
- If kappa >= 0.80, the review is considered reliable

### 6.3 Bundle Immutability

Any change to the bundle (corpus, index, config, ACL) after eval calibration begins MUST invalidate all test results. The test-strategist MUST maintain a bundle integrity check at each stage:

- F-003 start: record bundle hash
- F-003 end: verify bundle hash unchanged
- F-001 calibration: verify bundle hash unchanged
- F-004 review: verify bundle hash unchanged
- Launch: bundle hash matches eval bundle
