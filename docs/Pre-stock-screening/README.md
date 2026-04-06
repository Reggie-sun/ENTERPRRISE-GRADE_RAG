# Pre-stock Screening Versions

Date: 2026-04-06

## 1. Purpose

This directory collects multiple design versions for "upload-time pre-stock screening" in the current repository.

The goal is not to discuss generic RAG cleanup, but to decide how much filtering should happen before:

- chunking
- embedding
- vector indexing

The current ingest path is still:

- parse / OCR
- normalize text
- chunk
- embedding
- Qdrant upsert

Relevant current code:

- [backend/app/services/ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [backend/app/rag/parsers/document_parser.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/parsers/document_parser.py)
- [backend/app/rag/chunkers/structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)
- [backend/tests/test_document_ingestion.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/tests/test_document_ingestion.py)

## 2. Version Summary

### V1: Lite Two-Stage Screening

File:

- [V1-lite-two-stage-screening.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/docs/Pre-stock-screening/V1-lite-two-stage-screening.md)

Core idea:

- regex cleanup
- semantic keep / drop

Best for:

- first implementation
- low-risk rollout
- fast canary validation

Main tradeoff:

- simple enough to ship quickly
- not fine-grained enough for complex structured documents

### V2: Balanced Graded Screening

File:

- [V2-balanced-graded-screening.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/docs/Pre-stock-screening/V2-balanced-graded-screening.md)

Core idea:

- structure-aware preprocessing
- keep / demote / summary_only / drop

Best for:

- the recommended mainline version
- mixed corpora with SOP / WI / FAQ / fault manuals

Main tradeoff:

- more moving parts than V1
- still manageable without introducing a heavyweight new subsystem

### V3: Advanced Structure-Aware Screening

File:

- [V3-advanced-structure-aware-screening.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/docs/Pre-stock-screening/V3-advanced-structure-aware-screening.md)

Core idea:

- document-type routing
- duplicate block detection
- graded indexing policy
- audit and canary gating

Best for:

- higher-quality production hardening
- larger corpus with frequent rebuild and ops requirements

Main tradeoff:

- highest implementation and validation cost
- should not be the first version unless screening quality is already a proven bottleneck

## 3. Recommendation

If the team wants one version to implement first, choose V2.

Reason:

- V1 is safe but too binary
- V3 is stronger but too heavy for the first rollout
- V2 keeps the main design insight:
  screening should not only delete content, it should also support demotion and summary-only retention

## 4. Shared Guardrails

All versions assume the same repository constraints:

- do not change stable retrieval or chat contract unless required by plan
- do not delete original parsed text as the only source of truth
- keep SOP / WI clause evidence conservative
- treat metadata, clause number, document code, version, and effective date as possible retrieval anchors, not default noise
- verify with real ingest tests and retrieval eval before claiming improvement
