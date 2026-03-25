import { Card, HeroCard, StatusPill } from '@/components';
import { DocumentListPanel, UploadPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function DocumentsPage() {
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
          Documents
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          文档中心负责入库任务、文档列表和后续维护操作。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          这里是后续企业用户最常驻的页面。上传、预览、删除、重建向量都在这一页收口，检索和问答页只做验证与消费。
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
              文档：{currentDocumentName || '未选择文件'}
            </p>
            <p className="m-0 break-all">
              {currentDocId ? `doc_id: ${currentDocId}` : 'doc_id: -'}
            </p>
            <p className="m-0 leading-relaxed">
              相同内容文档再次上传时会覆盖旧记录并沿用原 `doc_id`，不再卡死在旧的死信任务上。
            </p>
            <p className="m-0 leading-relaxed">
              列表页支持继续预览、删除和重建向量，这样后续 SOP 页面也能直接复用同一套文档主数据。
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
