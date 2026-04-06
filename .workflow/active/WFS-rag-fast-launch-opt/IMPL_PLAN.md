# RAG Fast Launch Implementation Plan

**Session**: WFS-rag-fast-launch-opt
**Generated**: 2026-04-06
**Timeline**: 5 days
**Mode**: Single agent execution

## Goal

1周内完成证据型 RAG 问答系统的全量发布。首发仅暴露 `retrieval/search` + `chat/ask`，不包含 SOP。

## Scope

| In Scope | Out of Scope |
|----------|-------------|
| Evidence gate (score threshold) | SOP |
| Bundle freeze mechanism | Chunk/router/rerank refactoring |
| Eval calibration (43 → 60-80 samples) | New API endpoints |
| Human review (5-bucket) | General chat assistant positioning |
| Citation display (minimal frontend) | New infrastructure |
| Guided abstention (frontend) | Retrieval internal changes |
| Kill switch (config-level) | |
| Monitoring dashboard (script) | |

## Dependency Graph

```
IMPL-001 (kill-switch) ──→ IMPL-002 (evidence-gate, Phase A)
                                        ↓
IMPL-003 (bundle-freeze) ──→ IMPL-006 (eval-calibration)
                                        ↓
                               IMPL-007 (threshold-calibration)
                                        ↓
                               IMPL-008 (human-review + launch)

IMPL-004 (citation-display) ──┐
IMPL-005 (guided-abstention) ─┤── Parallel, no backend deps
IMPL-009 (monitoring) ────────┘
```

## Task Summary

| ID | Feature | Title | Priority | Day | Files |
|----|---------|-------|----------|-----|-------|
| IMPL-001 | F-007 | Kill Switch + Rollback Doc | High | 1 | `chat_service.py`, `system_config.py`, `scripts/toggle_kill_switch.py`, `ROLLBACK_PROCEDURE.md` |
| IMPL-002 | F-001 | Evidence Gate (Phase A: implement, threshold=0.0) | High | 1-2 | `evidence_gate_service.py` (new), `chat_service.py`, `system_config.py` |
| IMPL-003 | F-002 | Bundle Freeze Script | High | 1-2 | `scripts/freeze_bundle.py` (new) |
| IMPL-004 | F-005 | Citation Display (frontend minimal) | Medium | 1-2 | `ChatPanel.tsx` |
| IMPL-005 | F-006 | Guided Abstention (frontend) | Medium | 2 | `AbstentionCard.tsx` (new), `ChatPanel.tsx` |
| IMPL-006 | F-003 | Eval Calibration (43 → 60-80 samples) | High | 3 | `eval/retrieval_samples.yaml`, `run_retrieval_eval.py` |
| IMPL-007 | F-001 | Threshold Calibration (Phase B) | High | 4 | `system_config.json` |
| IMPL-008 | F-004 | Human Review + Launch Decision | High | 5 | `scripts/run_human_review.py` (new), `evidence_package.json` (new) |
| IMPL-009 | F-008 | Monitoring Dashboard Script | Low | 5 | `scripts/monitor_dashboard.py` (new) |

## Execution Order

### Day 1-2: Implementation (IMPL-001 → IMPL-005)

**Critical Path**: IMPL-001 → IMPL-002 (kill switch must be in chat_service.py before evidence gate modifies it)

**Parallel Track**:
- IMPL-003 (bundle freeze) — independent script
- IMPL-004 + IMPL-005 (frontend) — independent from backend

### Day 3: Freeze + Eval (IMPL-006)

**Prerequisite**: IMPL-002 Phase A (threshold=0.0) + IMPL-003 must be complete
**Action**: Freeze bundle → Run extended eval → Capture score distributions

### Day 4: Calibration (IMPL-007)

**Prerequisite**: IMPL-006 eval results with score distributions
**Action**: Analyze scores → Set threshold → Re-verify

### Day 5: Review + Launch (IMPL-008 + IMPL-009)

**Prerequisite**: IMPL-007 calibrated threshold
**Action**: Human review → Evidence package → Go/no-go → Launch

## Key Constraints

1. Evidence gate uses **post-rerank Citation.score** (NOT Qdrant raw cosine)
2. All user-facing messages MUST be Chinese
3. Kill switch MUST fail-open (default disabled on config error)
4. Bundle freeze blocks on uncommitted data/eval/ changes
5. Kill switch code must land before evidence gate code (same file: chat_service.py)

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Threshold too aggressive → high abstention | Start at 0.0, calibrate from data |
| Bundle drift after freeze | Monitoring script checks against launch-bundle.json |
| Config write race (kill switch) | Advisory file lock |
| Eval exposes more problems than expected | This is a feature, not a bug — fix before launch |
