import { AlertTriangle, Clock3, Gauge, RefreshCw, RotateCcw, Route, ServerCog, Workflow } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, StatusPill } from '@/components';
import {
  formatApiError,
  getOpsSummary,
  replayRequestSnapshot,
  type EventLogRecord,
  type OpsSummaryResponse,
  type RequestSnapshotRecord,
  type RequestSnapshotReplayMode,
  type RequestSnapshotReplayResponse,
  type RequestTraceRecord,
} from '@/api';

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

function renderTraceSubtitle(record: RequestTraceRecord): string {
  const parts = [
    record.actor.username || '-',
    record.mode || '-',
    record.total_duration_ms !== null ? `${record.total_duration_ms} ms` : '-',
    record.response_mode || '-',
  ];
  return parts.join(' / ');
}

function traceTone(record: RequestTraceRecord): 'ok' | 'warn' | 'error' | 'default' {
  if (record.outcome === 'failed') {
    return 'error';
  }
  if (record.downgraded_from) {
    return 'warn';
  }
  return 'ok';
}

function snapshotPrompt(snapshot: RequestSnapshotRecord): string {
  if ('question' in snapshot.request) {
    return snapshot.request.question;
  }
  if ('topic' in snapshot.request) {
    const topic = snapshot.request.topic;
    const processName = snapshot.request.process_name || '未指定工序';
    const scenarioName = snapshot.request.scenario_name || '未指定场景';
    return `按主题生成 SOP：${topic} / ${processName} / ${scenarioName}`;
  }
  if ('scenario_name' in snapshot.request && !('document_id' in snapshot.request)) {
    const processName = snapshot.request.process_name || '未指定工序';
    return `按场景生成 SOP：${processName} / ${snapshot.request.scenario_name}`;
  }
  if ('document_id' in snapshot.request) {
    return `根据文档 ${snapshot.request.document_id} 生成 SOP 草稿`;
  }
  return '未识别的请求快照';
}

function snapshotPreviewLabel(snapshot: RequestSnapshotRecord): string {
  return snapshot.category === 'sop_generation' ? '草稿预览' : '答案预览';
}

function replayResponseMode(response: RequestSnapshotReplayResponse['response']): string {
  return 'mode' in response ? response.mode : response.generation_mode;
}

function replayResponseContent(response: RequestSnapshotReplayResponse['response']): string {
  return 'answer' in response ? response.answer : response.content;
}

export function OpsPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);
  const [summary, setSummary] = useState<OpsSummaryResponse | null>(null);
  const [replayStatusBySnapshotId, setReplayStatusBySnapshotId] = useState<Record<string, PanelStatus>>({});
  const [replayErrorBySnapshotId, setReplayErrorBySnapshotId] = useState<Record<string, string>>({});
  const [replayResultBySnapshotId, setReplayResultBySnapshotId] = useState<Record<string, RequestSnapshotReplayResponse>>({});

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

  const triggerReplay = async (snapshotId: string, replayMode: RequestSnapshotReplayMode) => {
    setReplayStatusBySnapshotId((current) => ({ ...current, [snapshotId]: 'loading' }));
    setReplayErrorBySnapshotId((current) => ({ ...current, [snapshotId]: '' }));
    try {
      const payload = await replayRequestSnapshot(snapshotId, { replay_mode: replayMode });
      setReplayResultBySnapshotId((current) => ({ ...current, [snapshotId]: payload }));
      setReplayStatusBySnapshotId((current) => ({ ...current, [snapshotId]: 'success' }));
    } catch (err) {
      setReplayStatusBySnapshotId((current) => ({ ...current, [snapshotId]: 'error' }));
      setReplayErrorBySnapshotId((current) => ({
        ...current,
        [snapshotId]: formatApiError(err, replayMode === 'original' ? '原样重放' : '当前配置重放'),
      }));
    }
  };

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
        <Card className="col-span-12">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">在线并发通道</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                这里直接展示 fast / accurate / SOP 生成三条通道的实时占用、上限和剩余槽位，同时补一层单用户上限，避免一个人把在线资源全吃满。
              </p>
            </div>
            <StatusPill tone="ok">
              acquire {summary?.runtime_gate.acquire_timeout_ms ?? '-'} ms / retry {summary?.runtime_gate.busy_retry_after_seconds ?? '-'} s / per-user {summary?.runtime_gate.per_user_online_max_inflight ?? '-'}
            </StatusPill>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">单用户上限</strong>
              <p className="m-0 mt-2 text-3xl font-serif text-ink">
                {summary?.runtime_gate.per_user_online_max_inflight ?? '-'}
              </p>
              <p className="m-0 mt-2">同一用户最多同时占用的在线请求槽位</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">活跃用户数</strong>
              <p className="m-0 mt-2 text-3xl font-serif text-ink">
                {summary?.runtime_gate.active_users ?? '-'}
              </p>
              <p className="m-0 mt-2">当前正在占用在线通道的用户数量</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm text-ink-soft">
              <strong className="block text-ink">单用户峰值</strong>
              <p className="m-0 mt-2 text-3xl font-serif text-ink">
                {summary?.runtime_gate.max_user_inflight ?? '-'}
              </p>
              <p className="m-0 mt-2">当前快照里同一用户实际占用的最大槽位</p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {(summary?.runtime_gate.channels || []).map((channel) => {
              const tone = channel.available_slots === 0 ? 'error' : channel.available_slots <= 2 ? 'warn' : 'ok';
              const label = channel.channel === 'chat_fast'
                ? 'fast 问答'
                : channel.channel === 'chat_accurate'
                  ? 'accurate 问答'
                  : 'SOP 生成';
              return (
                <div key={channel.channel} className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.82)] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <strong className="text-ink">{label}</strong>
                    <StatusPill tone={tone}>
                      {channel.available_slots > 0 ? '可用' : '已打满'}
                    </StatusPill>
                  </div>
                  <p className="m-0 mt-4 text-3xl font-serif text-ink">
                    {channel.inflight} / {channel.limit}
                  </p>
                  <p className="m-0 mt-2 text-sm text-ink-soft">
                    available slots: {channel.available_slots}
                  </p>
                </div>
              );
            })}
          </div>
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
              <div className="flex items-center justify-between gap-3">
                <strong className="block text-ink">OCR</strong>
                <StatusPill tone={summary?.health.ocr.ready ? 'ok' : summary?.health.ocr.enabled ? 'error' : 'default'}>
                  {summary?.health.ocr.ready ? 'ready' : summary?.health.ocr.enabled ? 'not ready' : 'disabled'}
                </StatusPill>
              </div>
              <p className="m-0 mt-2">{summary?.health.ocr.provider || '-'}</p>
              <p className="m-0 mt-1">lang: {summary?.health.ocr.language || '-'}</p>
              <p className="m-0 mt-1">pdf fallback threshold: {summary?.health.ocr.pdf_native_text_min_chars ?? '-'} chars</p>
              <p className="m-0 mt-1">angle cls: {summary?.health.ocr.angle_cls_enabled ? 'on' : 'off'}</p>
              <p className="m-0 mt-1 leading-relaxed">{summary?.health.ocr.detail || '-'}</p>
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
              <p className="m-0 mt-1">gate timeout: {summary?.config.concurrency_controls.acquire_timeout_ms ?? '-'} ms</p>
              <p className="m-0 mt-1">retry-after: {summary?.config.concurrency_controls.busy_retry_after_seconds ?? '-'} s</p>
              <p className="m-0 mt-1">per-user limit: {summary?.config.concurrency_controls.per_user_online_max_inflight ?? '-'} </p>
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
        <Card className="col-span-12">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">最近请求 Trace</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                先把 chat 的最小链路 trace 收进来：`query_rewrite → retrieval → rerank → llm → answer`。
              </p>
            </div>
            <StatusPill tone={summary?.recent_traces.length ? 'ok' : 'default'}>
              {summary?.recent_traces.length ? `${summary.recent_traces.length} 条` : '暂无'}
            </StatusPill>
          </div>

          <div className="mt-4 grid gap-3">
            {(summary?.recent_traces || []).map((trace) => (
              <div key={trace.trace_id} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Route className="h-4 w-4 text-accent-deep" />
                      <strong className="text-ink">{trace.action}</strong>
                      <StatusPill tone={traceTone(trace)}>
                        {trace.outcome === 'failed' ? '失败' : trace.downgraded_from ? '已降级' : '正常'}
                      </StatusPill>
                    </div>
                    <p className="m-0 mt-2 text-sm text-ink-soft">{renderTraceSubtitle(trace)}</p>
                    <p className="m-0 mt-1 text-xs text-ink-soft">
                      trace_id {trace.trace_id} / request_id {trace.request_id}
                    </p>
                  </div>
                  <div className="text-right text-sm text-ink-soft">
                    <p className="m-0">发生时间：{formatLocalTime(trace.occurred_at)}</p>
                    <p className="m-0 mt-1">target：{trace.target_id || '-'}</p>
                  </div>
                </div>

                <div className="mt-4 grid gap-2 md:grid-cols-5">
                  {trace.stages.map((stage) => (
                    <div key={`${trace.trace_id}-${stage.stage}`} className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-white/80 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <strong className="text-sm text-ink">{stage.stage}</strong>
                        <StatusPill tone={stage.status === 'failed' ? 'error' : stage.status === 'degraded' ? 'warn' : stage.status === 'success' ? 'ok' : 'default'}>
                          {stage.status}
                        </StatusPill>
                      </div>
                      <p className="m-0 mt-2 text-xs text-ink-soft">
                        {renderNullable(stage.duration_ms)} ms / in {renderNullable(stage.input_size)} / out {renderNullable(stage.output_size)}
                      </p>
                    </div>
                  ))}
                </div>

                {trace.error_message && (
                  <div className="mt-3 rounded-2xl bg-[rgba(177,67,46,0.08)] px-4 py-3 text-sm text-[rgb(147,43,26)]">
                    {trace.error_message}
                  </div>
                )}
              </div>
            ))}

            {!summary?.recent_traces.length && (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-6 text-sm text-ink-soft">
                还没有最近 trace。先去问答页触发一条 chat 请求，再回来这里看各阶段耗时。
              </div>
            )}
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-12">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">最近请求快照与重放</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                先把 chat 和 SOP 生成的最小可复现链路收进来：保存原始请求、实际参数、命中证据和模型路由，再支持原样或当前配置重放。
              </p>
            </div>
            <StatusPill tone={summary?.recent_snapshots.length ? 'ok' : 'default'}>
              {summary?.recent_snapshots.length ? `${summary.recent_snapshots.length} 条` : '暂无'}
            </StatusPill>
          </div>

          <div className="mt-4 grid gap-3">
            {(summary?.recent_snapshots || []).map((snapshot: RequestSnapshotRecord) => {
              const replayStatus = replayStatusBySnapshotId[snapshot.snapshot_id] || 'idle';
              const replayResult = replayResultBySnapshotId[snapshot.snapshot_id];
              const replayError = replayErrorBySnapshotId[snapshot.snapshot_id];
              return (
                <div key={snapshot.snapshot_id} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <RotateCcw className="h-4 w-4 text-accent-deep" />
                        <strong className="text-ink">{snapshot.action}</strong>
                        <StatusPill tone={snapshot.outcome === 'failed' ? 'error' : 'ok'}>
                          {snapshot.outcome === 'failed' ? '失败快照' : '可重放'}
                        </StatusPill>
                      </div>
                      <p className="m-0 mt-2 break-words text-sm font-medium text-ink">{snapshotPrompt(snapshot)}</p>
                      <p className="m-0 mt-2 text-sm text-ink-soft">
                        {snapshot.actor.username || '-'} / {snapshot.profile.mode} / top_k {snapshot.profile.top_k} / 引用 {snapshot.result.citation_count}
                      </p>
                      <p className="m-0 mt-1 text-xs text-ink-soft">
                        snapshot_id {snapshot.snapshot_id} / trace_id {snapshot.trace_id} / request_id {snapshot.request_id}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={replayStatus === 'loading'}
                        onClick={() => void triggerReplay(snapshot.snapshot_id, 'original')}
                      >
                        原样重放
                      </Button>
                      <Button
                        type="button"
                        disabled={replayStatus === 'loading'}
                        onClick={() => void triggerReplay(snapshot.snapshot_id, 'current')}
                      >
                        当前配置重放
                      </Button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <div className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-white/80 p-3 text-sm text-ink-soft">
                      <strong className="block text-ink">模型路由</strong>
                      <p className="m-0 mt-2">{snapshot.model_route.provider}</p>
                      <p className="m-0 mt-1 break-all">{snapshot.model_route.model}</p>
                    </div>
                    <div className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-white/80 p-3 text-sm text-ink-soft">
                      <strong className="block text-ink">Rewrite / Memory</strong>
                      <p className="m-0 mt-2">rewrite: {snapshot.rewrite.status}</p>
                      <p className="m-0 mt-1">memory: {snapshot.memory_summary || '-'}</p>
                    </div>
                    <div className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-white/80 p-3 text-sm text-ink-soft">
                      <strong className="block text-ink">{snapshotPreviewLabel(snapshot)}</strong>
                      <p className="m-0 mt-2 leading-relaxed">{snapshot.result.answer_preview || '暂无答案预览。'}</p>
                    </div>
                  </div>

                  {replayError && (
                    <div className="mt-3 rounded-2xl bg-[rgba(177,67,46,0.08)] px-4 py-3 text-sm text-[rgb(147,43,26)]">
                      {replayError}
                    </div>
                  )}

                  {replayResult && (
                    <div className="mt-3 rounded-2xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.86)] p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <strong className="text-ink">
                          最近一次重放：{replayResult.replay_mode === 'original' ? '原样重放' : '当前配置重放'}
                        </strong>
                        <StatusPill tone={replayStatus === 'success' ? 'ok' : replayStatus === 'error' ? 'error' : replayStatus === 'loading' ? 'warn' : 'default'}>
                          {replayStatus === 'loading' ? '重放中' : replayStatus === 'success' ? '已完成' : replayStatus === 'error' ? '失败' : '待重放'}
                        </StatusPill>
                      </div>
                      <p className="m-0 mt-3 text-sm text-ink-soft">
                        mode {replayResult.replayed_request.mode || '-'} / top_k {renderNullable(replayResult.replayed_request.top_k)} / response {replayResponseMode(replayResult.response)}
                      </p>
                      <p className="m-0 mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink">
                        {replayResponseContent(replayResult.response)}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}

            {!summary?.recent_snapshots.length && (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-6 text-sm text-ink-soft">
                还没有最近快照。先去问答页触发一条 chat 请求，再回来这里做重放。
              </div>
            )}
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
