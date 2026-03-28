/**
 * 问答面板组件
 * 用于测试带引用的 RAG 问答功能
 */

import { useEffect, useState } from 'react';
import { MessageSquare } from 'lucide-react';  // 引入图标。
import { Card, Button, StatusPill, Textarea, Input, ResultBox, ResultCard } from '@/components';
import {
  askQuestionStream,
  formatApiError,
  type ChatResponse,
  type ChatStreamMeta,
  type Citation,
  type IngestJobStatus,
} from '@/api';
import { resetStoredSessionId } from '@/portal/portalStorage';

// 回答模式中文映射。
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

interface ChatPanelProps {
  resetSignal?: number;
  currentDocumentName?: string;
  currentDocId?: string;
  currentJobStatus?: IngestJobStatus;
}

export function ChatPanel({ resetSignal, currentDocumentName, currentDocId, currentJobStatus }: ChatPanelProps) {
  const normalizedDocId = currentDocId?.trim();

  // 表单状态。
  const [question, setQuestion] = useState('总结这份已上传文档里最相关的内容。');
  const [topK, setTopK] = useState(5);
  const [sessionId, setSessionId] = useState(() => resetStoredSessionId('workspace_chat_session_id'));

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [data, setData] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<string>('');

  // 每次新上传文档时，自动清空旧的问答结果和错误状态。
  useEffect(() => {
    setData(null);
    setError('');
    setStatus('idle');
    setSessionId(resetStoredSessionId('workspace_chat_session_id'));
  }, [resetSignal]);

  useEffect(() => {
    setSessionId(resetStoredSessionId('workspace_chat_session_id'));
  }, [normalizedDocId]);

  // 发起问答。
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (normalizedDocId && currentJobStatus !== 'completed') {
      const jobText = JOB_STATE_TEXT[currentJobStatus || ''] || currentJobStatus || '-';
      setStatus('error');
      setData(null);
      setError(`当前文档尚未完成入库（状态：${jobText}），暂不能问答。请等待任务完成后重试。`);
      return;
    }
    setStatus('loading');
    setError('');
    setData(null);  // 每次新请求先清空旧结果，避免误判为本轮流式内容。

    try {
      const result = await askQuestionStream(
        {
          question: question.trim(),
          top_k: topK,
          session_id: sessionId,
          document_id: normalizedDocId || undefined,
        },
        {
          onMeta: (meta: ChatStreamMeta) => {
            setData({
              question: meta.question,
              answer: '',
              mode: meta.mode,
              model: meta.model,
              citations: meta.citations,
            });
          },
          onDelta: (delta: string) => {
            setData((prev) => {
              if (!prev) {  // 极端情况下 delta 比 meta 先到，给一个兜底结构。
                return {
                  question: question.trim(),
                  answer: delta,
                  mode: 'rag',
                  model: '-',
                  citations: [],
                };
              }
              return { ...prev, answer: `${prev.answer}${delta}` };
            });
          },
          onDone: (done: ChatResponse) => {
            setData(done);
          },
        }
      );
      setData(result);
      setStatus('success');
    } catch (err) {
      setError(formatApiError(err, '文档问答'));
      setStatus('error');
    }
  };

  // 状态文本映射。
  const statusText = {
    idle: '待执行',
    loading: data ? `流式输出中 | 模型 ${data.model}` : '正在生成回答',
    success: data ? `${MODE_TEXT[data.mode] || data.mode} | 模型 ${data.model}` : '回答完成',
    error: '问答请求失败',
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
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">带引用的问答</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        输入真实问题，直接查看回答模式、模型信息和引用片段。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前资料：{currentDocumentName || '未选择资料'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前策略：有当前资料就按资料过滤；未指定时走全库问答（基于已入库知识片段）。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft break-all">
        {normalizedDocId ? `资料编号：${normalizedDocId}` : '资料编号：全库'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft break-all">
        {normalizedDocId
          ? `当前入库状态: ${currentJobStatus ? (JOB_STATE_TEXT[currentJobStatus] || currentJobStatus) : '-'}`
          : '当前入库状态: 全库模式（不依赖当前上传任务）'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        同一资料下会自动承接最近几轮追问；切换资料或重新上传后，会话上下文会自动重置。
      </p>

      {/* 表单 */}
      <form onSubmit={handleSubmit} className="grid gap-3">
        {/* 问题输入 */}
        <Textarea
          label="问题"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
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
                <MessageSquare className="w-4 h-4" />
                发起问答
              </span>
            </Button>
          </div>
        </div>
      </form>

      {/* 状态徽章 */}
      <div className="mt-4">
        <StatusPill tone={statusTone[status]}>{statusText[status]}</StatusPill>
      </div>

      {/* 回答展示 */}
      <div className="mt-4">
        <ResultBox>
          {data ? data.answer : error ? error : '还没有回答。'}
        </ResultBox>
      </div>

      {/* 引用片段列表 */}
      {data && data.citations.length > 0 && (
        <div className="mt-4 grid gap-3">
          <h3 className="text-lg font-semibold text-ink m-0">引用来源</h3>
          {data.citations.map((item: Citation, index: number) => (
            <ResultCard
              key={item.chunk_id}
              title={item.document_name}
              index={index}
              meta={[
                { label: '分数', value: item.score.toFixed(4) },
                { label: '片段', value: item.chunk_id.slice(0, 12) + '...' },
              ]}
            >
              {item.snippet.length > 300 ? `${item.snippet.slice(0, 300)}...` : item.snippet}
            </ResultCard>
          ))}
        </div>
      )}
    </Card>
  );
}
