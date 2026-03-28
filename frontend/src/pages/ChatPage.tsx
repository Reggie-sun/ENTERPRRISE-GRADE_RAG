import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';
import { ChatPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function ChatPage() {
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
          智能问答
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          问答页提供流式回答，用于查看当前权限范围内的回答内容与引用依据。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          问答过程会持续输出内容，但不会返回你无权查看的跨部门资料。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <ChatPanel
          resetSignal={panelResetSignal}
          currentDocumentName={currentDocumentName}
          currentDocId={currentDocId}
          currentJobStatus={latestJob?.status}
        />

        <Card className="col-span-6 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">问答页说明</h3>
          <div className="mt-4">
            <StatusPill tone="ok">当前回答链路保持流式输出</StatusPill>
          </div>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0 leading-relaxed">
              页面会逐步显示实时生成的回答，方便直接查看内容变化与引用来源。
            </p>
            <p className="m-0 leading-relaxed">{scopeSummary}</p>
            <p className="m-0 break-all">
              当前资料：{currentDocumentName || '全库模式'}
            </p>
            <p className="m-0 break-all">
              {currentDocId ? `资料编号：${currentDocId}` : '资料编号：-'}
            </p>
          </div>
        </Card>
      </section>
    </div>
  );
}
