import { MessageSquareText, Sparkles } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, StatusPill, Textarea } from '@/components';
import {
  askQuestionStream,
  formatApiError,
  type ChatResponse,
  type ChatStreamMeta,
  type Citation,
  type QueryMode,
} from '@/api';
import { rememberDocument, rememberQuestion } from '@/portal/portalStorage';

type PortalChatStatus = 'idle' | 'loading' | 'success' | 'error';
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
  const [status, setStatus] = useState<PortalChatStatus>('idle');
  const [data, setData] = useState<ChatResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (searchQuestion) {
      setQuestion(searchQuestion);
      return;
    }
    setQuestion((current) => current || suggestedDefaultQuestion);
  }, [searchQuestion, suggestedDefaultQuestion]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) {
      setStatus('error');
      setError('请输入问题后再发起问答。');
      return;
    }

    setStatus('loading');
    setError('');
    setData(null);
    rememberQuestion(normalizedQuestion);

    try {
      const response = await askQuestionStream(
        { question: normalizedQuestion, mode: queryMode },
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
            setData(done);
          },
        },
      );

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
    } catch (err) {
      setStatus('error');
      setError(formatApiError(err, '智能问答'));
    }
  };

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            Intelligent Q&A
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            直接提问题，系统会给出流式回答并附上参考来源。
          </h2>
          <p className="m-0 mt-3 max-w-[62ch] text-base leading-relaxed text-ink-soft">
            这里不展示模型名、检索模式和调试分数，只保留客户真正需要理解的信息：
            回答内容、参考出处，以及回答当前基于什么权限范围生成。
          </p>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <div className="flex items-center gap-2 text-accent-deep">
            <Sparkles className="h-4 w-4" />
            <span className="text-sm font-semibold">当前回答范围</span>
          </div>
          <div className="mt-4 grid gap-3 text-sm leading-relaxed text-ink-soft">
            <p className="m-0">{scopeSummary}</p>
            <p className="m-0">{experience.portalHeaderNote}</p>
            <p className="m-0">如果回答偏泛，优先把问题写成设备、场景、工序或报警条件。</p>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-8 max-lg:col-span-12">
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
            <div className="flex items-center justify-between gap-3">
              <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : status === 'loading' ? 'warn' : 'default'}>
                {status === 'idle' && '等待提问'}
                {status === 'loading' && '回答生成中'}
                {status === 'success' && '回答已生成'}
                {status === 'error' && '问答失败'}
              </StatusPill>
              <Button type="submit" loading={status === 'loading'}>
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
              <div className="min-h-40 whitespace-pre-wrap text-base leading-8 text-ink">
                {data?.answer || '回答会在这里以流式方式逐步展示。'}
              </div>
            )}
          </div>
        </Card>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">引用来源</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            回答基于下列文档片段生成。你可以继续查看原文确认细节。
          </p>
          <div className="mt-4 grid gap-3">
            {data?.citations.length ? (
              data.citations.map((item: Citation) => (
                <article
                  key={item.chunk_id}
                  className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.72)] p-4"
                >
                  <p className="m-0 font-semibold text-ink break-all">{item.document_name}</p>
                  <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                    {item.snippet.length > 180 ? `${item.snippet.slice(0, 180)}...` : item.snippet}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link
                      to={`/portal/library?doc_id=${encodeURIComponent(item.document_id)}`}
                      className="rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-semibold text-accent-deep no-underline"
                    >
                      查看资料
                    </Link>
                    <Link
                      to={`/portal/sop?doc_id=${encodeURIComponent(item.document_id)}`}
                      className="rounded-full bg-[rgba(23,32,42,0.06)] px-3 py-1.5 text-sm font-semibold text-ink no-underline"
                    >
                      去 SOP 中心
                    </Link>
                  </div>
                </article>
              ))
            ) : (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-relaxed text-ink-soft">
                回答完成后，这里会显示对应的参考来源。
              </div>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
