/**
 * 问答面板组件
 * 用于测试带引用的 RAG 问答功能
 */

import { useEffect, useState } from 'react';
import { MessageSquare } from 'lucide-react';  // 引入图标。
import { Card, Button, StatusPill, Textarea, Input, ResultBox, ResultCard } from '@/components';
import { askQuestion, type ChatResponse, type Citation } from '@/api';

// 回答模式中文映射。
const MODE_TEXT: Record<string, string> = {
  qdrant: 'Qdrant 向量检索',
  rag: 'RAG 回答',
  retrieval_fallback: '检索回退',
  no_context: '无上下文',
  mock: '模拟模式',
};

// 面板状态类型。
type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

interface ChatPanelProps {
  resetSignal?: number;
  currentDocumentName?: string;
  currentDocId?: string;
}

export function ChatPanel({ resetSignal, currentDocumentName, currentDocId }: ChatPanelProps) {
  // 表单状态。
  const [question, setQuestion] = useState('总结这份已上传文档里最相关的内容。');
  const [topK, setTopK] = useState(5);

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [data, setData] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<string>('');

  // 每次新上传文档时，自动清空旧的问答结果和错误状态。
  useEffect(() => {
    setData(null);
    setError('');
    setStatus('idle');
  }, [resetSignal]);

  // 发起问答。
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus('loading');
    setError('');

    try {
      const normalizedDocId = currentDocId?.trim();
      const result = await askQuestion({
        question: question.trim(),
        top_k: topK,
        document_id: normalizedDocId || undefined,
      });
      setData(result);
      setStatus('success');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  };

  // 状态文本映射。
  const statusText = {
    idle: '待执行',
    loading: '正在生成回答',
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
        把真实问题发给 chat 接口，直接看回答模式、模型名和引用片段。
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        当前文档：{currentDocumentName || '未选择文件'}
      </p>
      <p className="m-0 mb-3 text-sm text-ink-soft">
        未指定当前文档时，会按全库范围执行问答。
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
            <Button type="submit" loading={status === 'loading'} className="w-full">
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
                { label: '', value: item.chunk_id.slice(0, 12) + '...' },
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
