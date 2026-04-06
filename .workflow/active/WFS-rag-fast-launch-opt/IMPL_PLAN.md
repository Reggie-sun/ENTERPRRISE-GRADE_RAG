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

| ID | Feature | Title | Priority | Day | Files | Mode |
|----|---------|-------|----------|-----|-------|------|
| IMPL-001 | F-007 | Kill Switch + Rollback Doc | High | 1 | `chat_service.py`, `system_config.py`, `system_config_service.py`, `types.ts`, `toggle_kill_switch.py`, `ROLLBACK_PROCEDURE.md` | standard |
| IMPL-002 | F-001 | Evidence Gate (Phase A: implement, threshold=0.0) | High | 1-2 | `evidence_gate_service.py` (new), `chat_service.py`, `system_config.py`, `types.ts`, `client.ts`, `test_evidence_gate.py` (new) | standard |
| IMPL-003 | F-002 | Bundle Freeze Script | High | 1-2 | `scripts/freeze_bundle.py` (new) | lite |
| IMPL-004 | F-005 | Citation Display (frontend minimal) | Medium | 1-2 | `PortalChatPage.tsx` | lite |
| IMPL-005 | F-006 | Guided Abstention (frontend) | Medium | 2 | `AbstentionCard.tsx` (new), `PortalChatPage.tsx` | lite |
| IMPL-006 | F-003 | Eval Calibration (43 → 60-80 samples) | High | 3 | `eval/retrieval_samples_v2.yaml` (new), `run_retrieval_eval.py` | standard |
| IMPL-007 | F-001 | Threshold Calibration (Phase B) | High | 4 | `system_config.json` | standard |
| IMPL-008 | F-004 | Human Review + Launch Decision | High | 5 | `scripts/run_human_review.py` (new), `evidence_package.json` (new) | lite |
| IMPL-009 | F-008 | Monitoring Dashboard Script | Low | 3-4 | `scripts/monitor_dashboard.py` (new) | lite |

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

## AGENTS.md 合规要求

### 工作流模式分类

| Task | Mode | Reason |
|------|------|--------|
| IMPL-001 | **standard** | Cross-module (schema + service + scripts + frontend types). Adds mode to stable contract `POST /api/v1/chat/ask`. |
| IMPL-002 | **standard** | Cross-module (service + schema + frontend types). Adds `evidence_gate_abstain` mode to stable contract. Modifies chat chain. |
| IMPL-003 | lite | Single new script, no existing file modifications, no schema/API/retrieval changes. |
| IMPL-004 | lite | Single frontend file, pure display, no API/schema/retrieval changes. |
| IMPL-005 | lite | Frontend-only (component + page), no API/schema/retrieval changes. |
| IMPL-006 | **standard** | Touches eval domain → triggers Retrieval auto-enforcement (AGENTS.md § 自动触发规则 §1). |
| IMPL-007 | **standard** | Modifies system-config true source. Threshold selection is high-risk Brain decision. |
| IMPL-008 | lite | Creates new scripts, no existing file modifications. But go/no-go decision is Brain-only. |
| IMPL-009 | lite | Single new script, no existing file modifications. |

### Spec 必需（standard 模式任务）

以下任务必须先写 spec（使用 `.agent/specs/feature-template.md`）再实现：

- **IMPL-001**: Kill Switch — 跨模块，影响稳定主契约
- **IMPL-002**: Evidence Gate — 跨模块，影响稳定主契约，新增 response mode
- **IMPL-006**: Eval Calibration — 触发 Retrieval auto-enforcement，需 ack GATE NOT PASSED

### 所有任务必须 /review

AGENTS.md §3.3: "所有非文档代码改动默认必须 /review"。每个 IMPL 的 implementation_steps 最后一步都是 `/review`。

### 强制读取（Mandatory Reads）

每个任务 JSON 的 `agents_compliance.mandatory_reads` 字段列出了代码修改前必须完成的读取清单。实现步骤 step 0 统一为 "MANDATORY READS"。

### 主契约保护

IMPL-001 和 IMPL-002 在 `POST /api/v1/chat/ask` response 中新增 mode 值（`kill_switch`, `evidence_gate_abstain`）。必须：
1. 修改前核对 `MAIN_CONTRACT_MATRIX.md`
2. 同步更新 `frontend/src/api/types.ts`（ChatResponse mode union）
3. 检查 `frontend/src/api/client.ts` 兼容性
4. 跑 `backend/tests/test_main_contract_endpoints.py` + `test_main_contract_errors.py`

### Retrieval State 约束（IMPL-006）

IMPL-006 必须在实现前确认：
- 当前阶段：Phase 1B-B, GATE NOT PASSED
- eval 不稳定：conservative_trigger_count 1-11 波动
- 本任务只扩展 eval 样本 + 添加 score 捕获，**不改 retrieval 内部逻辑**
- 禁止进入 Phase 2B chunk 实现
- 禁止混用 8020/8021 baseline

### Harness Task Contracts（高风险任务）

以下任务需要 `.agent/runs/<task>.yaml` task contract（per `.agent/harness/policy.yaml`）：

- **IMPL-001**: `api_schema` category, task_required: true
- **IMPL-002**: `api_schema` category, task_required: true
- **IMPL-006**: `retrieval` category, task_required: true

### Brain / Executor 分工

| Decision | Who | Why |
|----------|-----|-----|
| Schema/contract 边界定义 | Brain (GPT-5.4) | 稳定主契约改动 |
| Evidence gate 集成边界 | Brain | 影响 chat→retrieval 链路 |
| Threshold 选择 | Brain | 高风险决策 |
| Go/No-Go 判决 | Brain | 发布决策 |
| 具体编码实现 | Executor (GLM) | 已确认边界内执行 |
| 前端组件开发 | Executor | 纯展示层 |
| 脚本开发 | Executor | 独立工具 |

### IMPL-001/002 新增文件

IMPL-002 额外需要修改：
- `frontend/src/api/types.ts` — 添加 `evidence_gate_abstain` mode
- `frontend/src/api/client.ts` — 检查 response handling 兼容性

IMPL-001 额外需要修改：
- `frontend/src/api/types.ts` — 添加 `kill_switch` mode

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Threshold too aggressive → high abstention | Start at 0.0, calibrate from data |
| Bundle drift after freeze | Monitoring script checks against launch-bundle.json |
| Config write race (kill switch) | Advisory file lock |
| Eval exposes more problems than expected | This is a feature, not a bug — fix before launch |
| Stable contract mode expansion | IMPL-001/002 must check MAIN_CONTRACT_MATRIX.md, sync frontend types |
| Eval instability (conservative_trigger_count 1-11) | IMPL-006 must ack retrieval-state.md, not claim calibration if unstable |
