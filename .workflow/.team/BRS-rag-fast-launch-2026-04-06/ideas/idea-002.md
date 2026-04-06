# Topic

最快上线当前 RAG，暂不处理 SOP，优先保证回答准确性，同时保留后续可优化空间

# Angles

- launch guardrails

# Mode

Initial Generation

# Ideas

## 1. Hard Scope Fence: launch only retrieval + chat, freeze SOP and experimental tuning surfaces

Keep the first release explicitly narrow: `POST /api/v1/retrieval/search` and `POST /api/v1/chat/ask` are the product surface, while SOP generation, rerank canary decisions, and chunk retuning stay behind internal-only workflows. This matches the repo's contract discipline and avoids spending launch time on cross-module behavior that the docs already classify as later-phase optimization.

- Key assumption: the business goal is a usable, accurate Q&A path now, not broad feature completeness.
- Potential impact: lowers launch risk by cutting the number of moving parts, contract changes, and unsupported failure modes.
- Implementation hint: ship UI navigation and permissions so SOP entry points, tuning toggles, and nonessential ops controls are hidden or admin-only in release mode.

## 2. Evidence-First Answer Gate: answer only when citation evidence clears a minimum bar

Use retrieval results as the admission control for generation: if the query does not produce enough high-confidence, non-noisy citations, the system should abstain instead of synthesizing. The repo already separates stable citation fields from diagnostics and already returns a no-context response path, so the fastest safe launch is to formalize that path as the default fallback rather than trying to "be helpful" with weak context.

- Key assumption: false confidence is materially worse than unanswered questions in the first release.
- Potential impact: improves trust by converting uncertain cases into explicit abstentions instead of hallucinated answers.
- Implementation hint: define a launch-time evidence threshold using existing retrieval diagnostics such as top result quality, average top-N quality, and citation count, then route below-threshold cases to a standard abstention template.

## 3. Source Discipline Contract: every non-abstained answer must include citations, and citations must be inspectable

Make citations mandatory for any substantive answer and treat citation absence as a launch blocker, not a UX nuance. Because `chat/ask` already has stable `citations[]` fields and retrieval/chat share the same underlying retrieval logic, this guardrail can be enforced without adding public contract fields.

- Key assumption: operators and users need a visible proof chain to validate early-launch answers.
- Potential impact: keeps answer quality auditable and makes later tuning measurable against a stable evidence surface.
- Implementation hint: require at least one citation for direct-answer modes, show source document/page/snippet in the UI, and downgrade to abstention when citations are empty or obviously redundant.

## 4. Conservative Recall Policy: prefer under-answering to cross-department overreach

The first release should keep supplemental recall conservative until auth profile mapping, ACL seed application, and department-based eval are all proven in the live environment. The repo docs already warn that supplemental metrics are only trustworthy when metadata seed is applied, so launch should default to "strict unless verified" rather than assuming cross-department recall is safe.

- Key assumption: access-boundary mistakes and noisy supplemental triggers are higher risk than some missed recall.
- Potential impact: reduces both answer noise and accidental scope leakage during launch.
- Implementation hint: freeze the current internal supplemental thresholds, require a reproducible seeded eval before relaxing them, and expose supplemental-trigger diagnostics only to admin/ops views.

## 5. Launch Scorecard Gate: ship only off a frozen sample set, config snapshot, and explicit pass/fail thresholds

Do not launch from anecdotal spot checks. The repo already has `eval/retrieval_samples.yaml`, `scripts/eval_retrieval.py`, and a baseline snapshot pattern, so the release guardrail should be a small scorecard: exact-match top1, top-k recall, abstention rate on known-hard queries, and citation presence rate.

- Key assumption: a small but reproducible benchmark is enough to decide MVP readiness.
- Potential impact: gives the team a concrete "go / no-go / rollback" rule and preserves room for later optimization experiments.
- Implementation hint: freeze a launch sample subset marked `verified`, snapshot config and data version, and require each deploy candidate to beat or match the baseline before rollout.

## 6. Observable by Default: trace every answer decision, especially abstentions and fallback paths

For launch, observability should answer one question quickly: why did the system answer, abstain, or retrieve the wrong source? This repo already has request traces, snapshots, event logs, ops endpoints, and structured retrieval diagnostics, so the guardrail is to make those artifacts part of the standard incident workflow instead of optional debugging tools.

- Key assumption: early-launch quality issues will be diagnosed faster through traces than through user reports alone.
- Potential impact: shortens time-to-root-cause and makes future optimization phases evidence-driven.
- Implementation hint: log per-request retrieval mode, supplemental trigger basis, citation count, answer mode, and effective model; add a simple daily review on low-citation answers and abstentions.

## 7. Fast Rollback Kit: one-switch disablement for risky behaviors plus a known-safe baseline profile

Launch with a predeclared rollback posture: if quality drops, the team should be able to revert to a known-safe config without code edits. Given the repo's emphasis on internal config truth, baseline snapshots, and phased optimization order, the safest rollback is configuration-first: restore threshold defaults, disable experimental rerank comparisons, and reduce the exposed surface to the known-good retrieval/chat core.

- Key assumption: the first production issue is more likely to be threshold/config drift than a need for new logic.
- Potential impact: limits blast radius and preserves momentum because rollback becomes operational rather than architectural.
- Implementation hint: maintain a named launch baseline snapshot, document the exact kill switches, and define which features must be disabled first: rerank canary compare, unverified supplemental relaxations, and any UI entry point tied to SOP or unfinished optimization flows.

# Summary

The safest fast-launch posture is not "make retrieval smarter quickly," but "make weak answers impossible to ship silently." Concretely: narrow the release surface, require evidence-backed answers, keep supplemental recall conservative until seeded eval proves it, make launch go/no-go depend on a frozen scorecard, and prepare an operational rollback that disables risky behavior before touching core contracts.
