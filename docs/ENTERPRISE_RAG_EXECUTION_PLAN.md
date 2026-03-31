# Enterprise RAG Execution Plan

Date: 2026-03-31

## 1. Purpose

This document is a new execution plan based on the current codebase, not a generic RAG roadmap.

Its goal is to move the repository from the current "runnable V1 slice" into a system that can reasonably be called enterprise-grade RAG:

- secure by default
- tenant-safe and auditable
- operationally observable
- retrieval-quality measurable
- resilient under concurrency and failure
- extensible for enterprise workflow integration

This plan is written against the current repository reality:

- FastAPI backend with auth, document management, async ingest, retrieval, chat, SOP generation, ops, logs, traces, snapshots, and replay
- React frontend with login, workspace, portal, admin, logs, ops, retrieval, chat, and SOP pages
- Qdrant-based online retrieval
- Celery + Redis async ingest
- partial PostgreSQL metadata path
- a mixed file-backed and database-backed system state

This plan does not replace [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md). It complements it by focusing on the concrete gap from current code to enterprise-grade delivery.

## 2. Current Baseline

### 2.1 What Already Exists

From the current branch and docs, the codebase already has a meaningful product baseline:

- employee login and role context
- document upload, batch create, preview, rebuild, delete, async ingest jobs
- OCR for image files, scanned PDFs, and DOCX embedded images
- hybrid retrieval with vector recall, lexical recall, weighted fusion, and rerank hooks
- chat answer generation with citations
- SOP generation, preview, export, and version management
- request trace, request snapshot, replay, event logs, rerank canary, ops page, and runtime concurrency gates
- frontend workspace and portal surfaces

### 2.2 Current Architecture Shape

The current architecture is roughly:

- API layer:
  `backend/app/api/v1/endpoints/*`
- business services:
  `backend/app/services/*`
- ingestion and RAG primitives:
  `backend/app/services/ingestion_service.py`
  `backend/app/rag/*`
- state persistence:
  mixed file-backed repositories under `data/` and optional PostgreSQL-backed metadata/asset stores
- async execution:
  `backend/app/worker/celery_app.py`
- frontend application:
  `frontend/src/pages/*`, `frontend/src/portal/*`, `frontend/src/auth/*`

### 2.3 Main Strengths To Preserve

- retrieval, chat, and SOP are already wired end-to-end
- hybrid retrieval is already more advanced than a naive vector-only baseline
- traceability concepts already exist:
  citations, traces, snapshots, replay, rerank canary
- async ingest pipeline exists and should be hardened, not rewritten from scratch
- frontend already exposes key operator and user workflows

## 3. Enterprise-Grade Target State

The final target state for this repository should be:

### 3.1 Security And Access

- all protected surfaces require explicit auth
- tenant boundary is hard and test-enforced
- department policy is deliberate and consistent
- secrets are never safe-by-default in code
- token revocation, rotation, refresh, and audit are production-safe
- no sensitive storage paths or internal topology leak through public contracts unless intentionally designed

### 3.2 Knowledge And Retrieval

- ingestion is idempotent, observable, retry-safe, and scalable
- retrieval supports tenant-safe cross-department knowledge access with policy-driven ranking
- metadata filters, ACL propagation, and retrieval diagnostics are first-class
- rerank, query rewrite, memory, and prompt packing are productionized rather than experimental
- answer quality is continuously measured

### 3.3 Data And Governance

- business truth is stored in durable database-backed models
- file-backed truth sources are transitional only
- logs, traces, snapshots, config, and SOP state have durable ownership
- auditability and replay have retention, scope control, and operator safeguards

### 3.4 Operations

- metrics, tracing, structured logging, dashboards, and alerts are standard
- failure modes are visible and actionable
- deployment, rollback, migration, and smoke-test procedures are documented and repeatable
- performance and concurrency limits are explicit and tuned

### 3.5 Product And Integration

- employee portal is stable and role-appropriate
- admin and ops consoles are safe enough for real operators
- enterprise identity, messaging, and contact sync can be integrated cleanly
- connector and corpus expansion can happen without redesigning the core

## 4. Gap Analysis Against Current Code

### 4.1 Security And Authorization Gaps

Current code has meaningful auth scaffolding but not yet enterprise-safe behavior:

- some business endpoints still use optional auth where production should require explicit auth
- auth revocation is process-local rather than distributed
- default auth secret is code-defined and unsafe for production
- login throttling and abuse controls are incomplete
- bootstrap identity data is still too close to runtime paths
- current access logic mixes direct resource access and retrieval-scope access

Impact:

- access semantics are harder to reason about
- production rollout would carry unnecessary data exposure risk
- policy evolution will be expensive if not cleaned up early

### 4.2 System-Of-Record Gaps

The repository still mixes durable workflow with transitional file truth:

- document/job metadata can be file-backed
- traces, snapshots, event logs, rerank canary, system config, and chat memory are still largely file-backed
- SOP records and versions are partially filesystem-backed
- operational state is not yet consistently queryable, migratable, or retention-managed

Impact:

- multi-instance deployment is fragile
- consistency, backup, retention, and compliance controls are weak
- analytics and governance remain expensive

### 4.3 Retrieval And Knowledge Policy Gaps

The retrieval stack is promising but not fully enterprise-ready:

- department-priority retrieval is only partially aligned with the intended enterprise knowledge policy
- retrieval ACL and direct resource ACL are too tightly coupled
- rerank is not yet fully production-validated as the default route
- query rewrite and memory are not yet fully enabled in the main path
- tokenizer-aware prompt budgeting and evidence packing need hardening
- evaluation loops are not yet systematic enough

Impact:

- answer quality is harder to predict
- policy behavior can drift from product intent
- retrieval changes are difficult to validate safely

### 4.4 Ingestion And Content Operations Gaps

- OCR coverage is good but not fully quality-governed
- ingest backlog, stale-job recovery, and dead-letter workflows need stronger operator tooling
- dedup, versioning, rebuild, and reindex semantics need stronger data contracts
- connector-driven ingestion and scheduled refresh are not yet present

Impact:

- knowledge freshness and content governance are not yet enterprise-ready
- operator burden stays high as corpus size grows

### 4.5 Observability And SRE Gaps

- request traces and logs exist but are not yet OpenTelemetry/Prometheus grade
- SLI/SLO definitions are not yet formalized
- alerting and dashboard standards are not yet present
- chaos, load, and soak validation are still missing

Impact:

- the system can run, but it is not yet supportable like an enterprise platform

### 4.6 Frontend Workflow Gaps

- frontend already covers many flows, but role boundaries and enterprise UX guardrails still need hardening
- admin and ops pages need safer action design and stronger status semantics
- portal experience needs explicit production-path validation

Impact:

- the UI is usable for development and internal trial, but not yet fully production-operational

### 4.7 Enterprise Integration Gaps

- enterprise messaging integration is not yet finished
- identity synchronization is not yet productionized
- external document connectors are not yet a first-class ingestion path

Impact:

- the system is still a strong internal RAG application, not yet a deeply integrated enterprise knowledge platform

## 5. Planning Principles

The execution plan should follow these principles:

1. Do not rewrite the whole stack.
   The current code already has too much working value to discard.

2. Separate "policy hardening" from "feature expansion".
   Security and truth-source cleanup must happen before large new integrations.

3. Make retrieval policy explicit.
   Direct-access policy, retrieval-access policy, and ranking policy must not be silently conflated.

4. Move state to durable storage incrementally.
   Migrate one domain at a time, with compatibility shims where necessary.

5. Keep every phase runnable.
   Each phase should leave the repository in a shippable internal state.

6. Require measurable gates.
   Quality, latency, and operational readiness must have explicit acceptance checks.

## 6. Workstreams

The roadmap should run as six coordinated workstreams.

### Workstream A: Identity, Auth, And Access Policy

Scope:

- auth hardening
- endpoint protection policy
- token lifecycle
- login abuse protection
- role and department policy semantics
- retrieval-scope versus direct-resource-scope separation

Primary code areas:

- `backend/app/services/auth_service.py`
- `backend/app/api/v1/endpoints/auth.py`
- `backend/app/services/document_service.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/sop_service.py`
- `docs/AUTH_EVOLUTION.md`

### Workstream B: Durable Data Truth

Scope:

- migrate file-backed truth sources to PostgreSQL and Redis where appropriate
- retain filesystem only for artifacts, not business truth
- unify migrations and schema ownership

Primary code areas:

- `backend/app/db/*`
- `backend/app/services/*repository-backed services*`
- `prisma/*`
- migration and backfill scripts

### Workstream C: Retrieval And Generation Quality

Scope:

- department-priority retrieval semantics
- metadata filters and ACL propagation
- rerank production validation
- query rewrite
- memory
- tokenizer-aware prompt construction
- evaluation harnesses

Primary code areas:

- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_query_router.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/chat_memory_service.py`
- `backend/app/services/query_rewrite_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/services/system_config_service.py`
- `backend/eval/*`

### Workstream D: Content Operations And Ingestion

Scope:

- ingest reliability
- stale-job and dead-letter operations
- OCR quality governance
- document lifecycle and reindex semantics
- connector ingestion and scheduled refresh

Primary code areas:

- `backend/app/services/document_service.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/rag/parsers/*`
- `backend/app/rag/ocr/*`
- `backend/app/worker/celery_app.py`
- ops endpoints and dashboards

### Workstream E: Frontend Productization

Scope:

- employee portal hardening
- admin workflow safety
- operator experience
- error states, progress semantics, and traceability UX

Primary code areas:

- `frontend/src/auth/*`
- `frontend/src/pages/*`
- `frontend/src/portal/*`
- `frontend/src/api/*`

### Workstream F: SRE, Compliance, And Integration

Scope:

- metrics, tracing, alerts, dashboards
- deployment, rollback, backup, disaster recovery
- enterprise messaging and identity sync
- security review, load test, and release governance

Primary code areas:

- ops services and endpoints
- deployment scripts
- runbooks
- future integration adapters

## 7. Roadmap Phases

### 7.1 Recommended Sequencing

The recommended execution order is:

| Sequence | Phase | Why it comes here |
| --- | --- | --- |
| 1 | Phase 0 | Without safer auth and clearer access policy, every later feature multiplies risk |
| 2 | Phase 1 | Durable state is required before serious multi-instance or operator-scale rollout |
| 3 | Phase 2 | Retrieval policy and quality should be fixed before expanding enterprise reach |
| 4 | Phase 3 | Generation quality should build on stable retrieval and stable truth sources |
| 5 | Phase 4 | Corpus-scale operations matter after core policy and workflow hardening |
| 6 | Phase 5 | Enterprise integration should plug into a stable platform, not a shifting prototype |
| 7 | Phase 6 | GA gate only makes sense after the platform shape is already stable |

Parallel work is acceptable, but the dependency order should remain:

- security and access policy before expansion
- durable truth before operator-scale rollout
- retrieval quality before large enterprise integrations
- SRE and observability as a continuous stream from Phase 0 onward

### Phase 0: Production-Safety Baseline

Target duration:

- 2 to 3 weeks

Goal:

- make the current branch safe enough for a serious internal pilot

Deliverables:

- classify every endpoint as public, optional-auth, or protected
- remove optional-auth from protected business endpoints where not intentional
- introduce retrieval-scope policy separate from direct resource access policy
- add login throttling and abuse controls
- replace unsafe auth defaults with environment-required production settings
- move token revocation to Redis or equivalent shared store
- stop leaking internal storage paths in external responses unless explicitly needed
- lock down identity bootstrap exposure

Acceptance criteria:

- protected flows fail closed without auth
- logout and token revocation work across processes
- rate-limited login path exists and is tested
- security-sensitive tests cover tenant boundary, department policy, and anonymous access

Exit condition:

- the system is still feature-complete for current flows, but no longer relies on development-only auth semantics

### Phase 1: Durable State And Data Ownership

Target duration:

- 3 to 5 weeks

Goal:

- reduce operational fragility by moving business truth out of ad hoc files

Deliverables:

- decide authoritative persistence model for:
  documents, ingest jobs, system config, event logs, traces, snapshots, chat memory, SOP records, SOP versions
- keep filesystem only for raw uploads and derived artifacts
- add migration/backfill path and compatibility read strategy
- standardize schema ownership between app code and migration tooling
- define retention policy by domain

Acceptance criteria:

- multi-instance deployment can read and write shared state safely
- operator-facing pages no longer depend on local disk truth
- backup and restore path is documented for all business-critical domains

Exit condition:

- no operator-critical workflow breaks when API runs on multiple instances

### Phase 2: Enterprise Retrieval Policy And Quality

Target duration:

- 3 to 4 weeks

Goal:

- make retrieval policy explicit, testable, and aligned with enterprise knowledge access

Deliverables:

- finalize tenant-safe department-priority retrieval:
  current department first, same-tenant supplemental knowledge second
- store and propagate retrieval ACL metadata cleanly
- formalize `source_scope` and retrieval diagnostics
- validate rerank production route and fallback policy
- add offline and online evaluation slices for:
  retrieval relevance, citation quality, rerank value, answer groundedness
- define retrieval and generation quality dashboards

Acceptance criteria:

- department-priority retrieval behavior is covered by service and endpoint tests
- rerank route can be promoted with observable quality evidence
- evaluation outputs exist for representative corpora and question sets

Exit condition:

- retrieval changes can be made with measurable confidence rather than intuition

### Phase 3: Generation Hardening And Knowledge Workflows

Target duration:

- 3 to 4 weeks

Goal:

- turn current chat and SOP generation flows into production-grade knowledge workflows

Deliverables:

- enable and govern query rewrite in the main path
- enable lightweight memory with explicit limits and policy
- implement tokenizer-aware prompt packing and evidence trimming
- improve fallback strategies and response semantics
- strengthen SOP generation traceability and version governance
- add golden-path smoke tests for portal chat, retrieval, SOP generation, export, and replay

Acceptance criteria:

- prompt budget behavior is deterministic and tested
- memory and rewrite do not silently violate policy boundaries
- SOP output quality and traceability are acceptable for pilot teams

Exit condition:

- main user workflows are no longer "advanced demo flows"; they are governed product flows

### Phase 4: Ingestion Operations And Corpus Governance

Target duration:

- 3 to 5 weeks

Goal:

- scale corpus operations beyond manual upload and ad hoc recovery

Deliverables:

- improve stale ingest recovery and dead-letter tooling
- add document lifecycle governance:
  create, supersede, archive, delete, rebuild, reindex
- improve OCR quality governance and explainability
- add connector ingestion abstraction
- support scheduled synchronization and re-ingestion for external sources
- add corpus-level health and freshness reporting

Acceptance criteria:

- operators can recover failed ingest without ad hoc file surgery
- knowledge freshness has visible status and recovery actions
- external-source ingestion has a clear extension point

Exit condition:

- corpus growth no longer directly increases manual operational burden

### Phase 5: Enterprise Integration

Target duration:

- 4 to 6 weeks

Goal:

- integrate the RAG platform into enterprise systems instead of treating it as a standalone tool

Deliverables:

- enterprise identity synchronization
- messaging and notification integration
- contact and organization mapping
- connector onboarding framework for common enterprise content sources
- policy-aware background jobs for sync and refresh

Acceptance criteria:

- login and user context can align with enterprise identity source
- at least one messaging or workflow integration is production-usable
- connector onboarding no longer requires core architectural change

Exit condition:

- the platform can participate in enterprise workflow rather than only serving a manually uploaded corpus

### Phase 6: Production Readiness And GA Gate

Target duration:

- 2 to 4 weeks after prior phases

Goal:

- pass a real production-readiness gate

Deliverables:

- SLI/SLO definitions
- dashboards and alerts
- load and soak tests
- security review and dependency review
- rollback and incident runbooks
- release checklist and go-live gate

Acceptance criteria:

- measured latency, throughput, and failure budgets are within target
- on-call runbooks and rollback procedures are tested
- pilot sign-off is based on quality, ops, and security evidence

Exit condition:

- the system is ready for controlled production rollout

## 8. Key Risks And Mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Access policy remains ambiguous | Security fixes become inconsistent and expensive | Finish Phase 0 before major product expansion |
| File-backed truth persists too long | Multi-instance behavior stays fragile | Treat Phase 1 as platform debt retirement, not optional cleanup |
| Retrieval policy and quality evolve without evaluation | User trust drops and regressions go unnoticed | Add eval slices and promotion criteria in Phase 2 |
| Connector work starts before core governance is stable | Integrations amplify unstable behavior | Delay enterprise connectors until Phase 4 and Phase 5 |
| Ops tooling stays behind feature delivery | Pilot incidents become manual and high-cost | Build metrics, alerts, and runbooks continuously from Phase 0 |

## 9. Cross-Phase Deliverables That Must Start Early

These should not wait until the end:

- test strategy expansion
- runbook cleanup
- metrics and structured logging foundation
- migration discipline
- seed data and evaluation dataset hygiene
- security review checkpoints

## 10. Acceptance Framework

Each phase should be approved against five gates:

1. Product gate
   The targeted workflow works end-to-end for the intended role.

2. Security gate
   Access policy, secrets, and exposure behavior are reviewed and tested.

3. Data gate
   Truth ownership, migration, backup, and retention are explicit.

4. Operations gate
   Failure detection, runbooks, and dashboards exist.

5. Quality gate
   Retrieval and generation quality are measured, not assumed.

## 11. Suggested Metrics

The platform should eventually track at least:

- ingest success rate
- dead-letter rate
- OCR fallback rate
- retrieval p50 and p95 latency
- chat and SOP generation p50 and p95 latency
- rerank fallback rate
- answer-with-citation rate
- citation acceptance or groundedness score
- replay success rate
- login failure and throttle rate
- per-tenant usage and cost allocation

## 12. Module-Level Implementation Priorities

### Highest-priority modules

- `backend/app/services/auth_service.py`
- `backend/app/services/document_service.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/services/system_config_service.py`
- `backend/app/services/request_trace_service.py`
- `backend/app/services/request_snapshot_service.py`
- `backend/app/services/event_log_service.py`
- `backend/app/worker/celery_app.py`

### Highest-priority frontend surfaces

- `frontend/src/auth/*`
- `frontend/src/pages/AdminPage.tsx`
- `frontend/src/pages/OpsPage.tsx`
- `frontend/src/pages/DocumentsPage.tsx`
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/pages/RetrievalPage.tsx`
- `frontend/src/pages/SopPage.tsx`
- `frontend/src/portal/*`

## 13. What This Plan Explicitly Avoids

This plan does not recommend:

- rewriting retrieval around a new vector database immediately
- replacing FastAPI, React, Celery, or Qdrant as a first move
- building a large plugin ecosystem before access policy and truth ownership are stable
- over-investing in new features before security and durability are fixed

## 14. Final Definition Of Done

This repository can be called enterprise-grade RAG when all of the following are true:

- protected knowledge access is explicit, safe, and test-enforced
- state is durable and multi-instance safe
- retrieval quality and generation quality are measurable and governable
- ingest and corpus operations are scalable and recoverable
- operators have observability, replay, and runbooks
- enterprise integrations can be added without redesigning the core
- the product supports a real tenant with real users and real operational ownership

At that point, the system stops being a strong internal prototype and becomes a maintainable enterprise knowledge platform.

## 15. Recommended Immediate Next Step

If only one next step is chosen, it should be:

- finish Phase 0 first

Reason:

- every later phase depends on trustworthy auth, clear access policy, and safer production defaults
- without that, retrieval quality work and enterprise integration work will amplify risk rather than value
