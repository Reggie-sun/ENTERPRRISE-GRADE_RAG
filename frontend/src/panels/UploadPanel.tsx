/**
 * 文档上传面板组件
 * 支持单文件/批量文件创建入库任务并轮询任务状态
 */

import { useEffect, useRef, useState } from 'react';
import { RefreshCw, Upload } from 'lucide-react';
import { useAuth } from '@/auth';
import { Card, Button, Input, ResultBox, StatusPill } from '@/components';
import {
  ApiError,
  createDocument,
  createDocumentsBatch,
  formatApiError,
  getIngestJobStatus,
  type DocumentCreateResponse,
  type IngestJobStatus,
  type IngestJobStatusResponse,
} from '@/api';

// 终态任务状态集合。
const TERMINAL_STATES = new Set<IngestJobStatus>([
  'completed',
  'failed',
  'dead_letter',
  'partial_failed',
]);

// 任务状态中文映射。
const JOB_STATE_TEXT: Record<string, string> = {
  pending: '待处理',
  uploaded: '已上传',
  queued: '已入队',
  parsing: '解析中',
  ocr_processing: 'OCR 处理中',
  chunking: '切块中',
  embedding: '向量化中',
  indexing: '索引写入中',
  completed: '已完成',
  failed: '失败',
  dead_letter: '死信',
  partial_failed: '部分失败',
};

// 面板状态类型。
type PanelStatus = 'idle' | 'uploading' | 'polling' | 'success' | 'error';

interface DuplicateDocumentDetail {
  code: 'DOCUMENT_ALREADY_EXISTS';
  doc_id: string;
  latest_job_id: string;
  file_name: string;
  file_hash: string;
}

interface BatchUploadRow {
  fileName: string;
  submitStatus: 'queued' | 'failed';
  docId: string | null;
  jobId: string | null;
  ingestStatus: IngestJobStatus | null;
  stage: string | null;
  progress: number | null;
  errorCode: string | null;
  errorMessage: string | null;
}

function toRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function parseDuplicateDocumentDetail(error: unknown): DuplicateDocumentDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }

  const candidates: unknown[] = [error.payload];
  if (typeof error.detail === 'string' && error.detail.trim().startsWith('{')) {
    try {
      candidates.push(JSON.parse(error.detail));
    } catch {
      // 兼容 detail 不是 JSON 的场景。
    }
  }

  for (const candidate of candidates) {
    const record = toRecord(candidate);
    const detail = toRecord(record?.detail) as DuplicateDocumentDetail | null;
    if (
      detail?.code === 'DOCUMENT_ALREADY_EXISTS'
      && typeof detail.doc_id === 'string'
      && typeof detail.latest_job_id === 'string'
    ) {
      return detail;
    }
  }

  return null;
}

interface UploadPanelProps {
  title?: string;
  description?: string;
  className?: string;
  allowMultiple?: boolean;
  showIdentityFields?: boolean;
  onUploadStart?: (fileName: string) => void;
  onUploadCreated?: (docId: string) => void;
  onJobStatusChange?: (job: IngestJobStatusResponse) => void;
  onUploadFailed?: () => void;
}

export function UploadPanel({
  title = '上传文档并轮询入库',
  description = '支持单文件和批量上传；每个文件都会创建独立 ingest job 并显示状态进度。',
  className = '',
  allowMultiple = true,
  showIdentityFields = true,
  onUploadStart,
  onUploadCreated,
  onJobStatusChange,
  onUploadFailed,
}: UploadPanelProps) {
  const { profile } = useAuth();
  // 表单状态。
  const [tenantId, setTenantId] = useState(profile?.user.tenant_id || 'wl');
  const [createdBy, setCreatedBy] = useState(profile?.user.user_id || 'demo-user');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [createResult, setCreateResult] = useState<DocumentCreateResponse | null>(null);
  const [jobStatus, setJobStatus] = useState<IngestJobStatusResponse | null>(null);
  const [batchRows, setBatchRows] = useState<BatchUploadRow[]>([]);
  const [error, setError] = useState('');
  const [hint, setHint] = useState('');

  // 轮询定时器和任务集合引用。
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingJobIdsRef = useRef<Set<string>>(new Set());
  const primaryJobIdRef = useRef<string | null>(null);  // 主任务 ID 用 ref 持有，避免轮询闭包拿到旧状态。
  const pollRequestInFlightRef = useRef(false);  // 避免上一次轮询还没结束时继续叠加新请求。
  const consecutivePollFailureCountRef = useRef(0);  // 记录连续轮询失败次数，只在持续异常时再把面板判成 error。

  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    pollingJobIdsRef.current.clear();
    pollRequestInFlightRef.current = false;
    consecutivePollFailureCountRef.current = 0;
  };

  // 组件卸载时清理定时器。
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
      pollingJobIdsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!profile) {
      return;
    }
    setTenantId(profile.user.tenant_id);
    setCreatedBy(profile.user.user_id);
  }, [profile]);

  // 批量获取当前轮询任务状态。
  const fetchBatchJobStatuses = async (fromTimer = false) => {
    const jobIds = Array.from(pollingJobIdsRef.current);
    if (!jobIds.length) {
      return;
    }
    if (pollRequestInFlightRef.current) {
      return;
    }
    if (!fromTimer) {
      setStatus('polling');
    }
    pollRequestInFlightRef.current = true;

    try {
      const results = await Promise.all(jobIds.map((jobId) => getIngestJobStatus(jobId)));
      consecutivePollFailureCountRef.current = 0;
      setError('');
      const resultByJobId = new Map(results.map((item) => [item.job_id, item]));

      setBatchRows((prev) => prev.map((row) => {
        if (!row.jobId) {
          return row;
        }
        const matched = resultByJobId.get(row.jobId);
        if (!matched) {
          return row;
        }
        return {
          ...row,
          ingestStatus: matched.status,
          stage: matched.stage,
          progress: matched.progress,
          errorCode: matched.error_code,
          errorMessage: matched.error_message,
        };
      }));

      if (primaryJobIdRef.current) {
        const primaryJob = resultByJobId.get(primaryJobIdRef.current);
        if (primaryJob) {
          setJobStatus(primaryJob);
          onJobStatusChange?.(primaryJob);
        }
      }

      const allTerminal = results.every((item) => TERMINAL_STATES.has(item.status));
      if (allTerminal) {
        const hasFailedTerminal = results.some((item) => item.status !== 'completed');
        setStatus(hasFailedTerminal ? 'error' : 'success');
        stopPolling();
      }
    } catch (err) {
      consecutivePollFailureCountRef.current += 1;
      const isRetriablePollError = err instanceof ApiError && (err.kind === 'timeout' || err.kind === 'network');
      if (isRetriablePollError && consecutivePollFailureCountRef.current < 3) {
        return;
      }
      setError(formatApiError(err, '任务状态轮询'));
      setStatus('error');
      onUploadFailed?.();
      stopPolling();
    } finally {
      pollRequestInFlightRef.current = false;
    }
  };

  // 开始轮询一组 job。
  const startPolling = (jobIds: string[]) => {
    const normalizedJobIds = jobIds.map((item) => item.trim()).filter((item) => item.length > 0);
    stopPolling();
    if (!normalizedJobIds.length) {
      return;
    }

    pollingJobIdsRef.current = new Set(normalizedJobIds);
    void fetchBatchJobStatuses(false);
    pollTimerRef.current = setInterval(() => {
      void fetchBatchJobStatuses(true);
    }, 1500);
  };

  // 创建入库任务（单文件或批量）。
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (selectedFiles.length === 0) {
      setError('请先选择文件');
      return;
    }

    const tenantValue = tenantId.trim() || 'wl';
    const createdByValue = createdBy.trim();
    const firstFile = selectedFiles[0];

    setStatus('uploading');
    setError('');
    setHint('');
    setCreateResult(null);
    setJobStatus(null);
    setBatchRows([]);
    primaryJobIdRef.current = null;
    stopPolling();
    onUploadStart?.(firstFile.name);

    if (selectedFiles.length === 1) {
      try {
        const formData = new FormData();
        formData.append('file', firstFile);
        formData.append('tenant_id', tenantValue);
        if (createdByValue) {
          formData.append('created_by', createdByValue);
        }

        const result = await createDocument(formData);
        setCreateResult(result);
        primaryJobIdRef.current = result.job_id;
        setBatchRows([
          {
            fileName: firstFile.name,
            submitStatus: 'queued',
            docId: result.doc_id,
            jobId: result.job_id,
            ingestStatus: 'queued',
            stage: 'queued',
            progress: 0,
            errorCode: null,
            errorMessage: null,
          },
        ]);
        onUploadCreated?.(result.doc_id);
        startPolling([result.job_id]);
      } catch (err) {
        const duplicateDetail = parseDuplicateDocumentDetail(err);
        if (duplicateDetail) {
          const existingResult: DocumentCreateResponse = {
            doc_id: duplicateDetail.doc_id,
            job_id: duplicateDetail.latest_job_id,
            status: 'queued',
          };
          setCreateResult(existingResult);
          primaryJobIdRef.current = existingResult.job_id;
          setBatchRows([
            {
              fileName: firstFile.name,
              submitStatus: 'queued',
              docId: duplicateDetail.doc_id,
              jobId: duplicateDetail.latest_job_id,
              ingestStatus: 'queued',
              stage: 'queued',
              progress: 0,
              errorCode: null,
              errorMessage: null,
            },
          ]);
          setHint('检测到重复文档，已复用历史 doc_id，并继续跟踪最新任务状态。');
          onUploadCreated?.(duplicateDetail.doc_id);
          startPolling([duplicateDetail.latest_job_id]);
          return;
        }

        setError(formatApiError(err, '上传并创建入库任务'));
        setStatus('error');
        onUploadFailed?.();
      }
      return;
    }

    try {
      const formData = new FormData();
      for (const file of selectedFiles) {
        formData.append('files', file);
      }
      formData.append('tenant_id', tenantValue);
      if (createdByValue) {
        formData.append('created_by', createdByValue);
      }

      const payload = await createDocumentsBatch(formData);
      const rows: BatchUploadRow[] = payload.items.map((item) => ({
        fileName: item.file_name,
        submitStatus: item.status,
        docId: item.doc_id,
        jobId: item.job_id,
        ingestStatus: item.status === 'queued' ? 'queued' : null,
        stage: item.status === 'queued' ? 'queued' : null,
        progress: item.status === 'queued' ? 0 : null,
        errorCode: item.error_code,
        errorMessage: item.error_message,
      }));
      setBatchRows(rows);
      setHint(`批量提交完成：共 ${payload.total} 个，已入队 ${payload.queued} 个，失败 ${payload.failed} 个。`);

      const firstQueued = rows.find((row) => row.submitStatus === 'queued' && row.docId && row.jobId);
      if (firstQueued?.docId && firstQueued.jobId) {
        const primaryResult: DocumentCreateResponse = {
          doc_id: firstQueued.docId,
          job_id: firstQueued.jobId,
          status: 'queued',
        };
        setCreateResult(primaryResult);
        primaryJobIdRef.current = primaryResult.job_id;
        onUploadCreated?.(primaryResult.doc_id);
      }

      const queuedJobIds = rows
        .filter((row) => row.submitStatus === 'queued' && row.jobId)
        .map((row) => row.jobId as string);
      if (queuedJobIds.length === 0) {
        setStatus('error');
        onUploadFailed?.();
        return;
      }

      startPolling(queuedJobIds);
    } catch (err) {
      setError(formatApiError(err, '批量上传并创建入库任务'));
      setStatus('error');
      onUploadFailed?.();
    }
  };

  // 手动轮询最新任务。
  const handlePoll = () => {
    if (pollingJobIdsRef.current.size > 0) {
      void fetchBatchJobStatuses(false);
      return;
    }
    if (createResult?.job_id) {
      startPolling([createResult.job_id]);
    }
  };

  // 获取状态徽章信息。
  const getStatusInfo = () => {
    const submitFailedCount = batchRows.filter((row) => row.submitStatus === 'failed').length;
    const queuedRows = batchRows.filter((row) => row.submitStatus === 'queued');
    const completedCount = queuedRows.filter((row) => row.ingestStatus === 'completed').length;
    const ingestFailedCount = queuedRows.filter((row) => (
      row.ingestStatus !== null && TERMINAL_STATES.has(row.ingestStatus) && row.ingestStatus !== 'completed'
    )).length;
    const totalFailed = submitFailedCount + ingestFailedCount;

    if (status === 'idle') {
      return { text: '等待上传', tone: 'warn' as const };
    }
    if (status === 'uploading') {
      return { text: '上传中...', tone: 'warn' as const };
    }
    if (status === 'polling') {
      return {
        text: `已提交 ${batchRows.length} 个，完成 ${completedCount}/${queuedRows.length}，失败 ${totalFailed} 个`,
        tone: 'warn' as const,
      };
    }
    if (status === 'success') {
      return { text: `任务完成：成功 ${completedCount} 个`, tone: 'ok' as const };
    }
    return { text: `任务结束：失败 ${totalFailed} 个`, tone: 'error' as const };
  };

  const statusInfo = getStatusInfo();
  const activeDocId = createResult?.doc_id ?? jobStatus?.doc_id ?? '-';
  const activeJobId = createResult?.job_id ?? jobStatus?.job_id ?? '-';
  const stageText = jobStatus ? (JOB_STATE_TEXT[jobStatus.stage] || jobStatus.stage) : '-';
  const failureCode = jobStatus?.error_code || '-';
  const failureText = jobStatus?.error_message || '-';
  const selectedFileText = selectedFiles.length === 0
    ? '-'
    : selectedFiles.length === 1
      ? selectedFiles[0].name
      : `${selectedFiles[0].name} 等 ${selectedFiles.length} 个文件`;

  return (
    <Card className={`col-span-8 ${className}`}>
      {/* 标题 */}
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">{title}</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        {description}
      </p>

      {/* 表单 */}
      <form onSubmit={handleSubmit} className="grid gap-3">
        {/* 两列布局 */}
        {showIdentityFields ? (
          <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
            <Input
              label="租户 ID"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              required
              disabled={Boolean(profile)}
            />
            <Input
              label="创建人"
              value={createdBy}
              onChange={(e) => setCreatedBy(e.target.value)}
              disabled={Boolean(profile)}
            />
          </div>
        ) : null}

        {profile ? (
          <p className="m-0 text-sm leading-relaxed text-ink-soft">
            当前已登录为 {profile.user.display_name || profile.user.username}。租户和上传人会以后端权限上下文自动校准。
          </p>
        ) : null}

        {/* 文件选择 */}
        <label className="grid gap-1.5 text-sm font-semibold">
          {allowMultiple ? '文件（可多选）' : '文件'}
          <input
            type="file"
            multiple={allowMultiple}
            accept=".pdf,.md,.markdown,.txt,.docx,.png,.jpg,.jpeg,.webp,.bmp"
            onChange={(e) => setSelectedFiles(Array.from(e.target.files || []))}
            className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 file:mr-4 file:rounded-full file:border-0 file:bg-accent file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-accent-deep"
          />
        </label>

        {/* 操作按钮 */}
        <div className="flex flex-wrap gap-2.5">
          <Button type="submit" loading={status === 'uploading'}>
            <span className="flex items-center gap-2">
              <Upload className="w-4 h-4" />
              {allowMultiple && selectedFiles.length > 1 ? '批量创建入库任务' : '创建入库任务'}
            </span>
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={handlePoll}
            disabled={batchRows.length === 0 && !createResult}
          >
            <span className="flex items-center gap-2">
              <RefreshCw className="w-4 h-4" />
              轮询最新任务
            </span>
          </Button>
        </div>
      </form>

      {/* 状态徽章 */}
      <StatusPill tone={statusInfo.tone}>{statusInfo.text}</StatusPill>
      {hint ? <p className="m-0 mt-2 text-sm text-ink-soft">{hint}</p> : null}

      {/* 主结果展示 */}
      <div className="mt-4">
        <ResultBox>
          {`文件: ${selectedFileText}
doc_id: ${activeDocId}
job_id: ${activeJobId}
当前阶段: ${stageText}
当前进度: ${jobStatus ? `${jobStatus.progress}%` : '-'}
错误码: ${failureCode}
错误信息: ${failureText}

${error ? `面板错误: ${error}` : '面板错误: -'}
`}
        </ResultBox>
      </div>

      {/* 批量明细 */}
      {batchRows.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm text-ink border-separate border-spacing-0">
            <thead>
              <tr>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">文件</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">提交状态</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">doc_id</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">job_id</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">入库阶段</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">进度</th>
                <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">错误</th>
              </tr>
            </thead>
            <tbody>
              {batchRows.map((row, index) => (
                <tr key={`${row.fileName}-${index}`}>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)] break-all">{row.fileName}</td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)]">
                    {row.submitStatus === 'queued' ? '已入队' : '失败'}
                  </td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)] break-all">{row.docId || '-'}</td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)] break-all">{row.jobId || '-'}</td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)]">
                    {row.stage ? (JOB_STATE_TEXT[row.stage] || row.stage) : '-'}
                  </td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)]">
                    {typeof row.progress === 'number' ? `${row.progress}%` : '-'}
                  </td>
                  <td className="p-2 border-b border-[rgba(23,32,42,0.08)] break-all">
                    {row.errorMessage || row.errorCode || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
}
