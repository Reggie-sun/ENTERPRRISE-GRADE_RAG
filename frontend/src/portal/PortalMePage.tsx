import { Clock3, FileClock, MessageSquareMore, Shield } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard } from '@/components';
import {
  loadRecentDocuments,
  loadRecentQuestions,
  type RecentDocumentItem,
  type RecentQuestionItem,
} from '@/portal/portalStorage';

function toLocalTime(isoText: string): string {
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
}

export function PortalMePage() {
  const { profile, canAccessWorkspace } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const location = useLocation();
  const [recentQuestions, setRecentQuestions] = useState<RecentQuestionItem[]>([]);
  const [recentDocuments, setRecentDocuments] = useState<RecentDocumentItem[]>([]);

  useEffect(() => {
    setRecentQuestions(loadRecentQuestions());
    setRecentDocuments(loadRecentDocuments());
  }, [location.key]);

  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
          My Portal
        </div>
        <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
          把当前账号、最近提问和最近查看资料收进一个个人入口。
        </h2>
        <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
          当前已经接入登录与最小权限上下文。“我的”页面先把你的角色、数据范围和使用建议讲清楚，后续再继续扩展个人资料、收藏和推荐能力。
        </p>

        <div className="mt-5 grid gap-3 md:grid-cols-3 text-sm text-ink-soft">
          <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
            <strong className="block text-ink">当前账号</strong>
            <p className="m-0 mt-2">{profile?.user.display_name || profile?.user.username}</p>
          </div>
          <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
            <strong className="block text-ink">当前角色</strong>
            <p className="m-0 mt-2">{experience.roleLabel}</p>
          </div>
          <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
            <strong className="block text-ink">当前权限范围</strong>
            <p className="m-0 mt-2 leading-relaxed">{scopeSummary}</p>
          </div>
        </div>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-5 max-lg:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">你当前可以做什么</h3>
          <div className="mt-4 grid gap-3 text-sm leading-relaxed text-ink-soft">
            {experience.myCapabilityItems.map((item) => (
              <div key={item} className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                {item}
              </div>
            ))}
          </div>
          {canAccessWorkspace ? (
            <Link
              to="/workspace"
              className="mt-4 inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.1)] px-4 py-2 text-sm font-semibold text-accent-deep no-underline"
            >
              <Shield className="h-4 w-4" />
              {experience.workspaceEntryLabel}
            </Link>
          ) : null}
        </Card>

        <Card className="col-span-7 max-lg:col-span-12">
          <div className="flex items-center gap-2">
            <MessageSquareMore className="h-5 w-5 text-accent-deep" />
            <h3 className="m-0 text-xl font-semibold text-ink">最近提问</h3>
          </div>
          <div className="mt-4 grid gap-3">
            {recentQuestions.length ? (
              recentQuestions.map((item) => (
                <Link
                  key={`${item.question}-${item.askedAt}`}
                  to={`/portal/chat?q=${encodeURIComponent(item.question)}`}
                  className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 no-underline transition-all duration-200 hover:-translate-y-0.5 hover:bg-white"
                >
                  <p className="m-0 font-medium text-ink">{item.question}</p>
                  <p className="m-0 mt-2 text-xs text-ink-soft">{toLocalTime(item.askedAt)}</p>
                </Link>
              ))
            ) : (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-relaxed text-ink-soft">
                还没有历史提问。可以先去智能问答页发起一次问题。
              </div>
            )}
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <div className="flex items-center gap-2">
            <FileClock className="h-5 w-5 text-accent-deep" />
            <h3 className="m-0 text-xl font-semibold text-ink">最近查看资料</h3>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {recentDocuments.length ? (
              recentDocuments.map((item) => (
                <Link
                  key={`${item.docId}-${item.viewedAt}`}
                  to={`/portal/library?doc_id=${encodeURIComponent(item.docId)}`}
                  className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 no-underline transition-all duration-200 hover:-translate-y-0.5 hover:bg-white"
                >
                  <p className="m-0 font-medium text-ink break-all">{item.fileName}</p>
                  <p className="m-0 mt-2 text-sm text-ink-soft">
                    {item.departmentId || '未标注部门'} / {item.categoryId || '未标注分类'}
                  </p>
                  <div className="mt-2 flex items-center gap-2 text-xs text-ink-soft">
                    <Clock3 className="h-3.5 w-3.5" />
                    {toLocalTime(item.viewedAt)}
                  </div>
                </Link>
              ))
            ) : (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-relaxed text-ink-soft">
                还没有最近查看的资料。可以去 SOP 中心或知识库页面浏览文档。
              </div>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
