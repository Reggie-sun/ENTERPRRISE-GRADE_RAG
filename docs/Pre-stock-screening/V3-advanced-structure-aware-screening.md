# V3 Advanced Structure-Aware Screening

Date: 2026-04-06

## 1. Positioning

This version treats pre-stock screening as a first-class ingest subsystem.

It is meant for a more mature stage, where the team already knows:

- screening is worth the complexity
- noisy content is a real retrieval bottleneck
- rebuild and audit operations need stronger control

## 2. Main Idea

V3 is not just "better filtering".

It is a routed, document-type-aware screening pipeline with graded retention and auditability.

It combines:

- document-type routing
- repeated block detection
- structure-aware classification
- semantic evidence scoring
- separate indexing policy
- audit report and canary gate

## 3. Document-Type Routing

Different corpora should not share the same screening profile.

Suggested routing families:

- SOP / WI / safety standard
- fault manual / troubleshooting sheet
- FAQ / knowledge article
- table export / report export
- OCR-heavy scan

Each family should have its own:

- regex pack
- duplicate heuristics
- semantic scoring thresholds
- indexing policy

## 4. Core Design

### 4.1 Block Graph Instead Of Flat Blocks

Each parsed document is represented as a block graph:

- document node
- section node
- clause node
- appendix node
- repeated block node

This makes it easier to:

- demote context without losing lineage
- generate summaries from screened content
- explain why content was removed or retained

### 4.2 Repeated Block Detection

Detect these patterns across pages or sections:

- repeating header/footer
- repeating table headers
- repeating company disclaimer
- repeating signature frame
- repeated scan artifacts

This stage should run before semantic scoring so the classifier does not waste work on obvious repeats.

### 4.3 Graded Retention Policy

Use the same four-way retention classes as V2:

- `keep`
- `demote`
- `summary_only`
- `drop`

But add routing-dependent rules.

Example:

- in SOP / WI, clause number and version lines are usually anchors
- in report exports, repeating column headers may be demoted or collapsed
- in OCR scans, low-confidence garbage can be dropped aggressively

## 5. Advanced Index Surface

V3 should explicitly support multiple index surfaces:

- primary evidence index
- low-priority context index
- summary surface
- audit surface

This allows later retrieval logic to choose:

- evidence-first retrieval
- context-assisted retrieval
- summary-first retrieval for broad questions

## 6. Audit And Operability

V3 should produce an artifact per ingestion job.

Suggested report fields:

```json
{
  "document_id": "doc_001",
  "screening_profile": "sop_wi",
  "original_blocks": 148,
  "keep_blocks": 82,
  "demote_blocks": 21,
  "summary_only_blocks": 19,
  "drop_blocks": 26,
  "top_drop_reasons": {
    "repeated_footer": 10,
    "page_number": 7,
    "ocr_garbage": 9
  },
  "canary_risk_flags": [
    "clause_anchor_removed"
  ]
}
```

This report should be stored alongside parsed and chunk artifacts, not only in logs.

## 7. Canary Gate

Before fully accepting a screened document into the main index, V3 can run a lightweight gate:

- if too many clause-like blocks are dropped, downgrade to safer mode
- if doc code / version / clause anchors vanish, downgrade to safer mode
- if chunk count collapses abnormally, flag review

This is useful for:

- OCR-heavy documents
- new document families
- newly added regex packs

## 8. Strengths

- best long-term quality ceiling
- best auditability
- best support for mixed document families
- strongest protection against over-filtering

## 9. Risks

- highest implementation cost
- highest testing burden
- easiest version to over-engineer
- should not be started before baseline validation and rollback plan are ready

This matters because current repo planning already treats chunk and ingest changes as heavier-risk work:

- [RETRIEVAL_OPTIMIZATION_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_PLAN.md)
- [RETRIEVAL_OPTIMIZATION_BACKLOG.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RETRIEVAL_OPTIMIZATION_BACKLOG.md)

## 10. Recommended Rollout Order

If V3 is the end-state target, rollout should still be staged:

1. land V1 or V2 first
2. prove screening helps retrieval
3. add document-type routing
4. add advanced audit
5. add canary gate
6. then consider multi-surface indexing

## 11. Verdict

V3 is the strongest strategic design.

It is not the best first implementation.

Use it as the target architecture if pre-stock screening becomes a major ingest-quality pillar, not as the very first patch.
