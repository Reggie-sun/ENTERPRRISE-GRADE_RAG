# Feature Spec: F-008 - Monitoring Dashboard

**Priority**: Low (MAY be deferred to post-launch)
**Contributing Roles**: system-architect (lead), product-manager, data-architect
**Status**: Draft (from synthesis)

---

## 1. Requirements Summary

The system MUST provide a CLI script that analyzes existing event_log and request_trace JSONL files to produce a human-readable health summary, without introducing any new infrastructure.

- The script MUST parse `data/event_logs/YYYY-MM-DD.jsonl` and `data/request_traces/YYYY-MM-DD.jsonl`
- The script MUST handle both old traces (pre-F-001/F-007) and new traces gracefully
- The script MUST use only Python stdlib (no external dependencies)
- Alert thresholds MUST be unified across all roles (EP-005)
- The script MAY support bundle drift detection against `launch-bundle.json`

## 2. Design Decisions

### 2.1 Unified Alert Thresholds (RESOLVED via EP-005)

**Decision**: Single threshold table agreed across system-architect, product-manager, and data-architect.

**Threshold table**:

| Metric | WARNING | CRITICAL | Source Role |
|--------|---------|----------|-------------|
| Error rate | 2% (data-architect) | 5% (sys-architect) | Merged |
| Gate trigger rate | 30% (sys-architect) | 40% (product-manager) | Merged |
| P95 latency | 10s (sys-architect) | 15s (product-manager) | Merged |
| Zero-result rate | 5% (data-architect) | — | data-architect only |
| Kill switch active | any > 0 | any > 0 | All roles |
| Timeout rate | 2% (data-architect) | — | data-architect only |

**Rationale**: data-architect's stricter error rate (2%) as WARNING, sys-architect's (5%) as CRITICAL. Product-manager's gate trigger (40%) as CRITICAL, sys-architect's (30%) as WARNING.

### 2.2 Output Format

**Decision**: Plain text to stdout, suitable for terminal or piping to file. Optional `--json` flag for machine-readable output.

**Sections**:
1. Chat metrics (total, success/error rate, latency)
2. Response mode distribution (rag, retrieval_fallback, no_context, evidence_gate_abstain, kill_switch)
3. Evidence gate metrics (trigger rate, score distribution) — post F-001
4. Retrieval metrics (top1 score, supplemental trigger rate)
5. Alerts (threshold violations)

### 2.3 Bundle Drift Detection (Optional)

**Decision**: `--check-bundle` flag compares current state against `data/launch-bundle.json`.

**Checks**:
- Current commit SHA vs bundle commit_sha
- Current config hash vs bundle config snapshot hash
- Current document count vs bundle corpus manifest count

**Priority**: SHOULD for v1, not MUST.

## 3. Interface Contract

### 3.1 CLI Interface

```bash
python scripts/monitor_dashboard.py --date today
python scripts/monitor_dashboard.py --date 2026-04-07
python scripts/monitor_dashboard.py --hours 6
python scripts/monitor_dashboard.py --compare 2026-04-06 2026-04-07
python scripts/monitor_dashboard.py --date today --check-bundle
python scripts/monitor_dashboard.py --date today --json
```

### 3.2 JSON Output Schema (optional)

```json
{
  "date": "2026-04-07",
  "chat": {
    "total": 142,
    "success_rate": 0.972,
    "error_rate": 0.028,
    "avg_latency_ms": 3200,
    "p95_latency_ms": 8100
  },
  "mode_distribution": {
    "rag": 89, "retrieval_fallback": 18,
    "no_context": 22, "evidence_gate_abstain": 11, "kill_switch": 0
  },
  "evidence_gate": {
    "trigger_rate": 0.124,
    "avg_top1_score": 0.78,
    "below_threshold_count": 11
  },
  "alerts": ["[WARN] Error rate above 2% threshold"]
}
```

## 4. Constraints & Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| JSONL files grow large | Low | Low | Script reads one day at a time; typical <10MB/day |
| New trace fields break parsing | Low | Low | Defensive `.get()` access; unknown fields ignored |
| Script not run frequently | Medium | Medium | Add to ops checklist; MAY add cron in future |
| Missing data for date | Low | None | Print "No data" and exit cleanly |

## 5. Acceptance Criteria

1. `monitor_dashboard.py --date today` produces formatted health summary with all 5 sections
2. Malformed JSONL lines are skipped with warning (not crash)
3. Old traces without evidence_gate_result fields are handled gracefully
4. Alert thresholds match unified table from EP-005
5. `--check-bundle` flag detects commit, config, and corpus drift against launch-bundle.json
6. No external dependencies (only Python stdlib)

## 6. Detailed Analysis References

- @../system-architect/analysis-F-008-monitoring-dashboard.md
- @../data-architect/analysis-F-008-monitoring-dashboard.md
- @../product-manager/analysis-cross-cutting.md (monitoring expectations)

## 7. Cross-Feature Dependencies

- **Depends on**: F-001 (evidence gate adds trace fields), F-007 (kill switch adds mode)
- **Required by**: None (observability is standalone)
- **Shared patterns**: Reads same JSONL files as eval framework (F-003)
- **Integration points**: Alert thresholds inform go/no-go decision in F-004
