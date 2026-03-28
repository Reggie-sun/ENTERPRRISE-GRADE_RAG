import { RefreshCw, Save, SlidersHorizontal, Wrench } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, Input, StatusPill } from '@/components';
import {
  type ConcurrencyControlsConfig,
  type DegradeControlsConfig,
  formatApiError,
  getAuthBootstrap,
  getHealth,
  getSystemConfig,
  type HealthResponse,
  type ModelRoutingConfig,
  updateSystemConfig,
  type QueryModeConfig,
  type QueryProfilesConfig,
  type RerankerRoutingConfig,
  type RetryControlsConfig,
  type UserRecord,
} from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

function buildEmptyProfiles(): QueryProfilesConfig {
  return {
    fast: {
      top_k_default: 5,
      candidate_multiplier: 2,
      lexical_top_k: 10,
      rerank_top_n: 3,
      timeout_budget_seconds: 12,
    },
    accurate: {
      top_k_default: 8,
      candidate_multiplier: 4,
      lexical_top_k: 32,
      rerank_top_n: 5,
      timeout_budget_seconds: 24,
    },
  };
}

function cloneProfiles(profiles: QueryProfilesConfig): QueryProfilesConfig {
  return {
    fast: { ...profiles.fast },
    accurate: { ...profiles.accurate },
  };
}

function buildEmptyModelRouting(): ModelRoutingConfig {
  return {
    fast_model: 'qwen2.5:7b',
    accurate_model: 'qwen2.5:7b',
    sop_generation_model: 'qwen2.5:7b',
  };
}

function cloneModelRouting(modelRouting: ModelRoutingConfig): ModelRoutingConfig {
  return { ...modelRouting };
}

function buildEmptyRerankerRouting(): RerankerRoutingConfig {
  return {
    provider: 'heuristic',
    model: 'BAAI/bge-reranker-v2-m3',
    timeout_seconds: 12,
    failure_cooldown_seconds: 15,
  };
}

function cloneRerankerRouting(rerankerRouting: RerankerRoutingConfig): RerankerRoutingConfig {
  return { ...rerankerRouting };
}

function buildEmptyDegradeControls(): DegradeControlsConfig {
  return {
    rerank_fallback_enabled: true,
    accurate_to_fast_fallback_enabled: true,
    retrieval_fallback_enabled: true,
  };
}

function cloneDegradeControls(degradeControls: DegradeControlsConfig): DegradeControlsConfig {
  return { ...degradeControls };
}

function buildEmptyRetryControls(): RetryControlsConfig {
  return {
    llm_retry_enabled: true,
    llm_retry_max_attempts: 2,
    llm_retry_backoff_ms: 400,
  };
}

function cloneRetryControls(retryControls: RetryControlsConfig): RetryControlsConfig {
  return { ...retryControls };
}

function buildEmptyConcurrencyControls(): ConcurrencyControlsConfig {
  return {
    fast_max_inflight: 24,
    accurate_max_inflight: 6,
    sop_generation_max_inflight: 3,
    per_user_online_max_inflight: 3,
    acquire_timeout_ms: 800,
    busy_retry_after_seconds: 5,
  };
}

function cloneConcurrencyControls(concurrencyControls: ConcurrencyControlsConfig): ConcurrencyControlsConfig {
  return { ...concurrencyControls };
}

function normalizeNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return parsed;
}

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

interface ToggleFieldProps {
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}

function ToggleField({ label, description, checked, disabled, onChange }: ToggleFieldProps) {
  return (
    <label className="flex items-start justify-between gap-4 rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-4">
      <div className="grid gap-1">
        <span className="text-sm font-semibold text-ink">{label}</span>
        <span className="text-sm leading-relaxed text-ink-soft">{description}</span>
      </div>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-5 w-5 rounded border border-[rgba(23,32,42,0.24)] accent-[rgb(182,70,47)]"
      />
    </label>
  );
}

interface ModeCardProps {
  description: string;
  modeKey: keyof QueryProfilesConfig;
  value: QueryModeConfig;
  disabled: boolean;
  onChange: (field: keyof QueryModeConfig, value: number) => void;
}

function ModeConfigCard({ description, modeKey, value, disabled, onChange }: ModeCardProps) {
  return (
    <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="m-0 text-xl font-semibold text-ink">
            {modeKey === 'fast' ? '快速档' : '准确档'}
          </h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">{description}</p>
        </div>
        <StatusPill tone={modeKey === 'fast' ? 'warn' : 'ok'}>
          {modeKey === 'fast' ? 'fast' : 'accurate'}
        </StatusPill>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Input
          label="top_k"
          type="number"
          min={1}
          max={20}
          value={String(value.top_k_default)}
          disabled={disabled}
          onChange={(event) => onChange('top_k_default', normalizeNumber(event.target.value, value.top_k_default))}
        />
        <Input
          label="candidate_multiplier"
          type="number"
          min={1}
          max={20}
          value={String(value.candidate_multiplier)}
          disabled={disabled}
          onChange={(event) => onChange('candidate_multiplier', normalizeNumber(event.target.value, value.candidate_multiplier))}
        />
        <Input
          label="lexical_top_k"
          type="number"
          min={1}
          max={200}
          value={String(value.lexical_top_k)}
          disabled={disabled}
          onChange={(event) => onChange('lexical_top_k', normalizeNumber(event.target.value, value.lexical_top_k))}
        />
        <Input
          label="rerank_top_n"
          type="number"
          min={1}
          max={20}
          value={String(value.rerank_top_n)}
          disabled={disabled}
          onChange={(event) => onChange('rerank_top_n', normalizeNumber(event.target.value, value.rerank_top_n))}
        />
        <Input
          label="timeout_budget_seconds"
          type="number"
          min={1}
          step="0.5"
          value={String(value.timeout_budget_seconds)}
          disabled={disabled}
          onChange={(event) => onChange('timeout_budget_seconds', normalizeNumber(event.target.value, value.timeout_budget_seconds))}
        />
      </div>
    </Card>
  );
}

export function AdminPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [saveStatus, setSaveStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [updatedBy, setUpdatedBy] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<QueryProfilesConfig>(buildEmptyProfiles());
  const [savedProfiles, setSavedProfiles] = useState<QueryProfilesConfig>(buildEmptyProfiles());
  const [modelRouting, setModelRouting] = useState<ModelRoutingConfig>(buildEmptyModelRouting());
  const [savedModelRouting, setSavedModelRouting] = useState<ModelRoutingConfig>(buildEmptyModelRouting());
  const [rerankerRouting, setRerankerRouting] = useState<RerankerRoutingConfig>(buildEmptyRerankerRouting());
  const [savedRerankerRouting, setSavedRerankerRouting] = useState<RerankerRoutingConfig>(buildEmptyRerankerRouting());
  const [degradeControls, setDegradeControls] = useState<DegradeControlsConfig>(buildEmptyDegradeControls());
  const [savedDegradeControls, setSavedDegradeControls] = useState<DegradeControlsConfig>(buildEmptyDegradeControls());
  const [retryControls, setRetryControls] = useState<RetryControlsConfig>(buildEmptyRetryControls());
  const [savedRetryControls, setSavedRetryControls] = useState<RetryControlsConfig>(buildEmptyRetryControls());
  const [concurrencyControls, setConcurrencyControls] = useState<ConcurrencyControlsConfig>(buildEmptyConcurrencyControls());
  const [savedConcurrencyControls, setSavedConcurrencyControls] = useState<ConcurrencyControlsConfig>(buildEmptyConcurrencyControls());
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    const loadPage = async () => {
      setStatus('loading');
      setError('');
      try {
        const [configPayload, bootstrapPayload, healthPayload] = await Promise.all([
          getSystemConfig(),
          getAuthBootstrap(),
          getHealth(),
        ]);
        setProfiles(cloneProfiles(configPayload.query_profiles));
        setSavedProfiles(cloneProfiles(configPayload.query_profiles));
        setModelRouting(cloneModelRouting(configPayload.model_routing));
        setSavedModelRouting(cloneModelRouting(configPayload.model_routing));
        setRerankerRouting(cloneRerankerRouting(configPayload.reranker_routing));
        setSavedRerankerRouting(cloneRerankerRouting(configPayload.reranker_routing));
        setDegradeControls(cloneDegradeControls(configPayload.degrade_controls));
        setSavedDegradeControls(cloneDegradeControls(configPayload.degrade_controls));
        setRetryControls(cloneRetryControls(configPayload.retry_controls));
        setSavedRetryControls(cloneRetryControls(configPayload.retry_controls));
        setConcurrencyControls(cloneConcurrencyControls(configPayload.concurrency_controls));
        setSavedConcurrencyControls(cloneConcurrencyControls(configPayload.concurrency_controls));
        setUpdatedAt(configPayload.updated_at);
        setUpdatedBy(configPayload.updated_by);
        setUsers(bootstrapPayload.users);
        setHealth(healthPayload as HealthResponse);
        setStatus('success');
      } catch (err) {
        setHealth(null);
        setStatus('error');
        setError(formatApiError(err, '系统配置加载'));
      }
    };

    void loadPage();
  }, [refreshTick]);

  const isDirty = useMemo(
    () => (
      JSON.stringify(profiles) !== JSON.stringify(savedProfiles)
      || JSON.stringify(modelRouting) !== JSON.stringify(savedModelRouting)
      || JSON.stringify(rerankerRouting) !== JSON.stringify(savedRerankerRouting)
      || JSON.stringify(degradeControls) !== JSON.stringify(savedDegradeControls)
      || JSON.stringify(retryControls) !== JSON.stringify(savedRetryControls)
      || JSON.stringify(concurrencyControls) !== JSON.stringify(savedConcurrencyControls)
    ),
    [profiles, savedProfiles, modelRouting, savedModelRouting, rerankerRouting, savedRerankerRouting, degradeControls, savedDegradeControls, retryControls, savedRetryControls, concurrencyControls, savedConcurrencyControls],
  );

  const updatedByLabel = useMemo(() => {
    if (!updatedBy) {
      return '-';
    }
    return users.find((item) => item.user_id === updatedBy)?.display_name || updatedBy;
  }, [updatedBy, users]);

  const updateModeField = (mode: keyof QueryProfilesConfig, field: keyof QueryModeConfig, value: number) => {
    setProfiles((current) => ({
      ...current,
      [mode]: {
        ...current[mode],
        [field]: value,
      },
    }));
  };

  const updateModelRoutingField = (field: keyof ModelRoutingConfig, value: string) => {
    setModelRouting((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const updateRerankerRoutingField = (field: keyof RerankerRoutingConfig, value: number | string) => {
    setRerankerRouting((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const updateDegradeControl = (field: keyof DegradeControlsConfig, value: boolean) => {
    setDegradeControls((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const updateRetryControl = (field: keyof RetryControlsConfig, value: number | boolean) => {
    setRetryControls((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const updateConcurrencyControl = (field: keyof ConcurrencyControlsConfig, value: number) => {
    setConcurrencyControls((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleSave = async () => {
    setSaveStatus('loading');
    setSaveError('');
    try {
      const payload = await updateSystemConfig({
        query_profiles: profiles,
        model_routing: modelRouting,
        reranker_routing: rerankerRouting,
        degrade_controls: degradeControls,
        retry_controls: retryControls,
        concurrency_controls: concurrencyControls,
      });
      const latestHealth = await getHealth();
      setProfiles(cloneProfiles(payload.query_profiles));
      setSavedProfiles(cloneProfiles(payload.query_profiles));
      setModelRouting(cloneModelRouting(payload.model_routing));
      setSavedModelRouting(cloneModelRouting(payload.model_routing));
      setRerankerRouting(cloneRerankerRouting(payload.reranker_routing));
      setSavedRerankerRouting(cloneRerankerRouting(payload.reranker_routing));
      setDegradeControls(cloneDegradeControls(payload.degrade_controls));
      setSavedDegradeControls(cloneDegradeControls(payload.degrade_controls));
      setRetryControls(cloneRetryControls(payload.retry_controls));
      setSavedRetryControls(cloneRetryControls(payload.retry_controls));
      setConcurrencyControls(cloneConcurrencyControls(payload.concurrency_controls));
      setSavedConcurrencyControls(cloneConcurrencyControls(payload.concurrency_controls));
      setUpdatedAt(payload.updated_at);
      setUpdatedBy(payload.updated_by);
      setHealth(latestHealth);
      setSaveStatus('success');
    } catch (err) {
      setSaveStatus('error');
      setSaveError(formatApiError(err, '系统配置保存'));
    }
  };

  const rerankerRuntimeTone: 'ok' | 'warn' | 'error' | 'default' = health?.reranker.ready
    ? 'ok'
    : health?.reranker.effective_strategy === 'heuristic' && health?.reranker.fallback_enabled
      ? 'warn'
      : health?.reranker
        ? 'error'
        : 'default';

  const rerankerRuntimeLabel = health?.reranker.ready
    ? 'provider ready'
    : health?.reranker?.effective_strategy === 'heuristic' && health?.reranker.fallback_enabled
      ? 'fallback active'
      : health?.reranker
        ? 'route unavailable'
        : '未加载';

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            Admin
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            管理后台先承接系统运行配置，把模型路由、降级和重试收口到一处。
          </h2>
          <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
            这页现在能直接控制查询档位、关键词召回上限、模型路由、rerank 默认路由、降级开关和 LLM 重试策略，不需要改代码重发版。
          </p>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前状态</h3>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前角色</strong>
              <p className="m-0 mt-2">{experience.roleLabel}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">权限边界</strong>
              <p className="m-0 mt-2 leading-relaxed">{scopeSummary}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">最近修改</strong>
              <p className="m-0 mt-2">{updatedByLabel}</p>
              <p className="m-0 mt-1">{formatLocalTime(updatedAt)}</p>
            </div>
          </div>
        </Card>
      </section>

      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="m-0 text-xl font-semibold text-ink">查询档位配置</h3>
            <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
              保存后会直接影响后续请求的参数展开、模型选择和降级行为。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill tone={status === 'error' ? 'error' : status === 'loading' ? 'warn' : 'ok'}>
              {status === 'loading' ? '加载中' : status === 'error' ? '加载失败' : '配置已就绪'}
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

        {saveError && (
          <div className="mt-4 rounded-2xl bg-[rgba(177,67,46,0.08)] px-4 py-3 text-sm text-[rgb(147,43,26)]">
            {saveError}
          </div>
        )}

        <div className="mt-4 grid gap-5 xl:grid-cols-2">
          <ModeConfigCard
            modeKey="fast"
            description="默认服务员工端问答，优先低延迟和稳定响应。"
            value={profiles.fast}
            disabled={status === 'loading' || saveStatus === 'loading'}
            onChange={(field, value) => updateModeField('fast', field, value)}
          />
          <ModeConfigCard
            modeKey="accurate"
            description="默认服务高质量问答与 SOP 生成，优先证据完整度和更高质量输出。"
            value={profiles.accurate}
            disabled={status === 'loading' || saveStatus === 'loading'}
            onChange={(field, value) => updateModeField('accurate', field, value)}
          />
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-3">
          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">模型路由</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                按档位和用途指定模型名，当前默认仍走同一 provider，只切模型名称。
              </p>
            </div>
            <div className="mt-4 grid gap-3">
              <Input
                label="fast_model"
                value={modelRouting.fast_model}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateModelRoutingField('fast_model', event.target.value)}
              />
              <Input
                label="accurate_model"
                value={modelRouting.accurate_model}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateModelRoutingField('accurate_model', event.target.value)}
              />
              <Input
                label="sop_generation_model"
                value={modelRouting.sop_generation_model}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateModelRoutingField('sop_generation_model', event.target.value)}
              />
            </div>
          </Card>

          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">Rerank 路由</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                控制当前默认使用 heuristic 还是 openai-compatible reranker，并直接看到当前实际生效路由有没有锁回 heuristic。
              </p>
            </div>
            <div className="mt-4 grid gap-3">
              <label className="grid gap-2 text-sm font-semibold text-ink">
                <span>provider</span>
                <select
                  value={rerankerRouting.provider}
                  disabled={status === 'loading' || saveStatus === 'loading'}
                  onChange={(event) => updateRerankerRoutingField('provider', event.target.value)}
                  className="h-12 rounded-2xl border border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.92)] px-4 text-sm text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.4)]"
                >
                  <option value="heuristic">heuristic</option>
                  <option value="openai_compatible">openai_compatible</option>
                </select>
              </label>
              <Input
                label="reranker_model"
                value={rerankerRouting.model}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateRerankerRoutingField('model', event.target.value)}
              />
              <Input
                label="reranker_timeout_seconds"
                type="number"
                min={1}
                max={60}
                step="0.5"
                value={String(rerankerRouting.timeout_seconds)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateRerankerRoutingField('timeout_seconds', normalizeNumber(event.target.value, rerankerRouting.timeout_seconds))}
              />
              <Input
                label="failure_cooldown_seconds"
                type="number"
                min={1}
                max={300}
                step="1"
                value={String(rerankerRouting.failure_cooldown_seconds)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateRerankerRoutingField('failure_cooldown_seconds', normalizeNumber(event.target.value, rerankerRouting.failure_cooldown_seconds))}
              />
            </div>
            <div className="mt-4 rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-4 text-sm text-ink-soft">
              <div className="flex items-center justify-between gap-3">
                <strong className="text-ink">当前实际路由</strong>
                <StatusPill tone={rerankerRuntimeTone}>{rerankerRuntimeLabel}</StatusPill>
              </div>
              <p className="m-0 mt-3">configured: {health?.reranker.provider || rerankerRouting.provider} / {health?.reranker.model || rerankerRouting.model}</p>
              <p className="m-0 mt-1">effective: {health?.reranker.effective_provider || '-'} / {health?.reranker.effective_strategy || '-'}</p>
              <p className="m-0 mt-1">effective model: {health?.reranker.effective_model || '-'}</p>
              <p className="m-0 mt-1">fallback: {health?.reranker.fallback_enabled ? 'on' : 'off'}</p>
              <p className="m-0 mt-1">timeout: {health?.reranker.timeout_seconds ?? rerankerRouting.timeout_seconds} s</p>
              <p className="m-0 mt-1">cooldown: {health?.reranker.failure_cooldown_seconds ?? rerankerRouting.failure_cooldown_seconds} s</p>
              <p className="m-0 mt-1">lock: {health?.reranker.lock_active ? 'active' : 'off'}{health?.reranker.lock_source ? ` / ${health.reranker.lock_source}` : ''}</p>
              <p className="m-0 mt-1">cooldown remaining: {health ? `${health.reranker.cooldown_remaining_seconds.toFixed(1)} s` : '-'}</p>
              <p className="m-0 mt-1 break-all">{health?.reranker.base_url || '-'}</p>
              <p className="m-0 mt-2 leading-relaxed">{health?.reranker.detail || '刷新后可看到当前 rerank 探针状态。'}</p>
            </div>
          </Card>

          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">降级开关</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                控制 rerank 不可用、accurate 通道抖动和 LLM 不可用时的回退路径。
              </p>
            </div>
            <div className="mt-4 grid gap-3">
              <ToggleField
                label="rerank -> heuristic"
                description="关闭后，provider rerank 失败会直接报错，不再自动回退到 heuristic。"
                checked={degradeControls.rerank_fallback_enabled}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(checked) => updateDegradeControl('rerank_fallback_enabled', checked)}
              />
              <ToggleField
                label="accurate -> fast"
                description="关闭后，accurate 通道不会自动退回 fast 的检索参数。"
                checked={degradeControls.accurate_to_fast_fallback_enabled}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(checked) => updateDegradeControl('accurate_to_fast_fallback_enabled', checked)}
              />
              <ToggleField
                label="LLM -> retrieval fallback"
                description="关闭后，LLM 重试后仍失败会直接返回错误，不再生成检索兜底结果。"
                checked={degradeControls.retrieval_fallback_enabled}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(checked) => updateDegradeControl('retrieval_fallback_enabled', checked)}
              />
            </div>
          </Card>
        </div>

        <div className="mt-5">
          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">重试策略</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                只作用于 LLM 可重试故障。流式回答只会在首个 token 输出前重试，避免中途断流重复输出。
              </p>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <label className="flex items-center gap-3 rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-4 text-sm font-semibold text-ink">
                <input
                  type="checkbox"
                  checked={retryControls.llm_retry_enabled}
                  disabled={status === 'loading' || saveStatus === 'loading'}
                  onChange={(event) => updateRetryControl('llm_retry_enabled', event.target.checked)}
                  className="h-5 w-5 rounded border border-[rgba(23,32,42,0.24)] accent-[rgb(182,70,47)]"
                />
                启用 LLM 重试
              </label>
              <Input
                label="llm_retry_max_attempts"
                type="number"
                min={1}
                max={5}
                value={String(retryControls.llm_retry_max_attempts)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateRetryControl('llm_retry_max_attempts', normalizeNumber(event.target.value, retryControls.llm_retry_max_attempts))}
              />
              <Input
                label="llm_retry_backoff_ms"
                type="number"
                min={0}
                max={10000}
                step="50"
                value={String(retryControls.llm_retry_backoff_ms)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateRetryControl('llm_retry_backoff_ms', normalizeNumber(event.target.value, retryControls.llm_retry_backoff_ms))}
              />
            </div>
          </Card>
        </div>

        <div className="mt-5">
          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">并发阈值</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                控制在线问答和 SOP 生成各通道最多同时占用多少槽位，同时限制单个用户最多能占多少在线请求，避免一人把 fast / accurate / SOP 槽位吃满。
              </p>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <Input
                label="fast_max_inflight"
                type="number"
                min={1}
                max={200}
                value={String(concurrencyControls.fast_max_inflight)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('fast_max_inflight', normalizeNumber(event.target.value, concurrencyControls.fast_max_inflight))}
              />
              <Input
                label="accurate_max_inflight"
                type="number"
                min={1}
                max={100}
                value={String(concurrencyControls.accurate_max_inflight)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('accurate_max_inflight', normalizeNumber(event.target.value, concurrencyControls.accurate_max_inflight))}
              />
              <Input
                label="sop_generation_max_inflight"
                type="number"
                min={1}
                max={50}
                value={String(concurrencyControls.sop_generation_max_inflight)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('sop_generation_max_inflight', normalizeNumber(event.target.value, concurrencyControls.sop_generation_max_inflight))}
              />
              <Input
                label="per_user_online_max_inflight"
                type="number"
                min={1}
                max={20}
                value={String(concurrencyControls.per_user_online_max_inflight)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('per_user_online_max_inflight', normalizeNumber(event.target.value, concurrencyControls.per_user_online_max_inflight))}
              />
              <Input
                label="acquire_timeout_ms"
                type="number"
                min={0}
                max={30000}
                step="50"
                value={String(concurrencyControls.acquire_timeout_ms)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('acquire_timeout_ms', normalizeNumber(event.target.value, concurrencyControls.acquire_timeout_ms))}
              />
              <Input
                label="busy_retry_after_seconds"
                type="number"
                min={1}
                max={300}
                value={String(concurrencyControls.busy_retry_after_seconds)}
                disabled={status === 'loading' || saveStatus === 'loading'}
                onChange={(event) => updateConcurrencyControl('busy_retry_after_seconds', normalizeNumber(event.target.value, concurrencyControls.busy_retry_after_seconds))}
              />
            </div>
          </Card>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-3xl bg-[rgba(255,255,255,0.72)] px-4 py-4">
          <div className="grid gap-2 text-sm text-ink-soft">
            <div className="inline-flex items-center gap-2 text-ink">
              <SlidersHorizontal className="h-4 w-4" />
              当前已开放查询档位、关键词召回上限、模型路由、降级和重试
            </div>
            <div className="inline-flex items-center gap-2">
              <Wrench className="h-4 w-4" />
              后续再继续往这一页补模型 provider、rewrite 和轻记忆控制。
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill tone={isDirty ? 'warn' : 'ok'}>
              {isDirty ? '有未保存修改' : '当前配置已保存'}
            </StatusPill>
            <Button
              type="button"
              onClick={() => void handleSave()}
              disabled={!isDirty || status === 'loading' || saveStatus === 'loading'}
              className="inline-flex items-center gap-2"
            >
              <Save className="h-4 w-4" />
              {saveStatus === 'loading' ? '保存中' : '保存配置'}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
