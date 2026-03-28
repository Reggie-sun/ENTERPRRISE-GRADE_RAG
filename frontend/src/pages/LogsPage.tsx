import { Clock3, Filter, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, Input, StatusPill } from '@/components';
import {
  formatApiError,
  getAuthBootstrap,
  getEventLogs,
  type DepartmentRecord,
  type EventLogCategory,
  type EventLogOutcome,
  type EventLogRecord,
} from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

function formatLocalTime(value: string): string {
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

export function LogsPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const accessibleDepartmentIds = profile?.accessible_department_ids || [];
  const lockedDepartmentId = profile?.user.role_id === 'department_admin' && accessibleDepartmentIds.length === 1
    ? accessibleDepartmentIds[0]
    : '';
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [records, setRecords] = useState<EventLogRecord[]>([]);
  const [selectedEventId, setSelectedEventId] = useState('');
  const [bootstrapDepartments, setBootstrapDepartments] = useState<DepartmentRecord[]>([]);

  const [category, setCategory] = useState<EventLogCategory | ''>('');
  const [outcome, setOutcome] = useState<EventLogOutcome | ''>('');
  const [action, setAction] = useState('');
  const [username, setUsername] = useState('');
  const [targetId, setTargetId] = useState('');
  const [rerankStrategy, setRerankStrategy] = useState('');
  const [rerankProvider, setRerankProvider] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [departmentId, setDepartmentId] = useState(lockedDepartmentId);

  useEffect(() => {
    if (lockedDepartmentId && departmentId !== lockedDepartmentId) {
      setDepartmentId(lockedDepartmentId);
    }
  }, [departmentId, lockedDepartmentId]);

  useEffect(() => {
    const loadBootstrap = async () => {
      try {
        const payload = await getAuthBootstrap();
        setBootstrapDepartments(payload.departments);
      } catch {
        setBootstrapDepartments([]);
      }
    };

    void loadBootstrap();
  }, []);

  useEffect(() => {
    const loadLogs = async () => {
      setStatus('loading');
      setError('');
      try {
        const payload = await getEventLogs({
          page,
          page_size: pageSize,
          category: category || undefined,
          outcome: outcome || undefined,
          action: action.trim() || undefined,
          username: username.trim() || undefined,
          target_id: targetId.trim() || undefined,
          rerank_strategy: rerankStrategy.trim() || undefined,
          rerank_provider: rerankProvider.trim() || undefined,
          department_id: departmentId || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        });
        setRecords(payload.items);
        setTotal(payload.total);
        setStatus('success');
      } catch (err) {
        setRecords([]);
        setTotal(0);
        setStatus('error');
        setError(formatApiError(err, '日志查询'));
      }
    };

    void loadLogs();
  }, [action, category, dateFrom, dateTo, departmentId, outcome, page, pageSize, refreshTick, rerankProvider, rerankStrategy, targetId, username]);

  useEffect(() => {
    if (!records.length) {
      setSelectedEventId('');
      return;
    }
    if (!selectedEventId || !records.some((item) => item.event_id === selectedEventId)) {
      setSelectedEventId(records[0].event_id);
    }
  }, [records, selectedEventId]);

  const selectedRecord = useMemo(
    () => records.find((item) => item.event_id === selectedEventId) || null,
    [records, selectedEventId],
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const departmentOptions = useMemo(
    () => bootstrapDepartments
      .filter((item) => accessibleDepartmentIds.includes(item.department_id))
      .sort((left, right) => left.department_name.localeCompare(right.department_name, 'zh-CN')),
    [accessibleDepartmentIds, bootstrapDepartments],
  );

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            Logs
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            日志页先承接查询与追溯，不先扩成大而全治理后台。
          </h2>
          <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
            这一页先服务排障和回放定位：看谁触发了什么动作、在哪个部门范围内、用了什么参数、什么时候开始变坏。
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
              <strong className="block text-ink">当前结果</strong>
              <p className="m-0 mt-2">{total} 条</p>
            </div>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-12">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">筛选条件</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                先按日期、动作、用户和目标收窄范围，再看右侧单条详情。
              </p>
            </div>
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

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="grid gap-1.5 text-sm font-semibold">
              分类
              <select
                value={category}
                onChange={(event) => {
                  setPage(1);
                  setCategory(event.target.value as EventLogCategory | '');
                }}
                className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-ink"
              >
                <option value="">全部分类</option>
                <option value="chat">chat</option>
                <option value="document">document</option>
                <option value="sop_generation">sop_generation</option>
              </select>
            </label>

            <label className="grid gap-1.5 text-sm font-semibold">
              结果
              <select
                value={outcome}
                onChange={(event) => {
                  setPage(1);
                  setOutcome(event.target.value as EventLogOutcome | '');
                }}
                className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-ink"
              >
                <option value="">全部结果</option>
                <option value="success">success</option>
                <option value="failed">failed</option>
              </select>
            </label>

            <Input
              label="动作"
              placeholder="例如 answer / create / generate_document"
              value={action}
              onChange={(event) => {
                setPage(1);
                setAction(event.target.value);
              }}
            />

            <Input
              label="用户名"
              placeholder="例如 digitalization.admin"
              value={username}
              onChange={(event) => {
                setPage(1);
                setUsername(event.target.value);
              }}
            />

            <Input
              label="目标 ID"
              placeholder="资料编号 / 任务编号 / 会话编号"
              value={targetId}
              onChange={(event) => {
                setPage(1);
                setTargetId(event.target.value);
              }}
            />

            <Input
              label="rerank_strategy"
              placeholder="provider / heuristic / fallback_profile"
              value={rerankStrategy}
              onChange={(event) => {
                setPage(1);
                setRerankStrategy(event.target.value);
              }}
            />

            <Input
              label="rerank_provider"
              placeholder="openai_compatible / heuristic"
              value={rerankProvider}
              onChange={(event) => {
                setPage(1);
                setRerankProvider(event.target.value);
              }}
            />

            <label className="grid gap-1.5 text-sm font-semibold">
              部门
              <select
                value={departmentId}
                disabled={Boolean(lockedDepartmentId)}
                onChange={(event) => {
                  setPage(1);
                  setDepartmentId(event.target.value);
                }}
                className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-ink disabled:opacity-70"
              >
                <option value="">全部部门</option>
                {departmentOptions.map((item) => (
                  <option key={item.department_id} value={item.department_id}>
                    {item.department_name}
                  </option>
                ))}
              </select>
            </label>

            <Input
              label="开始日期"
              type="date"
              value={dateFrom}
              onChange={(event) => {
                setPage(1);
                setDateFrom(event.target.value);
              }}
            />

            <Input
              label="结束日期"
              type="date"
              value={dateTo}
              onChange={(event) => {
                setPage(1);
                setDateTo(event.target.value);
              }}
            />
          </div>
        </Card>

        <Card className="col-span-7 max-lg:col-span-12">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">日志结果</h3>
              <p className="m-0 mt-2 text-sm text-ink-soft">
                优先看耗时、动作和 target_id，再决定是否需要点右侧详情。
              </p>
            </div>
            <StatusPill tone={status === 'error' ? 'error' : status === 'loading' ? 'warn' : 'ok'}>
              {status === 'loading' ? '查询中' : status === 'error' ? '查询失败' : '查询已完成'}
            </StatusPill>
          </div>

          {error && (
            <div className="mt-4 rounded-2xl bg-[rgba(177,67,46,0.08)] px-4 py-3 text-sm text-[rgb(147,43,26)]">
              {error}
            </div>
          )}

          {!error && !records.length && status !== 'loading' && (
            <div className="mt-4 rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-6 text-sm text-ink-soft">
              当前筛选条件下暂无日志记录。
            </div>
          )}

          <div className="mt-4 grid gap-3">
            {records.map((record) => {
              const active = record.event_id === selectedEventId;
              return (
                <button
                  key={record.event_id}
                  type="button"
                  onClick={() => setSelectedEventId(record.event_id)}
                  className={`
                    rounded-3xl border p-4 text-left transition-all duration-200
                    ${active
                      ? 'border-[rgba(182,70,47,0.2)] bg-white shadow-[0_18px_36px_rgba(77,42,16,0.08)]'
                      : 'border-transparent bg-[rgba(255,255,255,0.72)] hover:bg-white'}
                  `}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill tone={record.outcome === 'success' ? 'ok' : 'error'}>{record.outcome}</StatusPill>
                    <StatusPill tone="default">{record.category}</StatusPill>
                    {record.mode ? <StatusPill tone="warn">{record.mode}</StatusPill> : null}
                    {record.rerank_strategy ? <StatusPill tone="warn">{record.rerank_strategy}</StatusPill> : null}
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-ink-soft md:grid-cols-[1.3fr_1fr_1fr]">
                    <p className="m-0">
                      <strong className="text-ink">动作：</strong>
                      {record.action}
                    </p>
                    <p className="m-0">
                      <strong className="text-ink">用户：</strong>
                      {renderNullable(record.actor.username)}
                    </p>
                    <p className="m-0">
                      <strong className="text-ink">目标：</strong>
                      {renderNullable(record.target_id)}
                    </p>
                    <p className="m-0 inline-flex items-center gap-1">
                      <Clock3 className="h-4 w-4 text-accent-deep" />
                      {formatLocalTime(record.occurred_at)}
                    </p>
                    <p className="m-0">
                      <strong className="text-ink">耗时：</strong>
                      {record.duration_ms !== null ? `${record.duration_ms} ms` : '-'}
                    </p>
                    <p className="m-0">
                      <strong className="text-ink">部门：</strong>
                      {renderNullable(record.actor.department_id)}
                    </p>
                    <p className="m-0">
                      <strong className="text-ink">rerank：</strong>
                      {renderNullable(record.rerank_provider)} / {renderNullable(record.rerank_strategy)}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="m-0 text-sm text-ink-soft">
              第 {page} / {totalPages} 页，共 {total} 条
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                上一页
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={page >= totalPages}
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </Card>

        <Card className="col-span-5 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-accent-deep" />
            <h3 className="m-0 text-xl font-semibold text-ink">单条详情</h3>
          </div>
          {!selectedRecord && (
            <p className="m-0 mt-4 text-sm leading-relaxed text-ink-soft">
              先从左侧选一条日志，再看具体参数、降级信息和明细字段。
            </p>
          )}
          {selectedRecord && (
            <div className="mt-4 grid gap-3 text-sm text-ink-soft">
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                <strong className="block text-ink">核心信息</strong>
                <div className="mt-2 grid gap-2">
                  <p className="m-0"><strong className="text-ink">event_id：</strong>{selectedRecord.event_id}</p>
                  <p className="m-0"><strong className="text-ink">action：</strong>{selectedRecord.action}</p>
                  <p className="m-0"><strong className="text-ink">target_id：</strong>{renderNullable(selectedRecord.target_id)}</p>
                  <p className="m-0"><strong className="text-ink">occurred_at：</strong>{formatLocalTime(selectedRecord.occurred_at)}</p>
                </div>
              </div>

              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                <strong className="block text-ink">查询参数</strong>
                <div className="mt-2 grid gap-2">
                  <p className="m-0"><strong className="text-ink">mode：</strong>{renderNullable(selectedRecord.mode)}</p>
                  <p className="m-0"><strong className="text-ink">top_k：</strong>{renderNullable(selectedRecord.top_k)}</p>
                  <p className="m-0"><strong className="text-ink">candidate_top_k：</strong>{renderNullable(selectedRecord.candidate_top_k)}</p>
                  <p className="m-0"><strong className="text-ink">rerank_top_n：</strong>{renderNullable(selectedRecord.rerank_top_n)}</p>
                  <p className="m-0"><strong className="text-ink">rerank_strategy：</strong>{renderNullable(selectedRecord.rerank_strategy)}</p>
                  <p className="m-0"><strong className="text-ink">rerank_provider：</strong>{renderNullable(selectedRecord.rerank_provider)}</p>
                  <p className="m-0"><strong className="text-ink">rerank_model：</strong>{renderNullable(selectedRecord.rerank_model)}</p>
                </div>
              </div>

              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                <strong className="block text-ink">执行状态</strong>
                <div className="mt-2 grid gap-2">
                  <p className="m-0"><strong className="text-ink">outcome：</strong>{selectedRecord.outcome}</p>
                  <p className="m-0"><strong className="text-ink">duration_ms：</strong>{renderNullable(selectedRecord.duration_ms)}</p>
                  <p className="m-0"><strong className="text-ink">timeout_flag：</strong>{selectedRecord.timeout_flag ? 'true' : 'false'}</p>
                  <p className="m-0"><strong className="text-ink">downgraded_from：</strong>{renderNullable(selectedRecord.downgraded_from)}</p>
                </div>
              </div>

              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-accent-deep" />
                  <strong className="block text-ink">details</strong>
                </div>
                <pre className="m-0 mt-3 overflow-auto rounded-2xl bg-[rgba(23,32,42,0.04)] p-4 text-xs leading-relaxed text-ink whitespace-pre-wrap break-all">
                  {JSON.stringify(selectedRecord.details, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
