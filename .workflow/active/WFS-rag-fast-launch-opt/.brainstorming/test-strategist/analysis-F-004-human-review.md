# F-004: Human Review Protocol

**Feature**: 20-30 sample 5-bucket human review
**Priority**: High
**Date**: 2026-04-06

## 1. Purpose

Automated metrics (top1_accuracy, topk_recall, term_coverage) measure retrieval behavior but cannot judge answer quality from the user's perspective. A human review layer MUST validate that:

1. Correct retrievals actually produce useful, accurate answers
2. The evidence gate correctly identifies cases that should abstain
3. No permission boundary violations occur
4. The system does not produce confident wrong answers with citations

## 2. Bucket Definitions

### 2.1 Five-Bucket Classification

Each reviewed sample MUST be classified into exactly one bucket:

| Bucket | Definition | Severity |
|--------|-----------|----------|
| **correct** | The system retrieved the right document AND the generated answer accurately reflects the document content. Minor phrasing differences are acceptable. | Acceptable |
| **abstained** | The system correctly chose not to answer (evidence gate triggered or no citations found). The abstention is appropriate because no relevant document exists or the retrieval quality is insufficient. | Acceptable |
| **unsupported-query** | The user asked something the system cannot answer (outside document scope). The system correctly abstained or provided a helpful redirect. | Acceptable (expected behavior) |
| **wrong-with-citation** | The system provided a citation-based answer that is factually wrong, misleading, or misattributes content. The citation exists but does not support the answer. | CRITICAL -- launch blocker |
| **permission-boundary-failure** | The system retrieved or cited a document that the requester's department should not have access to. The ACL did not correctly filter the result. | CRITICAL -- launch blocker |

### 2.2 Bucket Decision Flowchart

For each sample, the reviewer follows this decision sequence:

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

## 3. Sample Selection

### 3.1 Selection Criteria

From the expanded eval results (F-003, 65-75 samples), select 20-30 samples:

1. **All error samples**: Include every sample where automated metrics show a failure (top1 miss, low score, wrong chunk type). Estimated: 2-5 samples.

2. **All boundary samples**: Include every sample where the top1_score is within 0.15 of the evidence gate threshold. These are the most informative cases. Estimated: 5-10 samples.

3. **Stratified random from successes**: From the remaining correct retrievals, randomly select to achieve:
   - At least 5 exact/fine samples
   - At least 5 semantic/coarse samples
   - At least 3 cross-department samples (supplemental_expected=true)
   - At least 3 same-department samples
   - At least 3 samples from each requester department

4. **Anti-pattern samples**: Include all 3-5 out-of-scope queries from Category C (F-003). These test unsupported-query bucket.

### 3.2 Selection Script

The selection SHOULD be automated:

```python
def select_review_samples(eval_results, threshold):
    samples = []

    # 1. All errors
    errors = [s for s in eval_results if not s['hit_at_1']]
    samples.extend(errors)

    # 2. All boundary cases
    boundary = [s for s in eval_results
                if s['hit_at_1']
                and abs(s['top1_score'] - threshold) < 0.15]
    samples.extend(boundary)

    # 3. Stratified random from remaining
    remaining = [s for s in eval_results if s not in samples]
    # ... stratified selection by query_type, department, supplemental

    # 4. Anti-pattern samples
    anti = [s for s in eval_results if s['should_refuse']]
    samples.extend(anti)

    return samples[:30]  # cap at 30
```

## 4. Review Form / Template

### 4.1 Review Form Structure

Each sample review MUST record:

```
Sample Review Form
==================

Sample ID: _______________
Query: _______________
Requester Department: _______________

System Behavior:
  Response Mode: [rag / evidence_gate_abstain / no_context]
  Top-1 Score: ____
  Top-1 Document: _______________
  Answer Preview: (first 200 chars) _______________

Review Classification:
  Bucket: [correct / abstained / unsupported-query / wrong-with-citation / permission-boundary-failure]

  If wrong-with-citation:
    What is wrong? _______________
    Expected correct answer: _______________

  If permission-boundary-failure:
    Which document should not have been accessible? _______________
    Requester's department: _______________
    Document's owning department: _______________

  Confidence in classification: [high / medium / low]

Reviewer Notes: _______________
```

### 4.2 What the Reviewer Sees

For each sample, the reviewer MUST be provided with:

1. The original query text
2. The system's answer (full text)
3. The cited document excerpts (not just IDs -- actual chunk text)
4. The original document content (for fact-checking)
5. The requester's department and the document's owning department

The review tooling MAY be a simple spreadsheet or a lightweight web form. A spreadsheet is sufficient for 20-30 samples.

## 5. Reviewer Instructions

### 5.1 General Instructions

- You are reviewing whether the system's answer is accurate and appropriately sourced
- Focus on factual accuracy, not answer style or completeness
- If the system abstained, judge whether abstention was the right choice
- If you are unsure about a classification, mark confidence as "low" and add a note

### 5.2 Per-Bucket Instructions

**correct bucket**: Verify that:
- The answer text matches what the cited document actually says
- The citation is from a document relevant to the query
- No fabricated details are present in the answer

**abstained bucket**: Verify that:
- The query had no relevant document in the corpus, OR
- The retrieval quality was genuinely insufficient (check the top1_score and the returned document)
- The abstention message was appropriate (not confusing or misleading)

**unsupported-query bucket**: Verify that:
- The query is genuinely outside the scope of indexed documents
- The system correctly identified this and did not hallucinate an answer
- The system's redirect or guidance was helpful

**wrong-with-citation bucket** (CRITICAL): Document:
- Exactly what factual claim in the answer is wrong
- What the cited document actually says (quote the relevant passage)
- Whether the error is in retrieval (wrong doc) or generation (right doc, wrong summary)

**permission-boundary-failure bucket** (CRITICAL): Document:
- Which document was accessed that should not have been
- The requester's department and the document's owner department
- Whether the document content is visible in the answer or only in the citation metadata

## 6. Inter-Rater Reliability

### 6.1 Two-Reviewer Protocol

Each sample SHOULD be reviewed by 2 independent reviewers. For a 20-30 sample set with 2 reviewers:

- Reviewer A reviews all 20-30 samples
- Reviewer B reviews all 20-30 samples independently (without seeing A's classifications)

### 6.2 Agreement Measurement

After both reviewers complete their classifications:

1. Calculate Cohen's kappa for the 5-bucket classification
2. Interpret the kappa value:

| Kappa Range | Interpretation | Action |
|-------------|---------------|--------|
| >= 0.80 | Strong agreement | Accept both reviewers' classifications |
| 0.60 - 0.79 | Moderate agreement | Discuss disagreements; accept majority |
| < 0.60 | Weak agreement | Third reviewer MUST adjudicate all samples |

### 6.3 Disagreement Resolution

For any sample where reviewers disagree on bucket:

1. Both reviewers re-examine the sample independently
2. If they still disagree, a third reviewer (preferably with domain expertise for that sample) makes the final classification
3. The third reviewer's classification is binding

Special handling for critical buckets:
- If either reviewer classifies a sample as "wrong-with-citation" or "permission-boundary-failure", the sample MUST be escalated regardless of the other reviewer's classification
- Critical-bucket samples are never downgraded without third-reviewer confirmation

### 6.4 Practical Time Estimate

- 20-30 samples, each requiring 3-5 minutes of review: 60-150 minutes total
- Two reviewers in parallel: ~2-3 hours
- Disagreement resolution: 30-60 minutes
- Total: half a day is realistic

## 7. Timeline

### 7.1 Half-Day Schedule

| Time | Activity | Duration |
|------|----------|----------|
| 0:00 | Brief reviewers on bucket definitions and decision flowchart | 15 min |
| 0:15 | Distribute review forms with sample data | 5 min |
| 0:20 | Reviewers independently classify all 20-30 samples | 90-120 min |
| 2:20 | Compile classifications; calculate agreement | 10 min |
| 2:30 | Disagreement resolution (if needed) | 30-60 min |
| 3:30 | Compile final bucket counts; check go/no-go gates | 15 min |
| 3:45 | DONE | -- |

### 7.2 Prerequisites

The human review session MUST NOT start until:

- F-003 eval calibration is complete (score distribution available)
- F-001 evidence gate threshold is set (so gate-triggered samples can be classified)
- The review form is populated with system outputs for all selected samples
- Two reviewers are available and briefed

## 8. Go/No-Go Gate Check

After human review completes, check the hard gates:

| Gate | Check | Pass Condition |
|------|-------|---------------|
| G-1 | Count of "permission-boundary-failure" | MUST be 0 |
| G-2 | Count of samples with citations in non-abstain answers | MUST be 100% |
| G-3 | Count of "wrong-with-citation" | MUST be 0 |

Soft gates:

| Gate | Check | Pass Condition |
|------|-------|---------------|
| S-2 | "correct" bucket proportion | SHOULD be >= 80% |
| S-5 | "abstained" + "unsupported-query" proportion | SHOULD be <= 20% |

### 8.1 Gate Failure Escalation

- **G-1 failure**: Block launch. Investigate ACL configuration. Review `retrieval_document_acl_seed.yaml` against `retrieval_auth_profiles.yaml`. Re-test after ACL fix.
- **G-3 failure**: Block launch. Lower the evidence gate threshold. Re-run F-001 calibration with adjusted threshold. Re-run human review on affected samples only.
- **S-2 failure**: Requires product owner sign-off with documented acceptance of risk. The test-strategist MUST provide the specific failure samples and their characteristics to inform the decision.

## 9. Output: Launch Evidence Package

The human review results form a critical part of the launch evidence package:

```
launch-evidence/
  eval-calibration-results.json     # From F-003
  score-distribution-report.json    # From F-003
  threshold-calibration.json        # From F-001
  human-review-results.yaml         # From F-004 (this section)
  go-no-go-checklist.yaml           # Compiled from all features
```

The human-review-results.yaml MUST include:

```yaml
human_review:
  date: YYYY-MM-DD
  reviewers: [name_a, name_b]
  sample_count: N
  buckets:
    correct: count
    abstained: count
    unsupported_query: count
    wrong_with_citation: count
    permission_boundary_failure: count
  inter_rater:
    cohen_kappa: 0.XX
    disagreement_count: N
    third_review_count: N
  gates:
    G-1_permission_boundary: pass/fail
    G-2_citation_presence: pass/fail
    G-3_wrong_with_citation: pass/fail
    S-2_correct_rate: pass/fail (value: X.XX)
  decision: go/no-go
  sign_off: product-owner-name
```

## 10. Post-Review Actions

### 10.1 Failure Sample Analysis

For every sample classified as "wrong-with-citation" or "permission-boundary-failure":

1. Create a detailed incident report
2. Root cause analysis: retrieval error, generation error, or ACL error
3. Fix recommendation: threshold adjustment, ACL fix, or retrieval pipeline fix
4. Verify the fix resolves the specific sample

### 10.2 Improvement Backlog

Non-critical findings from human review SHOULD be recorded for post-launch optimization:

- Answers that are technically correct but unhelpful (too terse, missing context)
- Answers that cite the right document but paraphrase inaccurately
- Abstentions that could have been answered with better retrieval
- These feed into the post-launch optimization path (supplemental -> chunk -> router -> rerank)
