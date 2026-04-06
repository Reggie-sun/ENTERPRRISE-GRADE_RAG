# Synthesis Changelog

**Session**: WFS-rag-fast-launch-opt
**Generated**: 2026-04-06

## Enhancements Applied

- **EP-001**: Mode mapping unified — no_context, evidence_gate_abstain, kill_switch, rag, retrieval_fallback. Applied to F-001, F-006, F-007, F-008 specs.
- **EP-002**: Bundle freeze dirty worktree strategy — block on data/eval/ changes, warn on others. Applied to F-002 spec.
- **EP-003**: Go/No-Go threshold harmonization — zero tolerance in human review, <5% in full eval. Applied to F-004 spec.
- **EP-004**: Score field source — evidence gate uses post-rerank Citation.score, not Qdrant raw cosine. Applied to F-001, F-003, F-008 specs.
- **EP-005**: Unified monitoring thresholds — error 2%, gate trigger WARNING 30%/CRITICAL 40%, P95 15s. Applied to F-008 spec.
- **EP-006**: Evidence gate boundary — no_context (empty citations) vs evidence_gate_abstain (non-empty, low score). Applied to F-001 spec.
- **EP-007**: Kill switch config write safety — advisory file lock. Applied to F-007 spec.
- **EP-008**: Chinese localization — all user-facing abstention messages must be Chinese (PM Template A/B/C). Applied to F-001, F-006, F-007 specs.
- **EP-009**: Unified 5-day timeline — Day1-2 implement → Day3 freeze+eval → Day4 calibrate → Day5 review+launch. Applied to all specs via feature-index.json.
- **EP-010**: Corpus manifest source — Qdrant as primary, filesystem as reconciliation check. Applied to F-002 spec.

## Conflicts Resolved

- **F-001 / Score field source**: RESOLVED — post-rerank Citation.score. Rationale: gate must evaluate the same score the user sees in citations. Trade-off: eval framework must capture post-rerank scores (one-time enhancement).
- **F-002 / Dirty worktree**: RESOLVED — block on data/eval/, warn on others. Rationale: 1-week sprint cannot afford full-clean-tree requirement during parallel development.
- **F-002 / Corpus manifest source**: RESOLVED — Qdrant primary + filesystem reconciliation. Rationale: Qdrant is the actual query source; filesystem catches upload-but-not-indexed gaps.
- **F-003 / Anti-pattern expected_doc_ids**: RESOLVED — exempt from non-empty requirement when should_refuse=true. Rationale: anti-pattern queries should not reference documents by definition.
- **F-004 / wrong-with-citation threshold**: RESOLVED — zero tolerance in human review subset, <5% in full eval. Rationale: review subset is the go/no-go decision; full eval is the monitoring baseline.
- **F-006 / Two vs three abstention modes**: RESOLVED — v1 uses two modes (no_context + evidence_gate_abstain). PM's Template B (out-of-scope) deferred to v2. Rationale: backend cannot reliably distinguish out-of-scope in v1.
- **F-007 / Config write race condition**: RESOLVED — advisory file lock (.config_write_lock) with 30s timeout. Rationale: adds ~20 lines of code, prevents worst-case corruption.
- **F-008 / Alert threshold inconsistency**: RESOLVED — unified threshold table merging sys-architect (WARNING), product-manager (CRITICAL), data-architect (strictest). Rationale: single source of truth prevents operator confusion.

## Unresolved Items

None. All cross-role conflicts have been resolved with explicit decisions.

## Complexity Score: 5/8

- Feature count: 8 → 2 points
- UNRESOLVED conflicts: 0 → 0 points
- Participating roles: 4 → 1 point
- Cross-feature dependencies: 6+ → 2 points
