# Feature Spec: F-001 - Evidence Gate

**Priority**: High
**Contributing Roles**: system-architect (lead), test-strategist, product-manager, data-architect
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL introduce a decision layer between retrieval and LLM generation that evaluates whether retrieved citations meet a minimum evidence quality threshold. When evidence is insufficient, the system MUST abstain from answering rather than risk generating a confident but unfounded response.

- The evidence gate MUST operate on post-rerank `Citation.score` values, NOT on Qdrant raw cosine similarity scores (EP-004).
- The gate MUST be inserted in `ChatService` after `build_citations()` returns and before the LLM generation call, leaving retrieval internals untouched.
- The gate MUST distinguish two abstention modes: `no_context` (empty citations) and `evidence_gate_abstain` (non-empty citations but score below threshold) (EP-006).
- The threshold value MUST be calibrated from the expanded eval dataset (F-003) using a zero false-positive methodology.
- All user-facing abstention messages MUST be in Chinese, using PM-defined Template A/B/C (EP-008).
- The gate MUST fail-open: if config read fails or score parsing fails, the system proceeds with normal answer generation.
- The gate MUST apply in both synchronous `answer()` and streaming `stream_answer_sse()` code paths.

## 2. Design Decisions

### 2.1 Score Source: Post-Rerank Citation.score (RESOLVED)

**Decision**: The evidence gate uses `citations[0].score` from the `Citation[]` list returned by `ChatCitationPipeline.build_citations()`, which is the post-rerank fused score.

**Options considered**:
- **Option A**: Use Qdrant raw cosine similarity from `primary_recall_stage.top1_score`. Rejected because raw cosine does not reflect reranking adjustments; the reranker may promote a different document to top-1 with a different score.
- **Option B**: Use post-rerank `Citation.score` (selected). This captures the final retrieval quality after fusion, reranking, and all quality threshold adjustments.

**Trade-off**: Citation.score is a composite metric influenced by fusion weights and reranker behavior. If either changes post-launch, the score distribution shifts and the threshold may need recalibration. This is acceptable because any such change triggers a new bundle freeze (F-002) and re-evaluation (F-003).

**Source roles**: system-architect (architecture integration point), test-strategist (threshold calibration), data-architect (score consistency).

### 2.2 Gate Insertion Point in ChatService

**Decision**: Insert the gate check in `ChatService.answer()` and `ChatService.stream_answer_sse()` immediately after the existing `if not citations` block and before the LLM generation call.

**Rationale**: This insertion point satisfies the hard constraint of not modifying retrieval internals. The gate operates entirely on the `Citation[]` list already produced by `build_citations()`. The existing `if not citations` branch demonstrates the pattern for skipping LLM generation, and the evidence gate follows the same pattern.

**Implementation pattern**:
```
ChatService.answer()
  -> query_rewrite
  -> build_citations()        # returns Citation[]
  -> if not citations: no_context response      # existing
  -> if evidence_gate.should_abstain(citations): gate response  # NEW
  -> else: LLM generation                        # existing
```

**Source roles**: system-architect (component design, SSE considerations).

### 2.3 Abstention Mode Naming (RESOLVED)

**Decision**: Use `mode="evidence_gate_abstain"` as the response mode string, distinct from existing `"no_context"` and `"rag"` modes.

**Mode mapping (EP-001)**:
| Mode | Condition | User-Facing Behavior |
|------|-----------|---------------------|
| `no_context` | Empty citation list | Template C (no documents available) |
| `evidence_gate_abstain` | Non-empty citations but top1_score < threshold | Template A (insufficient evidence) |
| `kill_switch` | Kill switch active (F-007) | Template A (same as gate) |
| `rag` | Normal answer with citations | Full answer display |
| `retrieval_fallback` | LLM unavailable | Citation summary display |

**Boundary clarification (EP-006)**: `no_context` fires when citations list is empty (zero results from retrieval). `evidence_gate_abstain` fires when citations exist but top1 score fails threshold. These are distinct telemetry events and MUST be tracked separately in monitoring.

**Source roles**: system-architect (response schema), product-manager (abstention templates), test-strategist (mode tracking).

### 2.4 EvidenceGateService as Separate Component

**Decision**: Create a dedicated `EvidenceGateService` class in `backend/app/services/evidence_gate_service.py` rather than inlining gate logic in `ChatService`.

**Rationale**: Single responsibility (gate evaluation isolated), testability (unit-testable without full chat pipeline), configurability (reads from `SystemConfigService`).

**Interface**:
```python
class EvidenceGateService:
    def should_abstain(self, citations: list[Citation]) -> tuple[bool, str | None]:
        # Returns (should_abstain, reason)
        # Reasons: None, "no_citations", "insufficient_score"
```

**Source roles**: system-architect (component design).

### 2.5 Config Schema Extension

**Decision**: Add `EvidenceGateConfig` under `_internal_retrieval_controls` in `system_config.json`, following the existing `supplemental_quality_thresholds` pattern.

```python
class EvidenceGateConfig(BaseModel):
    enabled: bool = True
    min_top1_score: float = Field(default=0.60, ge=0.0, le=1.0)
```

The default 0.60 is a starting point; F-003 calibration determines the final value. The initial implementation MUST ship with threshold=0.0 (disabled) and calibrate upward from F-003 results.

**Source roles**: system-architect (config schema), test-strategist (calibration methodology).

### 2.6 Threshold Calibration Methodology

**Decision**: Use a zero false-positive (FP) methodology with safety margin.

**Process**:
1. Run expanded eval (60-80 samples, F-003) against frozen bundle.
2. Construct binary classification per sample: correct vs incorrect retrieval.
3. Find highest threshold where FP (wrong answer allowed through) = 0.
4. Among zero-FP thresholds, select the one minimizing FN (valid answers blocked).
5. Add 0.03-0.05 safety margin above selected threshold.

**Fallback**: If near-100% accuracy persists (few negative samples), synthesize negative samples by pairing real queries with unrelated documents and record scores.

**Source roles**: test-strategist (ROC curve construction, threshold validation protocol), data-architect (score distribution export).

### 2.7 Chinese Localization (EP-008)

**Decision**: All user-facing abstention messages MUST be in Chinese. The evidence gate response text uses PM Template A for insufficient evidence cases.

**Template A (insufficient evidence)**:
```
未能在当前资料库中找到与您的问题直接相关的信息。

您可以尝试：
- 使用更具体的描述，例如包含设备名称、流程编号或文件标题
- 缩小问题范围，聚焦到一个具体环节
- 检查是否有相关资料尚未上传到知识库

您也可以参考以下问题格式：
"{suggested_q_1}"
"{suggested_q_2}"
```

**Source roles**: product-manager (wording templates, tone guidelines).

### 2.8 Fail-Open Error Handling

**Decision**: The evidence gate MUST fail-open. If config read fails, score parsing fails, or any unexpected exception occurs, the system proceeds with normal answer generation.

**Rationale**: The worst case of fail-open is a low-quality answer slipping through, which is the status quo before this feature. A fail-closed gate could block all answers, which is a worse outcome for users.

**Source roles**: system-architect (error containment principle).

## 3. Interface Contract

### 3.1 Backend Service Interface

```python
# backend/app/services/evidence_gate_service.py
class EvidenceGateService:
    def __init__(self, system_config_service: SystemConfigService) -> None: ...

    def should_abstain(self, citations: list[Citation]) -> tuple[bool, str | None]:
        """
        Returns (should_abstain: bool, reason: str | None).
        Reasons: None (gate not triggered), "no_citations", "insufficient_score".
        Fail-open: any exception returns (False, None).
        """
```

### 3.2 Config Schema Extension

```python
# backend/app/schemas/system_config.py (addition)
class EvidenceGateConfig(BaseModel):
    enabled: bool = True
    min_top1_score: float = Field(default=0.60, ge=0.0, le=1.0)

# Extend InternalRetrievalControlsConfig:
evidence_gate: EvidenceGateConfig = Field(default_factory=EvidenceGateConfig)
```

### 3.3 Response Mode Extension

`ChatResponse.mode` (already `str`, not enum) adds `"evidence_gate_abstain"`. No schema change needed.

### 3.4 Trace Enrichment

When evidence gate triggers, `answer` trace stage `details` includes:
```json
{
  "evidence_gate_result": {
    "triggered": true,
    "top1_score": 0.45,
    "threshold_used": 0.60,
    "abstention_reason": "insufficient_score"
  }
}
```

When gate does not trigger:
```json
{
  "evidence_gate_result": {
    "triggered": false,
    "top1_score": 0.82,
    "threshold_used": 0.60
  }
}
```

### 3.5 Streaming (SSE) Behavior

When gate triggers during streaming:
1. `meta` event: `mode="evidence_gate_abstain"`, empty citations
2. `delta` event: Chinese abstention message (Template A)
3. `done` event

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| No retrieval changes | Gate operates on Citation[] output only; retrieval_service internals untouched |
| Single threshold for v1 | No stratified threshold by query type; single `min_top1_score` for all queries |
| Config-based toggle | Threshold adjustable at runtime via `system_config.json` without redeployment |
| Score normalization | Relies on Citation.score being consistently normalized across retrieval modes |

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Threshold too aggressive, blocking valid answers | Medium | High | Start at 0.0; calibrate from F-003 data; runtime adjustable |
| Score distributions differ between eval and production | Medium | High | Safety margin of 0.03-0.05; monitoring dashboard tracks trigger rate |
| Gate adds latency | Low | Low | Score comparison is O(1); config read is cached |
| Fail-open hides real failures | Low | Medium | Monitoring dashboard tracks trigger rate; anomaly detection post-launch |
| Streaming path missed | Low | High | Both `answer()` and `stream_answer_sse()` MUST include gate check |

## 5. Acceptance Criteria

1. **Gate implementation**: `EvidenceGateService` exists in `backend/app/services/evidence_gate_service.py` with `should_abstain()` method.
2. **ChatService integration**: Both `answer()` and `stream_answer_sse()` call the gate after `build_citations()` and before LLM generation.
3. **Mode correctness**: When gate triggers, response has `mode="evidence_gate_abstain"`.
4. **Fail-open verified**: When config read fails or score is null, system proceeds with normal generation (unit test).
5. **Chinese messages**: All abstention response text is in Chinese, using PM-defined templates.
6. **Trace enrichment**: Evidence gate result appears in request trace `details` for both triggered and non-triggered cases.
7. **Threshold calibration**: Threshold value is derived from F-003 expanded eval using zero-FP methodology with safety margin.
8. **Retrospective validation**: Applying threshold to original 43 samples shows 0 false blocks.
9. **Edge cases tested**: Empty citations, score at exactly threshold, null score, score within 0.01 of threshold.
10. **Test suite**: `backend/tests/test_evidence_gate.py` has >= 10 test cases covering all edge cases.

## 6. Detailed Analysis References

- @system-architect/analysis-F-001-evidence-gate.md -- Architecture integration point, component design, SSE considerations, error handling
- @system-architect/analysis-cross-cutting.md -- Central config spine, trace schema alignment, dependency chain
- @test-strategist/analysis-F-001-evidence-gate.md -- Threshold determination method, ROC curve construction, edge case catalog, regression testing
- @test-strategist/analysis-cross-cutting.md -- Score distribution analysis methodology, validation protocol
- @product-manager/analysis-cross-cutting.md -- Evidence gate product behavior, full abstention decision, Chinese templates
- @product-manager/analysis-F-006-guided-abstention.md -- Abstention wording templates (Template A/B/C)
- @data-architect/analysis-F-003-eval-calibration.md -- Score distribution tracking, threshold candidates export

## 7. Cross-Feature Dependencies

**Depends on**:
- F-003 (eval-calibration): Provides score distribution data for threshold calibration. F-001 ships with threshold=0.0 first, then calibrates from F-003 results.

**Required by**:
- F-004 (human-review): Human review MUST evaluate evidence gate triggered samples; gate must be implemented before review.
- F-006 (guided-abstention): Frontend abstention UX renders based on `mode="evidence_gate_abstain"`; the mode string is the integration contract.
- F-008 (monitoring-dashboard): Dashboard tracks evidence gate trigger rate from trace data.

**Shared patterns**:
- Config infrastructure: Uses `SystemConfigService._internal_retrieval_controls` (shared with F-007 `kill_switch`).
- Trace enrichment: Adds `evidence_gate_result` to trace details (shared pattern with F-007 `kill_switch_active`).
- Bundle snapshot: F-002 freezes the evidence gate threshold as part of config_snapshot.

**Integration points**:
- `ChatService.answer()` and `ChatService.stream_answer_sse()` -- gate insertion point
- `SystemConfigService.get_internal_retrieval_controls()` -- config read
- `request_trace_service.record()` -- trace enrichment
