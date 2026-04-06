# F-002: Bundle Freeze -- Data Architecture

**Feature**: Bundle Freeze Script
**Priority**: High
**Data-Architect Role**: Define artifact schemas, export procedures, and integrity validation

## 1. Overview

The bundle freeze script MUST export a self-contained, verifiable snapshot of all data artifacts that determine system behavior. The guiding principle: **if it affects retrieval results, it MUST be in the bundle**. This snapshot becomes the immutable reference for eval, human review, and go/no-go decisions.

## 2. Launch Bundle Schema

### 2.1 Top-Level Structure

```json
{
  "bundle_id": "bundle-20260406-a1b2c3d4",
  "frozen_at": "2026-04-06T11:30:00Z",
  "commit_sha": "0f73d0f2",
  "schema_version": "1.0",
  "corpus": { },
  "index": { },
  "acl": { },
  "config": { },
  "validation": { }
}
```

### 2.2 Corpus Manifest (`corpus` field)

The corpus manifest MUST enumerate every document in the Qdrant collection with per-document chunk counts and content hashes.

**Export procedure**: Use Qdrant scroll API to iterate all points, group by `document_id` from the payload, and compute aggregates. The existing `QdrantVectorStore` already stores points with `document_id`, `document_name`, `chunk_index`, `text`, `source_path`, `parsed_path`, `char_start`, `char_end` in each payload.

```json
{
  "corpus": {
    "total_documents": 42,
    "total_chunks": 15234,
    "collection_name": "enterprise_rag_v1_local_bge_m3",
    "documents": [
      {
        "doc_id": "doc_20260321023926_5221d730",
        "doc_name": "The headache of Penq.pdf",
        "source_path": "data/uploads/doc_20260321023926_5221d730__The_headache_of_Penq.pdf",
        "parsed_path": "data/parsed/doc_20260321023926_5221d730.txt",
        "chunk_count": 492,
        "content_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb924...",
        "chunk_hash_algorithm": "sha256",
        "file_hash": "a3d717f0db83f53e244d3c5df6d016869f83a0501c40332574f205eb9ea5adc3",
        "source_type": "pdf",
        "department_ids": [],
        "visibility": "private",
        "status": "active"
      }
    ]
  }
}
```

**Field definitions**:

| Field | Source | Required | Validation |
|-------|--------|----------|------------|
| `doc_id` | Qdrant payload `document_id` | MUST | Non-empty, unique within corpus. Matches `data/documents/*.json` doc_id |
| `doc_name` | Qdrant payload `document_name` | MUST | Non-empty. Matches `file_name` in document metadata |
| `source_path` | Qdrant payload `source_path` | MUST | File MUST exist at this path |
| `parsed_path` | Qdrant payload `parsed_path` | SHOULD | File SHOULD exist at this path |
| `chunk_count` | Count of Qdrant points with matching `document_id` | MUST | MUST be > 0 |
| `content_hash` | SHA-256 of concatenated `text` from all chunks, sorted by `chunk_index` | MUST | MUST be reproducible on re-computation |
| `file_hash` | From document metadata `file_hash` field | SHOULD | MUST match SHA-256 of the actual uploaded file |
| `source_type` | From document metadata `source_type` | SHOULD | One of: pdf, txt, md, markdown, docx, pptx |
| `department_ids` | From document metadata `department_ids` | MUST | Each MUST appear in ACL seed departments list |
| `visibility` | From document metadata `visibility` | SHOULD | One of: private, public |
| `status` | From document metadata `status` | MUST | MUST be "active" for all frozen documents |

**Content hash computation**:

```python
import hashlib

# Scroll all Qdrant points for this document
points = [p for p in all_points if p.payload["document_id"] == doc_id]
chunks_sorted = sorted(points, key=lambda p: p.payload.get("chunk_index", 0))
concatenated = "\n".join(p.payload.get("text", "") for p in chunks_sorted)
content_hash = hashlib.sha256(concatenated.encode("utf-8")).hexdigest()
```

**Validation rules**:
- `sum(documents[*].chunk_count)` MUST equal `total_chunks`
- `total_chunks` MUST equal `QdrantVectorStore.count_points()` (exact match)
- Every `doc_id` in the manifest MUST have at least one Qdrant point
- Every Qdrant point's `document_id` MUST appear in the manifest (no orphans)
- Every `source_path` MUST reference an existing file on disk
- Every `department_ids` entry MUST appear in the ACL seed

### 2.3 Index Version (`index` field)

```json
{
  "index": {
    "collection_name": "enterprise_rag_v1_local_bge_m3",
    "vector_size": 1024,
    "distance_metric": "Cosine",
    "embedding_provider": "openai",
    "embedding_model": "BAAI/bge-m3",
    "embedding_base_url": "http://embedding.test",
    "point_count": 15234,
    "index_config_hash": "sha256:abc123..."
  }
}
```

**Field definitions**:

| Field | Source | Required | Validation |
|-------|--------|----------|------------|
| `collection_name` | `Settings.qdrant_collection` | MUST | MUST exist in Qdrant `get_collections()` |
| `vector_size` | Qdrant collection config `params.vectors.size` | MUST | MUST match embedding model output dimension (1024 for bge-m3) |
| `distance_metric` | Qdrant collection config `params.vectors.distance` | MUST | MUST be "Cosine" |
| `embedding_provider` | `Settings.embedding_provider` | MUST | One of: mock, ollama, openai |
| `embedding_model` | `Settings.embedding_model` | MUST | MUST match the model that generated current vectors |
| `embedding_base_url` | `Settings.embedding_base_url` | SHOULD | For traceability |
| `point_count` | `QdrantVectorStore.count_points()` | MUST | MUST equal corpus `total_chunks` |
| `index_config_hash` | SHA-256 of Qdrant collection config JSON | MUST | MUST be reproducible |

**Critical validation**: The freeze script MUST embed a short test string via `EmbeddingClient` and verify the output dimension matches `vector_size`. If this check fails, it means the current embedding model does not match the vectors in the collection, and all retrieval results would be invalid.

### 2.4 ACL Seed (`acl` field)

```json
{
  "acl": {
    "source": "identity_bootstrap.json",
    "tenant_id": "wl",
    "role_count": 3,
    "department_count": 8,
    "user_count": 15,
    "departments": [
      {
        "department_id": "dept_after_sales",
        "name": "售后服务部",
        "document_ids": ["doc_20260321070337_445684f4"]
      },
      {
        "department_id": "dept_production_technology",
        "name": "生产工艺部",
        "document_ids": ["doc_20260330055115_c20cfc5a", "doc_20260331021041_adff1740"]
      }
    ],
    "supplemental_access": {
      "doc_20260321070337_445684f4": {
        "owner_department": "dept_installation_service",
        "retrieval_department_ids": ["dept_production_technology"]
      }
    },
    "content_hash": "sha256:abc123..."
  }
}
```

**Export procedure**:
1. Read `identity_bootstrap.json` via `Settings.identity_bootstrap_path`
2. Read all document metadata from `data/documents/*.json`
3. Build per-department document ownership map from `document.department_ids`
4. Build supplemental access map from the `eval/retrieval_document_acl_seed.yaml` pattern (`retrieval_department_ids` per document)
5. Validate referential integrity

**Field definitions**:

| Field | Source | Required | Validation |
|-------|--------|----------|------------|
| `source` | File path of identity bootstrap | MUST | File MUST exist |
| `tenant_id` | From bootstrap `departments[0].tenant_id` | MUST | All departments/users MUST share this tenant |
| `role_count` | Length of `bootstrap.roles` | MUST | MUST be 3 (employee, department_admin, sys_admin) |
| `department_count` | Length of `bootstrap.departments` | MUST | MUST be > 0 |
| `user_count` | Length of `bootstrap.users` | MUST | MUST be > 0 |
| `departments` | Join between bootstrap and document metadata | MUST | Every department's document_ids MUST appear in corpus manifest |
| `supplemental_access` | From document ACL seed pattern | MUST | Cross-department retrieval mappings |
| `content_hash` | SHA-256 of canonical bootstrap JSON | MUST | MUST be reproducible |

**Completeness check**: Every document in the corpus manifest MUST have its owning department appear in the ACL seed. Every department in the ACL seed MUST have at least one user assigned in the bootstrap. If either fails, emit CRITICAL validation error.

### 2.5 Config Snapshot (`config` field)

```json
{
  "config": {
    "system_config_hash": "sha256:abc123...",
    "query_profiles": {
      "fast": { "top_k_default": 5, "candidate_multiplier": 4, "rerank_top_n": 5 },
      "accurate": { "top_k_default": 8, "candidate_multiplier": 4, "rerank_top_n": 5 }
    },
    "reranker_routing": {
      "provider": "openai_compatible",
      "default_strategy": "provider",
      "model": "BAAI/bge-reranker-v2-m3"
    },
    "supplemental_quality_thresholds": {
      "top1_threshold": 0.55,
      "avg_top_n_threshold": 0.45,
      "fine_query_top1_threshold": 0.95,
      "fine_query_avg_top_n_threshold": 0.7
    },
    "degrade_controls": {
      "rerank_fallback_enabled": true,
      "accurate_to_fast_fallback_enabled": true,
      "retrieval_fallback_enabled": true
    }
  }
}
```

**Source**: Read from `SystemConfigRepository.read()` (maps to `data/system_config.json`).

**Validation**: Re-serialize system_config.json with sorted keys and verify the hash is reproducible. The `updated_at` field in system_config.json MUST be <= `frozen_at` (config must not have been updated after freeze).

## 3. Bundle Export Procedure

### Step 1: Pre-flight Checks

Before any export, verify:
1. Qdrant is accessible and target collection exists
2. Identity bootstrap file exists and parses with valid structure (roles, departments, users)
3. System config file exists at `data/system_config.json`
4. All document metadata files exist under `data/documents/`
5. Git repository has no uncommitted changes in tracked files (WARNING only, do not block)

### Step 2: Export Corpus Manifest

```python
store = QdrantVectorStore(settings)
all_points = store.scroll_all_points()  # Use scroll API for full collection scan

# Group by document_id
docs = {}
for point in all_points:
    doc_id = point.payload["document_id"]
    docs.setdefault(doc_id, []).append(point)

# Build manifest
manifest_docs = []
for doc_id, points in docs.items():
    doc_meta = read_document_metadata(doc_id)  # from data/documents/
    chunks_sorted = sorted(points, key=lambda p: p.payload.get("chunk_index", 0))
    content = "\n".join(p.payload.get("text", "") for p in chunks_sorted)

    manifest_docs.append({
        "doc_id": doc_id,
        "doc_name": points[0].payload["document_name"],
        "source_path": points[0].payload.get("source_path", ""),
        "parsed_path": points[0].payload.get("parsed_path", ""),
        "chunk_count": len(points),
        "content_hash": f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
        "file_hash": doc_meta.get("file_hash", ""),
        "source_type": doc_meta.get("source_type", ""),
        "department_ids": doc_meta.get("department_ids", []),
        "visibility": doc_meta.get("visibility", "private"),
        "status": doc_meta.get("status", "active")
    })
```

### Step 3: Export Index Version

Read Qdrant collection config, record vector parameters, verify against embedding model.

### Step 4: Export ACL Seed

Read identity bootstrap, cross-reference with document metadata for department ownership.

### Step 5: Export Config Snapshot

Read system_config.json, compute hash, extract retrieval-relevant fields.

### Step 6: Validate and Write Bundle

Run all validations, generate bundle_id, write `launch-bundle.json` and `bundle-validation.json`.

## 4. Post-Write Integrity Verification

After `launch-bundle.json` is written, the script MUST re-read it and verify:
1. File parses as valid JSON
2. `total_chunks` still matches live Qdrant point count
3. All referenced files (`source_path`, `parsed_path`) still exist on disk
4. Content hashes are reproducible (spot-check 3 random documents by re-scrolling their points)
5. Config hash is reproducible (re-read system_config.json and re-compute)

If any post-write verification fails, the script MUST delete the bundle file and exit with non-zero code.

## 5. Bundle Consumption Contracts

### Eval Runner (F-003)

The eval runner MUST:
1. Read `launch-bundle.json` at startup
2. Verify `bundle_id` is present and well-formed
3. Verify `index.point_count` matches current Qdrant state
4. Verify `index.collection_name` matches `Settings.qdrant_collection`
5. Verify `index.embedding_model` matches `Settings.embedding_model`
6. Record `bundle_id` in eval results output
7. Abort if any verification fails

### Kill Switch (F-007)

The kill switch config SHOULD reference a `bundle_id` for rollback target. When rolling back, the system SHOULD verify that the current corpus matches the bundle's corpus manifest (WARNING if mismatch, do not block rollback).

### Monitoring (F-008)

The monitoring dashboard MUST read `launch-bundle.json` to establish the expected baseline. It MUST compare:
- Current point count vs. bundle `total_chunks`
- Current config hash vs. bundle `config.system_config_hash`
- Current embedding model vs. bundle `index.embedding_model`

Any mismatch MUST be reported as bundle drift.

## 6. Forward Compatibility

The bundle format MUST be forward-compatible. `schema_version: "1.0"` allows future versions to add fields without breaking existing parsers. Consumers MUST ignore unknown fields. The freeze script for future versions MUST generate bundles that 1.0 parsers can still read for the fields they understand.

When post-launch optimization changes corpus/index/ACL, a new bundle MUST be generated. The old bundle MUST be archived (renamed with bundle_id suffix) for historical comparison.
