# Feature Spec: F-004 - Human Review

**Priority**: High
**Contributing Roles**: test-strategist (lead), product-manager
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL provide a structured human review protocol for 20-30 samples drawn from the expanded eval results (F-003), using a 5-bucket classification scheme. The review validates that automated metrics align with human judgment and serves as the final go/no-go evidence before launch.

- The review MUST use exactly 5 buckets: correct, abstained, unsupported-query, wrong-with-citation, permission-boundary-failure.
- **wrong-with-citation** count MUST be 0 (zero tolerance) in human review (EP-003). This is a hard launch gate.
- **permission-boundary-failure** count MUST be 0 (zero tolerance). This is a hard launch gate.
- Overall wrong-with-citation rate in the full eval (F-003) MUST be < 5% (EP-003).
- Two independent reviewers MUST classify all samples; Cohen's kappa MUST be calculated.
- The review MUST complete within half a day.
- Reviewers MUST have domain knowledge but do NOT need technical knowledge of the retrieval pipeline.
- Reviewers MUST be different from the person who created eval samples (avoid confirmation bias).

## 2. Design Decisions

### 2.1 Wrong-With-Citation Threshold: Zero Tolerance in Review, <5% in Full Eval (RESOLVED)

**Decision**: In the human review (20-30 samples), `wrong-with-citation` count MUST be exactly 0. In the full automated eval (60-80 samples), `wrong-with-citation` rate MUST be < 5%.

**Rationale**: The human review is a focused check on the most critical failure mode. A single wrong-with-citation case among 20-30 carefully selected samples indicates a systemic problem. The 5% threshold in the full eval accounts for edge cases in the larger sample pool.

**Escalation path**: If G-3 fails in human review, block launch, lower evidence gate threshold, re-calibrate F-001, and re-run review on affected samples only.

**Source roles**: test-strategist (go/no-go gates), product-manager (go/no-go criteria).

### 2.2 Bucket Decision Flowchart

The classification follows a strict decision sequence:

```
1. Did the system return an answer (not abstain)?
   NO -> Did the query have a relevant document in the corpus?
     NO -> bucket = "unsupported-query"
     YES -> bucket = "abstained" (check: was abstention correct?)
   YES -> Continue to step 2

2. Does the answer accurately reflect the cited document's content?
   NO -> bucket = "wrong-with-citation"
   YES -> Continue to step 3

3. Does the requester have permission to access all cited documents?
   NO -> bucket = "permission-boundary-failure"
   YES -> bucket = "correct"
```

This flowchart ensures every sample is classified into exactly one bucket with no ambiguity. Critical buckets (wrong-with-citation, permission-boundary-failure) are checked before correct, preventing false positives.

**Source roles**: test-strategist (bucket definitions, decision flowchart), product-manager (bucket product implications).

### 2.3 Sample Selection Strategy

Samples are selected from F-003 eval results using a stratified approach:

1. **All error samples**: Every sample where `hit_at_1 = false` (estimated 2-5).
2. **All boundary samples**: Every sample where `top1_score` is within 0.15 of the evidence gate threshold (estimated 5-10).
3. **Stratified random from successes**: Ensure >=5 exact/fine, >=5 semantic/coarse, >=3 cross-department, >=3 same-department.
4. **Anti-pattern samples**: All `should_refuse: true` samples from F-003 Category C.

**Bucket allocation targets**:

| Bucket | Target Count | Selection Priority |
|--------|-------------|-------------------|
| correct | 12-15 | Random from high-confidence results |
| abstained | 3-5 | All evidence-gate-triggered samples |
| unsupported-query | 2-3 | All anti-pattern samples |
| wrong-with-citation | 0-2 | All top1 misses MUST be included |
| permission-boundary-failure | 2-3 | Cross-department ACL boundary samples |

### 2.4 Inter-Rater Reliability Protocol

**Decision**: Two reviewers classify all samples independently. Cohen's kappa is calculated. If kappa < 0.60, a third reviewer MUST adjudicate.

| Kappa Range | Interpretation | Action |
|-------------|---------------|--------|
| >= 0.80 | Strong agreement | Accept both reviewers' classifications |
| 0.60 - 0.79 | Moderate agreement | Discuss disagreements; accept majority |
| < 0.60 | Weak agreement | Third reviewer MUST adjudicate all samples |

**Special rule**: If either reviewer classifies a sample as `wrong-with-citation` or `permission-boundary-failure`, the sample MUST be escalated regardless of the other reviewer's classification. Critical buckets are never downgraded without third-reviewer confirmation.

**Time estimate**: 20-30 samples at 3-5 min each, two reviewers in parallel = ~2-3 hours total including disagreement resolution.

## 3. Interface Contract

### 3.1 Review Form Schema

Each sample review MUST record:

```yaml
sample_id: exact-001
query: "700000 ..."
requester_department: dept_after_sales
response_mode: rag | evidence_gate_abstain | no_context
top1_score: 0.98
top1_document: doc_20260321070337_445684f4
answer_preview: "(first 200 chars)"
bucket: correct | abstained | unsupported-query | wrong-with-citation | permission-boundary-failure
confidence: high | medium | low
wrong_with_citation_detail:
  what_is_wrong: "..."
  expected_correct_answer: "..."
permission_boundary_detail:
  inaccessible_document: "..."
  requester_department: "..."
  document_owner_department: "..."
reviewer_notes: "..."
```

### 3.2 Review Results Output

```yaml
human_review:
  date: "2026-04-06"
  bundle_id: "bundle-20260406-a1b2c3d4"
  reviewers: [reviewer_a, reviewer_b]
  sample_count: 25
  buckets:
    correct: 18
    abstained: 3
    unsupported_query: 2
    wrong_with_citation: 0
    permission_boundary_failure: 0
  inter_rater:
    cohen_kappa: 0.85
    disagreement_count: 2
    third_review_count: 0
  gates:
    G-1_permission_boundary: pass
    G-2_citation_presence: pass
    G-3_wrong_with_citation: pass
    S-2_correct_rate: pass (value: 0.72)
  decision: go
  sign_off: product-owner-name
```

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| Half-day window | Review MUST complete in ~3.5 hours (reviewer availability is limited) |
| Domain knowledge required | Reviewers must understand document content to judge accuracy |
| No technical knowledge needed | Reviewers should NOT need to understand retrieval pipeline |
| Spreadsheet or web form | Tooling is lightweight; no specialized review platform |

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Reviewers unavailable on short notice | Medium | High | Identify backup reviewers; schedule review slot in advance |
| Low inter-rater agreement (kappa < 0.60) | Low | Medium | Third reviewer protocol; extend timeline by 1 hour |
| G-3 failure blocks launch | Medium | Critical | Pre-identify potential threshold adjustments; prepare contingency |
| Reviewer bias toward "correct" | Medium | Medium | Use independent reviewers not involved in eval creation |
| Sample selection unrepresentative | Low | Medium | Use stratified selection with mandatory error/boundary inclusion |

## 5. Acceptance Criteria

1. **Sample count**: 20-30 samples selected from F-003 eval results.
2. **Bucket coverage**: All 5 buckets have at least 1 sample (except wrong-with-citation which is measured as count).
3. **Two reviewers**: Both complete independent classification of all samples.
4. **Cohen's kappa**: Calculated and reported; MUST be >= 0.60 for review validity.
5. **G-1 gate**: `permission-boundary-failure` count = 0 (PASS required for launch).
6. **G-3 gate**: `wrong-with-citation` count = 0 (PASS required for launch).
7. **G-2 gate**: Citation presence = 100% in non-abstain answers.
8. **S-2 soft gate**: `correct` bucket >= 80% (SHOULD pass; product owner override allowed with documented risk).
9. **Output artifact**: `human-review-results.yaml` written to `launch-evidence/` directory.
10. **Sign-off**: Product owner signs off on go/no-go decision with name and date.

## 6. Detailed Analysis References

- @test-strategist/analysis-F-004-human-review.md -- Full review protocol, bucket definitions, decision flowchart, sample selection, inter-rater reliability, timeline, go/no-go gates
- @test-strategist/analysis-cross-cutting.md -- Human review selection criteria, go/no-go decision framework, post-review actions
- @product-manager/analysis-cross-cutting.md -- Bucket product implications, go/no-go criteria, reviewer qualification

## 7. Cross-Feature Dependencies

**Depends on**:
- F-003 (eval-calibration): Provides per-sample results with scores for sample selection. Review MUST use F-003 results.
- F-001 (evidence-gate): Evidence gate must be implemented so gate-triggered samples can be classified in the "abstained" bucket.
- F-002 (bundle-freeze): Review results reference `bundle_id` for traceability.

**Required by**:
- Go/no-go decision: Human review results are the final input to the launch decision.

**Shared patterns**:
- Bundle identity: `bundle_id` propagates from F-002 through F-003 to F-004 output.
- 5-bucket taxonomy: Same classification used in test-strategist analysis and product-manager criteria.

**Integration points**:
- `eval/results/audit_YYYYMMDD.csv` from F-003 -- input for sample selection
- `launch-evidence/human-review-results.yaml` -- output consumed by go/no-go meeting
