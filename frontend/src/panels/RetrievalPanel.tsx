/**
 * 检索面板组件
 * 用于测试文档检索功能
 */

import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';  // 引入图标。
import { Card, Button, StatusPill, Textarea, Input, ResultCard } from '@/components';
import {
  formatApiError,
  searchDocuments,
  type RetrievalResponse,
  type RetrievedChunk,
  type IngestJobStatus,
} from '@/api';

// 检索模式中文映射。
const MODE_TEXT: Record<string, string> = {
  qdrant: 'Qdrant 向量检索',
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
  const normalizedDocId = currentDocId?.trim();

  // 表单状态。
  const [query, setQuery] = useState('这份文档主要讲了什么？');
  const [topK, setTopK] = useState(5);

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [data, setData] = useState<RetrievalResponse | null>(null);
  const [error, setError] = useState<string>('');

  // 每次新上传文档时，自动清空旧的检索结果。
  useEffect(() => {
    setData(null);
    setError('');
    setStatus('idle');
  }, [resetSignal]);

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
      const result = await searchDocuments({
        query: query.trim(),
        top_k: topK,
        document_id: normalizedDocId || undefined,
      });
      setData(result);
      setStatus('success');
    } catch (err) {
      setError(formatApiError(err, '文档检索'));
      setStatus('error');
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

  return (
    <Card className="col-span-6 max-md:col-span-12">
      {/* 标题 */}
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">检索测试</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        先看生成前的 top chunks，这是判断召回质量最快的方式。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前文档：{currentDocumentName || '未选择文件'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前策略：有当前文档就按文档过滤；未指定时走全库检索（读取已入库 chunk）。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft break-all">
        {normalizedDocId ? `document_id: ${normalizedDocId}` : 'document_id: 全库'}
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
              meta={[
                { label: '分数', value: item.score.toFixed(4) },
                { label: '', value: item.chunk_id.slice(0, 12) + '...' },
              ]}
            >
              {item.text.length > 300 ? `${item.text.slice(0, 300)}...` : item.text}
            </ResultCard>
          ))
        )}
      </div>
    </Card>
  );
}
