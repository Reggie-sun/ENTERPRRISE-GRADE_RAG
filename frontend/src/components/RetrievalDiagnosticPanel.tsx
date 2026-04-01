/**
 * 检索诊断面板
 * 渲染检索诊断的 5 个区块：Query & Routing、Primary Recall、Supplemental Recall、Filter Summary、Result Explainability
 */

import { StatusPill } from './StatusPill';
import type {
  RetrievalDiagnostic,
  RetrievalQueryStage,
  RetrievalRoutingStage,
  RetrievalPrimaryRecallStage,
  RetrievalSupplementalRecallStage,
  RetrievalFilterStage,
  ResultExplainability,
  FilteredCandidateSummary,
  RetrievalFinalizationStage,
} from '@/api';

// ---------- 中文标签映射 ----------

const QUERY_TYPE_TEXT: Record<string, string> = {
  keyword: '关键词',
  semantic: '语义',
  hybrid_query: '混合查询',
  structured: '结构化',
  unknown: '未知',
};

const QUERY_GRANULARITY_TEXT: Record<string, string> = {
  coarse: '粗粒度',
  medium: '中粒度',
  fine: '细粒度',
};

const SELECTED_VIA_TEXT: Record<string, string> = {
  department: '本部门',
  supplemental: '补充检索',
  global: '全局',
  both: '双重命中',
};

const SOURCE_SCOPE_TEXT: Record<string, string> = {
  department: '本部门',
  global: '全局',
  both: '双重命中',
};

const FILTER_LAYER_TEXT: Record<string, string> = {
  ocr_governance: 'OCR 质量',
  permission_check: '权限过滤',
  scope_check: '范围过滤',
  top_k: 'Top K 截断',
};

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function pickCount(record: Record<string, number> | undefined, ...keys: string[]) {
  if (!record) return 0;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number') return value;
  }
  return 0;
}

function normalizeQueryStage(diagnostic: RetrievalDiagnostic): RetrievalQueryStage {
  return diagnostic.query_stage ?? {
    raw_query: diagnostic.query,
    normalized_query: null,
    query_type: diagnostic.query_type,
    query_granularity: diagnostic.query_granularity ?? null,
    requested_mode: null,
    effective_mode: diagnostic.retrieval_mode,
  };
}

function normalizeRoutingStage(diagnostic: RetrievalDiagnostic): RetrievalRoutingStage {
  const weights = diagnostic.branch_weights ?? {};
  return diagnostic.routing_stage ?? {
    is_hybrid: diagnostic.retrieval_mode === 'hybrid',
    vector_weight: asNumber((weights as Record<string, unknown>).vector_weight),
    lexical_weight: asNumber((weights as Record<string, unknown>).lexical_weight),
    is_document_id_exact: diagnostic.document_id_filter_applied,
    department_priority_enabled: diagnostic.department_priority_enabled,
    structured_routing_applied: Boolean(diagnostic.structured_routing_applied),
  };
}

function normalizePrimaryRecallStage(diagnostic: RetrievalDiagnostic): RetrievalPrimaryRecallStage {
  const counts = diagnostic.recall_counts;
  const effectiveCount =
    diagnostic.primary_effective_count ??
    pickCount(counts, 'department_effective_count', 'effective_count', 'total_candidates', 'department_fused_count') ??
    0;
  const threshold = diagnostic.primary_threshold;
  return diagnostic.primary_recall_stage ?? {
    vector_count: pickCount(counts, 'department_vector_count', 'vector_count'),
    lexical_count: pickCount(counts, 'department_lexical_count', 'lexical_count'),
    fused_count: pickCount(counts, 'department_fused_count', 'fused_count', 'total_candidates'),
    effective_count: effectiveCount,
    threshold,
    whether_sufficient: threshold == null ? !diagnostic.supplemental_triggered : effectiveCount >= threshold,
  };
}

function normalizeSupplementalRecallStage(
  diagnostic: RetrievalDiagnostic,
): RetrievalSupplementalRecallStage {
  const counts = diagnostic.recall_counts;
  return diagnostic.supplemental_recall_stage ?? {
    triggered: diagnostic.supplemental_triggered,
    reason: diagnostic.supplemental_reason,
    vector_count: pickCount(counts, 'supplemental_vector_count'),
    lexical_count: pickCount(counts, 'supplemental_lexical_count'),
    fused_count: pickCount(counts, 'supplemental_fused_count'),
  };
}

function normalizeFilterStage(diagnostic: RetrievalDiagnostic): RetrievalFilterStage {
  const counts = diagnostic.filter_counts;
  const filteredCandidates: FilteredCandidateSummary[] =
    diagnostic.filter_stage?.filtered_candidates ?? diagnostic.filtered_candidates ?? [];
  return diagnostic.filter_stage ?? {
    ocr_quality_filtered_count: pickCount(counts, 'ocr_quality_filtered_count', 'ocr_quality_filtered'),
    permission_filtered_count: pickCount(counts, 'permission_filtered_count', 'permission_filtered'),
    document_scope_filtered_count: pickCount(
      counts,
      'document_scope_filtered_count',
      'document_scope_filtered',
    ),
    top_k_truncated_count: pickCount(counts, 'top_k_truncated_count', 'top_k_truncated'),
    filtered_candidates: filteredCandidates,
  };
}

function normalizeFinalizationStage(diagnostic: RetrievalDiagnostic): RetrievalFinalizationStage {
  return diagnostic.finalization_stage ?? {
    final_result_count: diagnostic.final_result_count,
    returned_top_k: diagnostic.final_result_count,
    response_mode: diagnostic.retrieval_mode,
    backfilled_chunk_count: diagnostic.backfilled_chunk_count ?? 0,
    result_explanations: diagnostic.result_explainability ?? [],
  };
}

// ---------- 子组件 ----------

function DiagBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.8)] p-4">
      <h4 className="m-0 text-base font-semibold text-ink">{title}</h4>
      <div className="mt-3 grid gap-2">{children}</div>
    </div>
  );
}

function DiagRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-ink-soft">{label}</span>
      <span className="text-ink font-medium">{value}</span>
    </div>
  );
}

function DiagMetric({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-1 text-xs text-ink-soft">
      {label} {typeof value === 'number' ? value.toFixed(4) : value}
    </span>
  );
}

// ---------- 5 个诊断区块 ----------

function QueryRoutingBlock({ stage }: { stage: RetrievalQueryStage }) {
  return (
    <DiagBlock title="查询解析与路由">
      <DiagRow label="原始查询" value={stage.raw_query || '-'} />
      {stage.normalized_query && stage.normalized_query !== stage.raw_query && (
        <DiagRow label="标准化查询" value={stage.normalized_query} />
      )}
      <DiagRow
        label="查询类型"
        value={stage.query_type ? (QUERY_TYPE_TEXT[stage.query_type] || stage.query_type) : '-'}
      />
      <DiagRow
        label="查询粒度"
        value={stage.query_granularity ? (QUERY_GRANULARITY_TEXT[stage.query_granularity] || stage.query_granularity) : '-'}
      />
      <DiagRow label="请求模式" value={stage.requested_mode || '-'} />
      <DiagRow label="实际模式" value={stage.effective_mode || '-'} />
    </DiagBlock>
  );
}

function RoutingDetailBlock({ stage }: { stage: RetrievalRoutingStage }) {
  return (
    <DiagBlock title="检索路由策略">
      <div className="flex flex-wrap gap-2">
        <StatusPill tone={stage.is_hybrid ? 'ok' : 'default'}>
          {stage.is_hybrid ? 'Hybrid 混合检索' : '向量检索'}
        </StatusPill>
        {stage.department_priority_enabled && (
          <StatusPill tone="ok">部门优先</StatusPill>
        )}
        {stage.is_document_id_exact && (
          <StatusPill tone="default">文档精确匹配</StatusPill>
        )}
        {stage.structured_routing_applied && (
          <StatusPill tone="default">结构化路由</StatusPill>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {stage.vector_weight !== null && stage.vector_weight !== undefined && (
          <DiagMetric label="向量权重" value={stage.vector_weight} />
        )}
        {stage.lexical_weight !== null && stage.lexical_weight !== undefined && (
          <DiagMetric label="词法权重" value={stage.lexical_weight} />
        )}
      </div>
    </DiagBlock>
  );
}

function PrimaryRecallBlock({ stage }: { stage: RetrievalPrimaryRecallStage }) {
  return (
    <DiagBlock title="主路召回（本部门 / 主池）">
      <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
        <DiagRow label="向量召回" value={stage.vector_count} />
        <DiagRow label="词法召回" value={stage.lexical_count} />
        <DiagRow label="融合后" value={stage.fused_count} />
      </div>
      <DiagRow label="有效结果数" value={stage.effective_count} />
      {stage.threshold !== null && stage.threshold !== undefined && (
        <DiagRow label="阈值" value={stage.threshold} />
      )}
      <DiagRow
        label="是否充足"
        value={
          <StatusPill tone={stage.whether_sufficient ? 'ok' : 'warn'}>
            {stage.whether_sufficient ? '充足' : '不足，触发补充检索'}
          </StatusPill>
        }
      />
    </DiagBlock>
  );
}

function SupplementalRecallBlock({ stage }: { stage: RetrievalSupplementalRecallStage }) {
  return (
    <DiagBlock title="补充召回（跨部门）">
      <div className="flex flex-wrap gap-2 mb-2">
        <StatusPill tone={stage.triggered ? 'warn' : 'ok'}>
          {stage.triggered ? '已触发' : '未触发'}
        </StatusPill>
      </div>
      {stage.reason && <DiagRow label="触发原因" value={stage.reason} />}
      {stage.triggered && (
        <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
          <DiagRow label="向量召回" value={stage.vector_count} />
          <DiagRow label="词法召回" value={stage.lexical_count} />
          <DiagRow label="融合后" value={stage.fused_count} />
        </div>
      )}
    </DiagBlock>
  );
}

function FilterSummaryBlock({ stage }: { stage: RetrievalFilterStage }) {
  const hasAnyFilter =
    stage.ocr_quality_filtered_count > 0 ||
    stage.permission_filtered_count > 0 ||
    stage.document_scope_filtered_count > 0 ||
    stage.top_k_truncated_count > 0;

  return (
    <DiagBlock title="过滤摘要">
      <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
        <DiagRow
          label="OCR 质量过滤"
          value={
            <span className={stage.ocr_quality_filtered_count > 0 ? 'text-accent-deep' : ''}>
              {stage.ocr_quality_filtered_count}
            </span>
          }
        />
        <DiagRow
          label="权限过滤"
          value={
            <span className={stage.permission_filtered_count > 0 ? 'text-accent-deep' : ''}>
              {stage.permission_filtered_count}
            </span>
          }
        />
        <DiagRow
          label="范围过滤"
          value={
            <span className={stage.document_scope_filtered_count > 0 ? 'text-accent-deep' : ''}>
              {stage.document_scope_filtered_count}
            </span>
          }
        />
        <DiagRow
          label="Top K 截断"
          value={
            <span className={stage.top_k_truncated_count > 0 ? 'text-accent-deep' : ''}>
              {stage.top_k_truncated_count}
            </span>
          }
        />
      </div>
      {!hasAnyFilter && (
        <p className="m-0 mt-2 text-sm text-ink-soft">本条检索请求没有被过滤的候选。</p>
      )}
      {stage.filtered_candidates.length > 0 && (
        <div className="mt-3">
          <p className="m-0 text-[11px] font-medium uppercase tracking-[0.18em] text-ink-soft">
            被过滤候选明细（最多显示前 10 条）
          </p>
          <div className="mt-2 grid gap-1">
            {stage.filtered_candidates.slice(0, 10).map((fc, i) => (
              <div
                key={`${fc.chunk_id}-${i}`}
                className="flex items-center gap-2 text-xs text-ink-soft"
              >
                <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-0.5">
                  {FILTER_LAYER_TEXT[fc.filter_layer] || fc.filter_layer}
                </span>
                <span className="truncate">{fc.document_id || fc.chunk_id}</span>
                <span className="text-ink-soft/60">{fc.filter_reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </DiagBlock>
  );
}

const STRUCTURED_BACKFILL_REASON_TEXT: Record<string, string> = {
  coarse_granularity_fallback: '粗粒度回退',
  document_level_backfill: '文档级回填',
  chunk_level_backfill: '片段级回填',
};

function StructuredRetrievalBlock({ diagnostic }: { diagnostic: RetrievalDiagnostic }) {
  const qs = normalizeQueryStage(diagnostic);
  const rs = normalizeRoutingStage(diagnostic);
  const fs = normalizeFinalizationStage(diagnostic);

  // 只有当存在结构化路由信号时才展示
  const hasGranularity = qs.query_granularity != null;
  const hasStructuredRouting = rs.structured_routing_applied;
  const hasBackfill = fs.backfilled_chunk_count != null && fs.backfilled_chunk_count > 0;
  if (!hasGranularity && !hasStructuredRouting && !hasBackfill) return null;

  return (
    <DiagBlock title="结构化检索诊断">
      {hasGranularity && (
        <DiagRow
          label="查询粒度"
          value={QUERY_GRANULARITY_TEXT[qs.query_granularity!] || qs.query_granularity}
        />
      )}
      <DiagRow
        label="结构化路由"
        value={
          <StatusPill tone={hasStructuredRouting ? 'ok' : 'default'}>
            {hasStructuredRouting ? '已应用' : '未应用'}
          </StatusPill>
        }
      />
      {hasBackfill && (
        <DiagRow label="回填片段数" value={fs.backfilled_chunk_count} />
      )}
    </DiagBlock>
  );
}

function ResultExplainabilityBlock({ items }: { items: ResultExplainability[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <DiagBlock title="结果可解释性">
      <div className="grid gap-3">
        {items.map((item) => (
          <div
            key={`${item.chunk_id}-${item.rank}`}
            className="rounded-xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.55)] p-3"
          >
            <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-[rgba(23,32,42,0.08)] text-xs font-bold text-ink">
                  {item.rank}
                </span>
                <span className="text-sm font-medium text-ink truncate max-w-[280px]">
                  {item.document_name || item.chunk_id}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {item.selected_via && (
                  <StatusPill tone={
                    item.selected_via === 'department' ? 'ok'
                    : item.selected_via === 'both' ? 'ok'
                    : item.selected_via === 'supplemental' ? 'warn'
                    : 'default'
                  }>
                    {SELECTED_VIA_TEXT[item.selected_via] || item.selected_via}
                  </StatusPill>
                )}
                {item.source_scope && item.source_scope !== item.selected_via && (
                  <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-0.5 text-xs text-ink-soft">
                    范围: {SOURCE_SCOPE_TEXT[item.source_scope] || item.source_scope}
                  </span>
                )}
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <DiagMetric label="向量分" value={item.vector_score} />
              <DiagMetric label="词法分" value={item.lexical_score} />
              <DiagMetric label="融合分" value={item.fused_score} />
              <DiagMetric label="最终分" value={item.final_score} />
            </div>
            {item.why_included && (
              <p className="m-0 mt-2 text-sm text-ink-soft">{item.why_included}</p>
            )}
            {item.structured_backfill && (
              <div className="mt-2 flex items-center gap-2">
                <StatusPill tone="default">结构化回填</StatusPill>
                {item.structured_backfill_reason && (
                  <span className="text-xs text-ink-soft">
                    {STRUCTURED_BACKFILL_REASON_TEXT[item.structured_backfill_reason] || item.structured_backfill_reason}
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </DiagBlock>
  );
}

// ---------- 主面板 ----------

interface RetrievalDiagnosticPanelProps {
  diagnostic: RetrievalDiagnostic;
}

export function RetrievalDiagnosticPanel({ diagnostic }: RetrievalDiagnosticPanelProps) {
  const qs = normalizeQueryStage(diagnostic);
  const rs = normalizeRoutingStage(diagnostic);
  const prs = normalizePrimaryRecallStage(diagnostic);
  const srs = normalizeSupplementalRecallStage(diagnostic);
  const fs = normalizeFilterStage(diagnostic);
  const finalization = normalizeFinalizationStage(diagnostic);
  const explainItems = diagnostic.result_explainability ?? finalization.result_explanations;

  return (
    <div className="mt-6 grid gap-3">
      <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
        <div>
          <h3 className="m-0 text-lg font-semibold text-ink">检索诊断</h3>
          <p className="m-0 mt-1 text-sm text-ink-soft">
            查看本次检索的完整管线状态与结果可解释性。
          </p>
        </div>
        <StatusPill tone="default">
          {diagnostic.retrieval_mode || 'unknown'}
        </StatusPill>
      </div>

      {/* Block 1: Query & Routing */}
      <QueryRoutingBlock stage={qs} />
      <RoutingDetailBlock stage={rs} />

      {/* Block 2: Primary Recall */}
      <PrimaryRecallBlock stage={prs} />

      {/* Block 3: Supplemental Recall */}
      <SupplementalRecallBlock stage={srs} />

      {/* Block 4: Filter Summary */}
      <FilterSummaryBlock stage={fs} />

      {/* Structured Retrieval Diagnostics (有则展示) */}
      <StructuredRetrievalBlock diagnostic={diagnostic} />

      {/* Block 5: Result Explainability */}
      <ResultExplainabilityBlock items={explainItems} />

      {/* Stage durations */}
      {Object.keys(diagnostic.stage_durations_ms ?? {}).length > 0 && (
        <DiagBlock title="阶段耗时">
          <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
            {Object.entries(diagnostic.stage_durations_ms ?? {}).map(([stage, ms]) => (
              <DiagRow key={stage} label={stage} value={`${ms} ms`} />
            ))}
          </div>
        </DiagBlock>
      )}
    </div>
  );
}
