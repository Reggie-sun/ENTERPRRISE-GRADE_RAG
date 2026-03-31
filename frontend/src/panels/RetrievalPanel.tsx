/**
 * 检索面板 — 支持文档检索与 rerank compare
 */

import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth';
import {
  RERANK_CANARY_DECISION_FILTERS,
  getRerankDecisionPresentation,
  type RerankCanaryDecisionFilter,
} from '@/app/rerankCanaryPresentation';
import { Card, Button, StatusPill, Textarea, Input, ResultCard, EvidenceSourceSummary } from '@/components';
import {
  compareRetrievalRerank,
  formatApiError,
  getRetrievalRerankCanary,
  getSystemConfig,
  searchDocuments,
  updateSystemConfig,
  type RerankCanaryListResponse,
  type RetrievalRerankCompareResponse,
  type RetrievalResponse,
  type RetrievedChunk,
  type IngestJobStatus,
} from '@/api';

// 检索模式中文映射。
const MODE_TEXT: Record<string, string> = {
  qdrant: 'Qdrant 向量检索',
  hybrid: 'Hybrid 混合检索',
  rag: 'RAG 回答',
  retrieval_fallback: '检索回退',
  no_context: '无上下文',
  mock: '模拟模式',
};

const JOB_STATE_TEXT: Record<string, string> = {
  pending: '待处理',
  uploaded: '已上传',
  queued: '已入队',
  parsing: '解析中',
  ocr_processing: 'OCR 处理中',
  chunking: '切块中',
  embedding: '向量化中',
  indexing: '索引写入中',
  completed: '已完成',
  failed: '失败',
  dead_letter: '死信',
  partial_failed: '部分失败',
};

// 面板状态类型。
type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

interface RetrievalPanelProps {
  resetSignal?: number;
  currentDocumentName?: string;
  currentDocId?: string;
  currentJobStatus?: IngestJobStatus;
}

export function RetrievalPanel({
  resetSignal,
  currentDocumentName,
  currentDocId,
  currentJobStatus,
}: RetrievalPanelProps) {
  const navigate = useNavigate();
  const { canAccessAdmin } = useAuth();
  const normalizedDocId = currentDocId?.trim();

  // 表单状态。
  const [query, setQuery] = useState('这份文档主要讲了什么？');
  const [topK, setTopK] = useState(5);

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [data, setData] = useState<RetrievalResponse | null>(null);
  const [error, setError] = useState<string>('');
  const [comparisonStatus, setComparisonStatus] = useState<PanelStatus>('idle');
  const [comparisonData, setComparisonData] = useState<RetrievalRerankCompareResponse | null>(null);
  const [comparisonError, setComparisonError] = useState<string>('');
  const [canaryStatus, setCanaryStatus] = useState<PanelStatus>('idle');
  const [canaryData, setCanaryData] = useState<RerankCanaryListResponse | null>(null);
  const [canaryError, setCanaryError] = useState<string>('');
  const [canaryDecisionFilter, setCanaryDecisionFilter] = useState<RerankCanaryDecisionFilter>('all');
  const [strategyActionStatus, setStrategyActionStatus] = useState<PanelStatus>('idle');
  const [strategyActionMessage, setStrategyActionMessage] = useState<string>('');

  // 每次新上传文档时，自动清空旧的检索结果。
  useEffect(() => {
    setData(null);
    setError('');
    setStatus('idle');
    setComparisonData(null);
    setComparisonError('');
    setComparisonStatus('idle');
    setCanaryData(null);
    setCanaryError('');
    setCanaryStatus('idle');
    setStrategyActionStatus('idle');
    setStrategyActionMessage('');
  }, [resetSignal]);

  useEffect(() => {
    void loadRecentCanary();
  }, [canaryDecisionFilter]);

  const buildRequest = () => ({
    query: query.trim(),
    top_k: topK,
    document_id: normalizedDocId || undefined,
  });

  const buildSampleRequest = (sample: NonNullable<RerankCanaryListResponse['items']>[number]) => ({
    query: sample.query.trim(),
    top_k: topK,
    document_id: normalizedDocId || sample.target_id || undefined,
  });

  const formatLocalTime = (value: string | null | undefined) => {
    if (!value) {
      return '-';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return parsed.toLocaleString('zh-CN', { hour12: false });
  };

  const loadRecentCanary = async () => {
    setCanaryStatus('loading');
    setCanaryError('');
    try {
      const result = await getRetrievalRerankCanary(
        8,
        canaryDecisionFilter === 'all' ? undefined : canaryDecisionFilter,
      );
      setCanaryData(result);
      setCanaryStatus('success');
    } catch (err) {
      setCanaryError(formatApiError(err, 'canary 样本加载'));
      setCanaryStatus('error');
    }
  };

  // 执行检索。
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (normalizedDocId && currentJobStatus !== 'completed') {
      const jobText = JOB_STATE_TEXT[currentJobStatus || ''] || currentJobStatus || '-';
      setStatus('error');
      setData(null);
      setError(`当前文档尚未完成入库（状态：${jobText}），暂不能检索。请等待任务完成后重试。`);
      return;
    }
    setStatus('loading');
    setError('');

    try {
      const result = await searchDocuments(buildRequest());
      setData(result);
      setStatus('success');
    } catch (err) {
      setError(formatApiError(err, '文档检索'));
      setStatus('error');
    }
  };

  const handleCompareRerank = async () => {
    if (normalizedDocId && currentJobStatus !== 'completed') {
      const jobText = JOB_STATE_TEXT[currentJobStatus || ''] || currentJobStatus || '-';
      setComparisonStatus('error');
      setComparisonData(null);
      setComparisonError(`当前文档尚未完成入库（状态：${jobText}），暂不能执行 rerank 对比。请等待任务完成后重试。`);
      return;
    }
    setComparisonStatus('loading');
    setComparisonError('');

    try {
      const result = await compareRetrievalRerank(buildRequest());
      setComparisonData(result);
      setComparisonStatus('success');
      await loadRecentCanary();
    } catch (err) {
      setComparisonError(formatApiError(err, '排序策略对比'));
      setComparisonStatus('error');
    }
  };

  const handleLoadSampleQuery = (sample: NonNullable<RerankCanaryListResponse['items']>[number]) => {
    setQuery(sample.query);
    setComparisonError('');
  };

  const handleReplaySampleCompare = async (sample: NonNullable<RerankCanaryListResponse['items']>[number]) => {
    setQuery(sample.query);
    setComparisonStatus('loading');
    setComparisonError('');

    try {
      const result = await compareRetrievalRerank(buildSampleRequest(sample));
      setComparisonData(result);
      setComparisonStatus('success');
      await loadRecentCanary();
    } catch (err) {
      setComparisonError(formatApiError(err, '样本重跑对比'));
      setComparisonStatus('error');
    }
  };

  const handleApplyDefaultStrategy = async (nextStrategy: 'heuristic' | 'provider') => {
    setStrategyActionStatus('loading');
    setStrategyActionMessage('');
    try {
      const configPayload = await getSystemConfig();
      const updatedConfig = await updateSystemConfig({
        query_profiles: configPayload.query_profiles,
        model_routing: configPayload.model_routing,
        reranker_routing: {
          ...configPayload.reranker_routing,
          default_strategy: nextStrategy,
        },
        degrade_controls: configPayload.degrade_controls,
        retry_controls: configPayload.retry_controls,
        concurrency_controls: configPayload.concurrency_controls,
        prompt_budget: configPayload.prompt_budget,
      });
      const refreshedComparison = await compareRetrievalRerank(buildRequest());
      setComparisonData(refreshedComparison);
      await loadRecentCanary();
      setStrategyActionStatus('success');
      setStrategyActionMessage(
        nextStrategy === 'provider'
          ? `已把默认策略切到 provider（${updatedConfig.reranker_routing.provider} / ${updatedConfig.reranker_routing.model}）。`
          : '已把默认策略回滚到 heuristic。',
      );
    } catch (err) {
      setStrategyActionStatus('error');
      setStrategyActionMessage(formatApiError(err, '默认策略切换'));
    }
  };

  // 状态文本映射。
  const statusText = {
    idle: '待执行',
    loading: '正在检索',
    success: data ? `${data.results.length} 条命中 | 模式 ${MODE_TEXT[data.mode] || data.mode}` : '检索完成',
    error: '检索失败',
  };

  // 状态色调映射。
  const statusTone: Record<PanelStatus, 'default' | 'ok' | 'warn' | 'error'> = {
    idle: 'default',
    loading: 'warn',
    success: 'ok',
    error: 'error',
  };

  const scoreMeta = (item: RetrievedChunk) => [
    { label: '相关度', value: item.score.toFixed(4) },
    { label: '片段', value: item.chunk_id.slice(0, 12) + '...' },
  ];

  const debugMetrics = (item: RetrievedChunk) => {
    const metrics = [
      { label: '融合原始分', value: item.fused_score },
      { label: '向量分', value: item.vector_score },
      { label: '词法分', value: item.lexical_score },
    ].filter((metric) => metric.value !== null && metric.value !== undefined);

    if (metrics.length === 0) {
      return null;
    }

    return (
      <div className="mt-3 border-t border-[rgba(23,32,42,0.08)] pt-3">
        <p className="m-0 text-[11px] font-medium uppercase tracking-[0.18em] text-ink-soft">Debug</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-soft">
          {metrics.map((metric) => (
            <span
              key={metric.label}
              className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-1"
            >
              {metric.label} {(metric.value as number).toFixed(4)}
            </span>
          ))}
        </div>
      </div>
    );
  };

  const renderChunkCardBody = (item: RetrievedChunk, previewLimit: number) => (
    <>
      {item.text.length > previewLimit ? `${item.text.slice(0, previewLimit)}...` : item.text}
      <EvidenceSourceSummary
        retrievalStrategy={item.retrieval_strategy}
        ocrUsed={item.ocr_used}
        parserName={item.parser_name}
        pageNo={item.page_no}
        ocrConfidence={item.ocr_confidence}
        qualityScore={item.quality_score}
      />
      {debugMetrics(item)}
    </>
  );

  const comparisonDecisionPresentation = comparisonData
    ? getRerankDecisionPresentation(comparisonData.recommendation.decision, { canAccessAdmin })
    : null;
  const canaryFilterPresentation = canaryDecisionFilter === 'all'
    ? null
    : getRerankDecisionPresentation(canaryDecisionFilter, { canAccessAdmin });

  return (
    <Card className="col-span-6 max-md:col-span-12">
      {/* 标题 */}
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">知识检索</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        先看命中的知识片段，这是判断资料匹配质量最快的方式。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前资料：{currentDocumentName || '未选择资料'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前策略：有当前资料就按资料过滤；未指定时走全库检索（读取已入库知识片段）。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft break-all">
        {normalizedDocId ? `资料编号：${normalizedDocId}` : '资料编号：全库'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft break-all">
        {normalizedDocId
          ? `当前入库状态: ${currentJobStatus ? (JOB_STATE_TEXT[currentJobStatus] || currentJobStatus) : '-'}`
          : '当前入库状态: 全库模式（不依赖当前上传任务）'}
      </p>

      {/* 表单 */}
      <form onSubmit={handleSubmit} className="grid gap-3">
        {/* 查询输入 */}
        <Textarea
          label="查询问题"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          required
        />

        {/* 两列布局：Top K 和按钮 */}
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <Input
            label="Top K"
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            required
          />
          <div className="flex items-end">
            <Button
              type="submit"
              loading={status === 'loading'}
              className="w-full"
            >
              <span className="flex items-center justify-center gap-2">
                <Search className="w-4 h-4" />
                执行检索
              </span>
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-1">
          <Button
            type="button"
            loading={comparisonStatus === 'loading'}
            variant="ghost"
            onClick={handleCompareRerank}
          >
            对比当前 rerank 与 heuristic 基线
          </Button>
        </div>
      </form>

      {/* 状态徽章 */}
      <div className="mt-4">
        <StatusPill tone={statusTone[status]}>{statusText[status]}</StatusPill>
      </div>

      {/* 检索结果列表 */}
      <div className="mt-4 grid gap-3">
        {error ? (
          <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)]">
            <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm text-ink">{error}</pre>
          </div>
        ) : data?.results.length === 0 ? (
          <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)]">
            <pre className="m-0 font-mono text-sm text-ink">没有检索命中结果。</pre>
          </div>
        ) : (
          data?.results.map((item: RetrievedChunk, index: number) => (
            <ResultCard
              key={item.chunk_id}
              title={item.document_name}
              index={index}
              meta={scoreMeta(item)}
            >
              {renderChunkCardBody(item, 300)}
            </ResultCard>
          ))
        )}
      </div>

      <div className="mt-6 grid gap-3">
        <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
          <div>
            <h3 className="m-0 text-lg font-semibold text-ink">排序策略对比</h3>
            <p className="m-0 mt-1 text-sm text-ink-soft">
              在同一批检索候选上直接比较“当前默认排序策略”和“规则基线”，判断模型排序是否值得作为默认路径。
            </p>
          </div>
          <StatusPill tone={
            comparisonStatus === 'success'
              ? 'ok'
              : comparisonStatus === 'loading'
                ? 'warn'
                : comparisonStatus === 'error'
                  ? 'error'
                  : 'default'
          }>
            {comparisonStatus === 'success'
              ? `候选 ${comparisonData?.candidate_count ?? 0} / rerank ${comparisonData?.rerank_top_n ?? 0}`
              : comparisonStatus === 'loading'
                ? '正在对比'
                : comparisonStatus === 'error'
                  ? '对比失败'
                  : '尚未执行'}
          </StatusPill>
        </div>

        {comparisonError ? (
          <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)]">
            <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm text-ink">{comparisonError}</pre>
          </div>
        ) : null}

        {comparisonData ? (
          <>
            <div className="rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.8)] p-4">
              <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
                <strong className="text-ink">当前默认路由实时状态</strong>
                <StatusPill tone={
                  comparisonData.route_status.ready
                    ? comparisonData.route_status.effective_strategy === 'provider'
                      ? 'ok'
                      : 'warn'
                    : 'error'
                }>
                  {comparisonData.route_status.effective_provider} / {comparisonData.route_status.effective_strategy}
                </StatusPill>
              </div>
              <p className="m-0 mt-3 text-sm text-ink-soft">
                当前配置：{comparisonData.route_status.provider} / {comparisonData.route_status.model}
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                默认策略：{comparisonData.route_status.default_strategy}
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                当前生效：{comparisonData.route_status.effective_provider} / {comparisonData.route_status.effective_strategy}
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                当前模型：{comparisonData.route_status.effective_model}
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                冷却时间：{comparisonData.route_status.failure_cooldown_seconds}s / 剩余 {comparisonData.route_status.cooldown_remaining_seconds.toFixed(1)}s
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                回退开关：{comparisonData.route_status.fallback_enabled ? '开启' : '关闭'}
              </p>
              <p className="m-0 mt-1 text-sm text-ink-soft">
                锁定状态：{comparisonData.route_status.lock_active ? '已锁定' : '未锁定'}{comparisonData.route_status.lock_source ? ` / ${comparisonData.route_status.lock_source}` : ''}
              </p>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink">
                {comparisonData.route_status.detail || '无额外状态说明。'}
              </p>
            </div>

            <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
              <ResultCard
                title="当前默认路由"
                meta={[
                  { label: '服务商', value: comparisonData.configured.provider },
                  { label: '策略', value: comparisonData.configured.strategy },
                ]}
              >
                {comparisonData.configured.model || '无模型'}
              </ResultCard>
              <ResultCard
                title="heuristic 基线"
                meta={[
                  { label: '服务商', value: comparisonData.heuristic.provider },
                  { label: '策略', value: comparisonData.heuristic.strategy },
                ]}
              >
                token overlap + vector blended
              </ResultCard>
              <ResultCard
                title="重叠结果"
                meta={[
                  { label: '重叠数', value: String(comparisonData.summary.overlap_count) },
                  { label: '首位结果', value: comparisonData.summary.top1_same ? '一致' : '发生变化' },
                ]}
              >
                {comparisonData.mode}
              </ResultCard>
              <ResultCard
                title="差异摘要"
                meta={[
                  { label: '当前策略独有', value: String(comparisonData.summary.configured_only_chunk_ids.length) },
                  { label: '规则基线独有', value: String(comparisonData.summary.heuristic_only_chunk_ids.length) },
                ]}
              >
                {comparisonData.configured.provider === 'heuristic'
                  ? '当前默认路由本身就是 heuristic。'
                  : comparisonData.configured.strategy === 'provider'
                    ? '当前默认路由已真实使用模型 rerank。'
                    : '当前默认路由已降级到 heuristic。'}
              </ResultCard>
            </div>

            <div className="rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.8)] p-4">
              <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
                <strong className="text-ink">默认策略切换建议</strong>
                <StatusPill tone={comparisonDecisionPresentation?.tone || 'default'}>
                  {comparisonDecisionPresentation?.label || comparisonData.recommendation.decision}
                </StatusPill>
              </div>
              <p className="m-0 mt-2 text-sm font-semibold text-ink">
                {comparisonDecisionPresentation?.title || '当前样本已生成判读结论。'}
              </p>
              <p className="m-0 mt-2 text-xs uppercase tracking-[0.18em] text-ink-soft">
                {comparisonData.recommendation.decision}
              </p>
              <p className="m-0 mt-2 text-sm text-ink-soft leading-relaxed">
                {comparisonDecisionPresentation?.summary || comparisonData.recommendation.message}
              </p>
              <div className="mt-3 rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3 text-sm text-ink-soft">
                <strong className="block text-ink">推荐动作</strong>
                <p className="m-0 mt-2 leading-relaxed">
                  {comparisonDecisionPresentation?.recommendedAction || '先结合最新样本再判断是否需要切默认策略。'}
                </p>
              </div>
              <p className="m-0 mt-2 text-sm text-ink-soft">
                canary 样本：{comparisonData.canary_sample_id || '未记录'}
              </p>
              <p className="m-0 mt-2 text-sm text-ink-soft">
                后端说明：{comparisonData.recommendation.message}
              </p>
              <div className="mt-3 flex flex-wrap gap-3">
                {comparisonData.recommendation.decision === 'eligible' && comparisonData.route_status.default_strategy !== 'provider' && canAccessAdmin ? (
                  <Button
                    type="button"
                    loading={strategyActionStatus === 'loading'}
                    onClick={() => handleApplyDefaultStrategy('provider')}
                  >
                    切换到模型排序默认
                  </Button>
                ) : null}
                {comparisonData.recommendation.decision === 'rollback_active' && comparisonData.route_status.default_strategy === 'provider' && canAccessAdmin ? (
                  <Button
                    type="button"
                    variant="ghost"
                    loading={strategyActionStatus === 'loading'}
                    onClick={() => handleApplyDefaultStrategy('heuristic')}
                  >
                    恢复为规则基线默认
                  </Button>
                ) : null}
                {comparisonData.recommendation.decision === 'hold' ? (
                  <Button
                    type="button"
                    variant="ghost"
                    loading={comparisonStatus === 'loading'}
                    onClick={() => void handleCompareRerank()}
                  >
                    再跑一次当前 query
                  </Button>
                ) : null}
                {comparisonData.recommendation.decision === 'provider_active' ? (
                  <Button
                    type="button"
                    variant="ghost"
                    loading={comparisonStatus === 'loading'}
                    onClick={() => void handleCompareRerank()}
                  >
                    刷新当前对比
                  </Button>
                ) : null}
              </div>
              {!canAccessAdmin && (comparisonData.recommendation.decision === 'eligible' || comparisonData.recommendation.decision === 'rollback_active') ? (
                <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
                  当前账号没有系统配置写权限；如果样本判读成立，需要系统管理员执行默认策略切换或回滚。
                </p>
              ) : null}
              {strategyActionMessage ? (
                <div className="mt-3">
                  <StatusPill tone={
                    strategyActionStatus === 'success'
                      ? 'ok'
                      : strategyActionStatus === 'error'
                        ? 'error'
                        : strategyActionStatus === 'loading'
                          ? 'warn'
                          : 'default'
                  }>
                    {strategyActionStatus === 'success'
                      ? '已执行'
                      : strategyActionStatus === 'error'
                        ? '执行失败'
                        : strategyActionStatus === 'loading'
                          ? '执行中'
                          : '待执行'}
                  </StatusPill>
                  <p className="m-0 mt-2 text-sm text-ink-soft leading-relaxed">
                    {strategyActionMessage}
                  </p>
                </div>
              ) : null}
            </div>

            {comparisonData.configured.error_message ? (
              <div className="p-4 rounded-xl border border-dashed border-[rgba(182,70,47,0.2)] bg-[rgba(255,248,245,0.85)]">
                <p className="m-0 text-sm font-semibold text-ink">当前默认路由错误</p>
                <pre className="m-0 mt-2 whitespace-pre-wrap break-words font-mono text-sm text-ink">
                  {comparisonData.configured.error_message}
                </pre>
              </div>
            ) : null}

            <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
              <div className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="m-0 text-base font-semibold text-ink">当前默认路由结果</h4>
                  <StatusPill tone={comparisonData.configured.strategy === 'provider' ? 'ok' : 'warn'}>
                    {comparisonData.configured.provider} / {comparisonData.configured.strategy}
                  </StatusPill>
                </div>
                {comparisonData.configured.results.length === 0 ? (
                  <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)] text-sm text-ink-soft">
                    当前默认路由没有返回结果。
                  </div>
                ) : comparisonData.configured.results.map((item, index) => (
                  <ResultCard
                    key={`configured-${item.chunk_id}`}
                    title={item.document_name}
                    index={index}
                    meta={scoreMeta(item)}
                  >
                    {renderChunkCardBody(item, 220)}
                  </ResultCard>
                ))}
              </div>

              <div className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="m-0 text-base font-semibold text-ink">heuristic 基线结果</h4>
                  <StatusPill tone="default">heuristic</StatusPill>
                </div>
                {comparisonData.heuristic.results.length === 0 ? (
                  <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)] text-sm text-ink-soft">
                    heuristic 基线没有返回结果。
                  </div>
                ) : comparisonData.heuristic.results.map((item, index) => (
                  <ResultCard
                    key={`heuristic-${item.chunk_id}`}
                    title={item.document_name}
                    index={index}
                    meta={scoreMeta(item)}
                  >
                    {renderChunkCardBody(item, 220)}
                  </ResultCard>
                ))}
              </div>
            </div>

            {comparisonData.provider_candidate ? (
              <div className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="m-0 text-base font-semibold text-ink">模型排序候选结果</h4>
                  <StatusPill tone={comparisonData.provider_candidate.strategy === 'provider' ? 'ok' : 'warn'}>
                    {comparisonData.provider_candidate.provider} / {comparisonData.provider_candidate.strategy}
                  </StatusPill>
                </div>
                  <p className="m-0 text-sm text-ink-soft">
                  这组结果会显式尝试模型排序能力，即使当前默认策略仍固定在规则基线，也能直接用它判断是否值得切换默认策略。
                </p>
                {comparisonData.provider_candidate_summary ? (
                  <p className="m-0 text-sm text-ink-soft">
                    重叠 {comparisonData.provider_candidate_summary.overlap_count} / 首位结果 {comparisonData.provider_candidate_summary.top1_same ? '一致' : '发生变化'}
                  </p>
                ) : null}
                {comparisonData.provider_candidate.error_message ? (
                  <div className="p-4 rounded-xl border border-dashed border-[rgba(182,70,47,0.2)] bg-[rgba(255,248,245,0.85)]">
                    <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm text-ink">
                      {comparisonData.provider_candidate.error_message}
                    </pre>
                  </div>
                ) : comparisonData.provider_candidate.results.length === 0 ? (
                  <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)] text-sm text-ink-soft">
                    模型排序候选没有返回结果。
                  </div>
                ) : (
                  <div className="grid gap-3">
                    {comparisonData.provider_candidate.results.map((item, index) => (
                      <ResultCard
                        key={`provider-candidate-${item.chunk_id}`}
                        title={item.document_name}
                        index={index}
                        meta={scoreMeta(item)}
                      >
                        {renderChunkCardBody(item, 220)}
                      </ResultCard>
                    ))}
                  </div>
                )}
              </div>
            ) : null}

            <div className="grid gap-3">
              <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
                <div>
                  <h4 className="m-0 text-base font-semibold text-ink">最近 canary 样本</h4>
                  <p className="m-0 mt-1 text-sm text-ink-soft">
                    这里只显示最近真实 compare 样本，方便判断 provider/heuristic 的默认策略是否值得切换。
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <label className="inline-flex items-center gap-2 text-sm text-ink-soft">
                    <span>decision</span>
                    <select
                      value={canaryDecisionFilter}
                      onChange={(e) => setCanaryDecisionFilter(e.target.value as RerankCanaryDecisionFilter)}
                      className="h-10 rounded-2xl border border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.92)] px-3 text-sm text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.4)]"
                    >
                      {RERANK_CANARY_DECISION_FILTERS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <StatusPill tone={
                    canaryStatus === 'success'
                      ? 'ok'
                      : canaryStatus === 'loading'
                        ? 'warn'
                        : canaryStatus === 'error'
                          ? 'error'
                          : 'default'
                  }>
                    {canaryStatus === 'success'
                      ? `最近 ${canaryData?.items.length ?? 0} 条`
                      : canaryStatus === 'loading'
                        ? '正在加载'
                        : canaryStatus === 'error'
                          ? '加载失败'
                          : '未加载'}
                  </StatusPill>
                  <Button type="button" variant="ghost" onClick={() => void loadRecentCanary()} loading={canaryStatus === 'loading'}>
                    刷新样本
                  </Button>
                </div>
              </div>

              {canaryError ? (
                <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)]">
                  <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm text-ink">{canaryError}</pre>
                </div>
              ) : null}

              {!canaryError && canaryStatus === 'success' && !(canaryData?.items.length) ? (
                <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)] text-sm text-ink-soft">
                  当前筛选下没有 canary 样本。先执行一次 rerank 对比，或切换 decision 筛选再查看。
                </div>
              ) : null}

              {canaryFilterPresentation && canaryData?.items.length ? (
                <div className="rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.8)] p-4">
                  <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
                    <div>
                      <strong className="text-ink">当前 decision 筛选说明</strong>
                      <p className="m-0 mt-2 text-sm font-semibold text-ink">{canaryFilterPresentation.title}</p>
                    </div>
                    <StatusPill tone={canaryFilterPresentation.tone}>
                      {canaryFilterPresentation.label} / {canaryData.items.length} 条
                    </StatusPill>
                  </div>
                  <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
                    {canaryFilterPresentation.summary}
                  </p>
                  <div className="mt-3 rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3 text-sm text-ink-soft">
                    <strong className="block text-ink">推荐动作</strong>
                    <p className="m-0 mt-2 leading-relaxed">{canaryFilterPresentation.recommendedAction}</p>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setCanaryDecisionFilter('all')}
                    >
                      清除筛选
                    </Button>
                    {canaryFilterPresentation.pageActionLabel && canaryFilterPresentation.pageActionPath && canaryFilterPresentation.pageActionPath !== '/workspace/retrieval' ? (
                      <Button
                        type="button"
                        onClick={() => navigate(canaryFilterPresentation.pageActionPath as string)}
                      >
                        {canaryFilterPresentation.pageActionLabel}
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {canaryData?.items.map((sample) => {
                const configuredTopChunkIds = Array.isArray(sample.details.configured_top_chunk_ids)
                  ? (sample.details.configured_top_chunk_ids as string[])
                  : [];
                const heuristicTopChunkIds = Array.isArray(sample.details.heuristic_top_chunk_ids)
                  ? (sample.details.heuristic_top_chunk_ids as string[])
                  : [];
                const providerTopChunkIds = Array.isArray(sample.details.provider_candidate_top_chunk_ids)
                  ? (sample.details.provider_candidate_top_chunk_ids as string[])
                  : [];
                const isLatestCompared = comparisonData?.canary_sample_id === sample.sample_id;
                const sampleDecisionPresentation = getRerankDecisionPresentation(sample.recommendation.decision, { canAccessAdmin });
                return (
                  <div
                    key={sample.sample_id}
                    className={`rounded-2xl border p-4 text-sm ${isLatestCompared ? 'border-[rgba(182,70,47,0.38)] bg-[rgba(255,248,245,0.88)]' : 'border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.8)]'}`}
                  >
                    <div className="flex items-center justify-between gap-3 max-md:flex-col max-md:items-start">
                      <div>
                        <strong className="text-ink">{sample.sample_id}</strong>
                        <p className="m-0 mt-1 text-ink-soft">{formatLocalTime(sample.occurred_at)}</p>
                      </div>
                      <StatusPill tone={sampleDecisionPresentation.tone}>
                        {sampleDecisionPresentation.label}
                      </StatusPill>
                    </div>
                    <p className="m-0 mt-3 text-sm font-semibold text-ink">{sampleDecisionPresentation.title}</p>
                    <p className="m-0 mt-1 text-xs uppercase tracking-[0.18em] text-ink-soft">
                      {sample.recommendation.decision}
                    </p>
                    <p className="m-0 mt-3 text-ink leading-relaxed">{sample.query}</p>
                    <div className="mt-3 grid gap-1 text-ink-soft">
                      <p className="m-0">mode: {sample.mode} / candidate {sample.candidate_count} / rerank {sample.rerank_top_n}</p>
                      <p className="m-0">configured: {sample.configured_provider} / {sample.configured_strategy}</p>
                      <p className="m-0">effective: {sample.route_status.effective_provider} / {sample.route_status.effective_strategy}</p>
                      <p className="m-0">provider candidate: {sample.provider_candidate_strategy || '-'}{sample.provider_candidate_error_message ? ` / ${sample.provider_candidate_error_message}` : ''}</p>
                    </div>
                    <div className="mt-3 rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3 text-sm text-ink-soft">
                      <strong className="block text-ink">推荐动作</strong>
                      <p className="m-0 mt-2 leading-relaxed">{sampleDecisionPresentation.recommendedAction}</p>
                    </div>
                    <p className="m-0 mt-3 text-ink-soft leading-relaxed">判读说明：{sample.recommendation.message}</p>
                    <div className="mt-3 flex flex-wrap gap-3">
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => handleLoadSampleQuery(sample)}
                      >
                        载入这条 query
                      </Button>
                      <Button
                        type="button"
                        loading={comparisonStatus === 'loading'}
                        onClick={() => void handleReplaySampleCompare(sample)}
                      >
                        按样本重跑对比
                      </Button>
                      {sampleDecisionPresentation.pageActionLabel && sampleDecisionPresentation.pageActionPath && sampleDecisionPresentation.pageActionPath !== '/workspace/retrieval' ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => navigate(sampleDecisionPresentation.pageActionPath as string)}
                        >
                          {sampleDecisionPresentation.pageActionLabel}
                        </Button>
                      ) : null}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-ink-soft">
                      <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-1">
                        configured top: {configuredTopChunkIds.slice(0, 3).join(', ') || '-'}
                      </span>
                      <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-1">
                        heuristic top: {heuristicTopChunkIds.slice(0, 3).join(', ') || '-'}
                      </span>
                      <span className="inline-flex items-center rounded-full bg-[rgba(23,32,42,0.06)] px-2 py-1">
                        provider top: {providerTopChunkIds.slice(0, 3).join(', ') || '-'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)] text-sm text-ink-soft">
            先执行一次对比，再看当前默认排序策略是否真的优于规则基线。
          </div>
        )}
      </div>
    </Card>
  );
}
