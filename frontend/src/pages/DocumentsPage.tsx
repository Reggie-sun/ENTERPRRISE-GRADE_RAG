import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';
import { DocumentListPanel, UploadPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function DocumentsPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const {
    currentDocumentName,
    currentDocId,
    currentJobStageText,
    currentJobTone,
    handleUploadStart,
    handleUploadCreated,
    handleJobStatusChange,
    handleUploadFailed,
  } = useUploadWorkspace();

  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
          资料管理
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          文档中心负责当前权限范围内的资料上传、资料列表和后续维护操作。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          这里提供上传、预览、删除和知识索引更新等管理能力，普通员工不会直接进入这一页。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-4 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前任务摘要</h3>
          <div className="mt-4">
            <StatusPill tone={currentJobTone}>{currentJobStageText}</StatusPill>
          </div>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0 break-all">
              资料：{currentDocumentName || '未选择资料'}
            </p>
            <p className="m-0 break-all">
              {currentDocId ? `资料编号：${currentDocId}` : '资料编号：-'}
            </p>
            <p className="m-0 leading-relaxed">{scopeSummary}</p>
            <p className="m-0 leading-relaxed">
              相同内容再次上传时会复用原资料编号，并继续跟进最新处理任务。
            </p>
          </div>
        </Card>

        <UploadPanel
          onUploadStart={handleUploadStart}
          onUploadCreated={handleUploadCreated}
          onJobStatusChange={handleJobStatusChange}
          onUploadFailed={handleUploadFailed}
        />

        <DocumentListPanel />
      </section>
    </div>
  );
}
