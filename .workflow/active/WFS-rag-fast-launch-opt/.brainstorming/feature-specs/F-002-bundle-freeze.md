# Feature Spec: F-002 - Bundle Freeze

**Priority**: High
**Contributing Roles**: system-architect (lead), data-architect (artifact schema and integrity)
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system SHALL provide a script that produces a single immutable JSON artifact (`launch-bundle.json`) capturing the complete deployable state: commit SHA, config snapshot, corpus manifest, index info, and ACL seed. This artifact establishes a verifiable chain of custody from evaluation to production deployment.

- The bundle freeze script MUST be a standalone CLI tool at `scripts/freeze_bundle.py` requiring only Python stdlib and `git` CLI.
- The script MUST block on uncommitted changes in `data/` and `eval/` directories, and MUST warn on uncommitted changes elsewhere (EP-002).
- Once written, `launch-bundle.json` MUST NOT be modified; any state change requires a new bundle with a new `bundle_id`.
- The corpus manifest MUST use Qdrant as the primary source of truth, with filesystem reconciliation for cross-validation (EP-010).
- The script MUST fail with a non-zero exit code on any CRITICAL validation failure (Qdrant unreachable, point count mismatch, missing documents).
- Bundle ID format: `bundle-{YYYYMMDDHHmmss}-{short_sha}` where `short_sha` is the first 8 chars of `SHA-256(commit_sha + frozen_at)`.
- All content hashes MUST use SHA-256 with `sha256:<hex_digest>` format.
- All timestamps MUST use ISO 8601 UTC format.

## 2. Design Decisions

### 2.1 Corpus Manifest Source: Qdrant Primary + Filesystem Check (RESOLVED)

**Decision**: The corpus manifest is built by scrolling Qdrant points via the scroll API, grouping by `document_id`, and computing per-document chunk counts and content hashes. Filesystem metadata (`data/documents/*.json`) provides supplementary fields (`file_hash`, `department_ids`, `visibility`).

**Options considered**:
- **Option A**: Filesystem-only manifest. Scan `data/documents/`, `data/chunks/`, `data/parsed/` and build manifest from files. Rejected because files may not reflect the actual indexed state in Qdrant (re-ingestion could change chunks without updating files).
- **Option B**: Qdrant primary + filesystem reconciliation (selected). Qdrant is the source the system actually queries at runtime; the manifest MUST reflect what Qdrant contains. Filesystem metadata supplements with administrative fields not stored in Qdrant payloads.

**Trade-off**: Requires Qdrant to be running during freeze. If Qdrant is unreachable, the script MUST fail with a clear error. This is acceptable because a bundle without index verification is invalid.

**Source roles**: system-architect (bundle schema), data-architect (corpus manifest export procedure, content hash computation).

### 2.2 Dirty Worktree Handling: Block data/eval, Warn Others (RESOLVED)

**Decision**: The freeze script checks `git status --porcelain` and blocks if there are uncommitted changes in `data/` or `eval/` directories. For other directories, it emits a warning but proceeds.

**Rationale**: `data/` and `eval/` directly affect retrieval behavior and evaluation results. If these change after freeze, the bundle does not reflect what was tested. Other files (e.g., `backend/` source) are less critical for data determinism and may have legitimate work-in-progress.

**Source roles**: system-architect (commit SHA capture), data-architect (validation framework).

### 2.3 Immutability via Atomic Write and Refuse-Overwrite

**Decision**: The bundle is written atomically (write to `.tmp`, rename to final) and the script MUST refuse to overwrite an existing `launch-bundle.json` unless `--force` is passed.

**Rationale**: Accidental re-freezing over an existing bundle would invalidate all downstream evaluations (F-003, F-004) that reference the bundle. The `--force` flag makes the override explicit and deliberate.

### 2.4 Validation Pipeline Order

The script executes validations in strict order:
1. **Connectivity** (CRITICAL): Qdrant accessible, collection exists
2. **Corpus integrity** (CRITICAL): point counts match, no orphan document_ids, every document has chunks
3. **ACL completeness** (CRITICAL): every document department_id maps to a known department in identity bootstrap
4. **Index consistency** (CRITICAL): vector_size matches embedding model output dimension, distance is Cosine
5. **Config determinism** (CRITICAL): system_config hash is reproducible
6. **Eval coverage** (WARNING): dataset has minimum per-type sample counts

If any CRITICAL check fails, the script MUST delete the partial bundle and exit non-zero.

**Source roles**: data-architect (validation framework, validation levels), system-architect (error containment principle).

## 3. Interface Contract

### 3.1 Bundle Schema (launch-bundle.json)

```json
{
  "bundle_id": "bundle-20260406113000-a1b2c3d4",
  "frozen_at": "2026-04-06T11:30:00Z",
  "commit_sha": "0f73d0f2...",
  "schema_version": "1.0",
  "corpus": {
    "total_documents": 42,
    "total_chunks": 15234,
    "collection_name": "enterprise_rag_v1_local_bge_m3",
    "documents": [
      {
        "doc_id": "doc_...",
        "doc_name": "...",
        "source_path": "data/uploads/...",
        "parsed_path": "data/parsed/...",
        "chunk_count": 492,
        "content_hash": "sha256:...",
        "file_hash": "...",
        "source_type": "pdf",
        "department_ids": [],
        "visibility": "private",
        "status": "active"
      }
    ]
  },
  "index": {
    "collection_name": "...",
    "vector_size": 1024,
    "distance_metric": "Cosine",
    "embedding_provider": "openai",
    "embedding_model": "BAAI/bge-m3",
    "point_count": 15234,
    "index_config_hash": "sha256:..."
  },
  "acl": {
    "source": "identity_bootstrap.json",
    "tenant_id": "wl",
    "role_count": 3,
    "department_count": 8,
    "user_count": 15,
    "departments": [],
    "supplemental_access": {},
    "content_hash": "sha256:..."
  },
  "config": {
    "system_config_hash": "sha256:...",
    "query_profiles": {},
    "reranker_routing": {},
    "supplemental_quality_thresholds": {},
    "degrade_controls": {}
  },
  "validation": {
    "bundle_id": "...",
    "validated_at": "...",
    "status": "pass|fail|warning",
    "checks": []
  }
}
```

### 3.2 CLI Interface

```bash
python scripts/freeze_bundle.py --output data/launch-bundle.json          # Freeze
python scripts/freeze_bundle.py --output data/launch-bundle.json --force  # Overwrite
python scripts/freeze_bundle.py --verify data/launch-bundle.json          # Verify against current state
```

### 3.3 Consumption Contracts

- **F-003 (eval runner)**: MUST read bundle, verify `bundle_id`, verify `index.point_count` matches live Qdrant, record `bundle_id` in results.
- **F-007 (kill switch)**: Rollback procedure references bundle to restore known-good state.
- **F-008 (monitoring)**: Compares live state against bundle for drift detection.

## 4. Constraints & Risks

| Constraint | Description |
|-----------|-------------|
| Qdrant must be running | Corpus manifest and index info require live Qdrant access; offline freeze is impossible |
| Python stdlib only | No external dependencies (no requests library); use `urllib.request` for Qdrant HTTP API |
| Script-only, no API | No backend endpoint; run directly via `python scripts/freeze_bundle.py` |
| `data/launch-bundle.json` is gitignored | Generated artifact not in version control; team MUST manually back up |

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Qdrant unreachable during freeze | Medium | High | Script fails with clear error; retry with Qdrant running |
| Corpus files modified during freeze | Low | Critical | Atomic scan + hash; freeze takes <5 seconds |
| Bundle file corrupted or lost | Low | High | Gitignored; team MUST back up manually |
| Document ID derivation mismatch | Medium | Medium | Script logs all doc files; `--verify` catches mismatches |
| Content hash non-reproducible | Low | High | Canonical JSON serialization with sorted keys |

## 5. Acceptance Criteria

1. **Script execution**: `python scripts/freeze_bundle.py --output data/launch-bundle.json` exits 0 and produces a valid JSON file.
2. **Immutability**: Running the script again without `--force` exits non-zero with "Bundle already exists" error.
3. **Dirty worktree block**: With uncommitted changes in `data/` or `eval/`, the script exits non-zero.
4. **Dirty worktree warning**: With uncommitted changes outside `data/`/`eval/`, the script prints WARNING but proceeds.
5. **Qdrant connectivity**: When Qdrant is unreachable, the script exits non-zero with a clear error message.
6. **Point count validation**: `sum(documents[*].chunk_count)` equals `QdrantVectorStore.count_points()`.
7. **Content hash reproducibility**: Re-computing hashes on the same corpus produces identical results.
8. **Verify mode**: `--verify` checks all bundle fields against current state and reports pass/fail per check.
9. **Validation output**: `bundle-validation.json` is written alongside the bundle with all check results.
10. **Forward compatibility**: Unknown fields in the bundle are ignored by consumers; `schema_version: "1.0"` supports future extensions.

## 6. Detailed Analysis References

- @system-architect/analysis-F-002-bundle-freeze.md -- Script design, bundle schema, immutability guarantee, dependency map
- @system-architect/analysis-cross-cutting.md -- Central config spine, bundle freeze contract, dependency sequencing
- @data-architect/analysis-F-002-bundle-freeze.md -- Full artifact schema definitions, export procedures, content hash computation, validation pipeline
- @data-architect/analysis-cross-cutting.md -- Bundle identity convention, hash standards, timestamp format, data validation framework

## 7. Cross-Feature Dependencies

**Depends on**: None (independent implementation). However, F-001 and F-007 config changes SHOULD be committed before freeze so the bundle captures their thresholds.

**Required by**:
- F-003 (eval-calibration): Eval MUST run against frozen bundle; `bundle_id` is mandatory in eval results.
- F-004 (human-review): Review package MUST reference `bundle_id`.
- F-007 (kill-switch): Rollback procedure references bundle for state restoration.

**Shared patterns**:
- Bundle identity propagation: All downstream artifacts (eval results, human review, monitoring) carry `bundle_id`.
- SHA-256 hash standard: Shared across F-002, F-003, F-008 for content integrity.

**Integration points**:
- `scripts/freeze_bundle.py` -- produces `data/launch-bundle.json` + `data/bundle-validation.json`
- `data/launch-bundle.json` -- consumed by eval runner, monitoring script, rollback procedure
