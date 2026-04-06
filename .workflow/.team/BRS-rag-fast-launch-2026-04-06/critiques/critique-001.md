# CHALLENGE-001

## Ideas Reviewed

- `ideas/idea-001.md` - accuracy-first MVP
- `ideas/idea-002.md` - launch guardrails
- `ideas/idea-003.md` - optimization-ready architecture

## Per-idea Challenges

### idea-001.md

1. `CRITICAL` "已验证语料 + 已验证权限模型" is underspecified and creates false safety.
If launch readiness is decided on a "verified corpus" without freezing the exact corpus manifest, index version, ACL seed state, and metadata store mode used in eval, the team can easily ship a materially different system than the one it validated. This is not a minor ops detail. It invalidates the core accuracy-first claim and introduces permission-boundary risk at the same time.

2. `HIGH` The proposed answerability gate assumes diagnostic signals are already calibrated enough to be a launch safety barrier.
Citation count, top1/topk quality, and conflict heuristics are useful signals, but none of the ideas prove they separate "safe to answer" from "looks plausible but wrong." Without an explicit negative set and a target abstention/error tradeoff, the gate can still allow confident wrong answers while also over-rejecting valid ones.

3. `HIGH` The eval gate proposal overstates what a small fixed sample can prove.
Using the current sample set as a blocker is better than using demo intuition, but the idea jumps too quickly from "reproducible benchmark" to "production-ready evidence." If semantic/coarse remains weak, a small or skewed set can make launch look more accurate than real traffic will be.

4. `MEDIUM` "Citation must be user-readable" is necessary, but it is not equivalent to "citation supports the claim."
Readable snippets and page numbers can still create persuasive but weak evidence when chunk boundaries are broad or the answer paraphrases beyond what the cited text supports.

### idea-002.md

1. `HIGH` The guardrail set is missing a hard operational gate for unsupported-query handling.
The ideas assume scope control through product messaging and abstention alone, but do not define what happens when users still submit broad summary, cross-document reasoning, or SOP-shaped questions. Without an explicit unsupported-query policy and UI-level containment, early users will test the system outside the claimed launch boundary and interpret abstentions or weak answers as inaccuracy.

2. `HIGH` The launch scorecard risks measuring the wrong thing.
Top1/topk, citation presence, and abstention rate are not enough if there is no reviewed "wrong but cited" bucket. A citation-rich wrong answer is more damaging than an abstention, and the proposed scorecard does not explicitly require claim-support review on answer outputs.

3. `HIGH` The rollback posture is too configuration-centric.
A config rollback helps with thresholds and experimental flags, but it does not address bad index builds, stale corpus content, broken ACL seed application, or frontend exposure drift. For a fast launch, the real rollback kit also needs data/index rollback and a way to disable specific corpora or answer generation entirely.

4. `MEDIUM` "Observable by default" can become passive logging without ownership.
The idea assumes traces and logs will shorten diagnosis, but it does not assign who reviews low-citation answers, who triages abstention spikes, or what metric threshold triggers rollback. Instrumentation without an operating loop does not materially reduce launch risk.

### idea-003.md

1. `HIGH` The optimization-ready architecture proposal leaks pre-optimization scope into the fast-launch path.
The chunk strategy registry is a future-facing seam, but it is still an ingestion refactor. That adds regression surface in a high-risk area before the team has proven the current launch bundle is stable. For a "fast launch now" recommendation, this is likely too much architecture for too little immediate accuracy gain.

2. `HIGH` "Same core for online serving and offline eval" is directionally correct, but "eval through the live API" is a hidden coupling risk.
Live-API replay can introduce nondeterminism from auth state, deployment config drift, request middleware, rate limiting, or environment-only toggles. The goal should be behavioral equivalence with pinned artifacts, not a hard dependency on the mutable serving edge.

3. `MEDIUM` Internal-only flags still need governance, not just isolation.
Keeping controls internal avoids contract churn, but it does not by itself prevent silent drift. If internal flags can change without a frozen baseline bundle and release checklist, the team can accidentally invalidate its own launch evidence while still claiming the public surface is unchanged.

## Cross-Idea Missing Gates

- `CRITICAL` No idea fully defines a launch bundle artifact.
The recommendation needs one frozen object that ties together sample set version, config snapshot, corpus manifest, index version, model version, ACL seed state, and effective rollout scope. Without that, "accuracy-first" remains a narrative, not a verifiable release condition.

- `HIGH` No idea defines a human review gate for answer correctness.
The proposals lean heavily on retrieval metrics and citation structure, but they still need a reviewed set of final answers classified as correct, abstained, unsupported, or wrong-with-citation.

- `HIGH` No idea defines a permission-leak or cross-scope launch check.
Since several ideas rely on conservative supplemental behavior and verified ACL, the launch plan needs an explicit preflight that proves the live permission boundary matches the evaluated one.

## Summary Table

| Scope | Critical | High | Medium | Low |
| --- | ---: | ---: | ---: | ---: |
| idea-001 | 1 | 2 | 1 | 0 |
| idea-002 | 0 | 3 | 1 | 0 |
| idea-003 | 0 | 2 | 1 | 0 |
| Cross-idea | 1 | 2 | 0 | 0 |
| Total | 2 | 9 | 3 | 0 |

## GC Signal

`REVISION_NEEDED`

The current direction is usable, but not yet safe to recommend as-is. The next revision should reduce false safety by adding a frozen launch bundle, explicit answer-review criteria, live permission-boundary checks, and a rollback posture that covers data/index state in addition to config thresholds.
