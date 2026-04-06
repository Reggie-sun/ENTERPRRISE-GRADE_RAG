# Feature Spec: F-007 - Kill Switch

**Priority**: Medium
**Contributing Roles**: system-architect (lead), product-manager, data-architect
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system MUST provide a configuration-level emergency toggle that forces all chat responses into abstention mode without requiring code deployment, container restart, or SSH access beyond a simple script execution.

- The kill switch MUST be activated by editing `system_config.json` via a provided CLI script
- When active, the system MUST skip retrieval, LLM generation, and citation pipeline entirely
- The kill switch MUST return a fixed Chinese-language abstention message (EP-008)
- The system MUST fail-open: if config read fails, default to normal operation
- The kill switch response MUST use `mode="kill_switch"` for monitoring distinction
- A rollback procedure document MUST exist before launch (ROLLBACK_PROCEDURE.md)

## 2. Design Decisions

### 2.1 Config-Only Activation (RESOLVED)

**Decision**: The kill switch is a pure config flag in `system_config.json`, read on every request.

**Options considered**:
- **Option A**: Environment variable toggle. Rejected: requires process restart to take effect.
- **Option B**: Config file flag (selected). Takes effect on next request via existing `FilesystemSystemConfigRepository.read()` which reads from file on every call.
- **Option C**: Admin API endpoint. Rejected: requires new endpoint, authentication setup, and code changes for v1.

**Trade-off**: No atomic cross-process safety (see EP-007), but acceptable for 1-week launch. Future MAY add admin API.

### 2.2 Kill Switch vs Evidence Gate Ordering (RESOLVED)

**Decision**: Kill switch check is FIRST (before evidence gate), ensuring it overrides all other logic.

**Rationale**: Kill switch is emergency stop; evidence gate is quality filter. Emergency stop must be highest priority.

### 2.3 User-Facing Message (RESOLVED via EP-008)

**Decision**: Kill switch message MUST be Chinese, using PM's Template A pattern. The message MUST NOT indicate system failure to the user.

**Config field**: `force_abstain_message` defaults to: "系统正在维护中，请稍后再试。"

**Source**: product-manager (tone guidelines), system-architect (implementation)

### 2.4 Config Write Safety (RESOLVED via EP-007)

**Decision**: For v1, the toggle script uses advisory file locking via `.config_write_lock`. If lock acquisition fails after 30s, the script aborts with error.

**Trade-off**: Adds ~20 lines of code vs. accepting race condition risk. Worth it for full-launch safety.

## 3. Interface Contract

### 3.1 Config Schema Extension

```json
{
  "_launch_controls": {
    "kill_switch_enabled": false,
    "force_abstain_message": "系统正在维护中，请稍后再试。"
  }
}
```

### 3.2 Response Format

```python
ChatResponse(
    question=request.question,
    answer=force_abstain_message,  # Chinese
    mode="kill_switch",
    model="none",
    citations=[],
)
```

### 3.3 CLI Script Interface

```bash
python scripts/toggle_kill_switch.py --enable   # Activate
python scripts/toggle_kill_switch.py --disable  # Deactivate
python scripts/toggle_kill_switch.py --status   # Check current state
```

## 4. Constraints & Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Config write race condition | Low | Critical | Advisory file lock (EP-007) |
| Kill switch accidentally left enabled | Medium | High | `--status` check; monitoring alerts on kill_switch mode count |
| Config file corrupted during toggle | Low | Critical | Script validates JSON after write; fail-open default |
| SSH access required for toggle | High | Low | Acceptable for v1; future MAY add admin API |

## 5. Acceptance Criteria

1. `scripts/toggle_kill_switch.py --enable` activates kill switch; next chat request returns `mode="kill_switch"` with Chinese message
2. `scripts/toggle_kill_switch.py --disable` restores normal operation
3. `scripts/toggle_kill_switch.py --status` correctly reports enabled/disabled state
4. Kill switch response is identical in both `answer()` and `stream_answer_sse()` code paths
5. Config read failure defaults to kill_switch_enabled=False (fail-open)
6. `ROLLBACK_PROCEDURE.md` exists in project root with step-by-step instructions
7. Advisory file lock prevents concurrent config writes

## 6. Detailed Analysis References

- @../system-architect/analysis-F-007-kill-switch.md
- @../product-manager/analysis-cross-cutting.md (tone guidelines, Template A)
- @../data-architect/analysis-cross-cutting.md (config hash integrity)

## 7. Cross-Feature Dependencies

- **Depends on**: None (fully independent)
- **Required by**: F-008 (monitoring counts kill_switch responses)
- **Shared patterns**: Config read pattern with F-001 (both read from SystemConfigService)
- **Integration points**: Kill switch check runs before F-001 evidence gate in ChatService flow
