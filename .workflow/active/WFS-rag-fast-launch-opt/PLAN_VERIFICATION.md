# Plan Verification Report
**Session**: WFS-rag-fast-launch-opt
**Date**: 2026-04-06

## Summary
**PROCEED_WITH_CAUTION** -- The plan is structurally sound with correct dependency ordering and full feature coverage. Three moderate issues require attention before execution: (1) a file reference mismatch between the IMPL_PLAN.md summary table and the actual task JSONs for IMPL-004/IMPL-005, (2) a missing test file for evidence gate (F-001 AC 10), and (3) an aggressive Day 5 schedule with 7 hours of work.

---

## Dimension Results

### 1. Feature Coverage -- PASS

| Feature | Mapped Task(s) | Status |
|---------|---------------|--------|
| F-001 evidence-gate | IMPL-002 (Phase A) + IMPL-007 (Phase B) | Covered |
| F-002 bundle-freeze | IMPL-003 | Covered |
| F-003 eval-calibration | IMPL-006 | Covered |
| F-004 human-review | IMPL-008 | Covered |
| F-005 citation-display | IMPL-004 | Covered |
| F-006 guided-abstention | IMPL-005 | Covered |
| F-007 kill-switch | IMPL-001 | Covered |
| F-008 monitoring-dashboard | IMPL-009 | Covered |

All 8 features are mapped to tasks.

**Feature-to-task acceptance criteria coverage detail**:

| Feature Spec | Total ACs | Covered by Tasks | Uncovered |
|-------------|-----------|-----------------|-----------|
| F-001 | 10 | 8 | AC 9 (edge case tests), AC 10 (test suite >=10 cases) |
| F-002 | 10 | 10 | None |
| F-003 | 10 | 8 | AC 3 (department parity), AC 10 (confidence intervals) |
| F-004 | 10 | 10 | None |
| F-005 | 8 | 8 | None |
| F-006 | 10 | 10 | None |
| F-007 | 7 | 7 | None |
| F-008 | 6 | 6 | None |
| **Total** | **71** | **67** | **4** |

Coverage rate: 94.4% (67/71 spec ACs reflected in task ACs).

### 2. Dependency Consistency -- PASS

**All task dependencies validated**:

| Task | depends_on | References valid? | Correct ordering? |
|------|-----------|-------------------|-------------------|
| IMPL-001 | [] | N/A | Yes, root task |
| IMPL-002 | [IMPL-001] | Yes | Yes, kill switch must land first (same file: chat_service.py) |
| IMPL-003 | [] | N/A | Yes, independent script |
| IMPL-004 | [] | N/A | Yes, independent frontend |
| IMPL-005 | [] | N/A | Yes, independent frontend |
| IMPL-006 | [IMPL-002, IMPL-003] | Yes | Yes, needs gate (threshold=0.0) + frozen bundle |
| IMPL-007 | [IMPL-006] | Yes | Yes, needs eval score distributions |
| IMPL-008 | [IMPL-007] | Yes | Yes, needs calibrated threshold |
| IMPL-009 | [] | N/A | Yes, independent script |

**Blocking relationships validated**:

| Task | blocking | Targets exist? | Bidirectional consistency? |
|------|----------|---------------|--------------------------|
| IMPL-001 | [IMPL-002] | Yes | Yes, IMPL-002 depends_on IMPL-001 |
| IMPL-002 | [IMPL-006] | Yes | Yes, IMPL-006 depends_on IMPL-002 |
| IMPL-003 | [IMPL-006] | Yes | Yes, IMPL-006 depends_on IMPL-003 |
| IMPL-006 | [IMPL-007] | Yes | Yes, IMPL-007 depends_on IMPL-006 |
| IMPL-007 | [IMPL-008] | Yes | Yes, IMPL-008 depends_on IMPL-007 |
| IMPL-004 | [] | N/A | Yes |
| IMPL-005 | [] | N/A | Yes |
| IMPL-008 | [] | N/A | Yes |
| IMPL-009 | [] | N/A | Yes |

**Acyclicity**: The dependency graph is a DAG. No cycles detected.

**Critical path**: IMPL-001 (3h) -> IMPL-002 (4h) -> IMPL-006 (4h) -> IMPL-007 (2h) -> IMPL-008 (4h) = 17 hours.

Note: plan.json critical_path field lists IMPL-003 as sequential with IMPL-001/002, but IMPL-003 is actually parallel (no dependency on IMPL-001 or IMPL-002). This is a cosmetic issue in plan.json, not a structural error. The true critical path does not include IMPL-003.

### 3. Acceptance Criteria Testability -- PASS

All 56 acceptance criteria across 9 tasks are measurable. No vague "works correctly" or "behaves as expected" criteria found.

Assessment by task:

| Task | AC Count | All specific? | All testable? | Notes |
|------|----------|--------------|--------------|-------|
| IMPL-001 | 7 | Yes | Yes | Schema names, method names, CLI flags, fail-open condition |
| IMPL-002 | 8 | Yes | Yes | Class/method names, config paths, score source, mode values |
| IMPL-003 | 7 | Yes | Yes | File contents, CLI flags, exit codes, API sources |
| IMPL-004 | 5 | Yes | Yes | Character counts, UI elements, defensive checks |
| IMPL-005 | 6 | Yes | Yes | Component rendering, mode detection, click behavior |
| IMPL-006 | 7 | Yes | Yes | Sample counts, score captures, report generation |
| IMPL-007 | 6 | Yes | Yes | Threshold values, validation methodology |
| IMPL-008 | 7 | Yes | Yes | Sample counts, bucket counts, gate checks, kappa |
| IMPL-009 | 6 | Yes | Yes | CLI output, JSONL handling, threshold values |

### 4. Task Completeness -- PASS

Every task has all required fields:

| Field | Present in all 9 tasks? |
|-------|------------------------|
| task_id | Yes |
| title | Yes |
| feature (F-xxx mapping) | Yes |
| priority | Yes |
| status | Yes |
| day | Yes |
| estimated_hours | Yes |
| depends_on | Yes |
| blocking | Yes |
| description | Yes |
| acceptance_criteria | Yes (5-8 per task) |
| files_to_create | Yes (explicitly listed, empty array when none) |
| files_to_modify | Yes (explicitly listed, empty array when none) |
| implementation_steps | Yes (numbered, sequential, actionable) |

**Estimated hours assessment**:

| Task | Hours | Assessment |
|------|-------|------------|
| IMPL-001 | 3h | Reasonable for schema + service method + CLI script + markdown doc |
| IMPL-002 | 4h | Reasonable for new service class + integration in two code paths + config |
| IMPL-003 | 3h | Reasonable for CLI script with Qdrant API calls + validation |
| IMPL-004 | 2h | Reasonable for minor frontend tweaks (truncate, badge, toggle) |
| IMPL-005 | 4h | Reasonable for new React component + integration |
| IMPL-006 | 4h | Tight for 17-37 new samples + eval run + distribution report |
| IMPL-007 | 2h | Reasonable for analysis + config update + re-run verification |
| IMPL-008 | 4h | Reasonable assuming reviewers are pre-scheduled |
| IMPL-009 | 3h | Reasonable for JSONL parsing script with multiple sections |
| **Total** | **29h** | Over 5 days = 5.8h/day average |

### 5. Enhancement Integration -- PASS

All 10 EPs from synthesis-changelog.md verified against tasks:

| EP | Description | Reflected in Tasks | Evidence |
|----|-------------|-------------------|----------|
| EP-001 | Mode mapping unified | IMPL-001, IMPL-002, IMPL-005, IMPL-009 | kill_switch mode, evidence_gate_abstain mode, mode detection in frontend, mode counting in dashboard |
| EP-002 | Bundle freeze dirty worktree | IMPL-003 | AC: "Blocks on uncommitted changes to data/ and eval/", "Warns on uncommitted changes to other directories" |
| EP-003 | Go/No-Go threshold harmonization | IMPL-008 | AC: hard gates wrong-with-citation=0, permission-boundary-failure=0; soft gates in TODO_LIST |
| EP-004 | Post-rerank Citation.score | IMPL-002, IMPL-006 | IMPL-002 AC: "Gate uses citations[0].score (post-rerank)"; IMPL-006 AC: "captures post-rerank Citation.score" |
| EP-005 | Unified monitoring thresholds | IMPL-009 | AC: "error_rate 2%, gate_trigger WARNING 30%/CRITICAL 40%, P95 15s" |
| EP-006 | Evidence gate boundary | IMPL-002 | AC: "Two abstention modes: no_context vs evidence_gate_abstain" |
| EP-007 | Kill switch advisory file lock | IMPL-001 | AC: "supports --enable/--disable/--status with advisory file lock" |
| EP-008 | Chinese localization | IMPL-001, IMPL-002, IMPL-005 | IMPL-001 AC: "All user-facing strings are Chinese"; IMPL-002 AC: "Chinese (PM Template A)"; IMPL-005 AC: "Chinese abstention messages" |
| EP-009 | 5-day timeline | All tasks | plan.json: timeline_days=5; all tasks have day field 1-5 |
| EP-010 | Corpus manifest: Qdrant primary + filesystem | IMPL-003 | AC: "Corpus manifest uses Qdrant scroll API as primary source + filesystem reconciliation" |

All 8 resolved conflicts from synthesis are also addressed in task acceptance criteria:
- Score field source -> IMPL-002 uses post-rerank
- Dirty worktree -> IMPL-003 blocks on data/eval
- Corpus manifest source -> IMPL-003 uses Qdrant primary
- Anti-pattern expected_doc_ids -> IMPL-006 AC: "5-8 anti-pattern queries with should_refuse=true"
- wrong-with-citation threshold -> IMPL-008 AC: "Hard gates: wrong-with-citation=0"
- Two vs three abstention modes -> IMPL-005 handles no_context + evidence_gate_abstain
- Config write race -> IMPL-001 AC: advisory file lock
- Alert threshold inconsistency -> IMPL-009 AC: unified thresholds

### 6. Cross-Feature Consistency -- PASS (with WARN)

**Shared file analysis**:

| File | Tasks modifying | Sequencing | Conflict? |
|------|----------------|------------|-----------|
| `chat_service.py` | IMPL-001, IMPL-002 | IMPL-001 -> IMPL-002 (explicit dep) | No, correctly sequenced |
| `system_config.py` | IMPL-001, IMPL-002 | IMPL-001 -> IMPL-002 (explicit dep) | No, correctly sequenced |
| `system_config.json` | IMPL-001, IMPL-002, IMPL-007 | IMPL-001/002 Day 1-2; IMPL-007 Day 4 | No, separated by days |
| `PortalChatPage.tsx` | IMPL-004, IMPL-005 | Both Day 1-2, no dependency | Manageable (different sections) |
| `run_retrieval_eval.py` | IMPL-006 | Single task | No conflict |

**WARN: File reference mismatch in IMPL_PLAN.md**:
The IMPL_PLAN.md task summary table lists `ChatPanel.tsx` for both IMPL-004 and IMPL-005. However:
- The actual IMPL-004.json lists `files_to_modify: ["frontend/src/portal/PortalChatPage.tsx"]`
- The actual IMPL-005.json lists `files_to_modify: ["frontend/src/portal/PortalChatPage.tsx"]`
- The feature specs F-005 and F-006 both reference `PortalChatPage.tsx`

The task JSONs are correct. The IMPL_PLAN.md summary table has an inaccurate shorthand. This is a documentation inconsistency, not a structural error, since the implementer will follow the task JSON files.

**F-001 and F-007 both modify chat_service.py**: Verified correct. IMPL-001 adds kill switch check at entry point, IMPL-002 adds evidence gate after build_citations(). The explicit dependency IMPL-002 depends_on IMPL-001 ensures correct ordering.

**F-005 and F-006 both modify PortalChatPage.tsx**: IMPL-004 modifies citation display section (snippet truncation, count badge). IMPL-005 adds conditional rendering for AbstentionCard. These touch different parts of the component. Since both are Day 1-2 with no dependency, they can be implemented sequentially within the same file. Minor merge awareness needed but no conflict.

### 7. Timeline Feasibility -- WARN

**Day-by-day breakdown**:

| Day | Tasks | Hours | Assessment |
|-----|-------|-------|------------|
| Day 1 | IMPL-001 (3h) + IMPL-002 (4h) | 7h (critical path) | Feasible |
| Day 1-2 | IMPL-003 (3h) parallel | 3h | Feasible (independent script) |
| Day 1-2 | IMPL-004 (2h) parallel | 2h | Feasible (independent frontend) |
| Day 2 | IMPL-005 (4h) | 4h | Feasible |
| Day 3 | IMPL-006 (4h) | 4h | Feasible but tight (sample creation effort) |
| Day 4 | IMPL-007 (2h) | 2h | Comfortable, with buffer for re-runs |
| Day 5 | IMPL-008 (4h) + IMPL-009 (3h) | 7h | **WARN: aggressive for final day** |

**Total**: 29 hours across 5 days = 5.8h/day average.

**Concerns**:
1. **Day 5 has 7 hours of work**: IMPL-008 (human review) requires coordinating two reviewers, which may take longer than estimated if reviewers are unavailable. IMPL-009 (monitoring) is fully independent and could be moved to Day 3 or Day 4 to reduce Day 5 to 4 hours.
2. **IMPL-006 sample creation may overrun**: Creating 17-37 new eval samples with domain knowledge, verification against live retrieval, and proper type coverage is substantive work. The 4-hour estimate is optimistic.
3. **No buffer**: The plan has minimal slack (11h over 5 days at 8h/day), but much of it is concentrated on Day 4. Any overrun on Days 1-3 compresses the critical path.

**Parallel tracks verified as truly independent**:
- Track 1 (IMPL-001, IMPL-003, IMPL-004): All modify different files, no shared state. Valid.
- Track 2 (IMPL-002): Depends on IMPL-001 completing first. Valid.
- Track 3 (IMPL-005, IMPL-009): Frontend component + independent script. Valid.

### 8. Missing Items -- WARN

**F-001 spec ACs not covered by any task**:

| F-001 Spec AC | Description | Covered? |
|---------------|-------------|----------|
| AC 9 | Edge cases tested (empty citations, score at exactly threshold, null score, score within 0.01 of threshold) | NOT in any task AC |
| AC 10 | Test suite `test_evidence_gate.py` has >= 10 test cases | NOT in any task; no task creates this file |

**F-003 spec ACs not covered by IMPL-006**:

| F-003 Spec AC | Description | Covered? |
|---------------|-------------|----------|
| AC 3 | Department parity: each of 3 departments has >=15 samples | NOT in IMPL-006 AC |
| AC 10 | Confidence intervals: 95% CIs for all reported proportions | NOT in IMPL-006 AC |

**Brainstorm decisions not reflected in tasks**:

1. **F-001 section 2.6 safety margin**: Specifies "0.03-0.05 safety margin above selected threshold." IMPL-007 does not mention safety margin in its AC.
2. **F-006 section 3.3 backend message**: The F-006 spec says "One MUST change: Rewrite the no_context message in chat_service.py from English to Chinese using Template C." This backend change is not listed in any task's files_to_modify. IMPL-002 covers Template A (evidence gate abstention) but not Template C (no_context).
3. **F-002 section 3.1 bundle-validation.json**: The spec says this validation output file should be written alongside the bundle. IMPL-003 does not mention this artifact.
4. **F-006 tone constraints**: The spec requires no apology language, no exclamation marks, no "AI" term. IMPL-005 does not include content validation ACs for these constraints.

---

## Gaps Found

### Moderate Gaps (should fix before execution)

1. **Missing test file for evidence gate**: F-001 spec AC 10 requires `test_evidence_gate.py` with >= 10 test cases. No task creates this file. IMPL-002 should include it in `files_to_create`.

2. **IMPL_PLAN.md file reference error**: The task summary table lists `ChatPanel.tsx` for IMPL-004 and IMPL-005, but the task JSONs correctly reference `PortalChatPage.tsx`. The IMPL_PLAN.md summary is misleading.

3. **Missing no_context Template C backend change**: F-006 spec requires rewriting the `no_context` message in `chat_service.py` to Chinese (Template C). This is not captured in any task. IMPL-002 covers Template A (evidence gate abstention) but not Template C.

### Minor Gaps (nice to fix)

4. **Department parity not in IMPL-006 AC**: F-003 spec requires >=15 samples per department.

5. **Confidence intervals not in IMPL-006 AC**: F-003 spec requires 95% CIs for reported proportions.

6. **Safety margin not in IMPL-007 AC**: F-001 spec specifies 0.03-0.05 safety margin for threshold.

7. **Day 5 overloaded**: 7 hours of work on the final day with no buffer.

---

## Recommendations

1. **Add test file to IMPL-002**: Add `backend/tests/test_evidence_gate.py` to IMPL-002's `files_to_create` and add AC: "Test suite with >= 10 test cases covering: empty citations, score above/below threshold, score at exactly threshold, null score, config read failure, both answer() and stream_answer_sse() paths."

2. **Fix IMPL_PLAN.md summary table**: Replace `ChatPanel.tsx` with `PortalChatPage.tsx` in the task summary table for IMPL-004 and IMPL-005 to match the task JSONs.

3. **Add Template C to IMPL-002 or IMPL-005**: Either extend IMPL-002 to also rewrite the existing `no_context` message to Chinese Template C, or add `chat_service.py` to IMPL-005's files_to_modify with a corresponding AC.

4. **Extend IMPL-006 AC**: Add:
   - "Each of the 3 departments has >=15 samples in the expanded dataset"
   - "Results include 95% confidence intervals for all reported proportions"

5. **Extend IMPL-007 AC**: Add: "Safety margin of 0.03-0.05 applied above zero-FP threshold."

6. **Reschedule IMPL-009**: Move IMPL-009 (monitoring dashboard, 3h) to Day 3 or Day 4 as a parallel task. It has no dependencies and reduces Day 5 from 7h to 4h.

7. **Clarify critical path in plan.json**: Update the critical_path field to the true path: `["IMPL-001", "IMPL-002", "IMPL-006", "IMPL-007", "IMPL-008"]` (remove IMPL-003 which is parallel).

---

## Quality Gate

- [x] Dimension 1: Feature Coverage -- **PASS** (8/8 features mapped, 67/71 spec ACs covered = 94.4%)
- [x] Dimension 2: Dependency Consistency -- **PASS** (acyclic DAG, all refs valid, blocking bidirectional)
- [x] Dimension 3: Acceptance Criteria Testability -- **PASS** (56/56 task ACs measurable, no vagueness)
- [x] Dimension 4: Task Completeness -- **PASS** (all fields present in all 9 tasks, hours reasonable)
- [x] Dimension 5: Enhancement Integration -- **PASS** (all 10 EPs reflected, all 8 conflicts addressed)
- [x] Dimension 6: Cross-Feature Consistency -- **PASS** (correct file sequencing, IMPL_PLAN.md doc mismatch only)
- [x] Dimension 7: Timeline Feasibility -- **WARN** (Day 5 = 7h, no buffer, IMPL-006 may overrun)
- [x] Dimension 8: Missing Items -- **WARN** (3 moderate gaps: test file, Template C backend, IMPL_PLAN.md paths; 4 minor gaps)

**Overall**: 6 PASS + 2 WARN = **PROCEED_WITH_CAUTION**

The plan is executable as-is. The 3 moderate recommendations (test file, Template C, path fix) would improve robustness but none are blocking. The implementer should prioritize the test file addition since the evidence gate is a safety-critical component.
