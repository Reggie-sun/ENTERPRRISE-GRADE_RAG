# Cross-Cutting Architecture Decisions — System Architect

**Scope**: Shared constraints and patterns spanning F-001, F-002, F-007, F-008
**Date**: 2026-04-06

## 1. Central Configuration Spine

### Decision: SystemConfigService as Single Runtime Truth

All four features converge on `SystemConfigService` as the authoritative runtime configuration source. The existing architecture already provides:

- `FilesystemSystemConfigRepository` with thread-safe read/write to `data/system_config.json`
- `SystemConfigService.get_effective_config()` for unauthenticated reads
- `SystemConfigService.get_internal_retrieval_controls()` for internal-only config
- `SystemConfigUpdateRequest` / `SystemConfigResponse` schemas with Pydantic validation

**Impact on features**:
- F-001 (evidence gate): Reads threshold from a new `_internal_retrieval_controls.evidence_gate` section
- F-007 (kill switch): Reads boolean from a new top-level `_launch_controls.kill_switch_enabled` section
- F-002 (bundle freeze): Snapshots the entire `system_config.json` file as part of `launch-bundle.json`
- F-008 (monitoring): No config dependency; reads JSONL files directly

### Schema Extension Pattern

New config sections MUST follow the existing `_internal_*` prefix convention for non-contract fields. This preserves the existing `SystemConfigUpdateRequest` schema (which only exposes contract-stable fields) and keeps internal controls invisible to the admin API.

```python
# In system_config.json, new sections:
{
  "_internal_retrieval_controls": {
    "supplemental_quality_thresholds": { ... },  # existing
    "evidence_gate": {                             # F-001 new
      "enabled": true,
      "min_top1_score": 0.60,
      "min_citation_count": 1
    }
  },
  "_launch_controls": {                            # F-007 new
    "kill_switch_enabled": false,
    "force_abstain_message": "..."
  }
}
```

The `get_internal_retrieval_controls()` method already implements the deep-merge-with-defaults pattern. F-001 and F-007 SHOULD extend this pattern rather than introduce new methods.

## 2. Trace Schema Alignment

### Decision: Reuse Existing Trace Fields, Add Minimal Extensions

The existing `request_trace_service.record()` already captures `mode`, `response_mode`, `error_message`, `details`, and `stages`. F-001 and F-007 MUST enrich these fields rather than create parallel logging paths.

**Required trace additions**:
- F-001: In the `answer` trace stage `details`, add `evidence_gate_result` with fields `triggered` (bool), `top1_score` (float), `threshold_used` (float), `abstention_reason` (str | null)
- F-007: In the `answer` trace stage `details`, add `kill_switch_active` (bool) when the switch overrides the response

These additions are additive. They MUST NOT change the shape of existing trace records. F-008 monitoring script MUST be able to parse both old and new trace formats gracefully.

## 3. Bundle Freeze Contract

### Decision: launch-bundle.json as Immutable Artifact

The bundle freeze (F-002) produces a single JSON file that captures the complete deployable state. Other features depend on this artifact:

- F-003 (eval calibration): MUST run against the exact commit SHA and corpus manifest recorded in the bundle
- F-004 (human review): MUST reference the bundle ID in its evidence package
- F-007 (kill switch): The rollback procedure references the bundle to restore a known-good state

**Bundle schema** (see @analysis-F-002-bundle-freeze.md for full specification):

```
launch-bundle.json
  bundle_id: str          # unique ID
  frozen_at: ISO8601      # timestamp
  commit_sha: str         # git HEAD
  config_snapshot: {}     # full system_config.json contents
  corpus_manifest: {}     # from data-architect
  index_info: {}          # collection + embedding model
  acl_seed: {}            # ACL snapshot
```

**Invariance rule**: Once written, launch-bundle.json MUST NOT be modified. Any change to commit/config/corpus/index/ACL after freeze triggers a new bundle with a new bundle_id.

## 4. Dependency and Sequencing Constraints

```
F-002 (bundle freeze)
  |
  +---> F-003 (eval calibration) -- MUST use frozen bundle
  |       |
  |       +---> F-004 (human review) -- MUST reference eval results
  |
  +---> F-007 (kill switch) -- rollback references bundle

F-001 (evidence gate) -- independent of bundle freeze, but config MUST be frozen with bundle
F-008 (monitoring dashboard) -- fully independent, lowest priority
```

**Critical path**: F-002 -> F-003 -> F-004 -> go/no-go decision. F-001 and F-007 SHOULD be implemented in parallel with F-002 since they share the config infrastructure. F-008 MAY be deferred to post-launch.

## 5. Error Containment Principle

No feature in this launch MAY introduce a new failure mode that crashes the system. Specifically:

- F-001: If evidence gate logic fails (config read error, score parsing), the system MUST fall through to normal answer generation (fail-open). This prevents the gate from becoming a single point of failure.
- F-007: If kill switch config is unreadable, the system MUST default to normal operation (fail-open), not to forced abstention. The switch is explicitly opt-in.
- F-002: If bundle freeze script encounters an error, it MUST fail loudly with a non-zero exit code and NOT produce a partial bundle file.
- F-008: Monitoring script errors MUST NOT affect running services.

## 6. File Layout Convention

New files introduced by these features MUST follow existing project conventions:

| Feature | New Files | Location Convention |
|---------|-----------|---------------------|
| F-001 | `evidence_gate_service.py` | `backend/app/services/` |
| F-001 | Schema additions | `backend/app/schemas/system_config.py` |
| F-002 | `freeze_bundle.py` | `scripts/` (project root) |
| F-002 | `launch-bundle.json` | `data/` (gitignored, generated) |
| F-007 | Config flag only | `data/system_config.json` (existing) |
| F-008 | `monitor_dashboard.py` | `scripts/` (project root) |

No new Python packages, no new infrastructure, no new database tables.
