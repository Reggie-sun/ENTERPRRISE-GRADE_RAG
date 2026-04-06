# Product Manager Analysis — RAG Fast Launch Optimization

**Role**: Product Manager
**Scope**: 8 features for 1-week full launch; PM primary ownership of F-005 and F-006, contributing to F-001 and F-004
**Date**: 2026-04-06

---

## Role Perspective

This analysis addresses the RAG fast launch from the user's side of the screen. The system already retrieves documents and generates answers. The product challenge is: (a) making the answer trustworthy through visible evidence, (b) communicating system limits honestly when evidence is insufficient, and (c) setting expectations so users never mistake this for a general-purpose assistant.

The 1-week constraint forces ruthless prioritization. Every frontend change carries integration risk. Every new string of text the user sees must be reviewed. The analysis below reflects these trade-offs.

---

## Feature Point Index

| Feature ID | Name | PM Role | Sub-document |
|------------|------|---------|--------------|
| F-001 | evidence-gate | Contributor (threshold triggers UX) | @analysis-cross-cutting.md |
| F-002 | bundle-freeze | Informed (launch readiness gate) | @analysis-cross-cutting.md |
| F-003 | eval-calibration | Informed (quality evidence for go/no-go) | @analysis-cross-cutting.md |
| F-004 | human-review | Contributor (review bucket definitions) | @analysis-cross-cutting.md |
| **F-005** | **citation-display** | **Primary owner** | **@analysis-F-005-citation-display.md** |
| **F-006** | **guided-abstention** | **Primary owner** | **@analysis-F-006-guided-abstention.md** |
| F-007 | kill-switch | Informed (emergency UX) | @analysis-cross-cutting.md |
| F-008 | monitoring-dashboard | Informed (post-launch feedback loop) | @analysis-cross-cutting.md |

---

## Priority Ordering (1-Week Constraint)

Based on user impact and implementation dependency chain:

1. **F-001 evidence-gate** — MUST land first; everything else depends on when/how abstention triggers.
2. **F-005 citation-display** — MUST land alongside F-001; users need to see why an answer was given.
3. **F-006 guided-abstention** — MUST land alongside F-001; users need to understand why an answer was NOT given.
4. **F-002 bundle-freeze** — MUST complete before launch day; no user-facing impact but blocks go/no-go.
5. **F-003 eval-calibration** — MUST complete before launch day; feeds human review.
6. **F-004 human-review** — MUST complete on launch day minus 1; final go/no-go evidence.
7. **F-007 kill-switch** — SHOULD land by launch day; safety net for emergency.
8. **F-008 monitoring-dashboard** — MAY land post-launch; nice-to-have for launch day monitoring.

F-005 and F-006 are co-dependent with F-001 and MUST be developed in parallel. The evidence gate determines when to abstain; citation display shows evidence; guided abstention explains the absence of evidence.

---

## Success Metrics (Product Perspective)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Citation click-through rate | > 30% of answered queries show at least one citation expanded | Frontend telemetry (post-launch) |
| Abstention clarity | > 80% of users who see abstention try a follow-up question | Event log (abstention → retry rate) |
| Wrong-answer complaints | 0 critical complaints in first 48h | Manual monitoring + feedback channel |
| User expectation accuracy | Users correctly identify system as "document Q&A, not chatbot" | Post-launch survey (week 2) |

---

## Cross-Cutting Summary

See @analysis-cross-cutting.md for:
- Product positioning strategy and messaging framework
- Launch communication plan (internal and user-facing)
- Human review bucket definitions and go/no-go criteria
- Post-launch feedback collection plan
- Kill switch UX behavior
- Monitoring expectations from product side

---

## Per-Feature Deep Dives

- **@analysis-F-005-citation-display.md** — Citation UX: what to show, when, layout, expand behavior, truncation rules, mobile considerations
- **@analysis-F-006-guided-abstention.md** — Abstention UX: wording templates, reformulation suggestions, example questions, tone guidelines, edge cases
