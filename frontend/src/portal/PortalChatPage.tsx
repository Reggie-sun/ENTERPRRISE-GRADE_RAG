import { MessageSquareText } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { getRoleExperience, useAuth } from '@/auth';
import { Button, Card, EvidenceSourceSummary, StatusPill, Textarea } from '@/components';
import {
  ApiError,
  askQuestion,
  askQuestionStream,
  formatApiError,
  type ChatResponse,
  type ChatStreamMeta,
  type Citation,
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
  const shouldShowSources = status === 'success' && Boolean(data?.citations.length);

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
          <form onSubmit={handleSubmit} className="grid gap-4">
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
                  className="rounded-full bg-[rgba(15,23,42,0.06)] px-3 py-2 text-sm text-ink transition-all duration-200 hover:-translate-y-0.5"
                  onClick={() => setQuestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-start justify-between gap-4">
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
                            ? 'bg-[rgba(194,65,12,0.14)] text-accent-deep shadow-[0_10px_20px_rgba(194,65,12,0.14)]'
                            : 'bg-[rgba(15,23,42,0.06)] text-ink hover:-translate-y-0.5'
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

              <div className="flex flex-wrap items-center justify-end gap-3 self-start max-sm:w-full max-sm:justify-start">
                <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : status === 'loading' ? 'warn' : 'default'}>
                  {status === 'idle' && '等待提问'}
                  {status === 'loading' && '回答生成中'}
                  {status === 'success' && '回答已生成'}
                  {status === 'error' && '问答失败'}
                </StatusPill>
                <Button type="submit" loading={status === 'loading'} className="min-w-[160px]">
                  <span className="flex items-center gap-2">
                    <MessageSquareText className="h-4 w-4" />
                    发起问答
                  </span>
                </Button>
              </div>
            </div>
          </form>

          <div className="mt-5 rounded-2xl border border-[rgba(15,23,42,0.08)] bg-[rgba(255,255,255,0.72)] p-5">
            {error ? (
              <p className="m-0 whitespace-pre-wrap leading-relaxed text-accent-deep">{error}</p>
            ) : (
              <div className="min-h-[280px] whitespace-pre-wrap text-base leading-8 text-ink">
                {data?.answer || '回答会在这里以流式方式逐步展示。'}
              </div>
            )}
          </div>

          {shouldShowSources ? (
            <section className="mt-4 rounded-2xl border border-[rgba(15,23,42,0.08)] bg-[rgba(255,255,255,0.72)] p-4">
              <h3 className="m-0 text-base font-semibold text-ink">信息来源</h3>
              <div className="mt-3 grid gap-3">
                {data?.citations.map((item: Citation) => (
                  <article
                    key={item.chunk_id}
                    className="rounded-2xl border border-[rgba(15,23,42,0.08)] bg-[rgba(255,255,255,0.78)] p-4"
                  >
                    <p className="m-0 font-semibold text-ink break-all">{item.document_name}</p>
                    <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                      {item.snippet.length > 220 ? `${item.snippet.slice(0, 220)}...` : item.snippet}
                    </p>
                    <EvidenceSourceSummary
                      retrievalStrategy={item.retrieval_strategy}
                      ocrUsed={item.ocr_used}
                      parserName={item.parser_name}
                      pageNo={item.page_no}
                      ocrConfidence={item.ocr_confidence}
                      qualityScore={item.quality_score}
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Link
                        to={`/portal/library?doc_id=${encodeURIComponent(item.document_id)}`}
                        className="rounded-full bg-[rgba(194,65,12,0.09)] px-3 py-1.5 text-sm font-semibold text-accent-deep no-underline"
                      >
                        查看资料
                      </Link>
                      <Link
                        to={`/portal/sop?doc_id=${encodeURIComponent(item.document_id)}`}
                        className="rounded-full bg-[rgba(15,23,42,0.06)] px-3 py-1.5 text-sm font-semibold text-ink no-underline"
                      >
                        去 SOP 中心
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ) : null}
        </Card>
      </section>
    </div>
  );
}
