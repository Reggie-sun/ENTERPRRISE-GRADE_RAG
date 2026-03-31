---
name: auto-feature-smoke-test
description: Run a focused smoke test after a feature, bug fix, or user-facing flow change. Use the smallest reliable verification and report clearly what was actually tested.
user-invocable: true
---

# Auto Feature Smoke Test

## When to use
Use this skill after:
- backend API changes
- frontend/backend integration changes
- upload, retrieval, chat, or form flow changes
- user-facing behavior changes

Do not use this skill for:
- docs-only changes
- comments-only changes
- non-runnable refactors with no changed behavior

## Critical rules
- Use `V1_PLAN.md` as the current execution baseline.
- Use `MAIN_CONTRACT_MATRIX.md` as the contract source of truth for stable field names and response envelopes.
- Prefer the smallest reliable validation.
- Do not claim a test passed unless it was actually run.
- Do not expand smoke-test fixes into architecture rewrites.
- If blocked by environment, auth, missing services, or missing data, report the blocker explicitly.

## Validation strategy
1. Identify the changed surface.
2. Choose the smallest reliable check.
3. Run one focused verification when applicable:
   - one API request, or
   - one targeted pytest, or
   - one minimal UI path verification
4. If the failure is clearly caused by the current change, make the smallest focused fix and rerun once.
5. Report exactly what passed, failed, was blocked, or was not applicable.

## Repository-specific alignment
For `/home/reggie/vscode_folder/Enterprise-grade_RAG`:
- follow `V1_PLAN.md` as the current scope baseline
- validate frozen V1 contract surfaces first
- prefer `MAIN_CONTRACT_MATRIX.md` when checking stable response fields
- treat debug and diagnostic endpoints as non-default contract targets unless explicitly requested

## Main contract surfaces
Default primary contract surfaces:
- health / auth
- documents / ingest jobs
- retrieval/search
- chat/ask
- chat/ask/stream
- sops mainline routes
- system-config
- logs
- ops/summary

Diagnostic-only surfaces unless explicitly requested:
- retrieval/rerank-compare
- traces
- request-snapshots
- replay endpoints
- OCR artifact details

## Report format
- API verification: passed / failed / blocked / not applicable
- UI smoke: passed / failed / blocked / not applicable
- Notes: 1 to 3 concrete lines