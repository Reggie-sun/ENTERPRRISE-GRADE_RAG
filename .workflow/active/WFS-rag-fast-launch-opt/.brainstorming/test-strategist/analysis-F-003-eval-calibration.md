# F-003: Eval Calibration Plan

**Feature**: Extend eval to 60-80 samples with balanced type coverage
**Priority**: High
**Date**: 2026-04-06

## 1. Current State Assessment

### 1.1 Existing Dataset Composition

The current 43 samples in `eval/retrieval_samples.yaml` break down as:

| Category | Count | Proportion |
|----------|-------|-----------|
| exact/fine | 24 | 56% |
| semantic/coarse | 19 | 44% |
| supplemental_expected=false | 20 | 47% |
| supplemental_expected=true | 23 | 53% |
| status=verified | 36 | 84% |
| status=unverified | 7 | 16% |
| P0 boundary samples | 5 | 12% |
| P1 lexical/hybrid boundary | 4 | 9% |
| P2 cross-dept diversity | 3 | 7% |

### 1.2 Key Gaps

1. **Semantic/coarse queries are under-tested**: 19 samples for the weakest query type provides a CI of approximately +/- 0.10 on accuracy metrics. This is too wide for a launch decision.

2. **Unverified samples**: 7 samples (boundary and lexical) are unverified. These MUST be verified or replaced before they contribute to calibration.

3. **Department parity**: after_sales=13, assembly=16, digitalization=14. Acceptable for current size, but MUST reach >= 15 each in expanded set.

4. **No negative samples**: All queries are designed to retrieve something. No queries test the system's ability to correctly abstain when no relevant document exists.

5. **Document type coverage**: Most queries target SOPs, WIs, and fault code manuals. Quality inspection standards, construction manuals, and planning documents are less covered.

## 2. Target Dataset Design

### 2.1 Size Target: 65-75 Samples

The range of 60-80 provides reasonable statistical power. Target 65-75 samples:
- 43 existing (verified + to-be-verified)
- 22-32 new samples

### 2.2 Type Distribution Target

| Query Type | Granularity | Current | Target | New Needed |
|-----------|-------------|---------|--------|-----------|
| exact | fine | 24 | 28-30 | 4-6 |
| exact | coarse | 0 | 3-5 | 3-5 |
| semantic | fine | 0 | 3-5 | 3-5 |
| semantic | coarse | 19 | 25-30 | 6-11 |
| anti-pattern | N/A | 0 | 3-5 | 3-5 |

**Rationale for anti-pattern samples**: The evidence gate (F-001) needs negative examples -- queries where the system SHOULD NOT find a relevant document. Without these, we cannot calibrate the threshold's specificity.

### 2.3 New Sample Categories

#### Category A: Semantic Rephrasings (10-12 samples)

Take existing exact queries and rewrite them as natural language questions a non-expert would ask:

- exact-001 ("700000 面板急停报警 现场先查什么") becomes "设备面板上出现了急停报警，编号好像是700000，现场应该先排查什么问题"
- exact-002 becomes "B轴夹紧放松信号出现异常，该怎么排查处理"
- fine-001 becomes "围栏急停报警恢复以后还是不消失，需要重点检查什么部件"
- fine-003 becomes "齿轮和齿条之间的间隙一般控制在什么范围"

These samples MUST:
- Use synonyms and paraphrases, NOT exact codes/identifiers
- Target the same expected_doc_ids as their source exact query
- Be classified as `query_type: semantic, expected_granularity: fine`

#### Category B: Coarse Summary Queries (6-8 samples)

Ask document-level questions about content structure:

- "电机齿轮安装SOP的整体流程包括哪些主要步骤" (targeting doc_20260331021041_adff1740)
- "摇臂钻床安全操作规范涵盖了哪些安全注意事项" (targeting doc_20260330055115_c20cfc5a)
- "滑触线施工手册的主要内容章节" (targeting doc_20260331081535_5d30086d)
- "电镀检验标准对不同表面缺陷的分类标准是什么" (targeting doc_20260401084714_b7ed464a)

These MUST:
- Ask about document-level structure, NOT specific parameter values
- Target `expected_granularity: coarse, expected_chunk_type: section_summary`
- Be classified as `query_type: semantic`

#### Category C: Anti-Pattern / Out-of-Scope Queries (3-5 samples)

Queries that should NOT retrieve relevant documents:

- "公司食堂的菜单和订餐方式" (no relevant docs in index)
- "员工年假申请流程和审批规则" (no HR policy docs)
- "办公室网络故障排查步骤" (no IT support docs in corpus)
- "如何操作数控车床进行零件加工" (no CNC-related docs)

These samples MUST:
- Have `expected_doc_ids: []` (empty)
- Have `should_refuse: true`
- Be designed to test the system's ability to correctly NOT answer

#### Category D: Cross-Department Parity (3-5 samples)

Fill department gaps:
- More queries from after_sales perspective (currently 13, need >= 15)
- More queries targeting digitalization documents from non-digitalization requesters

### 2.4 Verification Protocol

Every new sample MUST go through this verification process:

1. **Index verification**: Run query against `/api/v1/retrieval/search` and confirm expected_doc_ids appear in top-k results
2. **Score recording**: Record the top1_score and top5 scores for threshold calibration
3. **Type classification review**: Confirm query_type and expected_granularity classification is correct
4. **Domain review**: At least one person familiar with the document content confirms the expected_doc_ids are correct for the query

Status transitions: `unverified` -> `verified` (all 4 checks pass) or `rejected` (any check fails).

## 3. Baseline Comparison Methodology

### 3.1 Baseline Definition

The baseline is the latest eval run with the current 43 samples: `eval_20260406_113356.json`. Key baseline metrics:

| Metric | Baseline Value |
|--------|---------------|
| top1_accuracy | 0.977 |
| topk_recall | 1.000 |
| supplemental_precision | 0.920 |
| supplemental_recall | 1.000 |
| term_coverage_avg | 0.890 |
| chunk_type_full_match_rate | 0.442 |

### 3.2 Comparison Protocol

After expanding the dataset to 65-75 samples:

1. Run the full eval against the frozen bundle
2. Compute the same metrics on the expanded set
3. Compare each metric:

| Comparison | Interpretation | Action |
|-----------|---------------|--------|
| New metric >= baseline - 0.05 | Acceptable; larger dataset may slightly reduce proportions | Proceed |
| New metric < baseline - 0.05 | Significant degradation on new samples | Investigate which new samples fail; may indicate dataset quality issue |
| New metric significantly > baseline | New samples are "easier" than existing; possible selection bias | Audit new samples for representativeness |

### 3.3 Per-Sample Score Audit

For every new sample, record:
- `top1_score`: The relevance score of the top-1 result
- `top1_doc_id`: The document ID of the top-1 result
- `hit_at_1`: Whether top-1 matches expected_doc_ids
- `hit_at_5`: Whether any top-5 matches expected_doc_ids

Any new sample where `hit_at_1 = false` MUST be individually reviewed:
- Is the expected_doc_ids assignment correct?
- Is the query ambiguous (could legitimately match multiple documents)?
- Is the retrieval system making an error?

## 4. Statistical Significance

### 4.1 Sample Size Justification

With 65-75 samples:
- For top1_accuracy ~= 0.95: 95% CI is approximately [0.90, 0.99]
- For top1_accuracy ~= 0.90: 95% CI is approximately [0.83, 0.97]
- The CI width (~0.07-0.10) is acceptable for a launch go/no-go decision

This is NOT sufficient for detecting small differences (< 0.05) between configurations. That level of precision requires 200+ samples, which is post-launch work.

### 4.2 Subset Statistical Power

For per-type breakdowns (e.g., semantic queries only):
- With 25-30 semantic samples and accuracy ~= 0.90: CI is [0.78, 1.00]
- This is wide but usable for identifying gross problems

The eval report MUST include confidence intervals for all reported proportions to prevent over-interpretation of small differences.

### 4.3 Multiple Comparison Correction

When evaluating multiple metrics (top1, topk, supplemental precision, supplemental recall, term_coverage, chunk_type_match), the probability of at least one metric appearing significant by chance increases. The eval report SHOULD:

- Report all metrics with confidence intervals
- Flag any metric where the CI excludes the target threshold
- NOT apply formal Bonferroni correction (overly conservative for correlated metrics)
- Use a "flagged if any metric fails" approach instead

## 5. Score Distribution Reporting

### 5.1 Required Score Statistics

The calibration eval MUST produce a score distribution report:

```
Score Distribution (expanded eval, N=65-75):
  top1_score:
    min:    0.XX
    p10:    0.XX
    median: 0.XX
    p90:    0.XX
    max:    0.XX

  By query_type:
    exact:   min=0.XX, median=0.XX, max=0.XX
    semantic: min=0.XX, median=0.XX, max=0.XX

  By correctness:
    correct (top1 hit): min=0.XX, median=0.XX, max=0.XX
    incorrect (top1 miss): min=0.XX, median=0.XX, max=0.XX (if any)
```

This distribution is the primary input to the evidence gate threshold calibration (F-001).

### 5.2 Score Gap Analysis

Identify the largest gap in the score distribution between correct and incorrect retrievals. This gap is the natural threshold candidate. If no gap exists:

- Report the overlap region (scores where both correct and incorrect retrievals occur)
- Recommend threshold placement based on the "zero FP" criterion (see F-001)

## 6. Execution Plan

### 6.1 Day 1 Morning: Sample Creation

- Create 22-32 new samples following the Category A-D templates
- Verify each against live retrieval endpoint
- Commit to `eval/retrieval_samples.yaml`

### 6.2 Day 1 Afternoon: Calibration Run

- Run full eval pipeline on expanded dataset
- Generate score distribution report
- Generate per-sample audit list
- Hand off score distribution to F-001 threshold calibration

### 6.3 Deliverables

| Deliverable | Format | Consumer |
|------------|--------|----------|
| Expanded eval dataset | `eval/retrieval_samples.yaml` (updated) | F-001, F-004 |
| Calibration results | `eval/results/eval_YYYYMMDD_calibration.json` | F-001, go/no-go |
| Score distribution report | Section in calibration results JSON | F-001 |
| Per-sample audit | `eval/results/audit_YYYYMMDD.csv` | F-004 sample selection |

## 7. Anti-Regresssion: Dataset Freeze

After the calibration eval is complete and the threshold is set, the eval dataset MUST be frozen. Any future sample additions MUST:

1. Not alter existing samples (only append)
2. Be verified before inclusion
3. Trigger a re-calibration if they change the score distribution significantly

The dataset freeze coincides with the bundle freeze (F-002): dataset + bundle + threshold form the launch evidence package.
