# SYNTH-001

## Input Summary

- Reviewed initial directions from `ideas/idea-001.md`, `ideas/idea-002.md`, and `ideas/idea-003.md`.
- Incorporated critique from `critiques/critique-001.md`.
- Used the GC revision in `ideas/idea-004.md` as the strongest corrected baseline.
- Grounded the recommendation against this repo's frozen contract and retrieval rules in:
  - `MAIN_CONTRACT_MATRIX.md`
  - `RETRIEVAL_OPTIMIZATION_PLAN.md`
  - `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
  - `.agent/context/repo-map.md`

## Extracted Themes

| Theme | Strength | Supporting Ideas |
| --- | ---: | --- |
| Pinned launch bundle instead of loose "verified" claims | 10 | IDEA-001, IDEA-002, IDEA-004 |
| Narrow launch surface to current retrieval/chat contracts | 9 | IDEA-001, IDEA-002, IDEA-003, IDEA-004 |
| Accuracy must be evidence-first and abstention-friendly | 9 | IDEA-001, IDEA-002, IDEA-003, IDEA-004 |
| Go/no-go must include human review of final answers, not metrics alone | 10 | CHALLENGE-001, IDEA-004 |
| Post-launch optimization room should be preserved by deferring noncritical seams | 8 | IDEA-001, IDEA-003, IDEA-004 |

## Conflict Resolution

### 1. Fast launch vs optimization-ready refactors

- Conflict: `idea-003` wanted to land future-facing seams now, while the critique flagged ingestion/eval regression risk.
- Resolution: defer chunk strategy registry, live-API-coupled eval changes, and new internal tuning surfaces from the launch path.
- Rationale: `RETRIEVAL_OPTIMIZATION_PLAN.md` and backlog both enforce the order `supplemental -> chunk -> router -> rerank`; shipping faster means proving the current core, not widening it.

### 2. Retrieval diagnostics vs real answer safety

- Conflict: the early ideas leaned on citation count and diagnostic thresholds as launch gates.
- Resolution: keep diagnostics as supporting signals only; the real gate is a reviewed answer package with `correct`, `abstained`, `unsupported-query`, `wrong-with-citation`, and `permission-boundary-failure`.
- Rationale: this directly answers the critique that cited but wrong answers are the main trust risk.

### 3. Configuration rollback vs full release rollback

- Conflict: early rollback thinking was mostly threshold/config oriented.
- Resolution: define rollback at the bundle boundary: app commit, frontend exposure mode, config snapshot, corpus manifest, index artifact/version, metadata mode, ACL seed state.
- Rationale: the critique correctly identified data/index/ACL drift as launch-breaking even when config is unchanged.

## Integrated Proposals

### Proposal A: Pinned-Bundle Accuracy Launch

**Core concept**

Launch only the current `POST /api/v1/retrieval/search` and `POST /api/v1/chat/ask` surface, with SOP explicitly out of scope, and only from one pinned launch bundle plus one immutable evidence package. If the current bundle cannot pass that gate after minimal Phase 1 threshold calibration and containment tuning, stop and do not broaden scope.

**Source ideas combined**

- `idea-001`: evidence-first MVP, abstention bias, defer SOP, keep public contract stable
- `idea-002`: hard scope fence, mandatory citations, conservative supplemental behavior, scorecard/rollback posture
- `idea-003`: keep stable contracts and internal diagnostics, preserve optimization room
- `idea-004`: pinned launch bundle, immutable evidence, unsupported-query containment, bundle-level rollback
- `critique-001`: corrected false-safety around loose validation, metric-only gating, and config-only rollback

**Addressed challenges from critiques**

- Replaces vague "verified corpus" claims with a named launch bundle
- Replaces metric-only release logic with reviewed final-answer outcomes
- Adds explicit unsupported-query containment at UI and answer-policy level
- Defines permission-boundary and rollback checks beyond config thresholds
- Removes future-facing optimization seams from the fast-launch critical path

**Feasibility score:** 9/10  
**Innovation score:** 4/10

**Recommended path**

1. Freeze one launch bundle and treat it as the only candidate under review.
2. Keep product scope to evidence-backed Q&A only:
   - expose `retrieval/search` and `chat/ask`
   - hide/disable SOP entry points and unsupported workflows in release mode
   - frame the product as document-grounded Q&A, not general reasoning
3. Do one minimal launch-hardening pass on the existing retrieval/chat core only:
   - calibrate only current Phase 1 supplemental/answer containment behavior if needed
   - do not start chunk, router, rerank, contract, or ingestion refactors for launch
4. Generate one immutable evidence package from that exact bundle.
5. Release only if the package passes all hard gates; otherwise stop and iterate on the same narrow surface.

**Scope boundaries**

- In scope:
  - current stable retrieval/chat contracts from `MAIN_CONTRACT_MATRIX.md`
  - controlled corpus and ACL scope
  - abstain/reframe behavior for weak or unsupported requests
  - diagnostics/traces/logs as internal evidence surfaces
- Out of scope:
  - all SOP endpoints and UI exposure
  - chunk refactors or strategy registry work
  - router/hybrid/rerank optimization beyond what is strictly required to stabilize the current bundle
  - new public API fields, new user-facing tuning controls, broad assistant positioning

**Launch gates**

- Bundle integrity gate:
  - commit SHA
  - frontend release mode
  - model identifier
  - system-config snapshot
  - corpus manifest
  - index artifact/version
  - metadata store mode
  - ACL seed state
  - rollout scope
  - verified eval sample subset
- Evidence gate:
  - retrieval eval on the frozen sample subset
  - human-reviewed answer outcomes with buckets:
    - `correct`
    - `abstained`
    - `unsupported-query`
    - `wrong-with-citation`
    - `permission-boundary-failure`
  - zero unwaived `permission-boundary-failure`
  - zero tolerated `wrong-with-citation` in the reviewed launch set unless explicitly waived and documented
- Containment gate:
  - unsupported queries are visibly scoped out in UI copy
  - unsupported queries reliably abstain or reframe in answer policy
- Rollback gate:
  - prior known-safe bundle exists
  - answer-generation kill switch is defined
  - corpus disable list / rollback path is documented
  - bundle-level restore path for config, index, and ACL state is documented

**Minimum artifacts needed for safe release**

- `launch-bundle.json` or equivalent manifest with the exact pinned bundle fields
- immutable evidence package containing:
  - retrieval eval result
  - reviewed answer set and bucket counts
  - permission-boundary preflight result
  - signoff timestamp and reviewers
- rollout note defining exposed UI surface and unsupported query classes
- rollback note mapping kill switches and restore steps to the prior known-safe bundle

**Key benefits**

- Maximizes speed by refusing noncritical refactors
- Keeps the release promise aligned with current stable contracts
- Optimizes for trust: under-answering is preferred to persuasive wrong answers
- Preserves post-launch headroom because chunk/router/rerank work remains available after baseline proof

**Remaining risks**

- A narrow reviewed sample can still miss real traffic patterns
- Abstention rate may feel conservative until later optimization phases land
- Permission/corpus drift after signoff invalidates the evidence package immediately

## Coverage Analysis

- Speed: satisfied by narrowing the release to existing retrieval/chat flows and deferring optimization seams.
- Accuracy: satisfied by the pinned bundle plus reviewed answer-quality gate, not by retrieval metrics alone.
- Optimization headroom: satisfied by holding contracts steady and deferring chunk/router/rerank work to post-launch phases already defined in the retrieval plan/backlog.
- Main uncovered dependency: whoever owns release operations must actually maintain the launch bundle artifact and review loop; without that ownership, observability and rollback stay theoretical.

## Recommendation

Use `idea-004` as the final backbone and make one sharp call: **ship the current RAG only as a pinned-bundle, evidence-reviewed, retrieval/chat-only product, and do not pull future optimization work into the launch candidate.** If the current bundle cannot pass those gates after minimal Phase 1 containment tuning, delay launch rather than expanding scope.
