# F-007: Kill Switch — System Architect Analysis

**Feature**: Config-level emergency toggle + rollback documentation
**Priority**: Medium
**Constraint**: Zero code-branch runtime switch; MUST NOT require redeployment
**Date**: 2026-04-06

## 1. Problem Definition

A full-launch with no gradual rollout means there is no safety buffer. If a systemic issue appears post-launch (mass hallucination, corpus corruption, LLM provider outage causing bad fallback), operators need an immediate way to stop the system from generating potentially harmful answers without waiting for a code deploy or container restart. The kill switch provides this: a single config flag that forces all responses into abstention mode.

## 2. Architecture Integration

### Design Principle: Config-Only Activation

The kill switch MUST be a pure config toggle. When activated:

1. `SystemConfigService` reads the kill switch flag from `system_config.json`
2. `ChatService` checks the flag at the start of `answer()` and `stream_answer_sse()`
3. If active, ChatService skips retrieval, LLM, and citation pipeline entirely
4. Returns a fixed abstention response immediately

This avoids code branches in production deployments. The switch is activated by editing `data/system_config.json` on the running server. No restart required because `SystemConfigService` reads from file on every request (no in-memory cache that survives beyond the request).

### Current Config Read Pattern

Examining the existing code:

- `FilesystemSystemConfigRepository.read()` opens the JSON file on every call (no caching beyond the thread lock for write safety)
- `SystemConfigService.get_internal_retrieval_controls()` calls `_read_raw_payload()` which calls `self.repository.read()`
- This means config changes take effect on the next request with no restart

This existing behavior is exactly what the kill switch needs. No architectural changes to the config reading layer are required.

## 3. Component Design

### 3.1 Config Schema Extension

Add a new top-level internal section `_launch_controls` in system_config.json:

```json
{
  "_launch_controls": {
    "kill_switch_enabled": false,
    "force_abstain_message": "The system is temporarily unavailable. Please try again later or contact support."
  }
}
```

**Schema** (in `backend/app/schemas/system_config.py`):

```python
class LaunchControlsConfig(BaseModel):
    """Post-launch emergency controls."""
    kill_switch_enabled: bool = False
    force_abstain_message: str = (
        "The system is temporarily unavailable. "
        "Please try again later or contact support."
    )
```

**Loading**: Extend `SystemConfigService` with a new method following the existing `get_internal_retrieval_controls()` pattern:

```python
LAUNCH_CONTROLS_KEY = "_launch_controls"

def get_launch_controls(self) -> LaunchControlsConfig:
    defaults = LaunchControlsConfig()
    stored = self._read_raw_payload()
    if not stored:
        return defaults
    raw = stored.get(self.LAUNCH_CONTROLS_KEY)
    if raw is None:
        return defaults
    try:
        return LaunchControlsConfig.model_validate(raw)
    except Exception:
        logger.warning("Launch controls config invalid; using defaults", exc_info=True)
        return defaults
```

### 3.2 ChatService Integration

Add the kill switch check at the very start of `answer()` and `stream_answer_sse()`, before any other processing:

```python
def answer(self, request, *, auth_context=None):
    # Kill switch check -- MUST be first
    launch_controls = self.system_config_service.get_launch_controls()
    if launch_controls.kill_switch_enabled:
        return self._build_kill_switch_response(
            request.question, launch_controls.force_abstain_message
        )

    # ... existing flow continues unchanged
```

The check is placed first to minimize work when the switch is active. No retrieval, no query rewrite, no LLM call occurs when the switch is engaged.

### 3.3 Response Format

Kill switch response uses `mode="kill_switch"`:

```python
def _build_kill_switch_response(self, question: str, message: str) -> ChatResponse:
    return ChatResponse(
        question=question,
        answer=message,
        mode="kill_switch",
        model="none",
        citations=[],
    )
```

Using `model="none"` signals that no LLM was invoked. The monitoring dashboard (F-008) can count `mode="kill_switch"` responses to detect emergency states.

### 3.4 Streaming (SSE) Behavior

For `stream_answer_sse()`, the kill switch MUST still produce valid SSE events:

1. `meta` event with `mode="kill_switch"`, empty citations, `model="none"`
2. `delta` event with the force_abstain_message
3. `done` event

No streaming of LLM tokens occurs. The response is immediate.

## 4. Activation and Deactivation Procedure

### Activation (Emergency Stop)

```bash
# On the running server:
cd /path/to/Enterprise-grade_RAG
python -c "
import json
from pathlib import Path
config_path = Path('data/system_config.json')
config = json.loads(config_path.read_text())
config.setdefault('_launch_controls', {})['kill_switch_enabled'] = True
config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
"
# Effect is immediate on next request (no restart needed)
```

A dedicated script SHOULD be provided:

**File**: `scripts/toggle_kill_switch.py`

```bash
python scripts/toggle_kill_switch.py --enable   # Activate
python scripts/toggle_kill_switch.py --disable  # Deactivate
python scripts/toggle_kill_switch.py --status   # Check current state
```

### Deactivation (Resume Normal Operation)

```bash
python scripts/toggle_kill_switch.py --disable
```

The script MUST verify that the config file was successfully written and MUST NOT use atomic rename (which could race with concurrent config writes from the running service). Instead, it SHOULD use the same thread-safe write pattern as `FilesystemSystemConfigRepository`.

## 5. Rollback Documentation

The kill switch is the first line of defense. Full rollback to a known-good bundle (F-002) is the second line.

### Rollback Procedure

1. **Immediate**: Activate kill switch (`--enable`) -- all responses become abstention within seconds
2. **Assess**: Check monitoring dashboard (F-008) for error patterns; review recent traces
3. **Restore**: If bundle-level rollback is needed:
   a. `git checkout {bundle.commit_sha}`
   b. Restore `data/system_config.json` from `bundle.config_snapshot`
   c. Re-index corpus if corpus manifest changed
   d. Restart services: `docker-compose restart`
4. **Verify**: Run `scripts/freeze_bundle.py --verify data/launch-bundle.json`
5. **Deactivate**: `python scripts/toggle_kill_switch.py --disable`
6. **Confirm**: Monitor dashboard for normal response patterns

### Documentation Location

Rollback procedure MUST be documented in the project root as a standalone document:

**File**: `ROLLBACK_PROCEDURE.md`

This document is NOT auto-generated. It is a human-authored runbook that the team reviews before launch.

## 6. Error Handling

### Fail-Open on Config Read Error

If `get_launch_controls()` fails (corrupted config, missing file), the system MUST default to normal operation (`kill_switch_enabled = False`). An emergency switch that triggers on config errors would be far more dangerous than one that fails silently.

```python
def get_launch_controls(self) -> LaunchControlsConfig:
    try:
        # ... config read logic
    except Exception:
        logger.warning("Failed to read launch controls; defaulting to disabled", exc_info=True)
        return LaunchControlsConfig()  # kill_switch_enabled = False
```

### Concurrent Write Safety

The kill switch script writes to `system_config.json` while the running service also reads/writes this file. The existing `FilesystemSystemConfigRepository` uses a `threading.Lock` for writes, but this does NOT protect against external processes.

**Mitigation**: The toggle script SHOULD use the same file write pattern as `FilesystemSystemConfigRepository` (read full JSON, modify in memory, write full JSON). This reduces (but does not eliminate) the risk of race conditions. For the 1-week launch timeline, this is acceptable. A future improvement MAY introduce advisory file locking or a dedicated admin API endpoint.

## 7. Files to Create/Modify

| File | Change Type | Description |
|------|------------|-------------|
| `scripts/toggle_kill_switch.py` | NEW | CLI tool to enable/disable/check kill switch |
| `backend/app/schemas/system_config.py` | MODIFY | Add `LaunchControlsConfig` |
| `backend/app/services/system_config_service.py` | MODIFY | Add `get_launch_controls()` method |
| `backend/app/services/chat_service.py` | MODIFY | Add kill switch check at start of `answer()` and `stream_answer_sse()` |
| `data/system_config.json` | MODIFY | Add `_launch_controls` section |
| `ROLLBACK_PROCEDURE.md` | NEW | Human-authored rollback runbook |

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Race condition during config write | Low | Medium | Use same write pattern as existing service; accept risk for launch |
| Kill switch accidentally left enabled | Medium | High | Script `--status` check; monitoring dashboard alerts on kill_switch mode count |
| Config file corrupted during toggle | Low | Critical | Script validates JSON after write; fail-open default prevents cascade |
| Operator forgets rollback procedure | Medium | Medium | ROLLBACK_PROCEDURE.md reviewed by team before launch; keep it short and step-by-step |
| SSH access to production required for toggle | High | Low | Acceptable for launch; future MAY add admin API endpoint for remote toggle |
