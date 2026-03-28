import { StatusPill } from './StatusPill';

export interface StreamProgressMetrics {
  startedAt: number | null;
  firstDeltaAt: number | null;
  lastDeltaAt: number | null;
  completedAt: number | null;
  deltaCount: number;
  charCount: number;
}

interface StreamProgressSummaryProps {
  status: 'idle' | 'loading' | 'success' | 'error';
  metrics: StreamProgressMetrics;
  compact?: boolean;
}

function formatDuration(ms: number | null): string {
  if (ms === null || Number.isNaN(ms) || ms < 0) {
    return '-';
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 10_000) {
    return `${(ms / 1000).toFixed(1)} s`;
  }
  return `${Math.round(ms / 1000)} s`;
}

function resolvePhaseTone(status: StreamProgressSummaryProps['status']) {
  if (status === 'success') {
    return 'ok';
  }
  if (status === 'error') {
    return 'error';
  }
  if (status === 'loading') {
    return 'warn';
  }
  return 'default';
}

function resolvePhaseLabel(
  status: StreamProgressSummaryProps['status'],
  metrics: StreamProgressMetrics,
): string {
  if (status === 'loading') {
    return metrics.firstDeltaAt ? '持续生成中' : '等待首包';
  }
  if (status === 'success') {
    return '流式完成';
  }
  if (status === 'error') {
    return metrics.deltaCount > 0 ? '流式中断' : '请求失败';
  }
  return '未开始';
}

export function StreamProgressSummary({
  status,
  metrics,
  compact = false,
}: StreamProgressSummaryProps) {
  if (!metrics.startedAt && status === 'idle' && metrics.deltaCount === 0) {
    return null;
  }

  const firstPacketMs = metrics.startedAt !== null && metrics.firstDeltaAt !== null
    ? metrics.firstDeltaAt - metrics.startedAt
    : null;
  const totalMs = metrics.startedAt !== null
    ? (metrics.completedAt ?? metrics.lastDeltaAt ?? Date.now()) - metrics.startedAt
    : null;
  const phaseLabel = resolvePhaseLabel(status, metrics);
  const phaseTone = resolvePhaseTone(status);

  if (compact) {
    return (
      <div className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.74)] px-4 py-3">
        <div className="flex flex-wrap items-center gap-3 text-sm text-ink-soft">
          <StatusPill tone={phaseTone}>{phaseLabel}</StatusPill>
          <span>首包：{firstPacketMs === null ? '等待首包' : formatDuration(firstPacketMs)}</span>
          <span>片段：{metrics.deltaCount}</span>
          <span>字符：{metrics.charCount}</span>
          <span>耗时：{formatDuration(totalMs)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.74)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="m-0 text-sm font-semibold text-ink">流式进度</h4>
          <p className="m-0 mt-1 text-sm text-ink-soft">首包、增量片段和字符数会随着流式返回同步更新。</p>
        </div>
        <StatusPill tone={phaseTone}>{phaseLabel}</StatusPill>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <div className="rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-soft">首包耗时</div>
          <div className="mt-1 text-sm font-semibold text-ink">
            {firstPacketMs === null ? '等待首包' : formatDuration(firstPacketMs)}
          </div>
        </div>
        <div className="rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-soft">增量片段</div>
          <div className="mt-1 text-sm font-semibold text-ink">{metrics.deltaCount}</div>
        </div>
        <div className="rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-soft">已接收字符</div>
          <div className="mt-1 text-sm font-semibold text-ink">{metrics.charCount}</div>
        </div>
        <div className="rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-soft">总耗时</div>
          <div className="mt-1 text-sm font-semibold text-ink">{formatDuration(totalMs)}</div>
        </div>
      </div>
    </div>
  );
}
