---
name: auto-feature-smoke-test
description: "Use this skill after implementing a feature, bug fix, or flow change in this repository. Run a small validation pass before final handoff: targeted API verification for the changed surface and a Chrome MCP smoke test when a localhost UI flow is involved. Trigger for frontend/backend integration work, upload/retrieval/chat flows, form interactions, button behavior, and any user-facing local web page change. Skip only for docs-only work or changes with no runnable behavior."
---

# Auto Feature Smoke Test

Run this skill after a logical feature slice is implemented, not after every file save.

## Repository plan alignment

For `/home/reggie/vscode_folder/Enterprise-grade_RAG`, follow [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md) as the execution baseline before choosing validation scope, fixes, or follow-up actions.

- Treat `V1_PLAN.md` as the source of truth for current version priorities, frozen boundaries, and acceptable scope.
- Stay aligned with the plan's low-coupling rollout strategy. Prefer the smallest change that stabilizes the current feature slice instead of expanding into adjacent roadmap items.
- Respect the current frozen baseline from the plan unless the user explicitly asks for a deviation:
  - keep the current vector retrieval foundation
  - keep the current Embedding / Rerank / LLM integration approach
  - keep the current async ingest chain
  - keep the current local and server collaboration baseline
- Do not let smoke-test fixes turn into architecture rewrites, platform swaps, or roadmap expansion that conflicts with `V1_PLAN.md`.
- When reporting results or next steps, frame them against the active plan stage. If a request conflicts with `V1_PLAN.md`, call that out explicitly instead of silently drifting scope.

## Required validation

- If the change affects an API or backend behavior, run one targeted verification against the affected endpoint or the smallest relevant automated test.
- If the change affects a local UI or an end-to-end user flow, open the affected localhost or `127.0.0.1` page with Chrome MCP and exercise the changed path.
- If the change is docs-only or has no runnable surface, explicitly say the smoke test is not applicable.

## MCP usage strategy

This skill only declares MCP usage strategy. It must not contain MCP startup commands, filesystem paths, URLs, ports, token names, or authentication values.

- Keep MCP registration, transport details, auth wiring, and local wrapper commands in Codex config, not in this skill.
- Use Chrome MCP as the default tool for localhost UI smoke tests and short end-to-end interaction checks.
- Use filesystem, git, or codegraph tools only to discover the changed surface, local route, relevant fixture, or likely validation target before running the smoke test.
- Use a vector-store MCP such as Qdrant only when the changed behavior directly depends on retrieval, indexing, collection state, or vector-side evidence.
- Do not use GitHub MCP or diagram-generation MCPs by default for this skill. They are only relevant when the feature being validated explicitly depends on those integrations.
- Prefer the smallest tool set that can prove the changed behavior. Do not widen validation just because more MCP servers are available.
- If a recommended MCP is unavailable, blocked, or unnecessary, fall back to the smallest reliable local check and report the limitation explicitly.

## Workflow

1. Identify the changed surface.
   Examples:
   - upload flow
   - health check
   - retrieval
   - chat
   - a form button
   - a new page interaction

2. Choose the smallest reliable check.
   Prefer:
   - one focused API request
   - one focused pytest target
   - one focused Chrome MCP path

3. Run API verification when applicable.
   Check:
   - HTTP status
   - expected fields
   - obvious error payloads

4. Run Chrome MCP smoke test when UI is involved.
   Do the minimum path needed to prove the changed behavior works.
   Examples:
   - open the page
   - click the changed button
   - fill the changed form
   - upload one small test file when the feature requires it

5. If the smoke test fails and the failure is directly caused by the current change, make the smallest focused fix and rerun once.

6. Report the result in the final handoff.
   Include:
   - what was tested
   - whether API verification passed
   - whether Chrome MCP smoke passed
   - what was skipped and why

## Guardrails

- Do not claim a smoke test passed unless you actually ran it.
- Do not require a fresh upload if the feature can validly run against already persisted data.
- If a current `doc_id` is unavailable after page refresh, prefer testing full-library behavior before forcing a re-upload.
- Do not perform a broad refactor just to satisfy smoke coverage.
- If the UI depends on a local page and the port is unknown, inspect repo config, run scripts, compose files, or recent user instructions first.
- If the page or dependency is not running, state that clearly and report the smoke test as blocked rather than silently skipping it.

## Failure handling

- First try a focused fix when the failure is clearly inside the changed scope.
- Do not rewrite unrelated modules.
- Do not change architecture during smoke fixing.
- If blocked by missing services, auth, data, or environment state, report the exact blocker.

## Default report shape

Use a short result summary like:

- API verification: passed / failed / not applicable
- Chrome MCP smoke: passed / failed / blocked / not applicable
- Notes: one to three concrete lines
