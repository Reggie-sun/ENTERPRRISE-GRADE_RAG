# F-002: Bundle Freeze — System Architect Analysis

**Feature**: Script to freeze commit/config/corpus/index/ACL into launch-bundle.json
**Priority**: High
**Constraint**: MUST produce immutable artifact; MUST NOT modify running system
**Date**: 2026-04-06

## 1. Problem Definition

Without a formal freeze mechanism, there is no guarantee that the system evaluated during calibration is the same system deployed to production. A developer could change config, re-index corpus, or modify ACL rules between eval and deploy. The bundle freeze creates a single immutable snapshot that ties together all deployable state, establishing a verifiable chain of custody from eval to production.

## 2. Architecture Integration

### Existing Infrastructure

The project already provides all the data sources needed for a bundle:

| Bundle Component | Existing Source | Access Method |
|-----------------|----------------|---------------|
| Commit SHA | Git repository | `git rev-parse HEAD` |
| Config snapshot | `data/system_config.json` | Direct file read |
| Corpus manifest | `data/documents/`, `data/chunks/`, `data/parsed/` | Filesystem scan |
| Index info | Qdrant collection | `GET /collections/{name}` via Qdrant HTTP API |
| ACL seed | `backend/app/bootstrap/identity_bootstrap.json` | Direct file read |

No new backend services or API endpoints are required. The freeze script is a standalone CLI tool that reads existing state and writes a single JSON file.

### Script Location and Execution

**File**: `scripts/freeze_bundle.py`

The script MUST be executable from the project root with no special dependencies beyond Python stdlib and `git` CLI:

```bash
python scripts/freeze_bundle.py --output data/launch-bundle.json
```

## 3. Bundle Schema

```python
class LaunchBundle(BaseModel):
    bundle_id: str              # Format: "bundle-{YYYYMMDDHHmmss}-{short_sha}"
    frozen_at: str              # ISO 8601 timestamp
    commit_sha: str             # Full git commit SHA

    config_snapshot: dict       # Complete system_config.json contents
    corpus_manifest: CorpusManifest
    index_info: IndexInfo
    acl_seed: ACLSeed

class CorpusManifest(BaseModel):
    document_count: int
    documents: list[DocumentEntry]
    total_chunk_count: int

class DocumentEntry(BaseModel):
    document_id: str
    document_name: str
    source_path: str
    file_hash: str              # SHA-256 of original file
    chunk_count: int
    file_size_bytes: int

class IndexInfo(BaseModel):
    collection_name: str        # From settings.qdrant_collection
    embedding_model: str        # From settings.embedding_model (or hardcoded if not in config)
    vector_count: int           # From Qdrant collection info
    index_status: str           # "green" / "yellow" / "red"

class ACLSeed(BaseModel):
    source_file: str            # Path to bootstrap file
    file_hash: str              # SHA-256 of ACL bootstrap file
    role_count: int
    department_count: int
    user_count: int
```

## 4. Script Design

### 4.1 Commit SHA Capture

```python
def capture_commit_sha(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()
```

The script MUST verify that the working tree is clean (no uncommitted changes). If `git status --porcelain` returns any output, the script MUST fail with a clear error message: "Cannot freeze bundle with uncommitted changes. Commit or stash all changes before freezing."

### 4.2 Config Snapshot

Read `data/system_config.json` directly as a dict. This captures the exact runtime configuration including `_internal_retrieval_controls` (evidence gate threshold) and the future `_launch_controls` (kill switch).

```python
def snapshot_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"System config not found: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))
```

### 4.3 Corpus Manifest

Scan `data/documents/` for source files, `data/chunks/` for chunk counts, and compute SHA-256 hashes for each document.

```python
def build_corpus_manifest(data_dir: Path) -> CorpusManifest:
    documents_dir = data_dir / "documents"
    chunks_dir = data_dir / "chunks"
    entries = []
    for doc_file in documents_dir.rglob("*"):
        if doc_file.is_file():
            doc_id = derive_document_id(doc_file)  # match existing naming convention
            chunk_count = count_chunks_for_doc(chunks_dir, doc_id)
            file_hash = sha256_file(doc_file)
            entries.append(DocumentEntry(
                document_id=doc_id,
                document_name=doc_file.name,
                source_path=str(doc_file.relative_to(data_dir)),
                file_hash=file_hash,
                chunk_count=chunk_count,
                file_size_bytes=doc_file.stat().st_size,
            ))
    return CorpusManifest(
        document_count=len(entries),
        documents=sorted(entries, key=lambda e: e.document_id),
        total_chunk_count=sum(e.chunk_count for e in entries),
    )
```

The document ID derivation MUST match the existing naming convention used by the ingestion service. The script SHOULD log a warning if it encounters files that do not match the expected `doc_*` naming pattern.

### 4.4 Index Info

Query Qdrant via HTTP API to get collection status and vector count:

```python
def capture_index_info(qdrant_url: str, collection_name: str) -> IndexInfo:
    response = requests.get(f"{qdrant_url}/collections/{collection_name}", timeout=10)
    response.raise_for_status()
    info = response.json()["result"]
    return IndexInfo(
        collection_name=collection_name,
        embedding_model="...",  # from settings
        vector_count=info["points_count"],
        index_status=info["status"],
    )
```

If Qdrant is unreachable, the script MUST fail with a non-zero exit code. A bundle without index verification is invalid.

### 4.5 ACL Seed

Read the identity bootstrap file and compute its hash:

```python
def capture_acl_seed(bootstrap_path: Path) -> ACLSeed:
    if not bootstrap_path.exists():
        raise FileNotFoundError(f"ACL bootstrap not found: {bootstrap_path}")
    data = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    return ACLSeed(
        source_file=str(bootstrap_path),
        file_hash=sha256_file(bootstrap_path),
        role_count=len(data.get("roles", [])),
        department_count=len(data.get("departments", [])),
        user_count=len(data.get("users", [])),
    )
```

## 5. Immutability Guarantee

The script MUST write the bundle atomically:

1. Build complete bundle in memory
2. Validate all fields (no None values, all lists non-empty)
3. Write to a `.tmp` file
4. Rename `.tmp` to `launch-bundle.json`

If the output file already exists, the script MUST refuse to overwrite unless `--force` is passed. This prevents accidental re-freezing over an existing bundle.

```python
def write_bundle(bundle: LaunchBundle, output_path: Path, force: bool = False) -> None:
    if output_path.exists() and not force:
        raise FileExistsError(
            f"Bundle already exists: {output_path}. Use --force to overwrite."
        )
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    tmp_path.rename(output_path)
```

## 6. Bundle Verification

The script SHOULD include a `--verify` mode that checks an existing bundle against current state:

```bash
python scripts/freeze_bundle.py --verify data/launch-bundle.json
```

Verification checks:
- Current commit SHA matches `bundle.commit_sha`
- Current system_config.json matches `bundle.config_snapshot`
- Corpus files match `bundle.corpus_manifest` (by hash)
- Qdrant vector count matches `bundle.index_info.vector_count`
- ACL bootstrap matches `bundle.acl_seed` (by hash)

This verification step is critical for rollback: before restoring a bundle, verify that the target state is actually achievable.

## 7. Dependency on Other Features

| Feature | Dependency Direction | Description |
|---------|---------------------|-------------|
| F-001 (evidence gate) | Bundle consumes config | Bundle freezes the evidence gate threshold as part of config_snapshot |
| F-003 (eval calibration) | Eval consumes bundle | Eval MUST reference the bundle_id to prove it ran against frozen state |
| F-004 (human review) | Review consumes bundle | Human review package MUST include bundle_id |
| F-007 (kill switch) | Rollback references bundle | Rollback procedure restores state from bundle |
| F-008 (monitoring) | Dashboard reads bundle | Dashboard MAY compare current state against bundle for drift detection |

## 8. Files to Create/Modify

| File | Change Type | Description |
|------|------------|-------------|
| `scripts/freeze_bundle.py` | NEW | Bundle freeze + verify script |
| `data/launch-bundle.json` | GENERATED | Output artifact (gitignored) |
| `.gitignore` | MODIFY | Add `data/launch-bundle.json` if not already gitignored |

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Qdrant unreachable during freeze | Medium | High | Script fails with clear error; freeze MUST be retried with Qdrant running |
| Corpus files modified during freeze | Low | Critical | Atomic scan + hash; freeze takes <5 seconds for typical corpus |
| Bundle file corrupted or lost | Low | High | Script outputs to data/ which is in .gitignore; team MUST manually back up bundle |
| Document ID derivation mismatches ingestion naming | Medium | Medium | Script logs all doc files; verification step catches mismatches |
| Uncommitted git changes during freeze | Medium | Low | Pre-check rejects dirty working tree |
