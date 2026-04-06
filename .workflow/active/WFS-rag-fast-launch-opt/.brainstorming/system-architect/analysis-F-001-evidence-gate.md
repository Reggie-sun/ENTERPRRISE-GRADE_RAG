# F-001: Evidence Gate — System Architect Analysis

**Feature**: Chat layer score threshold + citation validation
**Priority**: High
**Constraint**: MUST NOT modify retrieval_service internals
**Date**: 2026-04-06

## 1. Problem Definition

The RAG system currently sends all retrieved citations to the LLM for answer generation regardless of their relevance score. This means low-quality retrievals can produce plausible but unfounded answers. The evidence gate introduces a decision point after retrieval but before LLM generation: if the best citation does not meet a minimum score threshold, the system MUST abstain rather than risk a confident wrong answer.

## 2. Architecture Integration Point

### Current Flow (simplified)

```
ChatService.answer()
  -> query_rewrite
  -> ChatCitationPipeline.build_citations()
     -> RetrievalService.search_candidates()  # returns candidates with scores
     -> rerank
     -> build Citation[] list
  -> if no citations: _build_no_context_response()
  -> else: LLMGenerationClient.generate()
  -> return ChatResponse
```

### Proposed Gate Insertion Point

The evidence gate MUST be inserted in `ChatService` after `build_citations()` returns and before the LLM generation call. The existing `if not citations` branch already demonstrates the pattern: when citations are insufficient, skip LLM and return an abstention response.

```
ChatService.answer()
  -> query_rewrite
  -> ChatCitationPipeline.build_citations()
     -> RetrievalService.search_candidates()
     -> rerank
     -> build Citation[] list
  -> if no citations: _build_no_context_response()         # existing
  -> **NEW: if evidence_gate.should_abstain(citations):    # F-001
         _build_evidence_gate_response()**
  -> else: LLMGenerationClient.generate()
  -> return ChatResponse
```

This insertion point satisfies the hard constraint: retrieval internals are untouched. The gate operates entirely on the `Citation[]` list that `build_citations()` already produces.

## 3. Component Design

### 3.1 EvidenceGateService

A new service class that encapsulates gate logic. Placing it in a separate service (rather than inline in ChatService) provides:

- Single responsibility: gate threshold evaluation is isolated
- Testability: can be unit-tested without the full chat pipeline
- Configurability: reads threshold from SystemConfigService

**File**: `backend/app/services/evidence_gate_service.py`

```python
class EvidenceGateService:
    """Evaluates whether retrieved citations meet minimum evidence thresholds."""

    def __init__(self, system_config_service: SystemConfigService) -> None: ...

    def should_abstain(self, citations: list[Citation]) -> tuple[bool, str | None]:
        """Returns (should_abstain, reason).

        Decision logic:
        1. If gate is disabled in config, return (False, None)
        2. If no citations, return (True, "no_citations") -- redundant with existing check
        3. If top-1 citation score < configured threshold, return (True, "insufficient_score")
        4. Return (False, None)
        """
```

### 3.2 Config Schema Extension

The evidence gate configuration MUST live under `_internal_retrieval_controls` in system_config.json, following the existing pattern established by `supplemental_quality_thresholds`.

**Extension to `InternalRetrievalControlsConfig`** in `backend/app/schemas/system_config.py`:

```python
class EvidenceGateConfig(BaseModel):
    enabled: bool = True
    min_top1_score: float = Field(default=0.60, ge=0.0, le=1.0)

class InternalRetrievalControlsConfig(BaseModel):
    supplemental_quality_thresholds: SupplementalQualityThresholdsConfig = ...
    evidence_gate: EvidenceGateConfig = Field(default_factory=EvidenceGateConfig)
```

The threshold default of 0.60 is a starting point. The eval calibration (F-003) will determine the final value. The bundle freeze (F-002) will snapshot whatever value is configured at freeze time.

### 3.3 ChatService Integration

In `ChatService.__init__`, instantiate `EvidenceGateService`:

```python
self.evidence_gate_service = EvidenceGateService(self.system_config_service)
```

In `ChatService.answer()` and `ChatService.stream_answer_sse()`, add the gate check after the existing `if not citations` block:

```python
if not citations:
    # existing no_context handling
    ...

# NEW: evidence gate check
should_abstain, gate_reason = self.evidence_gate_service.should_abstain(citations)
if should_abstain:
    response = self._build_evidence_gate_response(
        request.question, citations, gate_reason
    )
    response_mode = response.mode
    answer_text = response.answer
    # ... trace recording with evidence_gate_result details
    # ... skip to telemetry recording (same pattern as no_context branch)
```

### 3.4 Response Schema

The evidence gate response MUST use `mode="evidence_gate_abstain"` to distinguish from existing `"no_context"` and `"rag"` modes. This allows the monitoring dashboard (F-008) to count gate-triggered abstentions separately.

**No schema change needed**: `ChatResponse.mode` is `str`, not an enum. The new mode value is additive.

The abstention answer text SHOULD include guided reformulation suggestions per F-006 requirements. For the initial implementation, a static template suffices:

```
"Based on the available documents, I cannot find sufficiently relevant information to answer your question. Try rephrasing with specific document names, error codes, or equipment model numbers."
```

## 4. Error Handling

### Fail-Open Principle

The evidence gate MUST fail open. If any of the following occur, the system MUST proceed with normal answer generation:

- Config read fails (threshold unavailable)
- Citation score parsing fails (non-numeric score)
- EvidenceGateService raises an unexpected exception

This prevents the gate from becoming a system-level failure point. The worst case is that a low-quality answer slips through, which is the status quo before this feature.

### Implementation

```python
def should_abstain(self, citations: list[Citation]) -> tuple[bool, str | None]:
    try:
        controls = self.system_config_service.get_internal_retrieval_controls()
        gate_config = controls.evidence_gate
        if not gate_config.enabled:
            return False, None
        if not citations:
            return True, "no_citations"
        top1_score = citations[0].score
        if top1_score < gate_config.min_top1_score:
            return True, "insufficient_score"
        return False, None
    except Exception:
        logger.warning("Evidence gate evaluation failed; falling through to normal generation", exc_info=True)
        return False, None
```

## 5. Observability

### Trace Enrichment

When the evidence gate triggers, the `answer` trace stage details MUST include:

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

When the gate does NOT trigger, the details SHOULD still record:

```json
{
  "evidence_gate_result": {
    "triggered": false,
    "top1_score": 0.82,
    "threshold_used": 0.60
  }
}
```

This enables the monitoring dashboard (F-008) to track gate trigger rates and score distributions over time.

### Event Log

The existing `ChatTelemetryRecorder.record_chat_event()` already records outcome and response_mode. Using `response_mode="evidence_gate_abstain"` automatically integrates with the existing event log pipeline. No event log schema changes required.

## 6. Streaming (SSE) Considerations

The evidence gate check MUST also be applied in `stream_answer_sse()`. The gate evaluation happens before any SSE events are sent, so if the gate triggers, the stream MUST emit:

1. `meta` event with `mode="evidence_gate_abstain"` and empty citations
2. `delta` event with the abstention message
3. `done` event

This mirrors the existing pattern for the `no_context` case in the streaming path (see `stream_answer_sse()` around line 508-511).

## 7. Files to Modify

| File | Change Type | Description |
|------|------------|-------------|
| `backend/app/services/evidence_gate_service.py` | NEW | Gate evaluation logic |
| `backend/app/services/chat_service.py` | MODIFY | Instantiate gate service; add gate check in `answer()` and `stream_answer_sse()`; add `_build_evidence_gate_response()` |
| `backend/app/schemas/system_config.py` | MODIFY | Add `EvidenceGateConfig`; extend `InternalRetrievalControlsConfig` |
| `data/system_config.json` | MODIFY | Add `evidence_gate` section under `_internal_retrieval_controls` |

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Threshold too aggressive, blocking valid answers | Medium | High | Start conservative (0.60); calibrate via F-003; runtime adjustable via system config |
| Gate adds latency to every request | Low | Low | Score comparison is O(1); config read is cached by SystemConfigService |
| Fail-open causes false negatives (gate should trigger but does not) | Low | Medium | Monitoring dashboard tracks gate trigger rate; anomaly detection post-launch |
| Citation scores are not normalized consistently across retrieval modes | Medium | High | Use the `score` field from `Citation` which is already the normalized fusion score; verify with eval |
