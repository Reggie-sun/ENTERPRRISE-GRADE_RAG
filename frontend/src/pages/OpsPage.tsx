import { AlertTriangle, Clock3, Gauge, RefreshCw, ServerCog, Workflow } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, StatusPill } from '@/components';
import { formatApiError, getOpsSummary, type EventLogRecord, type OpsSummaryResponse } from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

function formatLocalTime(value: string | null): string {
  if (!value) {
    return '-';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString('zh-CN', { hour12: false });
}

function renderNullable(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
}

function renderEventSubtitle(record: EventLogRecord): string {
  const parts = [
    record.actor.username || '-',
    record.target_id || '-',
    record.mode || '-',
    record.duration_ms !== null ? `${record.duration_ms} ms` : '-',
  ];
  return parts.join(' / ');
}

export function OpsPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);
  const [summary, setSummary] = useState<OpsSummaryResponse | null>(null);

  useEffect(() => {
    const loadSummary = async () => {
      setStatus('loading');
      setError('');
      try {
        const payload = await getOpsSummary();
        setSummary(payload);
        setStatus('success');
      } catch (err) {
        setSummary(null);
        setStatus('error');
        setError(formatApiError(err, '运行态汇总'));
      }
    };

    void loadSummary();
  }, [refreshTick]);

  const queueTone = summary?.queue.available
    ? (summary.queue.backlog || 0) > 0
      ? 'warn'
      : 'ok'
    : 'error';
  const overallTone = status === 'error' ? 'error' : status === 'loading' ? 'warn' : 'ok';
  const categoryCards = useMemo(() => summary?.categories || [], [summary]);

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            Ops
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            先把系统什么时候开始变坏直观看出来，再继续补指标与追踪。
          </h2>
          <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
            这一页先聚合健康状态、队列积压、最近失败/降级与当前生效配置，让 v0.6 的运行侧能力不再只藏在日志和配置页里。
          </p>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前范围</h3>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前角色</strong>
              <p className="m-0 mt-2">{experience.roleLabel}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">部门边界</strong>
              <p className="m-0 mt-2 leading-relaxed">{scopeSummary}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">最近更新时间</strong>
              <p className="m-0 mt-2">{summary ? formatLocalTime(summary.checked_at) : '-'}</p>
            </div>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-12">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">运行态概览</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                先基于健康状态、最近事件日志窗口和当前配置做一个轻量驾驶舱，不伪装成正式 metrics 平台。
              </p>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill tone={overallTone}>
                {status === 'loading' ? '刷新中' : status === 'error' ? '汇总失败' : '运行态已加载'}
              </StatusPill>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setRefreshTick((value) => value + 1)}
                className="inline-flex items-center gap-2"
              >
                <RefreshCw className="h-4 w-4" />
                刷新
              </Button>
            </div>
          </div>

          {error && (
            <div className="mt-4 rounded-2xl bg-[rgba(177,67,46,0.08)] px-4 py-3 text-sm text-[rgb(147,43,26)]">
              {error}
            </div>
          )}

          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">总体健康</strong>
                <ServerCog className="h-4 w-4 text-accent-deep" />
              </div>
              <div className="mt-3">
                <StatusPill tone={summary?.health.status === 'ok' ? 'ok' : 'error'}>
                  {summary?.health.status || '-'}
                </StatusPill>
              </div>
              <p className="m-0 mt-3 text-sm text-ink-soft">
                {summary?.health.app_name || '未加载'}
              </p>
            </div>

            <div className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">队列积压</strong>
                <Workflow className="h-4 w-4 text-accent-deep" />
              </div>
              <div className="mt-3">
                <StatusPill tone={queueTone}>{summary?.queue.available ? '可探测' : '不可探测'}</StatusPill>
              </div>
              <p className="m-0 mt-3 text-sm text-ink-soft">
                backlog: {renderNullable(summary?.queue.backlog)}
              </p>
            </div>

            <div className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">最近失败</strong>
                <AlertTriangle className="h-4 w-4 text-accent-deep" />
              </div>
              <p className="m-0 mt-5 text-3xl font-serif text-ink">
                {renderNullable(summary?.recent_window.failed_count)}
              </p>
              <p className="m-0 mt-2 text-sm text-ink-soft">最近 {summary?.recent_window.sample_size || 0} 条事件窗口</p>
            </div>

            <div className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">最近降级</strong>
                <Gauge className="h-4 w-4 text-accent-deep" />
              </div>
              <p className="m-0 mt-5 text-3xl font-serif text-ink">
                {renderNullable(summary?.recent_window.downgraded_count)}
              </p>
              <p className="m-0 mt-2 text-sm text-ink-soft">accurate → fast / rerank → heuristic</p>
            </div>

            <div className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">P95 延迟</strong>
                <Clock3 className="h-4 w-4 text-accent-deep" />
              </div>
              <p className="m-0 mt-5 text-3xl font-serif text-ink">
                {summary?.recent_window.duration_p95_ms ?? '-'}
              </p>
              <p className="m-0 mt-2 text-sm text-ink-soft">
                p50 {renderNullable(summary?.recent_window.duration_p50_ms)} / p99 {renderNullable(summary?.recent_window.duration_p99_ms)}
              </p>
            </div>
          </div>

          {summary?.queue.error && (
            <div className="mt-4 rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-3 text-sm text-ink-soft">
              队列探测说明：{summary.queue.error}
            </div>
          )}
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-lg:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">依赖与当前配置</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            先看服务地址和当前生效模型，再判断“慢”是依赖问题、参数问题还是降级问题。
          </p>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">LLM</strong>
              <p className="m-0 mt-2">{summary?.health.llm.provider || '-'}</p>
              <p className="m-0 mt-1 break-all">{summary?.health.llm.model || '-'}</p>
              <p className="m-0 mt-1 break-all">{summary?.health.llm.base_url || '-'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">Embedding / Qdrant</strong>
              <p className="m-0 mt-2">{summary?.health.embedding.model || '-'}</p>
              <p className="m-0 mt-1 break-all">{summary?.health.embedding.base_url || '-'}</p>
              <p className="m-0 mt-1 break-all">{summary?.health.vector_store.collection || '-'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">模型路由</strong>
              <p className="m-0 mt-2">fast: {summary?.config.model_routing.fast_model || '-'}</p>
              <p className="m-0 mt-1">accurate: {summary?.config.model_routing.accurate_model || '-'}</p>
              <p className="m-0 mt-1">sop: {summary?.config.model_routing.sop_generation_model || '-'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">降级与重试</strong>
              <p className="m-0 mt-2">rerank fallback: {summary?.config.degrade_controls.rerank_fallback_enabled ? 'on' : 'off'}</p>
              <p className="m-0 mt-1">accurate → fast: {summary?.config.degrade_controls.accurate_to_fast_fallback_enabled ? 'on' : 'off'}</p>
              <p className="m-0 mt-1">retrieval fallback: {summary?.config.degrade_controls.retrieval_fallback_enabled ? 'on' : 'off'}</p>
              <p className="m-0 mt-1">retry: {summary?.config.retry_controls.llm_retry_enabled ? `${summary.config.retry_controls.llm_retry_max_attempts} 次 / ${summary.config.retry_controls.llm_retry_backoff_ms}ms` : 'off'}</p>
            </div>
          </div>
        </Card>

        <Card className="col-span-5 max-lg:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">分类汇总</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            用最近事件窗口先判断是问答、文档还是 SOP 链路在掉线或变慢。
          </p>

          <div className="mt-4 grid gap-3">
            {categoryCards.map((item) => (
              <div key={item.category} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
                <div className="flex items-center justify-between gap-3">
                  <strong className="text-ink">{item.category}</strong>
                  <StatusPill tone={item.failed_count > 0 ? 'error' : item.total > 0 ? 'ok' : 'default'}>
                    {item.total > 0 ? `${item.total} 条` : '暂无'}
                  </StatusPill>
                </div>
                <p className="m-0 mt-2">failed {item.failed_count} / timeout {item.timeout_count} / downgraded {item.downgraded_count}</p>
                <p className="m-0 mt-1">last event: {formatLocalTime(item.last_event_at)}</p>
                <p className="m-0 mt-1">last failed: {formatLocalTime(item.last_failed_at)}</p>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-6 max-lg:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">最近失败事件</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            这里只放最新几条失败，详细定位继续去日志页。
          </p>

          <div className="mt-4 grid gap-3">
            {!summary?.recent_failures.length && (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-5 text-sm text-ink-soft">
                最近窗口内没有失败事件。
              </div>
            )}
            {summary?.recent_failures.map((record) => (
              <div key={record.event_id} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
                <div className="flex items-center justify-between gap-3">
                  <strong className="text-ink">{record.category}.{record.action}</strong>
                  <StatusPill tone="error">failed</StatusPill>
                </div>
                <p className="m-0 mt-2">{renderEventSubtitle(record)}</p>
                <p className="m-0 mt-1">{formatLocalTime(record.occurred_at)}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card className="col-span-6 max-lg:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">最近降级事件</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            先看系统最近有没有靠降级兜住，如果频率开始上升，就说明该进下一步优化了。
          </p>

          <div className="mt-4 grid gap-3">
            {!summary?.recent_degraded.length && (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-5 text-sm text-ink-soft">
                最近窗口内没有降级事件。
              </div>
            )}
            {summary?.recent_degraded.map((record) => (
              <div key={record.event_id} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
                <div className="flex items-center justify-between gap-3">
                  <strong className="text-ink">{record.category}.{record.action}</strong>
                  <StatusPill tone="warn">{record.downgraded_from || 'degraded'}</StatusPill>
                </div>
                <p className="m-0 mt-2">{renderEventSubtitle(record)}</p>
                <p className="m-0 mt-1">{formatLocalTime(record.occurred_at)}</p>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
