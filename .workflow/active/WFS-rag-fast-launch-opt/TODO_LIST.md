# RAG Fast Launch — TODO List

**Session**: WFS-rag-fast-launch-opt
**Timeline**: 5 days

## Day 1-2: Implementation

- [ ] **IMPL-001**: Kill Switch + Rollback Doc (3h) `blocks: IMPL-002`
  - [ ] Add LaunchControlsConfig schema
  - [ ] Add get_launch_controls() to SystemConfigService
  - [ ] Add kill switch check in ChatService.answer() + stream_answer_sse()
  - [ ] Create scripts/toggle_kill_switch.py
  - [ ] Create ROLLBACK_PROCEDURE.md
- [ ] **IMPL-002**: Evidence Gate Phase A (threshold=0.0) (4h) `depends: IMPL-001`
  - [ ] Create evidence_gate_service.py
  - [ ] Integrate gate into ChatService after build_citations()
  - [ ] Add Chinese abstention message (Template A)
  - [ ] Add evidence_gate_result to trace
- [ ] **IMPL-003**: Bundle Freeze Script (3h)
  - [ ] Create scripts/freeze_bundle.py
  - [ ] Implement corpus manifest via Qdrant scroll + filesystem reconciliation
  - [ ] Add --verify mode for drift detection
- [ ] **IMPL-004**: Citation Display (frontend minimal) (2h)
  - [ ] Add citation count badge
  - [ ] Fix truncation to 200 chars
  - [ ] Add expand/collapse toggle

## Day 2: Frontend

- [ ] **IMPL-005**: Guided Abstention (frontend) (4h)
  - [ ] Create AbstentionCard.tsx (Template A + C)
  - [ ] Add Chinese abstention messages
  - [ ] Add suggested questions with click-to-submit
  - [ ] Integrate into ChatPanel.tsx

## Day 3: Freeze + Eval

- [ ] **IMPL-006**: Eval Calibration (60-80 samples) (4h) `depends: IMPL-002, IMPL-003`
  - [ ] Extend eval samples (semantic/coarse/anti-pattern)
  - [ ] Run eval with gate capturing post-rerank scores
  - [ ] Generate score distribution report per query type

## Day 4: Threshold Calibration

- [ ] **IMPL-007**: Set Evidence Gate Threshold (2h) `depends: IMPL-006`
  - [ ] Analyze score distributions
  - [ ] Select conservative_95 threshold
  - [ ] Validate zero false-positives
  - [ ] Update system_config.json

## Day 5: Human Review + Launch

- [ ] **IMPL-008**: Human Review + Go/No-Go (4h) `depends: IMPL-007`
  - [ ] Select 20-30 stratified samples
  - [ ] Two-reviewer 5-bucket classification
  - [ ] Check hard gates (wrong-with-citation=0)
  - [ ] Compile evidence_package.json
  - [ ] Launch decision
- [ ] **IMPL-009**: Monitoring Dashboard Script (3h)
  - [ ] Create scripts/monitor_dashboard.py
  - [ ] Unified alert thresholds
  - [ ] Optional bundle drift detection

---

**Go/No-Go Hard Gates**:
- wrong-with-citation = 0
- permission-boundary-failure = 0
- citation presence on non-abstain answers = 100%

**Go/No-Go Soft Gates**:
- correct + abstained >= 85%
- correct >= 80%
