# IDEA-004

## Topic

最快上线当前 RAG，暂不处理 SOP，优先保证回答准确性，同时保留后续可优化空间。

## Angles

- accuracy-first MVP
- launch guardrails
- optimization-ready architecture

## Mode

GC Revision

## Revision Context

This revision addresses the critique's `CRITICAL` and `HIGH` findings:

- launch claims were not tied to one frozen bundle containing corpus, index, model, config, and ACL state
- the answer gate relied too much on unproven diagnostics and lacked a reviewed `wrong-with-citation` bucket
- rollback was too config-centric and did not cover index, corpus, ACL, or frontend exposure drift
- optimization-ready seams were leaking into the fast-launch path and increasing regression surface

## Ideas

### 1. Replace "verified corpus" with one pinned launch bundle

The release recommendation should stop using vague terms like "verified corpus" and instead define one launch bundle that is the only valid object for go/no-go review. That bundle should pin: commit SHA, frontend release mode, model identifier, system-config snapshot, corpus manifest, index build/version, metadata store mode, ACL seed state, rollout scope, and the exact verified eval sample subset used for signoff.

Revision rationale: this replaces the earlier false-safety language around "verified corpus + verified ACL" with a single immutable release object. If any one of those elements changes, the bundle is no longer the launch candidate and prior accuracy evidence is invalid.

Potential impact: makes "accuracy-first" falsifiable and auditable instead of narrative-only, while also shrinking release ambiguity across app, data, and permission layers.

Implementation hint: treat the launch bundle as a named artifact, not a loose checklist. Every launch discussion, smoke pass, and rollback reference should point back to the same bundle ID.

### 2. Make go/no-go depend on an immutable evidence package, not retrieval metrics alone

The hard launch gate should be an evidence package generated from the pinned launch bundle and frozen at signoff time. It should include retrieval metrics, but also a human-reviewed answer set with at least these buckets: `correct`, `abstained`, `unsupported-query`, `wrong-with-citation`, and `permission-boundary-failure`. A candidate only passes if the reviewed answer outcomes stay within explicit thresholds and there are zero unwaived permission-boundary failures.

Revision rationale: this directly fixes the critique that citation count and top-k metrics can still ship persuasive wrong answers. Retrieval diagnostics remain useful, but only as supporting evidence under a reviewed answer-quality gate.

Potential impact: moves launch safety from "the system retrieved something plausible" to "the final answer behavior was reviewed and classified."

Implementation hint: keep the evidence package immutable after signoff. If config, corpus, index, ACL, or model changes, regenerate the package from scratch instead of carrying forward partial approvals.

### 3. Add a hard unsupported-query containment policy to the launch surface

The launch plan should explicitly define unsupported query classes and keep them out of the "accuracy" promise. For this release, unsupported classes should include SOP-shaped requests, broad cross-document synthesis, open-ended reasoning, and queries that require policy interpretation beyond cited text. Those queries should be contained at both the UI and answer-policy layer: clear product copy up front, constrained suggestions, and a standard abstain-or-reframe response path.

Revision rationale: earlier ideas assumed product framing and abstention would be enough, but the critique correctly noted that users will still test outside the intended scope. This adds a concrete containment boundary instead of relying on user restraint.

Potential impact: protects the fast-launch accuracy story by reducing the number of off-scope requests that get misread as product failure.

Implementation hint: the launch review should include a small unsupported-query set in the evidence package so the team verifies containment behavior before release, not after first-user surprises.

### 4. Define rollback by bundle boundary, not just by config switch

Rollback needs to cover the full release bundle: app commit, frontend exposure mode, config snapshot, corpus manifest, index artifact, and ACL seed state. The realistic posture is not "everything is one-click reversible," but "every launch bundle declares which layers are reversible immediately, which require restore/redeploy, and which require launch stop." That means the plan should include a generation kill switch, corpus disable list, known-safe prior bundle, and clear boundaries for when a bad index or ACL state forces rollback to the previous pinned bundle.

Revision rationale: this fixes the earlier overstatement that rollback could be treated mainly as threshold reset. Config-only rollback is insufficient if the live issue is caused by data/index drift, ACL mismatch, or frontend exposing unsupported paths.

Potential impact: gives operations a credible failure posture and avoids improvising during the first production regression.

Implementation hint: define rollback in descending order of blast-radius control: disable answer generation if needed, reduce exposed surface, restore prior config, restore prior corpus/index/ACL bundle, then reopen traffic.

### 5. Remove optimization seams from the fast-launch critical path and defer them behind the bundle

The revised recommendation should explicitly defer any change that exists mainly to prepare future optimization rather than reduce current launch risk. That includes the chunk strategy registry refactor, live-API-coupled eval flow, new internal tuning flags without governance, and any router/rerank/chunk tuning that is not required to stabilize the pinned bundle. Future optimization room is preserved by documenting these seams as post-launch tracks, not by landing them in the release candidate.

Revision rationale: the earlier architecture idea leaked future-facing changes into the launch path and increased regression surface in ingestion and evaluation. This revision preserves optimization space by keeping those changes outside the launch-critical bundle.

Potential impact: shortens the critical path, reduces regression risk, and makes the release recommendation internally coherent with the stated "fast launch now" goal.

Implementation hint: the synthesis should separate `launch-critical` from `post-launch optimization` workstreams. If a change does not strengthen bundle integrity, evidence quality, scope containment, or rollback readiness, it should be deferred.

## Summary

The revised recommendation is to launch only from a pinned release bundle and an immutable evidence package, with human-reviewed answer outcomes and explicit permission/scope checks as the real go/no-go gate. The critical path should stay narrow: freeze retrieval/chat scope, contain unsupported queries, define rollback at the bundle level, and defer optimization-ready seams until after the first stable launch bundle is proven.
