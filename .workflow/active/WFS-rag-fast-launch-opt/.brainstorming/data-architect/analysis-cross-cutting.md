# Cross-Cutting Data Decisions

**Scope**: Shared data contracts, integrity mechanisms, validation patterns, and post-launch migration path spanning F-002, F-003, F-008

## 1. Bundle Identity and Referencing

### Bundle ID Convention

Every launch bundle MUST carry a unique identifier:

```
bundle-{YYYYMMDD}-{short_hash}
```

Where `short_hash` is the first 8 characters of `SHA-256(commit_sha + frozen_at)`. This ID MUST appear in:
- `launch-bundle.json` (primary artifact)
- Eval result files (reference which bundle was tested)
- Monitoring dashboard output (reference which bundle is deployed)
- Human review input (reference which bundle's results are being reviewed)
- Kill switch config (reference which bundle to roll back to)

### Bundle Reference Propagation

All downstream data artifacts MUST include a `bundle_id` field, creating a traceability chain:

```
launch-bundle.json (bundle_id)
  -> eval_results.json (bundle_id: MUST match)
  -> human_review.json (bundle_id: MUST match)
  -> monitoring_output.json (deployed_bundle_id: MUST match current)
```

If any downstream artifact references a different `bundle_id` than the deployed bundle, the monitoring dashboard MUST surface this as a CRITICAL data integrity alert.

## 2. Hash and Integrity Standards

### Content Hash Algorithm

All content integrity checks MUST use SHA-256. This applies to:
- Corpus manifest per-document chunk content hashes
- Config file hashes in the bundle
- Identity bootstrap hash for ACL seed integrity

Rationale: SHA-256 is available in Python's `hashlib` with no additional dependencies, provides sufficient collision resistance for this corpus size (tens of thousands of chunks), and is fast enough for the fast launch timeline.

### Canonical Serialization for Hashing

Config and JSON artifacts MUST use canonical JSON before hashing:

```python
canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
sha256_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

Chunk content hashes MUST be computed over `text` (the field stored in Qdrant payloads), sorted by `chunk_index` within each document, then concatenated with newline delimiters. This matches the order used during ingestion in `TextChunker.split()`.

### Hash Storage Format

All hashes MUST be stored with the algorithm prefix: `sha256:<hex_digest>`. This allows future algorithm migration without schema changes.

## 3. Timestamp Format

All timestamps MUST use ISO 8601 UTC: `2026-04-06T11:30:00Z`. No timezone-naive datetimes. No epoch seconds as primary format.

The `frozen_at` field in `launch-bundle.json` is the bundle creation time. All sub-artifacts MUST carry their own `generated_at` timestamp, which MUST be >= `frozen_at` (eval runs after freeze, monitoring runs after deployment).

This convention aligns with the existing `occurred_at` field format in event logs and request traces (`2026-04-06T00:12:13.967857Z`), ensuring no format conversion is needed when comparing bundle timestamps against trace data.

## 4. Data Validation Framework

### Validation Levels

| Level | Behavior | Example |
|-------|----------|---------|
| CRITICAL | MUST pass; failure aborts bundle creation | Point count mismatch, missing documents, orphan chunks |
| WARNING | SHOULD pass; failure logs warning but allows creation | OCR confidence below threshold, eval sample type under-represented |
| INFO | Reporting only | Eval sample type distribution, department balance |

### Validation Pipeline Order

The bundle freeze script MUST execute validations in this order:

1. **Connectivity**: Qdrant accessible, collection exists, embedding service reachable
2. **Corpus integrity**: `total_point_count` matches manifest sum, no orphan `document_id` values, every document has chunks
3. **ACL completeness**: every document's `department_id` maps to a known department in identity bootstrap; every department in bootstrap has at least one user
4. **Index consistency**: collection `vector_size` matches embedding model output dimension; `distance_metric` is `Cosine`
5. **Config determinism**: `system_config` hash is reproducible from current runtime state
6. **Eval coverage**: eval dataset has minimum per-type sample counts (see F-003)

### Validation Output

Validation results MUST be written to `bundle-validation.json` alongside `launch-bundle.json`:

```json
{
  "bundle_id": "bundle-20260406-a1b2c3d4",
  "validated_at": "2026-04-06T11:35:00Z",
  "status": "pass|fail|warning",
  "checks": [
    {
      "name": "corpus_point_count",
      "level": "CRITICAL",
      "status": "pass",
      "expected": 15234,
      "actual": 15234,
      "message": null
    }
  ]
}
```

If any CRITICAL check fails, the freeze script MUST delete the partial `launch-bundle.json` and exit with non-zero code.

## 5. Shared Data Access Patterns

### Corpus Manifest Access

Both F-002 (bundle freeze) and F-003 (eval calibration) need corpus state. The corpus manifest MUST be generated once during freeze and referenced (not regenerated) during eval. The eval runner MUST verify the manifest matches current Qdrant state before executing by spot-checking `total_chunks` against `count_points()`.

### ACL Seed Access

The ACL seed MUST be a deterministic snapshot from two sources joined together:
1. `identity_bootstrap.json` -- defines roles, departments, users
2. Document metadata (`data/documents/*.json`) -- defines `department_ids` per document

The existing `eval/retrieval_document_acl_seed.yaml` already demonstrates this pattern with `doc_id`, `file_name_hint`, `department_id`, `retrieval_department_ids`, `visibility`. The bundle freeze MUST export this same structure into the bundle's `acl` section.

### Trace Data Access

F-008 (monitoring dashboard) reads the same JSONL trace files that `RequestTraceService` and `EventLogService` write to `data/request_traces/` and `data/event_logs/`. The monitoring script MUST NOT modify these files. It MUST support incremental analysis by tracking the last-processed timestamp in a state file (e.g., `monitoring_state.json` with `last_processed_trace_at` field).

### Event Log vs Request Trace Distinction

The codebase writes two separate JSONL streams:
- **event_logs**: Flat records with `event_id`, `category`, `action`, `outcome`, `duration_ms`, `details` (flattened retrieval diagnostics)
- **request_traces**: Nested records with `trace_id`, `request_id`, `stages` (per-stage duration/status array), `details` (structured retrieval diagnostics with `query_stage`, `routing_stage`, `primary_recall_stage`, `supplemental_recall_stage`)

Both carry the same core retrieval data but at different granularity. The monitoring dashboard MUST use `request_traces` for detailed analysis (per-stage timing, routing decisions) and `event_logs` for aggregate counts (action distribution, outcome rates).

## 6. Post-Launch Data Migration Path

The fast launch freezes data state but MUST NOT prevent post-launch optimization. Each optimization phase has distinct data migration implications:

### Phase 1: Supplemental Calibration

- **Data change**: Only `system_config.json` supplemental quality thresholds (`_internal_retrieval_controls.supplemental_quality_thresholds`)
- **Bundle impact**: New config snapshot, same corpus manifest. No corpus regeneration.
- **Eval requirement**: Re-run eval against same corpus, new config. New bundle_id required.
- **Migration risk**: LOW. Config-only change.

### Phase 2: Chunk Optimization

- **Data change**: `chunk_size_chars`, `chunk_overlap_chars` parameters change, triggering re-chunking of all documents. All `data/chunks/*.json` files regenerate. All Qdrant points are re-upserted with new `chunk_id` values and new `text` content.
- **Bundle impact**: New corpus manifest (different chunk counts, different content hashes). New index version (same collection but regenerated vectors). New ACL seed (unchanged). New config snapshot (different chunk params).
- **Eval requirement**: Full re-evaluation required. Score distributions WILL change because chunk boundaries shifted.
- **Migration risk**: HIGH. This is a full corpus rebuild. The old collection SHOULD be preserved (renamed, not deleted) until the new one is validated.

### Phase 3: Router/Hybrid Weight Optimization

- **Data change**: `vector_weight` and `lexical_weight` in `branch_weights` config, query classifier thresholds.
- **Bundle impact**: New config snapshot only. Same corpus, same index, same ACL.
- **Eval requirement**: Re-run eval. Results change because fusion weights affect ranking.
- **Migration risk**: MEDIUM. Config-only, but ranking changes affect all query types.

### Phase 4: Rerank Model Optimization

- **Data change**: `reranker_routing.provider`, `reranker_routing.model`, `reranker_routing.default_strategy` in system config.
- **Bundle impact**: New config snapshot. Same corpus, same index, same ACL.
- **Eval requirement**: Re-run eval. Results change because reranking changes top-K ordering.
- **Migration risk**: MEDIUM. The existing `RerankCanaryService` already supports A/B comparison between heuristic and model rerank, which can be leveraged for safe transition.

### Migration Invariant

Every phase change MUST trigger: new bundle freeze -> re-evaluation -> updated human review (if scores changed significantly) -> updated go/no-go. Old bundles MUST be archived, not deleted.

## 7. Data Size Estimates

| Artifact | Expected Size | Notes |
|----------|--------------|-------|
| corpus-manifest.json | 50-200 KB | ~20-100 docs, each with chunk count and hash |
| acl-seed.json | 5-10 KB | Identity bootstrap is small (~15 users, 8 departments) |
| launch-bundle.json (total) | 100-300 KB | Aggregates all sub-artifacts |
| eval dataset (60-80 samples) | 30-50 KB | YAML with query + expected IDs + metadata |
| eval results | 20-40 KB | Per-sample results + aggregate metrics + score distributions |
| Daily event log JSONL | 100 KB - 5 MB | Depends on query volume; current ~50KB/day observed |
| Daily request trace JSONL | 100 KB - 5 MB | Slightly larger than event logs due to nested stages |
| Monitoring output | 10-30 KB | Aggregated metrics + alerts |
| bundle-validation.json | 2-5 KB | Validation check results |

All sizes are well within filesystem and memory limits. No special handling for large data is required for the fast launch.
