# Test-Strategist Analysis: RAG Fast Launch Optimization

**Role**: Test Strategist
**Date**: 2026-04-06
**Scope**: F-001 (evidence-gate), F-003 (eval-calibration), F-004 (human-review)

## 1. Role Perspective

The test strategist is responsible for ensuring the RAG system ships with quantified, defensible quality evidence. The core tension: 1-week launch window demands speed, but launching an evidence-grounded Q&A system without rigorous quality gates risks reputational damage from confident wrong answers. The test strategy MUST prioritize "never confidently wrong" over "always has an answer."

Current state: 43 samples, top1_accuracy 0.977, topk_recall 1.0. These numbers look strong, but the dataset is skewed toward exact/fine queries and the threshold experiment is explicitly NOT a final calibration. The test strategy addresses three gaps: (a) insufficient sample diversity, (b) no human judgment layer, (c) no runtime quality gate.

## 2. Feature Index

| Feature | Sub-Document | Core Question |
|---------|-------------|---------------|
| F-001: evidence-gate | @analysis-F-001-evidence-gate.md | How to determine, validate, and regression-test the score threshold that decides abstain vs. answer? |
| F-003: eval-calibration | @analysis-F-003-eval-calibration.md | How to extend from 43 to 60-80 samples with balanced type coverage and achieve statistical significance? |
| F-004: human-review | @analysis-F-004-human-review.md | How to select 20-30 samples for 5-bucket human review in half a day with defensible results? |
| Cross-cutting | @analysis-cross-cutting.md | How do the three features interact? What is the go/no-go framework? What happens post-launch? |

## 3. Dependency Chain

The three features form a hard dependency chain:

```
F-003 (eval-calibration) --> F-001 (evidence-gate) --> F-004 (human-review)
```

1. F-003 produces the expanded eval dataset and score distribution
2. F-001 uses that score distribution to calibrate the threshold
3. F-004 validates both the threshold and the overall quality against human judgment

This chain MUST NOT be parallelized -- each step depends on the previous step's output.

## 4. Current Eval Gaps (Summary)

- **Type imbalance**: 24 exact vs 19 semantic samples; coarse queries are under-represented
- **No threshold-validated scores**: Current eval records `top1_score` but does not use it for pass/fail; the threshold_matrix.yaml experiments are provisional
- **No human overlay**: All metrics are automated; no sanity check against human judgment
- **Supplemental calibration incomplete**: supplemental_expected=true samples are verified for index hits but auth behavior is provisional
- **chunk_type_full_match_rate at 0.442**: Indicates citation granularity is misaligned for over half the results, but this is deferred to post-launch

## 5. Go/No-Gate Summary

The launch decision MUST satisfy all three hard gates:

| Gate | Metric | Threshold | Rationale |
|------|--------|-----------|-----------|
| G-1 | permission-boundary-failure count | = 0 | Zero tolerance for auth bypass |
| G-2 | citation presence rate | = 100% | Every non-abstain answer MUST have citations |
| G-3 | wrong-with-citation count | = 0 | Zero tolerance for fabricated citations |

Soft gates (SHOULD satisfy):

| Gate | Metric | Threshold | Rationale |
|------|--------|-----------|-----------|
| S-1 | top1_accuracy | >= 0.90 | Strong retrieval quality |
| S-2 | human review "correct" bucket | >= 80% | Human validation of automated metrics |
| S-3 | evidence gate trigger rate | 5-20% | Gate is active but not over-blocking |

## 6. Timeline Constraint

Given the 1-week window, the test strategy MUST be executable in 3 days (leaving 2 days for implementation, 2 days for buffer):

| Day | Activity | Deliverable |
|-----|----------|-------------|
| Day 1 | F-003: Extend eval dataset to 60-80 samples; run calibration | Score distribution report |
| Day 2 | F-001: Calibrate threshold from score distribution; implement gate | Threshold value + gate implementation |
| Day 3 | F-004: Human review (half day); compile go/no-go evidence package | Launch evidence package |

## 7. Cross-Role Handoff Points

- **To system-architect**: The threshold value and gate trigger criteria determined by F-001 MUST be implemented in EvidenceGateService
- **To product-manager**: The evidence gate abstention rate (from F-001 calibration) determines how often users see guided abstention (F-006); this MUST be communicated
- **To data-architect**: The eval calibration (F-003) MUST run against the frozen bundle (F-002); bundle changes invalidate eval results
