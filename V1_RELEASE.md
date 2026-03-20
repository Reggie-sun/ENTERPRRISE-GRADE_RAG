# V1 Release

## Status

V1 is ready to freeze as a "minimum closed-loop backend" release.

This release means the project has completed the `document -> ingest -> retrieval -> answer` path in a single-node development environment. It does not mean the full enterprise feature set is complete.

## Included In V1

- FastAPI API skeleton and routed endpoints
- Document upload and metadata persistence
- Real async ingest with `Celery + Redis`
- Ingest job status query
- Manual job re-run endpoint: `POST /api/v1/ingest/jobs/{job_id}/run`
- Retry-limit and `dead_letter` terminal semantics
- Document parsing for `PDF / Markdown / TXT`
- Chunking, embedding, vector upsert, retrieval, rerank, chat answer, citations
- Worker runbook and ingest state-machine docs

## Verification

Verified on `2026-03-20` in local development:

- Swagger MCP test passed for `POST /api/v1/documents`
- Swagger MCP test passed for `GET /api/v1/ingest/jobs/{job_id}`
- Swagger MCP test passed for `POST /api/v1/ingest/jobs/{job_id}/run`
- `pytest -q` passed: `24 passed`

## Explicitly Out Of Scope

The following are not part of the V1 release gate:

- ACL filtering
- BM25 / RRF hybrid retrieval
- OCR and Office deep parsing
- Multi-tenant enterprise controls
- High-concurrency tuning
- Full admin console
- Distributed scheduling

## Tagging Rule

Do not tag V1 from a dirty worktree.

Recommended release sequence:

1. Review local modifications
2. Commit the V1 freeze state
3. Create a tag such as `v0.1.0` or `v1-mvp`
4. Keep post-V1 work on a new commit after the tag
