import { ArrowRight, Layers3, Network, Workflow } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, HeroCard, StatusPill } from '@/components';
import { HealthPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

const quickLinks = [
  {
    to: '/documents',
    title: '文档中心',
    description: '上传文档、查看列表、预览内容、清理或重建向量。',
  },
  {
    to: '/retrieval',
    title: '检索验证',
    description: '直接检查召回 chunk，优先判断是否命中正确知识。',
  },
  {
    to: '/chat',
    title: '问答验证',
    description: '看流式回答、模型名和引用片段是否对得上。',
  },
];

export function OverviewPage() {
  const { currentDocumentName, currentDocId, latestJob, currentJobTone } = useUploadWorkspace();

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-[1.2fr_0.8fr] gap-5 max-[960px]:grid-cols-1">
        <HeroCard>
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
            v0.x 工作台骨架
          </div>
          <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
            页面先拆开，后面的企业能力才能低耦合往里加。
          </h2>
          <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
            现在不是重做前端，而是把单页 demo 调整成企业工作台结构。上传、检索、问答还是原来的真实链路，只是入口不再堆在一个页面里。
          </p>
        </HeroCard>

        <Card className="bg-panel border-[rgba(182,70,47,0.1)]">
          <p className="m-0 text-ink-soft">当前骨架覆盖</p>
          <strong className="block mt-2 text-2xl font-serif text-ink">
            总览 / 文档 / 检索 / 问答 / SOP / Admin
          </strong>
          <div className="mt-4 grid gap-2 text-sm text-ink-soft">
            <div className="flex items-center gap-2">
              <Layers3 className="h-4 w-4 text-accent-deep" />
              单页入口已拆分为独立业务页面
            </div>
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4 text-accent-deep" />
              上传上下文可跨页面复用
            </div>
            <div className="flex items-center gap-2">
              <Workflow className="h-4 w-4 text-accent-deep" />
              后续登录、SOP、权限可以按页扩展
            </div>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <HealthPanel />

        <Card className="col-span-8 max-md:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">当前工作入口</h3>
          <p className="m-0 mt-2 text-ink-soft leading-relaxed">
            先从文档中心建任务，再去检索和问答页做验证。没有当前文档时，检索和问答也支持全库模式。
          </p>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
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
                当前页面状态已经从 `App.tsx` 抽离，后续不需要再靠页面级 prop 一层层传。
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
