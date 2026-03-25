import { Card, HeroCard, StatusPill } from '@/components';
import { ChatPanel } from '@/panels';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

export function ChatPage() {
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
          Chat
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          问答页保留流式输出，只做回答验证和引用检查。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          这页以后会承接企业最终用户的使用体验，所以先把它和文档管理页拆开，避免后面接登录和权限时把交互全部绑死在一个 demo 页面里。
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
              当前实现会先收到 stream meta，再持续拼接 delta，所以页面展示的是逐步生成的真实回答，不是等全量结果回来后一次性填充。
            </p>
            <p className="m-0 leading-relaxed">
              当前文档完成入库后，这页会优先按当前文档问答；没有当前文档时，则自动走全库模式。
            </p>
            <p className="m-0 break-all">
              当前文档：{currentDocumentName || '全库模式'}
            </p>
            <p className="m-0 break-all">
              {currentDocId ? `doc_id: ${currentDocId}` : 'doc_id: -'}
            </p>
          </div>
        </Card>
      </section>
    </div>
  );
}
