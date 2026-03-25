/**
 * 应用根组件
 * 组合所有面板组件，构建完整的页面布局
 */

import { useState } from 'react';
import { Layout, HeroCard, Card } from '@/components';  // 引入布局和卡片组件。
import { HealthPanel, UploadPanel, DocumentListPanel, RetrievalPanel, ChatPanel } from '@/panels';  // 引入各功能面板。
import type { IngestJobStatusResponse } from '@/api';

type StatusTone = 'default' | 'ok' | 'warn' | 'error';

function getJobStatusTone(status?: string): StatusTone {
  if (!status) {
    return 'default';
  }
  if (status === 'completed') {
    return 'ok';
  }
  if (status === 'failed' || status === 'dead_letter' || status === 'partial_failed') {
    return 'error';
  }
  return 'warn';
}

export default function App() {
  const [currentDocumentName, setCurrentDocumentName] = useState<string>('');
  const [currentDocId, setCurrentDocId] = useState<string>('');
  const [latestJob, setLatestJob] = useState<IngestJobStatusResponse | null>(null);
  const [panelResetSignal, setPanelResetSignal] = useState(0);

  const currentJobStageText = latestJob
    ? `任务 ${latestJob.status} | 阶段 ${latestJob.stage} | ${latestJob.progress}%`
    : '尚未创建上传任务';
  const currentJobTone = getJobStatusTone(latestJob?.status);
  const currentJobIdText = latestJob?.job_id || '-';

  const handleUploadStart = (fileName: string) => {
    setCurrentDocumentName(fileName);
    setCurrentDocId('');
    setLatestJob(null);
    setPanelResetSignal((prev) => prev + 1);
  };

  const handleUploadCreated = (docId: string) => {
    setCurrentDocId(docId);
  };

  const handleJobStatusChange = (job: IngestJobStatusResponse) => {
    setLatestJob(job);
  };

  const handleUploadFailed = () => {
    setCurrentDocumentName('');
    setCurrentDocId('');
    setLatestJob(null);
  };

  return (
    <Layout>
      {/* 顶部 Hero 区域 */}
      <section className="grid grid-cols-[1.3fr_0.7fr] gap-5 mb-5 max-[960px]:grid-cols-1">
        {/* 左侧：主标题和描述 */}
        <HeroCard>
          {/* 标签 */}
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
            V1 演示界面
          </div>

          {/* 标题 */}
          <h1 className="m-0 mb-2.5 font-serif text-3xl md:text-4xl lg:text-5xl leading-tight tracking-tight text-ink">
            从文档入库到回答生成，后面连的都是真实后端。
          </h1>

          {/* 描述 */}
          <p className="m-0 text-ink-soft leading-relaxed max-w-[60ch]">
            这个页面只是现有 FastAPI 接口的一层可视化外壳，不做假流程。上传会真实创建
            ingest job，轮询会读取真实任务状态，检索会命中向量库，问答也会返回真实引用。
          </p>
        </HeroCard>

        {/* 右侧：指标卡片 */}
        <aside className="grid gap-3">
          <Card className="!p-4.5 bg-panel border-[rgba(182,70,47,0.1)]">
            <p className="m-0 text-ink-soft">当前覆盖</p>
            <strong className="block mt-2 text-2xl font-serif">
              健康检查 / 入库任务 / 检索 / 问答
            </strong>
          </Card>
          <Card className="!p-4.5 bg-panel border-[rgba(182,70,47,0.1)]">
            <p className="m-0 text-ink-soft">当前目标</p>
            <strong className="block mt-2 text-2xl font-serif">
              先把链路看清楚，再扩平台能力
            </strong>
          </Card>
          <Card className="!p-4.5 bg-panel border-[rgba(182,70,47,0.12)]">
            <p className="m-0 text-ink-soft">当前操作文档</p>
            <strong className="block mt-2 text-lg leading-tight break-all text-ink">
              {currentDocumentName || '未选择文件'}
            </strong>
            <p className="m-0 mt-2 text-sm text-ink-soft break-all">
              {currentDocId ? `doc_id: ${currentDocId}` : 'doc_id: -'}
            </p>
            <p className="m-0 mt-1 text-sm text-ink-soft break-all">
              {`job_id: ${currentJobIdText}`}
            </p>
            <p
              className={`
                m-0 mt-2 text-sm font-semibold
                ${currentJobTone === 'ok' ? 'text-ok' : ''}
                ${currentJobTone === 'warn' ? 'text-warn' : ''}
                ${currentJobTone === 'error' ? 'text-accent-deep' : ''}
                ${currentJobTone === 'default' ? 'text-ink-soft' : ''}
              `}
            >
              {currentJobStageText}
            </p>
          </Card>
        </aside>
      </section>

      {/* 功能面板区域 - 使用 12 列网格 */}
      <section className="grid grid-cols-12 gap-5">
        {/* 健康检查面板 - 占 4 列 */}
        <HealthPanel />

        {/* 文档上传面板 - 占 8 列 */}
        <UploadPanel
          onUploadStart={handleUploadStart}
          onUploadCreated={handleUploadCreated}
          onJobStatusChange={handleJobStatusChange}
          onUploadFailed={handleUploadFailed}
        />

        {/* 文档列表面板 - 占 12 列 */}
        <DocumentListPanel />

        {/* 检索面板 - 占 6 列 */}
        <RetrievalPanel
          resetSignal={panelResetSignal}
          currentDocumentName={currentDocumentName}
          currentDocId={currentDocId}
          currentJobStatus={latestJob?.status}
        />

        {/* 问答面板 - 占 6 列 */}
        <ChatPanel
          resetSignal={panelResetSignal}
          currentDocumentName={currentDocumentName}
          currentDocId={currentDocId}
          currentJobStatus={latestJob?.status}
        />
      </section>

      {/* 底部提示 */}
      <p className="mt-5 text-ink-soft text-sm">
        建议顺序：先做健康检查，再上传文件，等任务完成后再跑检索和问答。
      </p>
    </Layout>
  );
}
