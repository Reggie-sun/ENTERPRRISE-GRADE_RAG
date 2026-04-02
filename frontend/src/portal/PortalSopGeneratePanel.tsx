import { Download, LibraryBig, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { getDepartmentScopeSummary, useAuth } from '@/auth';
import { Button, Card, Input, StatusPill, StreamProgressSummary, Textarea, type StreamProgressMetrics, EvidenceSourceSummary } from '@/components';
import { UploadPanel } from '@/panels';
import {
  ApiError,
  downloadSopDraftFile,
  formatApiError,
  generateSopByDocument,
  generateSopByDocumentStream,
  getAuthBootstrap,
  type DepartmentRecord,
  type IngestJobStatusResponse,
  type QueryMode,
  type SopGenerationCitation,
  type SopGenerationDraftResponse,
  type SopGenerationRequestMode,
  type SopGenerationStreamMeta,
} from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';
type StatusTone = 'default' | 'ok' | 'warn' | 'error';
type DraftRequestMode = SopGenerationRequestMode | '';
const SOP_STREAM_START_TIMEOUT_MS = 15_000;

const SELECT_CLASS_NAME = `
  w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)]
  px-4 py-3 text-ink transition-all duration-200 focus:outline-none
  focus:border-[rgba(182,70,47,0.48)] focus:-translate-y-0.5
`;

const GENERATION_MODE_OPTIONS: Array<{
  value: QueryMode;
  label: string;
  description: string;
  defaultTopK: string;
}> = [
  { value: 'fast', label: '快速', description: '优先生成速度，适合先拿到第一版草稿。', defaultTopK: '5' },
  { value: 'accurate', label: '准确', description: '优先证据质量，适合正式生成 SOP 草稿。', defaultTopK: '8' },
];

interface DraftState {
  title: string;
  departmentId: string;
  departmentName: string;
  processName: string;
  scenarioName: string;
  topic: string;
  content: string;
  requestMode: DraftRequestMode;
  generationMode: string;
  model: string;
  citations: SopGenerationCitation[];
}

type StreamProgressState = StreamProgressMetrics;

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

function stripExtension(fileName: string): string {
  const normalized = fileName.trim();
  return normalized.replace(/\.[^.]+$/, '') || normalized;
}

function normalizeTopK(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return 5;
  }
  return Math.max(1, Math.min(20, parsed));
}

function sanitizeDownloadFilename(value: string): string {
  const normalized = value.trim().replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '_');
  return normalized || 'sop_draft';
}

function downloadTextFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function toDraftFromGeneration(payload: SopGenerationDraftResponse): DraftState {
  return {
    title: payload.title,
    departmentId: payload.department_id,
    departmentName: payload.department_name,
    processName: payload.process_name || '',
    scenarioName: payload.scenario_name || '',
    topic: payload.topic || '',
    content: payload.content,
    requestMode: payload.request_mode,
    generationMode: payload.generation_mode,
    model: payload.model,
    citations: payload.citations,
  };
}

function mergeDraftWithStreamMeta(current: DraftState, meta: SopGenerationStreamMeta): DraftState {
  return {
    ...current,
    title: meta.title,
    departmentId: meta.department_id,
    departmentName: meta.department_name,
    processName: meta.process_name || '',
    scenarioName: meta.scenario_name || '',
    topic: meta.topic || '',
    requestMode: meta.request_mode,
    generationMode: meta.generation_mode,
    model: meta.model,
    citations: meta.citations,
  };
}

function createEmptyDraft(departmentId: string, departmentName: string): DraftState {
  return {
    title: '',
    departmentId,
    departmentName,
    processName: '',
    scenarioName: '',
    topic: '',
    content: '',
    requestMode: '',
    generationMode: 'manual',
    model: 'manual',
    citations: [],
  };
}

function createEmptyStreamProgress(): StreamProgressState {
  return {
    startedAt: null,
    firstDeltaAt: null,
    lastDeltaAt: null,
    completedAt: null,
    deltaCount: 0,
    charCount: 0,
  };
}

function createStartedStreamProgress(): StreamProgressState {
  return {
    ...createEmptyStreamProgress(),
    startedAt: Date.now(),
  };
}

function recordStreamDelta(progress: StreamProgressState, delta: string): StreamProgressState {
  const now = Date.now();
  return {
    ...progress,
    firstDeltaAt: progress.firstDeltaAt ?? now,
    lastDeltaAt: now,
    deltaCount: progress.deltaCount + 1,
    charCount: progress.charCount + delta.length,
  };
}

function completeStreamProgress(progress: StreamProgressState): StreamProgressState {
  return {
    ...progress,
    completedAt: progress.completedAt ?? progress.lastDeltaAt ?? Date.now(),
  };
}

export function PortalSopGeneratePanel() {
  const { profile } = useAuth();
  const accessibleDepartmentIds = profile?.accessible_department_ids || [];
  const lockedDepartmentId = accessibleDepartmentIds.length === 1 ? accessibleDepartmentIds[0] : '';
  const fallbackDepartmentId = profile?.department.department_id || lockedDepartmentId;
  const fallbackDepartmentName = profile?.department.department_name || '当前部门';
  const scopeSummary = getDepartmentScopeSummary(profile);

  const [departments, setDepartments] = useState<DepartmentRecord[]>([]);
  const [currentDocumentName, setCurrentDocumentName] = useState('');
  const [currentDocId, setCurrentDocId] = useState('');
  const [latestJob, setLatestJob] = useState<IngestJobStatusResponse | null>(null);

  const [generateDepartmentId, setGenerateDepartmentId] = useState(fallbackDepartmentId);
  const [processName, setProcessName] = useState('');
  const [scenarioName, setScenarioName] = useState('');
  const [titleHint, setTitleHint] = useState('');
  const [queryMode, setQueryMode] = useState<QueryMode>('accurate');
  const [topK, setTopK] = useState('8');
  const [generateStatus, setGenerateStatus] = useState<PanelStatus>('idle');
  const [generateMessage, setGenerateMessage] = useState('');
  const [downloadMessage, setDownloadMessage] = useState('');
  const [downloadingFormat, setDownloadingFormat] = useState<'markdown' | 'docx' | 'pdf' | ''>('');

  const [draft, setDraft] = useState<DraftState>(() => createEmptyDraft(fallbackDepartmentId, fallbackDepartmentName));
  const [streamProgress, setStreamProgress] = useState<StreamProgressState>(() => createEmptyStreamProgress());
  const activeRequestRef = useRef<{ controller: AbortController; reason: 'superseded' | 'unmounted' | 'startup-timeout' | null } | null>(null);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    const loadDepartments = async () => {
      try {
        const bootstrap = await getAuthBootstrap();
        setDepartments(
          bootstrap.departments
            .filter((item) => accessibleDepartmentIds.length === 0 || accessibleDepartmentIds.includes(item.department_id))
            .sort((left, right) => left.department_name.localeCompare(right.department_name, 'zh-CN')),
        );
      } catch {
        if (!fallbackDepartmentId) {
          setDepartments([]);
          return;
        }
        setDepartments([
          {
            department_id: fallbackDepartmentId,
            tenant_id: profile?.department.tenant_id || 'tenant_default',
            department_name: fallbackDepartmentName,
            parent_department_id: null,
            is_active: true,
          },
        ]);
      }
    };

    void loadDepartments();
  }, [accessibleDepartmentIds, fallbackDepartmentId, fallbackDepartmentName, profile?.department.tenant_id]);

  useEffect(() => {
    if (lockedDepartmentId && generateDepartmentId !== lockedDepartmentId) {
      setGenerateDepartmentId(lockedDepartmentId);
    }
  }, [generateDepartmentId, lockedDepartmentId]);

  useEffect(() => {
    if (!titleHint && currentDocumentName) {
      setTitleHint(`${stripExtension(currentDocumentName)} SOP 草稿`);
    }
  }, [currentDocumentName, titleHint]);

  useEffect(() => () => {
    if (activeRequestRef.current) {
      activeRequestRef.current.reason = 'unmounted';
      activeRequestRef.current.controller.abort();
      activeRequestRef.current = null;
    }
  }, []);

  const currentJobStageText = latestJob
    ? `任务 ${latestJob.status} | 阶段 ${latestJob.stage} | ${latestJob.progress}%`
    : '尚未创建上传任务';
  const currentJobTone = getJobStatusTone(latestJob?.status);
  const isCurrentDocumentReady = Boolean(currentDocId)
    && (!latestJob || latestJob.doc_id !== currentDocId || latestJob.status === 'completed');
  const generationHint = !currentDocId
    ? '先上传一个来源文件。'
    : latestJob && latestJob.doc_id === currentDocId && latestJob.status === 'completed'
      ? '当前文件已完成入库，可以直接生成 SOP 草稿。'
      : latestJob && latestJob.doc_id === currentDocId && (latestJob.status === 'failed' || latestJob.status === 'dead_letter' || latestJob.status === 'partial_failed')
        ? '当前文件入库失败，修复后重新上传，再生成 SOP。'
        : '当前文件还在入库，等任务完成后再生成 SOP。';
  const canDownloadDraft = Boolean(draft.content.trim());
  const selectedGenerationMode = useMemo(
    () => GENERATION_MODE_OPTIONS.find((item) => item.value === queryMode) || GENERATION_MODE_OPTIONS[1],
    [queryMode],
  );
  const departmentOptions = useMemo(
    () => departments.map((item) => ({ value: item.department_id, label: item.department_name })),
    [departments],
  );

  const handleGenerate = async () => {
    if (!currentDocId) {
      setGenerateStatus('error');
      setGenerateMessage('请先上传来源文件，再生成 SOP。');
      return;
    }
    if (!isCurrentDocumentReady) {
      setGenerateStatus('error');
      setGenerateMessage('当前文件还在入库或入库失败，处理完成后再生成 SOP。');
      return;
    }

    if (activeRequestRef.current) {
      activeRequestRef.current.reason = 'superseded';
      activeRequestRef.current.controller.abort();
    }

    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const controller = new AbortController();
    activeRequestRef.current = { controller, reason: null };
    let sawStreamEvent = false;
    let fallbackRequested = false;
    const requestPayload = {
      document_id: currentDocId,
      department_id: lockedDepartmentId || generateDepartmentId || undefined,
      process_name: processName.trim() || undefined,
      scenario_name: scenarioName.trim() || undefined,
      title_hint: titleHint.trim() || undefined,
      mode: queryMode,
      top_k: normalizeTopK(topK),
    } as const;
    const clearActiveRequest = () => {
      if (activeRequestRef.current?.controller === controller) {
        activeRequestRef.current = null;
      }
    };
    const markStreamEvent = () => {
      sawStreamEvent = true;
      window.clearTimeout(startupTimer);
    };
    const persistDraft = (payload: SopGenerationDraftResponse) => {
      setDraft(toDraftFromGeneration(payload));
      setGenerateDepartmentId(payload.department_id);
      setGenerateStatus('success');
      setGenerateMessage(`已基于当前文档生成草稿，模型：${payload.model}`);
      setStreamProgress((prev) => completeStreamProgress(prev));
    };
    const startupTimer = window.setTimeout(() => {
      if (!sawStreamEvent && activeRequestRef.current?.controller === controller) {
        fallbackRequested = true;
        activeRequestRef.current.reason = 'startup-timeout';
        controller.abort();
      }
    }, SOP_STREAM_START_TIMEOUT_MS);

    setGenerateStatus('loading');
    setGenerateMessage('');
    setDownloadMessage('');
    setStreamProgress(createStartedStreamProgress());

    try {
      setDraft(createEmptyDraft(
        lockedDepartmentId || generateDepartmentId || fallbackDepartmentId,
        departments.find((item) => item.department_id === (lockedDepartmentId || generateDepartmentId || fallbackDepartmentId))?.department_name
          || fallbackDepartmentName,
      ));
      const payload = await generateSopByDocumentStream(
        requestPayload,
        {
          onMeta: (meta) => {
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setDraft((prev) => mergeDraftWithStreamMeta(prev, meta));
            setGenerateDepartmentId(meta.department_id);
            setGenerateMessage(`已建立流式连接，模型：${meta.model}，等待首包...`);
          },
          onDelta: (delta) => {
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setDraft((prev) => ({ ...prev, content: `${prev.content}${delta}` }));
            setStreamProgress((prev) => recordStreamDelta(prev, delta));
          },
          onDone: (response) => {
            if (requestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setDraft(toDraftFromGeneration(response));
            setGenerateDepartmentId(response.department_id);
            setStreamProgress((prev) => completeStreamProgress(prev));
          },
        },
        { signal: controller.signal },
      );

      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      persistDraft(payload);
    } catch (error) {
      let resolvedError: unknown = error;
      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      const abortReason = activeRequestRef.current?.controller === controller ? activeRequestRef.current.reason : null;
      const shouldFallback =
        !sawStreamEvent &&
        (fallbackRequested ||
          (resolvedError instanceof ApiError &&
            (resolvedError.kind === 'timeout' || resolvedError.kind === 'network' || resolvedError.kind === 'parse')));
      if (shouldFallback && abortReason !== 'superseded' && abortReason !== 'unmounted') {
        try {
          const fallbackPayload = await generateSopByDocument(requestPayload);
          if (requestVersionRef.current !== requestVersion) {
            return;
          }
          persistDraft(fallbackPayload);
          return;
        } catch (fallbackError) {
          resolvedError = fallbackError;
        }
      }
      if (abortReason === 'superseded' || abortReason === 'unmounted') {
        return;
      }
      setGenerateStatus('error');
      setGenerateMessage(formatApiError(resolvedError, 'SOP 草稿生成'));
      setStreamProgress((prev) => completeStreamProgress(prev));
    } finally {
      window.clearTimeout(startupTimer);
      clearActiveRequest();
    }
  };

  const handleDownloadDraft = () => {
    if (!draft.content.trim()) {
      setDownloadMessage('当前还没有可下载的 SOP 草稿。');
      return;
    }
    setDownloadingFormat('markdown');
    const baseName = sanitizeDownloadFilename(stripExtension(currentDocumentName || draft.title || 'sop_draft'));
    const content = draft.content.startsWith('#')
      ? draft.content
      : `# ${draft.title || stripExtension(currentDocumentName || 'SOP 草稿')}\n\n${draft.content}`;
    downloadTextFile(`${baseName}_sop_draft.md`, content);
    setDownloadMessage('已下载 Markdown 草稿，可直接在本地继续修改。');
    window.setTimeout(() => setDownloadingFormat(''), 200);
  };

  const handleDownloadFormattedDraft = async (format: 'docx' | 'pdf') => {
    if (!draft.content.trim()) {
      setDownloadMessage(`当前还没有可导出的 ${format.toUpperCase()} 草稿。`);
      return;
    }
    setDownloadingFormat(format);
    setDownloadMessage('');
    try {
      await downloadSopDraftFile({
        title: draft.title || stripExtension(currentDocumentName || 'SOP 草稿'),
        content: draft.content,
        format,
        department_id: draft.departmentId || generateDepartmentId || fallbackDepartmentId || undefined,
        process_name: draft.processName || undefined,
        scenario_name: draft.scenarioName || undefined,
        source_document_id: currentDocId || undefined,
      });
      setDownloadMessage(`已下载 ${format.toUpperCase()} 草稿，可直接在本地继续修改。`);
    } catch (error) {
      setDownloadMessage(formatApiError(error, `${format.toUpperCase()} 草稿导出`));
    } finally {
      setDownloadingFormat('');
    }
  };

  return (
    <div className="grid gap-5">
      <UploadPanel
        title="第一步：上传来源文档"
        description="员工可以直接在门户上传一份来源资料。处理完成后，系统会锁定当前资料编号，并基于这份资料生成 SOP 草稿。"
        className="col-span-12"
        allowMultiple={false}
        showIdentityFields={false}
        onUploadStart={(fileName) => {
          setCurrentDocumentName(fileName);
          setCurrentDocId('');
          setLatestJob(null);
          setGenerateStatus('idle');
          setGenerateMessage('');
          setDownloadMessage('');
          setTitleHint(`${stripExtension(fileName)} SOP 草稿`);
          setDraft(createEmptyDraft(fallbackDepartmentId, fallbackDepartmentName));
          setStreamProgress(createEmptyStreamProgress());
        }}
        onUploadCreated={(docId) => {
          setCurrentDocId(docId);
        }}
        onJobStatusChange={(job) => {
          setLatestJob(job);
        }}
        onUploadFailed={(message) => {
          setCurrentDocumentName('');
          setCurrentDocId('');
          setLatestJob(null);
          setGenerateStatus('error');
          setGenerateMessage(message || '来源文档上传或入库失败，请修复后重试。');
          setStreamProgress(createEmptyStreamProgress());
        }}
      />

      <section className="grid grid-cols-12 gap-5">
        <div className="col-span-4 grid gap-5 max-lg:col-span-12">
          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="m-0 text-xl font-semibold text-ink">当前文件上下文</h3>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">{scopeSummary}</p>
              </div>
              <StatusPill tone={currentDocId ? 'ok' : 'warn'}>
                {currentDocId ? '已锁定当前文件' : '等待上传文件'}
              </StatusPill>
            </div>
            <div className="mt-4 grid gap-3 text-sm text-ink-soft">
              <div className="rounded-2xl bg-[rgba(255,255,255,0.76)] p-4">
                <strong className="block text-ink">来源文件</strong>
                <p className="m-0 mt-2 break-all">{currentDocumentName || '未上传来源文件'}</p>
              </div>
              <div className="rounded-2xl bg-[rgba(255,255,255,0.76)] p-4">
                <strong className="block text-ink">当前资料编号</strong>
                <p className="m-0 mt-2 break-all">{currentDocId || '-'}</p>
              </div>
              <div className="rounded-2xl bg-[rgba(255,255,255,0.76)] p-4">
                <div className="flex items-center justify-between gap-3">
                  <strong className="block text-ink">入库状态</strong>
                  <StatusPill tone={currentJobTone}>{latestJob?.status || 'idle'}</StatusPill>
                </div>
                <p className="m-0 mt-2 leading-relaxed">{currentJobStageText}</p>
              </div>
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="m-0 text-xl font-semibold text-ink">第二步：直接生成 SOP</h3>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                  主流程只围绕当前资料生成。工序、场景和标题提示是辅助项，不再要求手填主题或资料编号。
                </p>
              </div>
              <Sparkles className="h-5 w-5 text-accent-deep" />
            </div>

            <div className="mt-4 grid gap-4">
              <label className="grid gap-1.5 text-sm font-semibold">
                目标部门
                <select
                  className={SELECT_CLASS_NAME}
                  value={generateDepartmentId}
                  onChange={(event) => setGenerateDepartmentId(event.target.value)}
                  disabled={Boolean(lockedDepartmentId)}
                >
                  {departmentOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <Input
                label="标题提示"
                value={titleHint}
                onChange={(event) => setTitleHint(event.target.value)}
                placeholder="默认使用文件名生成标题"
              />

              <Input
                label="工序（可选）"
                value={processName}
                onChange={(event) => setProcessName(event.target.value)}
                placeholder="如：巡检 / 发版 / 异常处理"
              />

              <Input
                label="场景（可选）"
                value={scenarioName}
                onChange={(event) => setScenarioName(event.target.value)}
                placeholder="如：系统巡检 / 数据异常 / 版本发布"
              />

              <div className="grid gap-2">
                <div className="text-sm font-semibold text-ink">生成档位</div>
                <div className="flex flex-wrap gap-2">
                  {GENERATION_MODE_OPTIONS.map((item) => {
                    const active = queryMode === item.value;
                    return (
                      <button
                        key={item.value}
                        type="button"
                        className={`
                          rounded-full px-4 py-2 text-sm font-semibold transition-all duration-200
                          ${active
                            ? 'bg-[rgba(182,70,47,0.14)] text-accent-deep shadow-[0_10px_20px_rgba(182,70,47,0.14)]'
                            : 'bg-[rgba(23,32,42,0.06)] text-ink hover:-translate-y-0.5'
                          }
                        `}
                        onClick={() => {
                          setQueryMode(item.value);
                          setTopK(item.defaultTopK);
                        }}
                      >
                        {item.label}
                      </button>
                    );
                  })}
                </div>
                <p className="m-0 text-sm leading-relaxed text-ink-soft">{selectedGenerationMode.description}</p>
              </div>

              <Input
                label="召回 top_k"
                inputMode="numeric"
                value={topK}
                onChange={(event) => setTopK(event.target.value)}
                placeholder="1-20"
              />
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button onClick={() => void handleGenerate()} loading={generateStatus === 'loading'} disabled={!isCurrentDocumentReady}>
                根据当前文档生成 SOP 草稿
              </Button>
              <StatusPill
                tone={
                  generateStatus === 'success'
                    ? 'ok'
                    : generateStatus === 'error'
                      ? 'error'
                      : generateStatus === 'loading'
                        ? 'warn'
                        : 'default'
                }
              >
                {generateStatus === 'loading'
                  ? '正在生成'
                  : generateStatus === 'success'
                    ? '草稿已生成'
                    : generateStatus === 'error'
                      ? '生成失败'
                      : '等待生成'}
              </StatusPill>
            </div>

            <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
              {generateMessage || generationHint}
            </p>
            <StreamProgressSummary status={generateStatus} metrics={streamProgress} />
          </Card>
        </div>

        <div className="col-span-8 grid gap-5 max-lg:col-span-12">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="m-0 text-xl font-semibold text-ink">第三步：下载本地草稿</h3>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                  门户主流程只负责预览和轻量调整。生成后直接下载 Markdown 草稿，在本地继续修改即可。
                </p>
              </div>
              <StatusPill tone={draft.content ? 'ok' : 'warn'}>
                {draft.content ? '已生成草稿' : '等待草稿'}
              </StatusPill>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <Input
                label="草稿标题"
                value={draft.title}
                onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                placeholder="生成后会自动填充标题"
              />
              <Input
                label="来源文档主题"
                value={draft.topic}
                onChange={(event) => setDraft((prev) => ({ ...prev, topic: event.target.value }))}
                placeholder="通常由来源文件名自动生成"
              />
            </div>

            <div className="mt-4">
              <Textarea
                label="SOP 正文"
                className="min-h-[320px]"
                value={draft.content}
                onChange={(event) => setDraft((prev) => ({ ...prev, content: event.target.value }))}
                placeholder="生成后的 SOP 草稿会出现在这里。"
              />
            </div>

            <div className="mt-4">
              <StreamProgressSummary status={generateStatus} metrics={streamProgress} compact />
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button onClick={handleDownloadDraft} disabled={!canDownloadDraft || downloadingFormat !== ''}>
                <span className="inline-flex items-center gap-2">
                  <Download className="h-4 w-4" />
                  {downloadingFormat === 'markdown' ? '导出中...' : '下载 Markdown 草稿'}
                </span>
              </Button>
              <Button
                variant="ghost"
                onClick={() => void handleDownloadFormattedDraft('docx')}
                disabled={!canDownloadDraft || downloadingFormat !== ''}
              >
                {downloadingFormat === 'docx' ? 'DOCX 导出中...' : '下载 DOCX 草稿'}
              </Button>
              <Button
                variant="ghost"
                onClick={() => void handleDownloadFormattedDraft('pdf')}
                disabled={!canDownloadDraft || downloadingFormat !== ''}
              >
                {downloadingFormat === 'pdf' ? 'PDF 导出中...' : '下载 PDF 草稿'}
              </Button>
            </div>

            <div className="mt-3 grid gap-2 text-sm text-ink-soft">
              <p className="m-0">
                {downloadMessage || '当前草稿现在支持直接导出 Markdown、DOCX、PDF；如果还要查标准流程或下载已沉淀版本，可继续使用下方 SOP 资产区。'}
              </p>
              <p className="m-0">
                当前模型：{draft.model || draft.generationMode}
              </p>
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="m-0 text-xl font-semibold text-ink">引用证据</h3>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                  这里显示生成当前草稿时命中的证据块，便于确认 SOP 是否确实来自你刚上传的文档。
                </p>
              </div>
              <div className="inline-flex items-center gap-2 text-sm text-ink-soft">
                <LibraryBig className="h-4 w-4 text-accent-deep" />
                共 {draft.citations.length} 条
              </div>
            </div>

            <div className="mt-4 grid gap-3">
              {draft.citations.map((item) => (
                <article
                  key={item.chunk_id}
                  className="rounded-2xl border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.74)] p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                    <strong className="text-ink">{item.document_name}</strong>
                    <span className="text-ink-soft">相关度：{item.score.toFixed(4)}</span>
                  </div>
                  <p className="m-0 mt-2 text-xs text-ink-soft break-all">
                    资料编号：{item.document_id} / 片段编号：{item.chunk_id}
                  </p>
                  <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">{item.snippet}</p>
                  <EvidenceSourceSummary
                    retrievalStrategy={item.retrieval_strategy}
                    ocrUsed={item.ocr_used}
                    parserName={item.parser_name}
                    pageNo={item.page_no}
                    ocrConfidence={item.ocr_confidence}
                    qualityScore={item.quality_score}
                  />
                  <p className="m-0 mt-3 text-xs text-ink-soft break-all">{item.source_path}</p>
                </article>
              ))}

              {!draft.citations.length ? (
                <div className="rounded-2xl border border-dashed border-[rgba(23,32,42,0.12)] px-4 py-8 text-sm leading-relaxed text-ink-soft">
                  先上传来源文件并生成 SOP，这里才会显示引用证据。
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}
