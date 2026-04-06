# F-008: Monitoring Dashboard -- Data Architecture

**Feature**: Monitoring Dashboard (script to analyze existing traces)
**Priority**: Low
**Data-Architect Role**: Define data quality signals, JSONL parsing approach, metric extraction, bundle drift detection

## 1. Overview

The monitoring dashboard is a read-only analysis script that processes existing trace data to surface launch health signals. It MUST NOT introduce new infrastructure -- it reads the same JSONL files that `EventLogService` and `RequestTraceService` already write. From the data-architect perspective, the key challenges are: parsing potentially malformed JSONL, extracting meaningful metrics from nested retrieval diagnostics, and comparing live state against the frozen bundle baseline.

## 2. Data Sources

### 2.1 Event Logs

**Location**: `data/event_logs/YYYY-MM-DD.jsonl`

**Format**: One JSON object per line. Each record contains:

```json
{
  "event_id": "evt_41cbd8f181314798",
  "category": "retrieval",
  "action": "search",
  "outcome": "success",
  "occurred_at": "2026-04-06T00:12:13.967679Z",
  "actor": {
    "tenant_id": "wl",
    "user_id": "user_installation_employee_demo",
    "username": "installation.employee.demo",
    "role_id": "employee",
    "department_id": "dept_installation_service"
  },
  "mode": "fast",
  "top_k": 5,
  "candidate_top_k": 20,
  "rerank_top_n": 5,
  "duration_ms": 584,
  "timeout_flag": false,
  "downgraded_from": null,
  "details": {
    "query": "700000 面板急停报警 现场先查什么",
    "query_type": "fixed",
    "query_granularity": "fine",
    "retrieval_mode": "hybrid",
    "document_id_filter_applied": false,
    "department_priority_enabled": true,
    "primary_threshold": 5,
    "primary_effective_count": 20,
    "supplemental_triggered": false,
    "supplemental_reason": "department_sufficient",
    "recall_counts": {
      "department_vector_count": 16,
      "department_lexical_count": 17,
      "department_fused_count": 20
    },
    "filter_counts": { "top_k_truncated": 15 },
    "final_result_count": 5,
    "branch_weights": {
      "vector_weight": 1.0,
      "lexical_weight": 1.0,
      "dynamic_enabled": false
    }
  }
}
```

**Data quality signals available**:
- `outcome`: success/failure/timeout -- overall health
- `duration_ms`: latency tracking
- `timeout_flag`: timeout events
- `downgraded_from`: degradation events (accurate->fast, model->heuristic)
- `details.supplemental_triggered`: supplemental recall activation rate
- `details.supplemental_reason`: why supplemental triggered or did not trigger
- `details.recall_counts`: recall volume per branch
- `details.final_result_count`: how many results returned (evidence for abstention rate)

### 2.2 Request Traces

**Location**: `data/request_traces/YYYY-MM-DD.jsonl`

**Format**: One JSON object per line. Each record contains the same top-level fields as event logs, plus:

```json
{
  "trace_id": "trc_retrieval_56ef25395a6c4e88",
  "request_id": "req_retrieval_5a8c5f55c5a143c6",
  "stages": [],
  "details": {
    "query_stage": { "raw_query": "...", "query_type": "fixed", "query_granularity": "fine" },
    "routing_stage": { "is_hybrid": true, "vector_weight": 1.0, "lexical_weight": 1.0 },
    "primary_recall_stage": {
      "vector_count": 16,
      "lexical_count": 17,
      "fused_count": 20,
      "effective_count": 20,
      "threshold": 5,
      "whether_sufficient": true,
      "top1_score": 1.0,
      "avg_top_n_score": 0.9499,
      "quality_top1_threshold": 0.95,
      "quality_avg_threshold": 0.7
    },
    "supplemental_recall_stage": { }
  }
}
```

**Additional data quality signals from traces**:
- `details.primary_recall_stage.top1_score`: per-request top-1 relevance score
- `details.primary_recall_stage.avg_top_n_score`: per-request average score across top-N
- `details.primary_recall_stage.whether_sufficient`: whether primary recall was sufficient
- `details.primary_recall_stage.quality_top1_threshold` and `quality_avg_threshold`: current quality thresholds in effect
- `details.routing_stage`: retrieval mode and weight decisions
- `stages[]`: per-stage duration breakdown for latency analysis

### 2.3 Chat Memory

**Location**: `data/chat_memory/sess_*.json`

Not a primary monitoring source, but MAY be used to correlate retrieval failures with chat outcomes. The monitoring script SHOULD NOT parse chat memory by default.

## 3. JSONL Parsing and Analysis Approach

### 3.1 Robust JSONL Parsing

The monitoring script MUST handle real-world JSONL issues:

```python
import json
from pathlib import Path
from datetime import datetime

def parse_jsonl_safe(filepath: Path) -> list[dict]:
    """Parse JSONL file, skipping malformed lines."""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Log the malformed line but do not crash
                logger.warning(f"Malformed JSON at {filepath}:{line_num}")
    return records
```

The script MUST NOT crash on malformed lines. It SHOULD log a count of skipped lines and include this count in the monitoring output as a data quality signal.

### 3.2 Incremental Analysis

The monitoring script MUST support incremental analysis to avoid re-processing historical data on each run:

```python
# State file: monitoring_state.json
{
  "last_processed_event_log": "2026-04-06",
  "last_processed_trace_log": "2026-04-06",
  "last_processed_line_event": 245,
  "last_processed_line_trace": 245,
  "last_run_at": "2026-04-06T18:00:00Z"
}
```

On each run, the script reads the state file, processes only new files and new lines, and updates the state. This keeps runtime bounded regardless of how much historical trace data accumulates.

### 3.3 Date Range Selection

The script MUST accept a `--since` parameter (default: last 24 hours) and a `--until` parameter (default: now). It MUST parse only JSONL files within the date range, derived from filenames (`YYYY-MM-DD.jsonl`).

## 4. Key Metrics to Extract

### 4.1 Score Distribution

From request traces `details.primary_recall_stage`:

```json
{
  "score_distribution": {
    "top1": {
      "mean": 0.85,
      "median": 0.88,
      "std": 0.12,
      "min": 0.35,
      "p10": 0.52,
      "p25": 0.71,
      "p50": 0.88,
      "p75": 0.94,
      "p90": 0.97,
      "max": 1.0,
      "sample_count": 245
    },
    "avg_top_n": {
      "mean": 0.72,
      "median": 0.75,
      "std": 0.10
    }
  }
}
```

**Alerting**: If the p10 of top1_score drops below the evidence gate threshold (from launch-bundle.json config), the dashboard MUST flag this as a WARNING. This indicates that more than 10% of queries are scoring near or below the abstention threshold.

### 4.2 Mode Distribution

From event logs `mode` field and `downgraded_from` field:

```json
{
  "mode_distribution": {
    "fast": { "count": 200, "percentage": 81.6 },
    "accurate": { "count": 45, "percentage": 18.4 },
    "total": 245
  },
  "degradation_events": {
    "accurate_to_fast": { "count": 3, "reasons": ["timeout", "concurrency_limit"] },
    "model_to_heuristic_rerank": { "count": 1, "reasons": ["timeout"] }
  }
}
```

**Alerting**: If degradation events exceed 10% of total requests, the dashboard MUST flag this as a WARNING. High degradation indicates infrastructure stress.

### 4.3 Evidence Gate Trigger Rate

Derived from event logs `details.supplemental_triggered`, `details.primary_recall_stage.whether_sufficient`, and `details.final_result_count`:

```json
{
  "evidence_gate_signals": {
    "primary_sufficient_rate": 0.92,
    "supplemental_triggered_rate": 0.08,
    "supplemental_reasons": {
      "department_sufficient": 200,
      "quality_below_threshold": 30,
      "low_lexical_score": 10,
      "mono_document_literal_coverage": 5
    },
    "zero_result_rate": 0.02,
    "avg_final_result_count": 4.8
  }
}
```

**Alerting**: If `zero_result_rate` exceeds 5%, this indicates queries that find no evidence at all. If `primary_sufficient_rate` drops below 85%, this indicates retrieval quality degradation.

### 4.4 Outcome and Error Distribution

From event logs `outcome` field:

```json
{
  "outcome_distribution": {
    "success": { "count": 240, "percentage": 98.0 },
    "failure": { "count": 3, "percentage": 1.2 },
    "timeout": { "count": 2, "percentage": 0.8 },
    "total": 245
  },
  "timeout_rate": 0.008,
  "error_rate": 0.012
}
```

**Alerting**: If error_rate exceeds 2% or timeout_rate exceeds 2%, the dashboard MUST flag this as CRITICAL. These indicate service-level problems.

### 4.5 Latency Distribution

From event logs `duration_ms`:

```json
{
  "latency_distribution": {
    "mean_ms": 450,
    "median_ms": 380,
    "p90_ms": 620,
    "p95_ms": 850,
    "p99_ms": 1200,
    "max_ms": 2400
  }
}
```

**Alerting**: If p95_ms exceeds the timeout budget (12 seconds for fast mode per system config), the dashboard MUST flag this as CRITICAL. If p90_ms exceeds 2x the baseline median, flag as WARNING.

### 4.6 Department Activity

From event logs `actor.department_id`:

```json
{
  "department_activity": {
    "dept_installation_service": { "query_count": 80, "percentage": 32.7 },
    "dept_production_technology": { "query_count": 70, "percentage": 28.6 },
    "dept_digitalization": { "query_count": 60, "percentage": 24.5 },
    "dept_after_sales": { "query_count": 35, "percentage": 14.3 }
  }
}
```

## 5. Bundle Drift Detection

### 5.1 Baseline Comparison

The monitoring script MUST read `launch-bundle.json` and compare current live state against the frozen baseline:

```json
{
  "bundle_drift": {
    "bundle_id": "bundle-20260406-a1b2c3d4",
    "checks": [
      {
        "check": "point_count",
        "bundle_value": 15234,
        "current_value": 15234,
        "status": "match"
      },
      {
        "check": "config_hash",
        "bundle_value": "sha256:abc123...",
        "current_value": "sha256:abc123...",
        "status": "match"
      },
      {
        "check": "embedding_model",
        "bundle_value": "BAAI/bge-m3",
        "current_value": "BAAI/bge-m3",
        "status": "match"
      },
      {
        "check": "collection_name",
        "bundle_value": "enterprise_rag_v1_local_bge_m3",
        "current_value": "enterprise_rag_v1_local_bge_m3",
        "status": "match"
      }
    ],
    "overall_status": "no_drift"
  }
}
```

### 5.2 Drift Severity Levels

| Check | Drift Status | Severity | Action |
|-------|-------------|----------|--------|
| `point_count` | current != bundle | CRITICAL | Corpus changed since launch; eval results invalid |
| `config_hash` | current != bundle | CRITICAL | Config changed; quality thresholds may have shifted |
| `embedding_model` | current != bundle | CRITICAL | Embedding model changed; all score calibrations invalid |
| `collection_name` | current != bundle | CRITICAL | Different collection entirely |
| `vector_size` | current != bundle | CRITICAL | Embedding dimension mismatch |

Any CRITICAL drift MUST be surfaced prominently in the monitoring output and SHOULD trigger an alert notification (at minimum, write to a `monitoring_alerts.json` file that can be picked up by operators).

### 5.3 Content Integrity Spot-Check

For deeper drift detection, the monitoring script SHOULD spot-check document content integrity:
1. Pick 3 random documents from the bundle corpus manifest
2. Scroll their current Qdrant points
3. Re-compute content hashes
4. Compare against manifest hashes

This catches the case where point count is correct but individual chunk content was modified.

## 6. Output Format

### 6.1 Monitoring Output Structure

The monitoring script MUST write its output to a JSON file:

```json
{
  "monitoring_run_at": "2026-04-06T18:00:00Z",
  "bundle_id": "bundle-20260406-a1b2c3d4",
  "analysis_period": {
    "since": "2026-04-06T00:00:00Z",
    "until": "2026-04-06T18:00:00Z"
  },
  "data_quality": {
    "event_log_lines_processed": 245,
    "event_log_lines_skipped": 0,
    "trace_lines_processed": 245,
    "trace_lines_skipped": 0
  },
  "metrics": {
    "score_distribution": { },
    "mode_distribution": { },
    "evidence_gate_signals": { },
    "outcome_distribution": { },
    "latency_distribution": { },
    "department_activity": { }
  },
  "bundle_drift": {
    "overall_status": "no_drift",
    "checks": [ ]
  },
  "alerts": [
    {
      "severity": "WARNING",
      "check": "zero_result_rate",
      "message": "Zero result rate at 6.1%, exceeds 5% threshold",
      "observed_value": 0.061,
      "threshold": 0.05
    }
  ]
}
```

### 6.2 Console Summary

The script SHOULD also print a human-readable summary to stdout:

```
RAG Launch Health Monitor
========================
Period: 2026-04-06 00:00 - 18:00 UTC
Bundle: bundle-20260406-a1b2c3d4

Requests: 245 | Success: 98.0% | Timeout: 0.8%
Latency P95: 850ms (budget: 12000ms)
Top-1 Score Mean: 0.85 | P10: 0.52

Evidence Gate: Primary sufficient 92.0% | Supplemental 8.0% | Zero-result 2.0%
Bundle Drift: NONE

Alerts: 0
```

## 7. Script Execution Model

### 7.1 Invocation

```bash
python scripts/monitoring_dashboard.py \
  --bundle launch-bundle.json \
  --since "2026-04-06T00:00:00Z" \
  --output monitoring_output.json
```

### 7.2 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks pass, no alerts |
| 1 | WARNING alerts present |
| 2 | CRITICAL alerts present |
| 3 | Script error (file not found, parse failure) |

This allows integration with cron or systemd: non-zero exit triggers operator attention.

### 7.3 Scheduling

For the fast launch, the script SHOULD be run manually on demand. Post-launch, it MAY be scheduled via cron (e.g., every 15 minutes) with the state file tracking incremental processing. The script MUST complete within 30 seconds for a typical day's traces (~50KB per JSONL file).

## 8. Data Retention

The monitoring script MUST NOT delete or modify trace files. It MUST NOT create new trace data. Its output files (monitoring_output.json, monitoring_state.json) SHOULD be written to a configurable output directory, defaulting to `monitoring/` at the project root.

Historical monitoring outputs MAY be retained for trend analysis. The script SHOULD support a `--compare` flag that reads a previous monitoring output and highlights changes.
