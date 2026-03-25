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
          Retrieval
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          检索页只负责确认召回是否正确，并验证结果没有跨出当前权限范围。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          先看 top chunks 命中什么，再决定问题是 embedding、切块、元数据过滤还是向量索引。
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
              有当前 doc_id 时，这页会直接按当前文档过滤；没有当前文档时，检索会直接命中数据库里已经存在的 chunk，不需要重新上传。
            </p>
            <p className="m-0 leading-relaxed">{scopeSummary}</p>
            <p className="m-0 break-all">
              当前文档：{currentDocumentName || '全库模式'}
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
