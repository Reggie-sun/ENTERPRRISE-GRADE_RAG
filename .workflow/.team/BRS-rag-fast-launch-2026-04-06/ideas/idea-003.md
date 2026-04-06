# Topic

最快上线当前 RAG，暂不处理 SOP，优先保证回答准确性，同时保留后续可优化空间。

## Angles

- optimization-ready architecture

## Mode

- Initial Generation

## Ideas

### 1. Thin Stable Contract, Fat Internal Diagnostics

Keep launch scope strictly behind the already frozen `retrieval/search`, `chat/ask`, and `system-config` contracts. Treat accuracy iteration as an internal concern: extend `diagnostic`, traces, snapshots, and eval outputs instead of adding public request or response fields.

- Key assumption: current stable contracts are already sufficient for launch traffic and frontend integration.
- Potential impact: fastest path to production because frontend and external callers do not need to re-integrate when retrieval logic changes.
- Implementation hint: keep new knobs under internal config and diagnostic surfaces only, following the existing `_internal_retrieval_controls` pattern and the contract split in `MAIN_CONTRACT_MATRIX.md`.

### 2. Single Retrieval Core With Dual Lanes: Online Serving and Offline Eval

Do not build a separate “optimization pipeline” code path. Use the same `RetrievalService` core and protected `/api/v1/retrieval/search` behavior for both real answers and replay evaluation, so any threshold, chunk, or router change is measurable against the exact online logic.

- Key assumption: launch risk is dominated by drift between what is tested and what actually serves users.
- Potential impact: later optimization stays cheap because every experiment is automatically comparable to production behavior.
- Implementation hint: keep eval scripts calling the live API, persist request snapshots and event traces, and make config/index version part of every baseline artifact.

### 3. Internal Feature Flags Only for Retrieval Controls, Not Public Product Shape

Ship with a narrow set of internal switches for threshold tuning, canary compare, and fallback behavior, but avoid exposing new user-facing options. This preserves a simple launch surface while leaving room to tune supplemental recall, rerank canary, and future router weights without contract churn.

- Key assumption: most near-term optimization will come from runtime control of existing behavior, not from new product features.
- Potential impact: faster iteration with lower rollback cost because experiments are reversible configuration changes first.
- Implementation hint: continue storing retrieval-only controls under internal system config, and snapshot every experiment to `eval/results/` plus a baseline config file before changes.

### 4. Chunk Strategy Registry Inside Ingestion, With Default-Preserving Fallback

Refactor the chunking decision boundary conceptually into an internal strategy registry, even if launch only uses the existing `TextChunker` plus current structured path. The goal is not to add document-type product features now, but to create one stable seam where future `manual / policy / faq / sop_wi / generic` strategies can plug in without reopening ingestion flow or upload contracts.

- Key assumption: chunk quality will become the next bottleneck after threshold calibration stabilizes.
- Potential impact: avoids a later rewrite of ingestion when optimization moves from online tuning to index-quality work.
- Implementation hint: keep routing fully internal to ingestion; derive family from filename/content heuristics first and preserve current fallback semantics.

### 5. Evidence-First Answer Gate Above Retrieval, Not a New Retrieval Fork

For fast launch, accuracy should come from a small answerability gate: if retrieval evidence is weak, sparse, or contradictory, prefer a constrained answer or explicit insufficiency response instead of speculative generation. This should sit above the shared retrieval core so the same retrieval outputs can later feed stricter scoring, citation shaping, or answer abstention policies.

- Key assumption: early launch quality failures are more likely to come from over-answering than from under-answering.
- Potential impact: higher perceived trustworthiness without needing Phase 2-4 retrieval optimization to finish first.
- Implementation hint: drive the gate from existing diagnostic signals such as top1 quality, avg-top-n quality, supplemental trigger basis, and citation density rather than inventing a separate retrieval path.

### 6. Iteration Data Plane: Baseline, Diff, and Failure Guard as First-Class Artifacts

Treat optimization evidence as a product asset from day one. Every launch iteration should record sample set version, auth profile mapping mode, ACL seed state, threshold snapshot, index/chunk config, commit hash, and eval summary so the team can explain whether a change improved accuracy or only moved noise around.

- Key assumption: the main blocker to sustained optimization is not missing ideas but missing comparable evidence.
- Potential impact: lets the team stop guessing, respect the repo’s “baseline before chunk, chunk before router, router before rerank” rule, and recover quickly from regressions.
- Implementation hint: standardize a minimal experiment bundle around `eval/retrieval_samples.yaml`, `scripts/eval_retrieval.py`, `eval/results/`, and baseline snapshot files; require every future tuning pass to attach before/after diffs.

## Summary

Recommended architecture direction: launch on the current shared retrieval core, keep the public API surface frozen, and invest the remaining effort into internal seams that make later optimization cheap and observable. The highest-value seams are internal retrieval controls, shared online/offline evaluation, an internal chunk-strategy boundary in ingestion, and artifact-grade experiment tracking that prevents future tuning from becoming guesswork.
