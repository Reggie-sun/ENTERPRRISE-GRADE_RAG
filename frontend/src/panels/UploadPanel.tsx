/**
 * 文档上传面板组件
 * 支持创建入库任务并轮询任务状态
 */

import { useState, useEffect, useRef } from 'react';
import { Upload, RefreshCw } from 'lucide-react';  // 引入图标。
import { Card, Button, StatusPill, ResultBox, Input } from '@/components';
import {
  ApiError,
  createDocument,
  getIngestJobStatus,
  type IngestJobStatusResponse,
  type DocumentCreateResponse,
  type IngestJobStatus,
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

function parseDuplicateDocumentDetail(error: unknown): DuplicateDocumentDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }

  try {
    const parsed = JSON.parse(error.detail) as { detail?: DuplicateDocumentDetail };
    const detail = parsed.detail;
    if (
      detail?.code === 'DOCUMENT_ALREADY_EXISTS'
      && typeof detail.doc_id === 'string'
      && typeof detail.latest_job_id === 'string'
    ) {
      return detail;
    }
  } catch {
    return null;
  }

  return null;
}

interface UploadPanelProps {
  onUploadStart?: (fileName: string) => void;
  onUploadCreated?: (docId: string) => void;
  onJobStatusChange?: (job: IngestJobStatusResponse) => void;
  onUploadFailed?: () => void;
}

export function UploadPanel({
  onUploadStart,
  onUploadCreated,
  onJobStatusChange,
  onUploadFailed,
}: UploadPanelProps) {
  // 表单状态。
  const [tenantId, setTenantId] = useState('wl');
  const [createdBy, setCreatedBy] = useState('demo-user');
  const [file, setFile] = useState<File | null>(null);

  // 面板状态。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [createResult, setCreateResult] = useState<DocumentCreateResponse | null>(null);
  const [jobStatus, setJobStatus] = useState<IngestJobStatusResponse | null>(null);
  const [error, setError] = useState<string>('');

  // 轮询定时器引用。
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 组件卸载时清理定时器。
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, []);

  // 获取任务状态。
  const fetchJobStatus = async (jobId: string, fromTimer = false) => {
    if (!fromTimer) {
      setStatus('polling');
    }

    try {
      const result = await getIngestJobStatus(jobId);
      setJobStatus(result);
      onJobStatusChange?.(result);

      // 判断是否为终态。
      const isTerminal = TERMINAL_STATES.has(result.status);
      if (isTerminal) {
        setStatus(result.status === 'completed' ? 'success' : 'error');
        // 终态时停止轮询。
        if (pollTimerRef.current) {
          clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
      onUploadFailed?.();
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }
  };

  // 开始轮询。
  const startPolling = (jobId: string) => {
    // 清理已有定时器。
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
    }

    // 立即获取一次状态。
    fetchJobStatus(jobId);

    // 每 1.5 秒轮询一次。
    pollTimerRef.current = setInterval(() => fetchJobStatus(jobId, true), 1500);
  };

  // 创建入库任务。
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) {
      setError('请先选择文件');
      return;
    }

    setStatus('uploading');
    setError('');
    onUploadStart?.(file.name);

    try {
      // 构建 FormData。
      const formData = new FormData();
      formData.append('file', file);
      formData.append('tenant_id', tenantId.trim() || 'wl');
      if (createdBy.trim()) {
        formData.append('created_by', createdBy.trim());
      }

      // 发送创建请求。
      const result = await createDocument(formData);
      setCreateResult(result);
      onUploadCreated?.(result.doc_id);

      // 开始轮询任务状态。
      startPolling(result.job_id);
    } catch (err) {
      const duplicateDetail = parseDuplicateDocumentDetail(err);
      if (duplicateDetail) {
        const existingResult: DocumentCreateResponse = {
          doc_id: duplicateDetail.doc_id,
          job_id: duplicateDetail.latest_job_id,
          status: 'queued',
        };
        setCreateResult(existingResult);
        setJobStatus(null);
        setError('');
        onUploadCreated?.(duplicateDetail.doc_id);
        startPolling(duplicateDetail.latest_job_id);
        return;
      }

      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
      onUploadFailed?.();
    }
  };

  // 手动轮询最新任务。
  const handlePoll = () => {
    if (createResult?.job_id) {
      fetchJobStatus(createResult.job_id);
    }
  };

  // 获取状态徽章信息。
  const getStatusInfo = () => {
    if (!jobStatus) {
      return { text: status === 'idle' ? '等待上传' : '处理中...', tone: 'warn' as const };
    }

    const stateText = JOB_STATE_TEXT[jobStatus.status] || jobStatus.status;
    const stageText = JOB_STATE_TEXT[jobStatus.stage] || jobStatus.stage;

    if (jobStatus.status === 'completed') {
      return { text: `任务${stateText} | ${jobStatus.progress}%`, tone: 'ok' as const };
    }
    if (TERMINAL_STATES.has(jobStatus.status)) {
      return { text: `任务${stateText} | 阶段 ${stageText}`, tone: 'error' as const };
    }
    return { text: `任务${stateText} | 阶段 ${stageText} | ${jobStatus.progress}%`, tone: 'warn' as const };
  };

  const statusInfo = getStatusInfo();

  return (
    <Card className="col-span-8">
      {/* 标题 */}
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">上传文档并轮询入库</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        创建真实 ingest job，然后持续观察状态流转，直到 worker 进入终态。
      </p>

      {/* 表单 */}
      <form onSubmit={handleSubmit} className="grid gap-3">
        {/* 两列布局 */}
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <Input
            label="租户 ID"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            required
          />
          <Input
            label="创建人"
            value={createdBy}
            onChange={(e) => setCreatedBy(e.target.value)}
          />
        </div>

        {/* 文件选择 */}
        <label className="grid gap-1.5 text-sm font-semibold">
          文件
          <input
            type="file"
            accept=".pdf,.md,.markdown,.txt"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 file:mr-4 file:rounded-full file:border-0 file:bg-accent file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-accent-deep"
          />
        </label>

        {/* 操作按钮 */}
        <div className="flex flex-wrap gap-2.5">
          <Button type="submit" loading={status === 'uploading'}>
            <span className="flex items-center gap-2">
              <Upload className="w-4 h-4" />
              创建入库任务
            </span>
          </Button>
          <Button type="button" variant="ghost" onClick={handlePoll} disabled={!createResult}>
            <span className="flex items-center gap-2">
              <RefreshCw className="w-4 h-4" />
              轮询最新任务
            </span>
          </Button>
        </div>
      </form>

      {/* 状态徽章 */}
      <StatusPill tone={statusInfo.tone}>{statusInfo.text}</StatusPill>

      {/* 结果展示 */}
      <div className="mt-4">
        <ResultBox>
          {jobStatus ? (
            JSON.stringify(jobStatus, null, 2)
          ) : createResult ? (
            JSON.stringify(createResult, null, 2)
          ) : error ? (
            error
          ) : (
            '还没有任务。'
          )}
        </ResultBox>
      </div>
    </Card>
  );
}
