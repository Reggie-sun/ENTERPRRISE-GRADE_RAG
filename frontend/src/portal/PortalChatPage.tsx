import { MessageSquareText, Sparkles } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, StatusPill, Textarea } from '@/components';
import {
  ApiError,
  askQuestion,
  askQuestionStream,
  formatApiError,
  type ChatResponse,
  type ChatStreamMeta,
  type QueryMode,
} from '@/api';
import { getOrCreateStoredSessionId, rememberDocument, rememberQuestion } from '@/portal/portalStorage';

type PortalChatStatus = 'idle' | 'loading' | 'success' | 'error';
const PORTAL_STREAM_START_TIMEOUT_MS = 15_000;
const QUERY_MODE_OPTIONS: Array<{
  value: QueryMode;
  label: string;
  description: string;
}> = [
  { value: 'fast', label: '快速', description: '优先响应速度，适合常规提问。' },
  { value: 'accurate', label: '准确', description: '优先证据质量，响应会慢一些。' },
];

export function PortalChatPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [searchParams, setSearchParams] = useSearchParams();
  const searchQuestion = searchParams.get('q');
  const suggestedDefaultQuestion = experience.suggestedQuestions[0] ?? '';
  const initialQuestion = searchQuestion || suggestedDefaultQuestion;
  const [question, setQuestion] = useState(initialQuestion);
  const [queryMode, setQueryMode] = useState<QueryMode>('fast');
  const [sessionId] = useState(() => getOrCreateStoredSessionId('portal_chat_session_id'));
  const [status, setStatus] = useState<PortalChatStatus>('idle');
  const [data, setData] = useState<ChatResponse | null>(null);
  const [error, setError] = useState('');
  const activeRequestRef = useRef<{ controller: AbortController; reason: 'superseded' | 'unmounted' | 'startup-timeout' | null } | null>(null);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    if (searchQuestion) {
      setQuestion(searchQuestion);
      return;
    }
    setQuestion((current) => current || suggestedDefaultQuestion);
  }, [searchQuestion, suggestedDefaultQuestion]);

  useEffect(() => () => {
    if (activeRequestRef.current) {
      activeRequestRef.current.reason = 'unmounted';
      activeRequestRef.current.controller.abort();
      activeRequestRef.current = null;
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) {
      setStatus('error');
      setError('请输入问题后再发起问答。');
      return;
    }

    if (activeRequestRef.current) {
      activeRequestRef.current.reason = 'superseded';
      activeRequestRef.current.controller.abort();
    }

    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const controller = new AbortController();
    activeRequestRef.current = { controller, reason: null };
    let sawStreamEvent = false;
    let fallbackRequested = false;
    const requestPayload = { question: normalizedQuestion, mode: queryMode, session_id: sessionId } as const;
    const clearActiveRequest = () => {
      if (activeRequestRef.current?.controller === controller) {
        activeRequestRef.current = null;
      }
    };
    const markStreamEvent = () => {
      sawStreamEvent = true;
      window.clearTimeout(startupTimer);
    };
    const persistResponse = (response: ChatResponse) => {
      response.citations.forEach((item) => {
        rememberDocument({
          docId: item.document_id,
          fileName: item.document_name,
          departmentId: null,
          categoryId: null,
          source: 'chat',
        });
      });
      setData(response);
      setStatus('success');
      setSearchParams(
        normalizedQuestion
          ? new URLSearchParams({ q: normalizedQuestion })
          : new URLSearchParams(),
      );
    };
    const startupTimer = window.setTimeout(() => {
      if (!sawStreamEvent && activeRequestRef.current?.controller === controller) {
        fallbackRequested = true;
        activeRequestRef.current.reason = 'startup-timeout';
        controller.abort();
      }
    }, PORTAL_STREAM_START_TIMEOUT_MS);

    setStatus('loading');
    setError('');
    setData(null);
    rememberQuestion(normalizedQuestion);

    try {
      const response = await askQuestionStream(
        requestPayload,
        {
          onMeta: (meta: ChatStreamMeta) => {
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setData({
              question: meta.question,
              answer: '',
              mode: meta.mode,
              model: meta.model,
              citations: meta.citations,
            });
          },
          onDelta: (delta: string) => {
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setData((prev) => {
              if (!prev) {
                return {
                  question: normalizedQuestion,
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
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setData(done);
          },
        },
        { signal: controller.signal },
      );

      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      persistResponse(response);
    } catch (error) {
      let resolvedError: unknown = error;
      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      const abortReason = activeRequestRef.current?.controller === controller ? activeRequestRef.current.reason : null;
      const shouldFallback =
        !sawStreamEvent &&
        (fallbackRequested ||
          (resolvedError instanceof ApiError &&
            (resolvedError.kind === 'timeout' || resolvedError.kind === 'network' || resolvedError.kind === 'parse')));
      if (shouldFallback && abortReason !== 'superseded' && abortReason !== 'unmounted') {
        try {
          const fallbackResponse = await askQuestion(requestPayload);
          if (requestVersionRef.current !== requestVersion) {
            return;
          }
          persistResponse(fallbackResponse);
          return;
        } catch (fallbackError) {
          resolvedError = fallbackError;
        }
      }
      if (abortReason === 'superseded' || abortReason === 'unmounted') {
        return;
      }
      setStatus('error');
      setError(formatApiError(resolvedError, '智能问答'));
    } finally {
      window.clearTimeout(startupTimer);
      clearActiveRequest();
    }
  };

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-12">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold text-accent-deep">
                <MessageSquareText className="h-4 w-4" />
                智能问答
              </div>
              <h2 className="m-0 mt-4 text-2xl font-semibold text-ink md:text-3xl">
                输入问题后，系统会直接返回回答。
              </h2>
              <p className="m-0 mt-2 max-w-[64ch] text-sm leading-relaxed text-ink-soft md:text-base">
                首屏只保留提问和回答。当前会话会自动承接最近几轮上下文，如需完全切换话题，刷新页面即可重置。
              </p>
            </div>
            <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : status === 'loading' ? 'warn' : 'default'}>
              {status === 'idle' && '等待提问'}
              {status === 'loading' && '回答生成中'}
              {status === 'success' && '回答已生成'}
              {status === 'error' && '问答失败'}
            </StatusPill>
          </div>

          <div className="mt-5 rounded-[24px] border border-[rgba(182,70,47,0.12)] bg-[rgba(255,248,240,0.72)] p-4">
            <div className="flex items-start gap-2 text-sm leading-relaxed text-ink-soft">
              <Sparkles className="mt-0.5 h-4 w-4 flex-none text-accent-deep" />
              <div className="grid gap-1">
                <p className="m-0 font-semibold text-ink">当前回答范围</p>
                <p className="m-0">{scopeSummary}</p>
                <p className="m-0">{experience.portalHeaderNote}</p>
                <p className="m-0">如果回答偏泛，优先把问题写成设备、场景、工序或报警条件。</p>
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="mt-5 grid gap-4">
            <Textarea
              label="请输入你的问题"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：设备报警后，标准处理流程是什么？"
              required
            />
            <div className="flex flex-wrap gap-2">
              {experience.suggestedQuestions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="rounded-full bg-[rgba(23,32,42,0.06)] px-3 py-2 text-sm text-ink transition-all duration-200 hover:-translate-y-0.5"
                  onClick={() => setQuestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="grid gap-2">
              <div className="text-sm font-semibold text-ink">回答档位</div>
              <div className="flex flex-wrap gap-2">
                {QUERY_MODE_OPTIONS.map((item) => {
                  const active = queryMode === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      className={`
                        rounded-full px-4 py-2 text-sm font-semibold transition-all duration-200
                        ${active
                          ? 'bg-[rgba(182,70,47,0.14)] text-accent-deep shadow-[0_10px_20px_rgba(182,70,47,0.14)]'
                          : 'bg-[rgba(23,32,42,0.06)] text-ink hover:-translate-y-0.5'
                        }
                      `}
                      onClick={() => setQueryMode(item.value)}
                    >
                      {item.label}
                    </button>
                  );
                })}
              </div>
              <p className="m-0 text-sm leading-relaxed text-ink-soft">
                {QUERY_MODE_OPTIONS.find((item) => item.value === queryMode)?.description}
              </p>
            </div>
            <div className="flex justify-end">
              <Button type="submit" loading={status === 'loading'} className="min-w-[160px]">
                <span className="flex items-center gap-2">
                  <MessageSquareText className="h-4 w-4" />
                  发起问答
                </span>
              </Button>
            </div>
          </form>

          <div className="mt-5 rounded-[28px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.72)] p-5">
            {error ? (
              <p className="m-0 whitespace-pre-wrap leading-relaxed text-accent-deep">{error}</p>
            ) : (
              <div className="min-h-[280px] whitespace-pre-wrap text-base leading-8 text-ink">
                {data?.answer || '回答会在这里以流式方式逐步展示。'}
              </div>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
