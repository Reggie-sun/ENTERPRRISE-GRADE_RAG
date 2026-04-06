# System Architect Analysis — RAG Fast Launch Optimization

**Role**: System Architect
**Date**: 2026-04-06
**Scope**: F-001, F-002, F-007, F-008 (primary); contributes to F-003, F-004
**Constraint**: 1-week launch window; no retrieval internal changes; minimal frontend; no new infrastructure

## Role Perspective

The system architect evaluates launch readiness from a structural integrity standpoint: are the component boundaries clean, are the failure modes contained, and can the system be frozen, deployed, and if necessary rolled back with confidence? Every feature is measured against three criteria: (1) does it touch retrieval internals, (2) can it be toggled at runtime, and (3) does it leave a trace for post-launch diagnosis.

## Feature Point Index

| Feature | Name | Architectural Concern | Sub-document |
|---------|------|-----------------------|--------------|
| F-001 | evidence-gate | New decision layer in chat pipeline; score threshold as runtime config | @analysis-F-001-evidence-gate.md |
| F-002 | bundle-freeze | Immutable artifact generation; commit/config/corpus/index/ACL snapshot | @analysis-F-002-bundle-freeze.md |
| F-003 | eval-calibration | Dependency on frozen bundle; eval MUST run against pinned state | (test-strategist lead; architect supplies bundle contract) |
| F-004 | human-review | 5-bucket taxonomy alignment with trace schema | (test-strategist lead; architect supplies trace fields) |
| F-007 | kill-switch | Config-level emergency toggle; zero-code-branch runtime switch | @analysis-F-007-kill-switch.md |
| F-008 | monitoring-dashboard | Script-based analysis of existing JSONL traces | @analysis-F-008-monitoring-dashboard.md |

## Cross-Cutting Summary

All four primary features share a common architectural spine: **SystemConfigService** acts as the single source of runtime truth. Evidence gate reads its threshold from system config; kill switch is a boolean flag in system config; bundle freeze snapshots the entire system config file; monitoring dashboard parses the trace files that chat_service already writes. This means system_config.json is the central coordination point and MUST be version-controlled alongside launch-bundle.json.

The dependency chain is strict: bundle freeze (F-002) MUST complete before eval calibration (F-003) and human review (F-004) begin. Evidence gate (F-001) and kill switch (F-007) are independent of the bundle freeze but MUST use the same config infrastructure. Monitoring dashboard (F-008) is fully independent and MAY be deferred.

See @analysis-cross-cutting.md for shared architectural decisions, technology choices, and cross-feature constraints.
