import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { IngestJobStatusResponse } from '@/api';

export type StatusTone = 'default' | 'ok' | 'warn' | 'error';

interface UploadWorkspaceValue {
  currentDocumentName: string;
  currentDocId: string;
  latestJob: IngestJobStatusResponse | null;
  panelResetSignal: number;
  currentJobStageText: string;
  currentJobIdText: string;
  currentJobTone: StatusTone;
  handleUploadStart: (fileName: string) => void;
  handleUploadCreated: (docId: string) => void;
  handleJobStatusChange: (job: IngestJobStatusResponse) => void;
  handleUploadFailed: () => void;
}

const UploadWorkspaceContext = createContext<UploadWorkspaceValue | null>(null);

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

export function UploadWorkspaceProvider({ children }: { children: ReactNode }) {
  const [currentDocumentName, setCurrentDocumentName] = useState('');
  const [currentDocId, setCurrentDocId] = useState('');
  const [latestJob, setLatestJob] = useState<IngestJobStatusResponse | null>(null);
  const [panelResetSignal, setPanelResetSignal] = useState(0);

  const value = useMemo<UploadWorkspaceValue>(() => ({
    currentDocumentName,
    currentDocId,
    latestJob,
    panelResetSignal,
    currentJobStageText: latestJob
      ? `任务 ${latestJob.status} | 阶段 ${latestJob.stage} | ${latestJob.progress}%`
      : '尚未创建上传任务',
    currentJobIdText: latestJob?.job_id || '-',
    currentJobTone: getJobStatusTone(latestJob?.status),
    handleUploadStart: (fileName: string) => {
      setCurrentDocumentName(fileName);
      setCurrentDocId('');
      setLatestJob(null);
      setPanelResetSignal((prev) => prev + 1);
    },
    handleUploadCreated: (docId: string) => {
      setCurrentDocId(docId);
    },
    handleJobStatusChange: (job: IngestJobStatusResponse) => {
      setLatestJob(job);
    },
    handleUploadFailed: () => {
      setCurrentDocumentName('');
      setCurrentDocId('');
      setLatestJob(null);
    },
  }), [currentDocumentName, currentDocId, latestJob, panelResetSignal]);

  return (
    <UploadWorkspaceContext.Provider value={value}>
      {children}
    </UploadWorkspaceContext.Provider>
  );
}

export function useUploadWorkspace(): UploadWorkspaceValue {
  const context = useContext(UploadWorkspaceContext);
  if (!context) {
    throw new Error('useUploadWorkspace must be used within UploadWorkspaceProvider');
  }
  return context;
}
