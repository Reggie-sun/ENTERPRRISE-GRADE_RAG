import {
  ArrowRight,
  BookOpenText,
  LibraryBig,
  MessageSquareText,
  Shield,
  Sparkles,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';
import { formatApiError, getDocuments, type DocumentSummary } from '@/api';

function toLocalTime(isoText: string): string {
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
}

export function PortalHomePage() {
  const { profile, canAccessWorkspace } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [recentDocs, setRecentDocs] = useState<DocumentSummary[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [error, setError] = useState('');
  const quickLinks = [
    {
      to: '/portal/chat',
      title: '智能问答',
      description: '直接提问，获取带引用的知识回答。',
      icon: MessageSquareText,
    },
    {
      to: '/portal/sop',
      title: 'SOP 中心',
      description: '上传文档生成草稿，并继续查看标准 SOP。',
      icon: BookOpenText,
    },
    {
      to: '/portal/library',
      title: '知识库',
      description: '浏览企业知识资料并在线预览。',
      icon: LibraryBig,
    },
    ...(canAccessWorkspace
      ? [{
        to: '/workspace',
        title: experience.workspaceEntryLabel,
        description: experience.workspaceBoundary,
        icon: Shield,
      }]
      : []),
  ];

  useEffect(() => {
    const loadRecentDocs = async () => {
      setStatus('loading');
      setError('');
      try {
        const payload = await getDocuments({ page: 1, page_size: 6, status: 'active' });
        setRecentDocs(payload.items);
        setStatus('success');
      } catch (err) {
        setStatus('error');
        setError(formatApiError(err, '首页资料加载'));
      }
    };

    void loadRecentDocs();
  }, []);

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            智能知识服务
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-5xl leading-tight text-ink">
            {experience.portalTitle}
          </h2>
          <p className="m-0 mt-4 max-w-[60ch] text-base leading-relaxed text-ink-soft">
            {experience.portalDescription}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              to="/portal/chat"
              className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-accent to-[#d16837] px-5 py-3 font-semibold text-white no-underline shadow-[0_18px_28px_rgba(182,70,47,0.24)] transition-transform duration-200 hover:-translate-y-0.5"
            >
              立即提问
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to="/portal/sop"
              className="inline-flex items-center gap-2 rounded-full bg-[rgba(255,255,255,0.8)] px-5 py-3 font-semibold text-ink no-underline transition-transform duration-200 hover:-translate-y-0.5 hover:bg-white"
            >
              生成 SOP
            </Link>
          </div>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.12)]">
          <p className="m-0 text-sm text-ink-soft">当前视角</p>
          <strong className="mt-2 block text-2xl font-serif text-ink">
            {experience.roleLabel}
          </strong>
          <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
            {scopeSummary}
          </p>
          <div className="mt-4 grid gap-3 text-sm leading-relaxed text-ink-soft">
            <p className="m-0 font-semibold text-ink">{experience.homeFocusTitle}</p>
            {experience.homeFocusPoints.map((item) => (
              <div key={item} className="flex items-start gap-2">
                <Sparkles className="mt-0.5 h-4 w-4 text-accent-deep" />
                {item}
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className={`grid grid-cols-12 gap-5 ${quickLinks.length === 4 ? '' : ''}`}>
        {quickLinks.map((item) => {
          const Icon = item.icon;
          const widthClass = quickLinks.length === 4 ? 'col-span-6 max-lg:col-span-12' : 'col-span-4 max-lg:col-span-12';
          return (
            <Link
              key={item.to}
              to={item.to}
              className={`${widthClass} rounded-[28px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.74)] p-5 no-underline transition-all duration-200 hover:-translate-y-0.5 hover:bg-white`}
            >
              <div className="inline-flex rounded-2xl bg-[rgba(182,70,47,0.1)] p-3 text-accent-deep">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="m-0 mt-4 text-xl font-semibold text-ink">{item.title}</h3>
              <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">{item.description}</p>
              <span className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-accent-deep">
                进入
                <ArrowRight className="h-4 w-4" />
              </span>
            </Link>
          );
        })}
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-lg:col-span-12">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">最近更新资料</h3>
              <p className="m-0 mt-2 text-sm text-ink-soft">
                {experience.libraryScopeDescription}
              </p>
            </div>
            <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : 'warn'}>
              {status === 'loading' && '资料加载中'}
              {status === 'success' && `已加载 ${recentDocs.length} 条`}
              {status === 'error' && '资料加载失败'}
              {status === 'idle' && '待加载'}
            </StatusPill>
          </div>
          <div className="mt-4 grid gap-3">
            {status === 'error' ? (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-relaxed text-accent-deep">
                {error}
              </div>
            ) : recentDocs.length > 0 ? (
              recentDocs.map((item) => (
                <Link
                  key={item.document_id}
                  to={`/portal/library?doc_id=${encodeURIComponent(item.document_id)}`}
                  className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.68)] p-4 no-underline transition-all duration-200 hover:bg-white"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="m-0 font-semibold text-ink break-all">{item.filename}</p>
                      <p className="m-0 mt-2 text-sm text-ink-soft">
                        {item.department_id || '未标注部门'} / {item.category_id || '未标注分类'}
                      </p>
                    </div>
                    <span className="text-xs text-ink-soft">{toLocalTime(item.updated_at)}</span>
                  </div>
                </Link>
              ))
            ) : (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-relaxed text-ink-soft">
                还没有可展示的知识资料。
              </div>
            )}
          </div>
        </Card>

        <Card className="col-span-5 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">推荐提问</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            系统会结合你的角色与部门范围，推荐更贴近日常工作的提问入口。
          </p>
          <div className="mt-4 grid gap-3">
            {experience.suggestedQuestions.map((item) => (
              <Link
                key={item}
                to={`/portal/chat?q=${encodeURIComponent(item)}`}
                className="rounded-2xl bg-[rgba(255,255,255,0.72)] px-4 py-3 text-sm font-medium leading-relaxed text-ink no-underline transition-all duration-200 hover:-translate-y-0.5 hover:bg-white"
              >
                {item}
              </Link>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}
