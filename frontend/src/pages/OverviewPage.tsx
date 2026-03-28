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
        ? '查看全局资料、在线预览内容并维护资料状态。'
        : '维护本部门资料、在线预览内容并保持资料更新。',
    },
    {
      to: '/workspace/retrieval',
      title: '知识检索',
      description: '查看问题是否命中正确资料与知识内容。',
    },
    {
      to: '/workspace/chat',
      title: '智能问答',
      description: '检查回答内容与引用依据是否符合当前权限范围。',
    },
    {
      to: '/workspace/logs',
      title: '操作记录',
      description: '按时间、动作和人员查看近期平台操作。',
    },
    {
      to: '/workspace/ops',
      title: '平台状态',
      description: '查看服务状态、任务排队和异常提醒。',
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
            管理中心总览
          </div>
          <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
            {experience.workspaceTitle}为资料管理、服务检查和平台运营提供统一入口。
          </h2>
          <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
            {experience.workspaceDescription}
          </p>
        </HeroCard>

        <Card className="bg-panel border-[rgba(182,70,47,0.1)]">
          <p className="m-0 text-ink-soft">当前管理范围</p>
          <strong className="block mt-2 text-2xl font-serif text-ink">
            {canAccessAdmin ? '总览 / 文档 / 检索 / 问答 / SOP / 后台' : '总览 / 文档 / 检索 / 问答 / SOP'}
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
          <h3 className="m-0 text-xl font-semibold text-ink">常用管理入口</h3>
          <p className="m-0 mt-2 text-ink-soft leading-relaxed">
            可以先在文档中心维护资料，再前往知识检索、智能问答和平台状态页面持续跟进服务质量与处理进度。
          </p>

          <div className={`mt-4 grid gap-3 ${quickLinks.length <= 4 ? 'md:grid-cols-2' : 'md:grid-cols-3'}`}>
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
              <h3 className="m-0 text-xl font-semibold text-ink">当前处理进度</h3>
              <p className="m-0 mt-2 text-ink-soft">
                这里会同步当前资料和处理状态，方便在不同功能页之间连续处理同一项工作。
              </p>
            </div>
            <StatusPill tone={latestJob ? currentJobTone : 'default'}>
              {latestJob ? `任务编号 ${latestJob.job_id}` : '当前暂无进行中任务'}
            </StatusPill>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3 text-sm text-ink-soft">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前资料</strong>
              <p className="m-0 mt-2 break-all">{currentDocumentName || '未选择资料'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">资料编号</strong>
              <p className="m-0 mt-2 break-all">{currentDocId || '-'}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">处理状态</strong>
              <p className="m-0 mt-2 break-all">{latestJob?.status || '尚未创建处理任务'}</p>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
