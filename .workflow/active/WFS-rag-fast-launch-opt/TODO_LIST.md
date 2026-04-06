# RAG Fast Launch — TODO List

**Session**: WFS-rag-fast-launch-opt
**Timeline**: 5 days
**AGENTS.md Compliance**: All tasks follow `spec → plan → implement → review` workflow

## Pre-Day 1: Spec Preparation (Standard Mode Tasks)

- [ ] **IMPL-001 spec**: Write feature spec using `.agent/specs/feature-template.md` (cross-module: schema + service + scripts + frontend)
- [ ] **IMPL-002 spec**: Write feature spec using `.agent/specs/feature-template.md` (cross-module: service + schema + frontend types, affects stable contract)
- [ ] **IMPL-006 spec**: Write feature spec using `.agent/specs/feature-template.md` (eval domain, triggers Retrieval auto-enforcement)

## Day 1-2: Implementation

- [ ] **IMPL-001**: Kill Switch + Rollback Doc (4h) `blocks: IMPL-002` `mode: standard`
  - [ ] **MANDATORY READS** (API/Contract + Schema module):
    - [ ] MAIN_CONTRACT_MATRIX.md
    - [ ] backend/app/api/v1/endpoints/chat.py
    - [ ] backend/app/schemas/chat.py + system_config.py
    - [ ] frontend/src/api/types.ts + client.ts
    - [ ] backend/tests/test_main_contract_endpoints.py + test_main_contract_errors.py
    - [ ] .agent/context/repo-map.md
  - [ ] Check MAIN_CONTRACT_MATRIX.md for POST /api/v1/chat/ask mode field constraints
  - [ ] Add LaunchControlsConfig schema
  - [ ] Add get_launch_controls() to SystemConfigService
  - [ ] Add kill switch check in ChatService.answer() + stream_answer_sse()
  - [ ] Update frontend/src/api/types.ts with 'kill_switch' mode
  - [ ] Create scripts/toggle_kill_switch.py
  - [ ] Create ROLLBACK_PROCEDURE.md
  - [ ] **/review** before marking complete
  - [ ] Write harness task contract `.agent/runs/IMPL-001.yaml`

- [ ] **IMPL-002**: Evidence Gate Phase A (threshold=0.0) (5h) `depends: IMPL-001` `mode: standard`
  - [ ] **MANDATORY READS** (API/Contract + Schema + chat chain):
    - [ ] MAIN_CONTRACT_MATRIX.md
    - [ ] backend/app/api/v1/endpoints/chat.py
    - [ ] backend/app/schemas/chat.py + system_config.py
    - [ ] frontend/src/api/types.ts + client.ts
    - [ ] backend/tests/test_main_contract_endpoints.py + test_main_contract_errors.py
    - [ ] backend/app/services/chat_service.py
    - [ ] backend/app/services/chat_citation_pipeline.py
    - [ ] .agent/context/repo-map.md + retrieval-state.md
  - [ ] Check MAIN_CONTRACT_MATRIX.md for POST /api/v1/chat/ask mode field constraints
  - [ ] Create evidence_gate_service.py
  - [ ] Integrate gate into ChatService after build_citations()
  - [ ] Add Chinese abstention message (Template A)
  - [ ] Add evidence_gate_result to trace
  - [ ] Update frontend/src/api/types.ts with 'evidence_gate_abstain' mode
  - [ ] Review frontend/src/api/client.ts for response handling compatibility
  - [ ] Create test_evidence_gate.py with >=10 test cases
  - [ ] **/review** before marking complete
  - [ ] Write harness task contract `.agent/runs/IMPL-002.yaml`

- [ ] **IMPL-003**: Bundle Freeze Script (3h) `mode: lite`
  - [ ] **MANDATORY READS**: .agent/context/repo-map.md, data/system_config.json, MAIN_CONTRACT_MATRIX.md
  - [ ] Create scripts/freeze_bundle.py
  - [ ] Implement corpus manifest via Qdrant scroll + filesystem reconciliation
  - [ ] Add --verify mode for drift detection
  - [ ] **/review** before marking complete

- [ ] **IMPL-004**: Citation Display (frontend minimal) (2h) `mode: lite`
  - [ ] **MANDATORY READS**: .agent/context/repo-map.md, frontend/src/api/types.ts, PortalChatPage.tsx
  - [ ] Add citation count badge
  - [ ] Fix truncation to 200 chars
  - [ ] Add expand/collapse toggle
  - [ ] **/review** before marking complete

## Day 2: Frontend

- [ ] **IMPL-005**: Guided Abstention (frontend) (4h) `mode: lite`
  - [ ] **MANDATORY READS**: .agent/context/repo-map.md, frontend/src/api/types.ts, PortalChatPage.tsx
  - [ ] Verify mode values ('no_context', 'evidence_gate_abstain') match IMPL-002 types.ts update
  - [ ] Create AbstentionCard.tsx (Template A + C)
  - [ ] Add Chinese abstention messages
  - [ ] Add suggested questions with click-to-submit
  - [ ] Integrate into PortalChatPage.tsx
  - [ ] **/review** before marking complete

## Day 3: Freeze + Eval

- [ ] **IMPL-006**: Eval Calibration (60-80 samples) (5h) `depends: IMPL-002, IMPL-003` `mode: standard`
  - [ ] **MANDATORY READS** (FULL Retrieval module):
    - [ ] MAIN_CONTRACT_MATRIX.md
    - [ ] RETRIEVAL_OPTIMIZATION_PLAN.md
    - [ ] RETRIEVAL_OPTIMIZATION_BACKLOG.md
    - [ ] eval/README.md
    - [ ] eval/retrieval_samples.yaml
    - [ ] scripts/eval_retrieval.py
    - [ ] backend/app/services/retrieval_service.py
    - [ ] **.agent/context/retrieval-state.md** (acknowledge Phase 1B-B GATE NOT PASSED)
  - [ ] **ACKNOWLEDGE**: retrieval-state.md — Phase 1B-B, GATE NOT PASSED, eval instability
  - [ ] **CONSTRAINT**: Do NOT modify retrieval_service.py or any retrieval internals
  - [ ] **CONSTRAINT**: Do NOT enter Phase 2B chunk implementation
  - [ ] **CONSTRAINT**: Do NOT mix 8020/8021 baselines
  - [ ] Extend eval samples (semantic/coarse/anti-pattern)
  - [ ] Run eval with gate capturing post-rerank scores
  - [ ] Generate score distribution report per query type
  - [ ] Document retrieval-state acknowledgment in eval report
  - [ ] **/review** before marking complete
  - [ ] Write harness task contract `.agent/runs/IMPL-006.yaml`

## Day 4: Threshold Calibration

- [ ] **IMPL-007**: Set Evidence Gate Threshold (2h) `depends: IMPL-006` `mode: standard`
  - [ ] **MANDATORY READS**: system_config_service.py, chat_service.py, evidence_gate_service.py, data/system_config.json
  - [ ] **Brain decision required**: Threshold selection is a Brain (GPT-5.4) decision
  - [ ] Analyze score distributions
  - [ ] Select conservative_95 threshold with safety margin (0.03-0.05)
  - [ ] Validate zero false-positives
  - [ ] Update system_config.json
  - [ ] **/review** before marking complete

## Day 5: Human Review + Launch

- [ ] **IMPL-008**: Human Review + Go/No-Go (4h) `depends: IMPL-007` `mode: lite`
  - [ ] **MANDATORY READS**: .agent/context/repo-map.md, data/system_config.json, eval/results/
  - [ ] **Brain decision required**: Go/No-Go verdict is a Brain (GPT-5.4) decision
  - [ ] Select 20-30 stratified samples
  - [ ] Two-reviewer 5-bucket classification
  - [ ] Check hard gates (wrong-with-citation=0)
  - [ ] Compile evidence_package.json
  - [ ] Launch decision
  - [ ] **/review** before marking complete

- [ ] **IMPL-009**: Monitoring Dashboard Script (3h) `mode: lite`
  - [ ] **MANDATORY READS**: .agent/context/repo-map.md, trace/log file formats
  - [ ] Create scripts/monitor_dashboard.py
  - [ ] Unified alert thresholds
  - [ ] Optional bundle drift detection
  - [ ] **/review** before marking complete

---

**Go/No-Go Hard Gates**:
- wrong-with-citation = 0
- permission-boundary-failure = 0
- citation presence on non-abstain answers = 100%

**Go/No-Go Soft Gates**:
- correct + abstained >= 85%
- correct >= 80%

**AGENTS.md Compliance Checklist** (every task):
- [ ] Mandatory reads completed BEFORE code changes
- [ ] MAIN_CONTRACT_MATRIX.md checked (if touching schema/API)
- [ ] frontend types.ts/client.ts synced (if touching API response)
- [ ] Spec written (standard mode tasks only)
- [ ] /review completed
- [ ] Harness task contract written (standard mode + high-risk tasks)
- [ ] Output format: "改了什么 / 验证了什么 / 风险是什么"
