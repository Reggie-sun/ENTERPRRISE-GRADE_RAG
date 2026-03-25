import { ArrowRight, Layers3, Network, Workflow } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';
import { HealthPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function OverviewPage() {
  const { profile, canAccessAdmin } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const { currentDocumentName, currentDocId, latestJob, currentJobTone } = useUploadWorkspace();
  const quickLinks = [
    {
      to: '/workspace/documents',
      title: '文档中心',
      description: canAccessAdmin
        ? '查看全局文档、预览内容、清理或重建向量。'
        : '维护本部门文档、预览内容、清理或重建向量。',
    },
    {
      to: '/workspace/retrieval',
      title: '检索验证',
      description: '直接检查召回 chunk，优先判断是否命中正确知识。',
    },
    {
      to: '/workspace/chat',
      title: '问答验证',
      description: '看流式回答和引用是否与当前权限范围一致。',
    },
    ...(canAccessAdmin
      ? [{
        to: '/workspace/admin',
        title: '管理后台',
        description: '进入全局身份、权限和后续配置入口。',
      }]
      : []),
  ];

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-[1.2fr_0.8fr] gap-5 max-[960px]:grid-cols-1">
        <HeroCard>
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
            Workspace Overview
          </div>
          <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
            {experience.workspaceTitle}继续保留验证与排障能力，门户和工作台已经分开按角色演进。
          </h2>
          <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
            {experience.workspaceDescription}
          </p>
        </HeroCard>

        <Card className="bg-panel border-[rgba(182,70,47,0.1)]">
          <p className="m-0 text-ink-soft">当前工作台覆盖</p>
          <strong className="block mt-2 text-2xl font-serif text-ink">
            {canAccessAdmin ? '总览 / 文档 / 检索 / 问答 / SOP / Admin' : '总览 / 文档 / 检索 / 问答 / SOP'}
          </strong>
          <div className="mt-4 grid gap-2 text-sm text-ink-soft">
            <div className="flex items-center gap-2">
              <Layers3 className="h-4 w-4 text-accent-deep" />
              {experience.roleLabel}
            </div>
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4 text-accent-deep" />
              {scopeSummary}
            </div>
            <div className="flex items-center gap-2">
              <Workflow className="h-4 w-4 text-accent-deep" />
              {experience.workspaceBoundary}
            </div>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <HealthPanel />

        <Card className="col-span-8 max-md:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">当前内部入口</h3>
          <p className="m-0 mt-2 text-ink-soft leading-relaxed">
            先从文档中心维护资料，再去检索和问答页做验证。角色边界已经固定：普通员工留在门户，管理员才进入工作台。
          </p>

          <div className={`mt-4 grid gap-3 ${quickLinks.length === 4 ? 'md:grid-cols-2' : 'md:grid-cols-3'}`}>
            {quickLinks.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="rounded-3xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.72)] p-4 no-underline transition-all duration-200 hover:-translate-y-0.5 hover:bg-white"
              >
                <p className="m-0 text-lg font-semibold text-ink">{item.title}</p>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                  {item.description}
                </p>
                <span className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-accent-deep">
                  进入页面
                  <ArrowRight className="h-4 w-4" />
                </span>
              </Link>
            ))}
          </div>
        </Card>

        <Card className="col-span-12">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="m-0 text-xl font-semibold text-ink">当前上下文</h3>
              <p className="m-0 mt-2 text-ink-soft">
                当前页面状态已经从根入口抽离，工作台内部不需要再靠页面级 prop 一层层传。
              </p>
            </div>
            <StatusPill tone={latestJob ? currentJobTone : 'default'}>
              {latestJob ? `已跟踪 job: ${latestJob.job_id}` : '还没有当前任务'}
            </StatusPill>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3 text-sm text-ink-soft">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前文档</strong>
              <p className="m-0 mt-2 break-all">{currentDocumentName || '未选择文件'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前 doc_id</strong>
              <p className="m-0 mt-2 break-all">{currentDocId || '-'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前状态</strong>
              <p className="m-0 mt-2 break-all">{latestJob?.status || '尚未创建上传任务'}</p>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
