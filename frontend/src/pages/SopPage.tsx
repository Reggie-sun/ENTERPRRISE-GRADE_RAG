import { Download, History, LibraryBig, RefreshCcw, Save, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';
import { Button, Card, HeroCard, Input, StatusPill, StreamProgressSummary, Textarea, type StreamProgressMetrics, EvidenceSourceSummary } from '@/components';
import { UploadPanel } from '@/panels';
import {
  ApiError,
  downloadSopDraftFile,
  formatApiError,
  generateSopByDocument,
  generateSopByDocumentStream,
  getAuthBootstrap,
  getSops,
  getSopVersionDetail,
  getSopVersions,
  saveSop,
  type DepartmentRecord,
  type QueryMode,
  type SopGenerationCitation,
  type SopGenerationDraftResponse,
  type SopGenerationRequestMode,
  type SopGenerationStreamMeta,
  type SopStatus,
  type SopSummary,
  type SopVersionSummary,
} from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';
type DraftRequestMode = SopGenerationRequestMode | '';
const SOP_STREAM_START_TIMEOUT_MS = 15_000;
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
  sopId: string;
  version: number | null;
  title: string;
  departmentId: string;
  departmentName: string;
  processName: string;
  scenarioName: string;
  topic: string;
  status: SopStatus;
  content: string;
  requestMode: DraftRequestMode;
  generationMode: string;
  model: string;
  citations: SopGenerationCitation[];
  tagsText: string;
  updatedAt: string;
  isCurrent: boolean;
}

type StreamProgressState = StreamProgressMetrics;

const SELECT_CLASS_NAME = `
  w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)]
  px-4 py-3 text-ink transition-all duration-200 focus:outline-none
  focus:border-[rgba(182,70,47,0.48)] focus:-translate-y-0.5
`;

function toLocalTime(isoText: string | null | undefined): string {
  if (!isoText) {
    return '-';
  }
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
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

function buildTags(tagsText: string): string[] {
  const values = tagsText
    .split(/[,\n，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(values));
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
    sopId: '',
    version: null,
    title: payload.title,
    departmentId: payload.department_id,
    departmentName: payload.department_name,
    processName: payload.process_name || '',
    scenarioName: payload.scenario_name || '',
    topic: payload.topic || '',
    status: 'draft',
    content: payload.content,
    requestMode: payload.request_mode,
    generationMode: payload.generation_mode,
    model: payload.model,
    citations: payload.citations,
    tagsText: '',
    updatedAt: '',
    isCurrent: true,
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
    sopId: '',
    version: null,
    title: '',
    departmentId,
    departmentName,
    processName: '',
    scenarioName: '',
    topic: '',
    status: 'draft',
    content: '',
    requestMode: '',
    generationMode: 'manual',
    model: 'manual',
    citations: [],
    tagsText: '',
    updatedAt: '',
    isCurrent: true,
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

export function SopPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const {
    currentDocumentName,
    currentDocId,
    latestJob,
    currentJobStageText,
    currentJobTone,
    handleUploadStart,
    handleUploadCreated,
    handleJobStatusChange,
    handleUploadFailed,
  } = useUploadWorkspace();
  const accessibleDepartmentIds = profile?.accessible_department_ids || [];
  const lockedDepartmentId = accessibleDepartmentIds.length === 1 ? accessibleDepartmentIds[0] : '';
  const fallbackDepartmentId = profile?.department.department_id || lockedDepartmentId;
  const fallbackDepartmentName = profile?.department.department_name || '当前部门';

  const [directoryStatus, setDirectoryStatus] = useState<PanelStatus>('idle');
  const [directoryError, setDirectoryError] = useState('');
  const [departments, setDepartments] = useState<DepartmentRecord[]>([]);
  const [sops, setSops] = useState<SopSummary[]>([]);
  const [selectedSopId, setSelectedSopId] = useState('');

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

  const [versionsStatus, setVersionsStatus] = useState<PanelStatus>('idle');
  const [versionsError, setVersionsError] = useState('');
  const [versions, setVersions] = useState<SopVersionSummary[]>([]);
  const [activeVersionKey, setActiveVersionKey] = useState('');

  const [draft, setDraft] = useState<DraftState>(() => createEmptyDraft(fallbackDepartmentId, fallbackDepartmentName));
  const [saveStatus, setSaveStatus] = useState<PanelStatus>('idle');
  const [saveMessage, setSaveMessage] = useState('');
  const [streamProgress, setStreamProgress] = useState<StreamProgressState>(() => createEmptyStreamProgress());
  const activeGenerateRequestRef = useRef<{ controller: AbortController; reason: 'superseded' | 'unmounted' | 'startup-timeout' | null } | null>(null);
  const generateRequestVersionRef = useRef(0);

  const departmentNameById = useMemo(() => {
    const mapping = new Map<string, string>();
    departments.forEach((item) => {
      mapping.set(item.department_id, item.department_name);
    });
    if (fallbackDepartmentId) {
      mapping.set(fallbackDepartmentId, fallbackDepartmentName);
    }
    return mapping;
  }, [departments, fallbackDepartmentId, fallbackDepartmentName]);

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

  useEffect(() => {
    if (!draft.departmentId && fallbackDepartmentId) {
      setDraft((prev) => ({
        ...prev,
        departmentId: fallbackDepartmentId,
        departmentName: fallbackDepartmentName,
      }));
    }
  }, [draft.departmentId, fallbackDepartmentId, fallbackDepartmentName]);

  const refreshDirectory = async (preferredSopId?: string) => {
    setDirectoryStatus('loading');
    setDirectoryError('');

    let resolvedDepartments: DepartmentRecord[] = [];
    try {
      const bootstrap = await getAuthBootstrap();
      resolvedDepartments = bootstrap.departments
        .filter((item) => accessibleDepartmentIds.length === 0 || accessibleDepartmentIds.includes(item.department_id))
        .sort((left, right) => left.department_name.localeCompare(right.department_name, 'zh-CN'));
    } catch {
      resolvedDepartments = fallbackDepartmentId
        ? [{
          department_id: fallbackDepartmentId,
          tenant_id: profile?.department.tenant_id || 'tenant_default',
          department_name: fallbackDepartmentName,
          parent_department_id: null,
          is_active: true,
        }]
        : [];
    }

    setDepartments(resolvedDepartments);

    try {
      const payload = await getSops({
        page: 1,
        page_size: 200,
        department_id: lockedDepartmentId || undefined,
      });
      const sorted = [...payload.items].sort(
        (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
      );
      setSops(sorted);
      setDirectoryStatus('success');

      const nextSelectedSopId = preferredSopId && sorted.some((item) => item.sop_id === preferredSopId)
        ? preferredSopId
        : selectedSopId && sorted.some((item) => item.sop_id === selectedSopId)
          ? selectedSopId
          : sorted[0]?.sop_id || '';
      setSelectedSopId(nextSelectedSopId);
    } catch (error) {
      setSops([]);
      setSelectedSopId('');
      setDirectoryStatus('error');
      setDirectoryError(formatApiError(error, 'SOP 工作台列表加载'));
    }
  };

  useEffect(() => {
    void refreshDirectory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockedDepartmentId]);

  const loadVersionDetail = async (sopId: string, version: number) => {
    setVersionsStatus('loading');
    setVersionsError('');
    try {
      const payload = await getSopVersionDetail(sopId, version);
      setDraft({
        sopId: payload.sop_id,
        version: payload.version,
        title: payload.title,
        departmentId: payload.department_id,
        departmentName: departmentNameById.get(payload.department_id) || fallbackDepartmentName,
        processName: payload.process_name || '',
        scenarioName: payload.scenario_name || '',
        topic: payload.topic || '',
        status: payload.status,
        content: payload.content,
        requestMode: payload.request_mode || '',
        generationMode: payload.generation_mode,
        model: payload.generation_mode,
        citations: payload.citations,
        tagsText: payload.tags.join(', '),
        updatedAt: payload.updated_at,
        isCurrent: payload.is_current,
      });
      setActiveVersionKey(`${payload.sop_id}:${payload.version}`);
      setVersionsStatus('success');
    } catch (error) {
      setVersionsStatus('error');
      setVersionsError(formatApiError(error, 'SOP 版本详情加载'));
    }
  };

  const loadVersionsForSop = async (sopId: string, preferredVersion?: number) => {
    setVersionsStatus('loading');
    setVersionsError('');
    try {
      const payload = await getSopVersions(sopId);
      setVersions(payload.items);
      const currentVersion = preferredVersion
        ? payload.items.find((item) => item.version === preferredVersion) || payload.items[0]
        : payload.items.find((item) => item.is_current) || payload.items[0];
      setActiveVersionKey(currentVersion ? `${sopId}:${currentVersion.version}` : '');
      if (currentVersion) {
        await loadVersionDetail(sopId, currentVersion.version);
      } else {
        setVersionsStatus('success');
      }
    } catch (error) {
      setVersions([]);
      setVersionsStatus('error');
      setVersionsError(formatApiError(error, 'SOP 版本列表加载'));
    }
  };

  useEffect(() => {
    if (!selectedSopId) {
      setVersions([]);
      setActiveVersionKey('');
      return;
    }
    void loadVersionsForSop(selectedSopId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSopId]);

  const departmentOptions = useMemo(() => departments.map((item) => ({
    value: item.department_id,
    label: item.department_name,
  })), [departments]);

  const selectedSopSummary = useMemo(
    () => sops.find((item) => item.sop_id === selectedSopId) || null,
    [selectedSopId, sops],
  );

  const isCurrentDocumentReady = Boolean(currentDocId) && (!latestJob || latestJob.doc_id !== currentDocId || latestJob.status === 'completed');
  const generationHint = !currentDocId
    ? '先上传一个来源文件。'
    : latestJob && latestJob.doc_id === currentDocId && latestJob.status !== 'completed'
      ? '当前文件还在入库，等任务完成后再生成 SOP。'
      : '当前文件已完成入库，可以直接生成 SOP 草稿。';

  useEffect(() => () => {
    if (activeGenerateRequestRef.current) {
      activeGenerateRequestRef.current.reason = 'unmounted';
      activeGenerateRequestRef.current.controller.abort();
      activeGenerateRequestRef.current = null;
    }
  }, []);

  const handleGenerate = async () => {
    if (!currentDocId) {
      setGenerateStatus('error');
      setGenerateMessage('请先上传来源文件，再生成 SOP。');
      return;
    }
    if (latestJob && latestJob.doc_id === currentDocId && latestJob.status !== 'completed') {
      setGenerateStatus('error');
      setGenerateMessage('当前文件还在入库，完成后再生成 SOP。');
      return;
    }

    if (activeGenerateRequestRef.current) {
      activeGenerateRequestRef.current.reason = 'superseded';
      activeGenerateRequestRef.current.controller.abort();
    }

    const requestVersion = generateRequestVersionRef.current + 1;
    generateRequestVersionRef.current = requestVersion;
    const controller = new AbortController();
    activeGenerateRequestRef.current = { controller, reason: null };
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
      if (activeGenerateRequestRef.current?.controller === controller) {
        activeGenerateRequestRef.current = null;
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
      setSaveStatus('idle');
      setSaveMessage('');
      setStreamProgress((prev) => completeStreamProgress(prev));
    };
    const startupTimer = window.setTimeout(() => {
      if (!sawStreamEvent && activeGenerateRequestRef.current?.controller === controller) {
        fallbackRequested = true;
        activeGenerateRequestRef.current.reason = 'startup-timeout';
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
        departmentNameById.get(lockedDepartmentId || generateDepartmentId || fallbackDepartmentId) || fallbackDepartmentName,
      ));
      const payload = await generateSopByDocumentStream(
        requestPayload,
        {
          onMeta: (meta) => {
            if (generateRequestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setDraft((prev) => mergeDraftWithStreamMeta(prev, meta));
            setGenerateDepartmentId(meta.department_id);
            setGenerateMessage(`已建立流式连接，模型：${meta.model}，等待首包...`);
          },
          onDelta: (delta) => {
            if (generateRequestVersionRef.current !== requestVersion) {
              return;
            }
            markStreamEvent();
            setDraft((prev) => ({ ...prev, content: `${prev.content}${delta}` }));
            setStreamProgress((prev) => recordStreamDelta(prev, delta));
          },
          onDone: (response) => {
            if (generateRequestVersionRef.current !== requestVersion) {
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

      if (generateRequestVersionRef.current !== requestVersion) {
        return;
      }
      persistDraft(payload);
    } catch (error) {
      let resolvedError: unknown = error;
      if (generateRequestVersionRef.current !== requestVersion) {
        return;
      }
      const abortReason = activeGenerateRequestRef.current?.controller === controller ? activeGenerateRequestRef.current.reason : null;
      const shouldFallback =
        !sawStreamEvent &&
        (fallbackRequested ||
          (resolvedError instanceof ApiError &&
            (resolvedError.kind === 'timeout' || resolvedError.kind === 'network' || resolvedError.kind === 'parse')));
      if (shouldFallback && abortReason !== 'superseded' && abortReason !== 'unmounted') {
        try {
          const fallbackPayload = await generateSopByDocument(requestPayload);
          if (generateRequestVersionRef.current !== requestVersion) {
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

  const handleSave = async () => {
    setSaveStatus('loading');
    setSaveMessage('');
    try {
      const payload = await saveSop({
        sop_id: draft.sopId || undefined,
        title: draft.title.trim(),
        department_id: draft.departmentId || lockedDepartmentId || generateDepartmentId || undefined,
        process_name: draft.processName.trim() || undefined,
        scenario_name: draft.scenarioName.trim() || undefined,
        topic: draft.topic.trim() || undefined,
        status: draft.status,
        content: draft.content.trim(),
        request_mode: draft.requestMode || undefined,
        generation_mode: draft.generationMode.trim() || 'manual',
        citations: draft.citations,
        tags: buildTags(draft.tagsText),
      });
      setSaveStatus('success');
      setSaveMessage(`已保存 ${payload.title}，当前版本 v${payload.version}`);
      await refreshDirectory(payload.sop_id);
      await loadVersionsForSop(payload.sop_id, payload.version);
    } catch (error) {
      setSaveStatus('error');
      setSaveMessage(formatApiError(error, 'SOP 保存'));
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
    setDownloadMessage('已下载 Markdown 草稿，可直接在本地编辑。');
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
        department_id: draft.departmentId || lockedDepartmentId || generateDepartmentId || undefined,
        process_name: draft.processName || undefined,
        scenario_name: draft.scenarioName || undefined,
        source_document_id: currentDocId || undefined,
      });
      setDownloadMessage(`已下载 ${format.toUpperCase()} 草稿，可直接在本地编辑。`);
    } catch (error) {
      setDownloadMessage(formatApiError(error, `${format.toUpperCase()} 草稿导出`));
    } finally {
      setDownloadingFormat('');
    }
  };

  const canDownloadDraft = Boolean(draft.content.trim());
  const canSave = Boolean(draft.title.trim()) && Boolean(draft.content.trim());
  const selectedGenerationMode = GENERATION_MODE_OPTIONS.find((item) => item.value === queryMode) || GENERATION_MODE_OPTIONS[1];

  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
          SOP 管理
        </div>
        <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          这里提供更完整的 SOP 管理能力，适合维护来源资料、生成草稿和沉淀版本。
        </h2>
        <p className="m-0 mt-3 max-w-[74ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          这里保留上传、按当前资料生成、下载 Markdown 草稿和平台版本沉淀等能力，适合管理员做补录、校对和版本维护。
        </p>
      </HeroCard>

      <UploadPanel
        title="第一步：上传来源文件"
        description="一份 SOP 对应一份来源资料。上传完成后，页面会自动锁定当前资料编号，并基于这份资料直接生成草稿。"
        className="col-span-12"
        allowMultiple={false}
        showIdentityFields={false}
        onUploadStart={(fileName) => {
          handleUploadStart(fileName);
          setGenerateStatus('idle');
          setGenerateMessage('');
          setDownloadMessage('');
          setSaveStatus('idle');
          setSaveMessage('');
          setTitleHint(`${stripExtension(fileName)} SOP 草稿`);
          setDraft(createEmptyDraft(fallbackDepartmentId, fallbackDepartmentName));
          setStreamProgress(createEmptyStreamProgress());
        }}
        onUploadCreated={handleUploadCreated}
        onJobStatusChange={handleJobStatusChange}
        onUploadFailed={(message) => {
          handleUploadFailed();
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
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
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
                <p className="m-0 text-sm leading-relaxed text-ink-soft">
                  {selectedGenerationMode.description}
                </p>
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
              <Button
                onClick={() => void handleGenerate()}
                loading={generateStatus === 'loading'}
                disabled={!isCurrentDocumentReady}
              >
                根据当前文件生成 SOP 草稿
              </Button>
              <StatusPill tone={
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
                  页面内只负责预览和轻量调整。你可以直接下载 Markdown 草稿，在本地继续改，不必先走系统内审核。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusPill tone={draft.sopId ? 'ok' : 'warn'}>
                  {draft.sopId ? `sop_id: ${draft.sopId}` : '未保存到系统'}
                </StatusPill>
                <StatusPill tone={draft.version ? 'ok' : 'warn'}>
                  {draft.version ? `v${draft.version}` : '草稿态'}
                </StatusPill>
              </div>
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
                className="min-h-[360px]"
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
                {downloadMessage || '先生成草稿，再直接导出 Markdown、DOCX 或 PDF。如果后面要沉淀系统版本，再展开下方高级区保存。'}
              </p>
              <p className="m-0">
                最近更新时间：{toLocalTime(draft.updatedAt)} / 当前模型：{draft.model || draft.generationMode}
              </p>
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="m-0 text-xl font-semibold text-ink">引用证据</h3>
                <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                  这里显示生成当前草稿时命中的知识片段，便于确认 SOP 是否确实来自你刚上传的资料。
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

      <details className="rounded-3xl border border-line bg-bg-soft p-6 shadow-soft">
        <summary className="cursor-pointer list-none text-lg font-semibold text-ink">
          高级：保存到平台版本库 / 查看历史版本
        </summary>
        <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
          默认主流程不依赖这部分。如果你后面想把草稿沉淀成系统内 SOP，再用这里保存和回看历史版本。
        </p>

        <section className="mt-5 grid grid-cols-12 gap-5">
          <div className="col-span-4 grid gap-5 max-lg:col-span-12">
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="m-0 text-xl font-semibold text-ink">版本侧栏</h3>
                  <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                    选择一个已保存 SOP，随时切回历史版本继续编辑。
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-accent-deep" />
                  <button
                    type="button"
                    onClick={() => void refreshDirectory(selectedSopId || undefined)}
                    className="inline-flex items-center gap-2 rounded-full border-0 bg-[rgba(23,32,42,0.06)] px-3 py-2 text-sm font-semibold text-ink transition-all duration-200 hover:-translate-y-0.5"
                  >
                    <RefreshCcw className="h-4 w-4" />
                    刷新
                  </button>
                </div>
              </div>

              <label className="mt-4 grid gap-1.5 text-sm font-semibold">
                当前 SOP
                <select
                  className={SELECT_CLASS_NAME}
                  value={selectedSopId}
                  onChange={(event) => setSelectedSopId(event.target.value)}
                >
                  <option value="">选择已保存 SOP</option>
                  {sops.map((item) => (
                    <option key={item.sop_id} value={item.sop_id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>

              <div className="mt-4">
                <StatusPill tone={
                  versionsStatus === 'loading'
                    ? 'warn'
                    : directoryStatus === 'success'
                      ? 'ok'
                      : directoryStatus === 'error'
                        ? 'error'
                        : directoryStatus === 'loading'
                          ? 'warn'
                          : 'default'
                }
                >
                  {versionsStatus === 'loading'
                    ? '正在读取版本'
                    : directoryStatus === 'loading'
                      ? '正在加载目录'
                      : directoryStatus === 'error'
                        ? '目录加载失败'
                        : `已收录 ${sops.length} 条 SOP`}
                </StatusPill>
              </div>

              {selectedSopSummary ? (
                <div className="mt-4 rounded-2xl bg-[rgba(255,255,255,0.74)] p-4 text-sm text-ink-soft">
                  <strong className="block text-ink">{selectedSopSummary.title}</strong>
                  <p className="m-0 mt-2">
                    {selectedSopSummary.department_name}
                    {selectedSopSummary.process_name ? ` / ${selectedSopSummary.process_name}` : ''}
                    {selectedSopSummary.scenario_name ? ` / ${selectedSopSummary.scenario_name}` : ''}
                  </p>
                  <p className="m-0 mt-2">当前版本：v{selectedSopSummary.version}</p>
                </div>
              ) : null}

              <div className="mt-4 grid gap-3">
                {versions.map((item) => {
                  const versionKey = `${item.sop_id}:${item.version}`;
                  const isActive = versionKey === activeVersionKey;
                  return (
                    <button
                      key={versionKey}
                      type="button"
                      onClick={() => void loadVersionDetail(item.sop_id, item.version)}
                      className={`
                        rounded-2xl border px-4 py-3 text-left transition-all duration-200
                        ${isActive
                          ? 'border-[rgba(182,70,47,0.22)] bg-white shadow-[0_18px_30px_rgba(77,42,16,0.08)]'
                          : 'border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.72)] hover:bg-white'}
                      `}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <strong className="text-sm text-ink">v{item.version}</strong>
                        <StatusPill tone={item.is_current ? 'ok' : 'default'}>
                          {item.is_current ? '当前版本' : item.status}
                        </StatusPill>
                      </div>
                      <p className="m-0 mt-2 text-sm text-ink-soft">{item.generation_mode}</p>
                      <p className="m-0 mt-2 text-xs text-ink-soft">
                        {toLocalTime(item.updated_at)} / 引用 {item.citations_count} 条
                      </p>
                    </button>
                  );
                })}

                {!versions.length ? (
                  <div className="rounded-2xl border border-dashed border-[rgba(23,32,42,0.12)] px-4 py-6 text-sm leading-relaxed text-ink-soft">
                    {selectedSopId ? '当前 SOP 还没有历史版本。' : '先保存一条 SOP，版本侧栏才会出现内容。'}
                  </div>
                ) : null}
              </div>

              {directoryError ? (
                <p className="m-0 mt-4 text-sm leading-relaxed text-[rgb(150,50,35)]">{directoryError}</p>
              ) : null}
              {versionsError ? (
                <p className="m-0 mt-4 text-sm leading-relaxed text-[rgb(150,50,35)]">{versionsError}</p>
              ) : null}
            </Card>
          </div>

          <div className="col-span-8 grid gap-5 max-lg:col-span-12">
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="m-0 text-xl font-semibold text-ink">保存到系统版本库</h3>
                  <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
                    只有当你需要把草稿沉淀到系统里时，才需要这一步。
                  </p>
                </div>
                <StatusPill tone={
                  saveStatus === 'success'
                    ? 'ok'
                    : saveStatus === 'error'
                      ? 'error'
                      : saveStatus === 'loading'
                        ? 'warn'
                        : 'default'
                }
                >
                  {saveStatus === 'loading'
                    ? '正在保存'
                    : saveStatus === 'success'
                      ? '保存成功'
                      : saveStatus === 'error'
                        ? '保存失败'
                        : '等待保存'}
                </StatusPill>
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <Input
                  label="标题"
                  value={draft.title}
                  onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                  placeholder="如：数字化部系统巡检 SOP 草稿"
                />
                <label className="grid gap-1.5 text-sm font-semibold">
                  状态
                  <select
                    className={SELECT_CLASS_NAME}
                    value={draft.status}
                    onChange={(event) => setDraft((prev) => ({ ...prev, status: event.target.value as SopStatus }))}
                  >
                    <option value="draft">draft</option>
                    <option value="active">active</option>
                    <option value="archived">archived</option>
                  </select>
                </label>
                <label className="grid gap-1.5 text-sm font-semibold">
                  所属部门
                  <select
                    className={SELECT_CLASS_NAME}
                    value={draft.departmentId}
                    onChange={(event) => setDraft((prev) => ({
                      ...prev,
                      departmentId: event.target.value,
                      departmentName: departmentNameById.get(event.target.value) || prev.departmentName,
                    }))}
                    disabled={Boolean(lockedDepartmentId)}
                  >
                    {departmentOptions.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <Input
                  label="标签"
                  value={draft.tagsText}
                  onChange={(event) => setDraft((prev) => ({ ...prev, tagsText: event.target.value }))}
                  placeholder="逗号分隔，如：巡检, 数字化, 标准流程"
                />
                <Input
                  label="工序"
                  value={draft.processName}
                  onChange={(event) => setDraft((prev) => ({ ...prev, processName: event.target.value }))}
                  placeholder="如：巡检"
                />
                <Input
                  label="场景"
                  value={draft.scenarioName}
                  onChange={(event) => setDraft((prev) => ({ ...prev, scenarioName: event.target.value }))}
                  placeholder="如：系统巡检"
                />
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Button onClick={() => void handleSave()} loading={saveStatus === 'loading'} disabled={!canSave}>
                  <span className="inline-flex items-center gap-2">
                    <Save className="h-4 w-4" />
                    保存当前版本
                  </span>
                </Button>
              </div>

              <div className="mt-3 grid gap-2 text-sm text-ink-soft">
                <p className="m-0">{saveMessage || '保存后会写入系统版本库，并在左侧版本列表中立即可见。'}</p>
                <p className="m-0">
                  最近更新时间：{toLocalTime(draft.updatedAt)} / 当前模型：{draft.model || draft.generationMode}
                </p>
              </div>
            </Card>
          </div>
        </section>
      </details>
    </div>
  );
}
