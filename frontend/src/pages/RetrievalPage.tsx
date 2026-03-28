import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';
import { RetrievalPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function RetrievalPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const {
    currentDocumentName,
    currentDocId,
    latestJob,
    panelResetSignal,
  } = useUploadWorkspace();

  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
          知识检索
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          检索页用于确认资料命中是否准确，并验证结果没有超出当前权限范围。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          先看命中的知识片段，再判断问题来自检索策略、资料切分方式还是资料标签设置。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <RetrievalPanel
          resetSignal={panelResetSignal}
          currentDocumentName={currentDocumentName}
          currentDocId={currentDocId}
          currentJobStatus={latestJob?.status}
        />

        <Card className="col-span-6 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">检索页说明</h3>
          <div className="mt-4">
            <StatusPill tone={currentDocId ? 'warn' : 'default'}>
              {currentDocId ? '当前按文档过滤' : '当前为全库检索模式'}
            </StatusPill>
          </div>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0 leading-relaxed">
              有当前资料编号时，这页会直接按当前资料过滤；没有当前资料时，检索会直接命中系统里已有的知识片段，不需要重新上传。
            </p>
            <p className="m-0 leading-relaxed">{scopeSummary}</p>
            <p className="m-0 break-all">
              当前资料：{currentDocumentName || '全库模式'}
            </p>
            <p className="m-0 break-all">
              当前任务状态：{latestJob?.status || '未绑定任务'}
            </p>
          </div>
        </Card>
      </section>
    </div>
  );
}
