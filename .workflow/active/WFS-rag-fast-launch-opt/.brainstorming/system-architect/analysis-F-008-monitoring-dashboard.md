# F-008: Monitoring Dashboard — System Architect Analysis

**Feature**: Script-based analysis of existing event_log + request_trace JSONL files
**Priority**: Low (MAY be deferred to post-launch)
**Constraint**: MUST NOT introduce new infrastructure; MUST NOT modify running services
**Date**: 2026-04-06

## 1. Problem Definition

Post-launch observability is essential but the project constraints forbid introducing Prometheus, Grafana, or any new infrastructure. The system already writes rich telemetry to two JSONL file sources:

- `data/event_logs/YYYY-MM-DD.jsonl` -- high-level event records (category, action, outcome, duration)
- `data/request_traces/YYYY-MM-DD.jsonl` -- detailed per-request stage traces with scores, strategies, and candidate details

The monitoring dashboard is a CLI script that parses these existing files and produces a human-readable health summary.

## 2. Existing Data Sources

### 2.1 Event Log Structure

From `event_log_service.py`, each JSONL line contains:

```json
{
  "trace_id": "trc_chat_...",
  "request_id": "req_chat_...",
  "category": "chat",
  "action": "answer",
  "outcome": "success",
  "occurred_at": "ISO8601",
  "actor": { "user_id": "...", "role_id": "...", "department_id": "..." },
  "mode": "fast",
  "response_mode": "rag",
  "duration_ms": 3500,
  "error_message": null,
  "details": { ... }
}
```

### 2.2 Request Trace Structure

From `request_trace_service.py`, each JSONL line contains:

```json
{
  "trace_id": "trc_retrieval_...",
  "category": "retrieval",
  "action": "search",
  "outcome": "success",
  "details": {
    "query": "...",
    "retrieval_mode": "hybrid",
    "final_result_count": 5,
    "primary_recall_stage": {
      "top1_score": 0.82,
      "avg_top_n_score": 0.71
    },
    "supplemental_recall_stage": {
      "triggered": false,
      "reason": "department_sufficient"
    },
    "result_explainability": [ ... ]
  }
}
```

### 2.3 New Fields from F-001 and F-007

After F-001 and F-007 are implemented, additional fields will appear in trace details:

- `evidence_gate_result.triggered` (bool) -- whether the gate triggered
- `evidence_gate_result.top1_score` (float) -- the score that was evaluated
- `kill_switch_active` (bool) -- whether kill switch was active

The monitoring script MUST handle both old traces (without these fields) and new traces (with these fields) gracefully.

## 3. Script Design

### 3.1 Location and Execution

**File**: `scripts/monitor_dashboard.py`

```bash
# Today's health summary
python scripts/monitor_dashboard.py --date today

# Specific date
python scripts/monitor_dashboard.py --date 2026-04-07

# Last N hours
python scripts/monitor_dashboard.py --hours 6

# Compare two dates
python scripts/monitor_dashboard.py --compare 2026-04-06 2026-04-07
```

### 3.2 Output Format

The script outputs plain text to stdout, suitable for terminal viewing or piping to a file:

```
=== RAG Health Dashboard — 2026-04-06 ===

CHAT METRICS
  Total requests:        142
  Success rate:          97.2% (138/142)
  Error rate:            2.8%  (4/142)
  Avg response time:     3.2s
  P95 response time:     8.1s

RESPONSE MODE DISTRIBUTION
  rag:                   89 (62.7%)
  retrieval_fallback:    18 (12.7%)
  no_context:            22 (15.5%)
  evidence_gate_abstain: 11 (7.7%)
  kill_switch:           0  (0.0%)

EVIDENCE GATE (post F-001)
  Gate trigger rate:     12.4% (11/89 rag candidates)
  Avg top1 score:        0.78
  Score < 0.60:          11 queries

RETRIEVAL METRICS
  Avg top1 score:        0.79
  Avg top-N score:       0.62
  Supplemental trigger:  23.1% (33/142)
  Hybrid mode usage:     100%

ALERTS
  [WARN] Error rate above 2% threshold
  [INFO] Evidence gate trigger rate stable
```

### 3.3 Metrics Computation

**Chat metrics** (from event_logs):
- Filter by `category == "chat"` and `action == "answer"`
- Count by `outcome` for success/error rates
- Compute mean and P95 of `duration_ms`
- Group by `response_mode` for distribution

**Evidence gate metrics** (from request_traces, post F-001):
- Filter traces with `evidence_gate_result` in details
- Compute trigger rate: `triggered=True / total evaluated`
- Compute score distribution: min, avg, max of `top1_score`
- Count queries below threshold

**Retrieval metrics** (from request_traces):
- Filter by `category == "retrieval"`
- Extract `primary_recall_stage.top1_score` and `avg_top_n_score`
- Compute supplemental trigger rate from `supplemental_recall_stage.triggered`

### 3.4 Alert Rules

The script SHOULD define configurable alert thresholds:

```python
ALERT_THRESHOLDS = {
    "error_rate_pct": 5.0,         # Alert if error rate exceeds 5%
    "kill_switch_active": True,    # Alert if any kill_switch responses
    "gate_trigger_rate_pct": 30.0, # Alert if gate triggers > 30% of queries
    "avg_response_time_s": 10.0,   # Alert if avg response time > 10s
    "p95_response_time_s": 20.0,   # Alert if P95 response time > 20s
}
```

Alerts are informational. The script does NOT send notifications (no new infrastructure). Operators run the script manually or schedule it via cron.

## 4. Implementation Details

### 4.1 JSONL Parsing

The script MUST handle malformed lines gracefully:

```python
def parse_jsonl(file_path: Path) -> list[dict]:
    records = []
    with file_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[WARN] Malformed JSON at {file_path.name}:{line_num}", file=sys.stderr)
    return records
```

### 4.2 Date Resolution

```python
def resolve_date(date_str: str) -> str:
    if date_str == "today":
        return datetime.now().strftime("%Y-%m-%d")
    if date_str == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return date_str  # Assume YYYY-MM-DD format
```

### 4.3 File Discovery

```python
def find_trace_files(data_dir: Path, date: str) -> tuple[Path, Path]:
    event_log = data_dir / "event_logs" / f"{date}.jsonl"
    request_trace = data_dir / "request_traces" / f"{date}.jsonl"
    return event_log, request_trace
```

If a file does not exist for the requested date, the script SHOULD print "No data for {date}" and exit cleanly.

### 4.4 Score Distribution Histogram

For quick visual assessment of score distributions:

```python
def ascii_histogram(values: list[float], bins: int = 10, width: int = 40) -> str:
    if not values:
        return "(no data)"
    # Bin values 0.0-1.0, produce ASCII bar chart
    ...
```

## 5. Bundle Drift Detection (Optional)

If a `launch-bundle.json` exists in `data/`, the script MAY compare current state against the frozen bundle:

```bash
python scripts/monitor_dashboard.py --date today --check-bundle
```

Drift checks:
- Current commit SHA vs `bundle.commit_sha`
- Current config hash vs bundle config snapshot hash
- Current document count vs `bundle.corpus_manifest.document_count`

This is a SHOULD, not a MUST. It adds value but is not required for launch.

## 6. No Infrastructure Requirement

The script uses only Python stdlib (`json`, `pathlib`, `datetime`, `statistics`, `sys`). No external dependencies. No database queries. No API calls. It reads local JSONL files that the running system already produces.

This satisfies the hard constraint: no new infrastructure.

## 7. Files to Create

| File | Change Type | Description |
|------|------------|-------------|
| `scripts/monitor_dashboard.py` | NEW | CLI monitoring dashboard script |

No existing files are modified. This is a pure addition.

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| JSONL files grow too large for script to parse efficiently | Low | Low | Script reads one file per day; typical size is <10MB/day |
| New trace fields break parsing | Low | Low | Script uses defensive `.get()` access; unknown fields are ignored |
| Script not run frequently enough | Medium | Medium | Team SHOULD add to cron or manual ops checklist; not a blocker for launch |
| Missing data for date with no requests | Low | None | Script prints "No data" and exits cleanly |
