/**
 * 文档列表面板
 * 展示文档主数据、状态和分页筛选能力
 */

import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Card, Button, Input, ResultBox, StatusPill } from '@/components';
import {
  deleteDocument,
  formatApiError,
  getDocumentPreview,
  getDocuments,
  rebuildDocumentVectors,
  type DocumentLifecycleStatus,
  type DocumentPreviewResponse,
  type DocumentSummary,
} from '@/api';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

const STATUS_OPTIONS: Array<{ label: string; value: DocumentLifecycleStatus | '' }> = [
  { label: '全部状态', value: '' },
  { label: '已排队', value: 'queued' },
  { label: '已上传', value: 'uploaded' },
  { label: '可检索', value: 'active' },
  { label: '已删除', value: 'deleted' },
  { label: '失败', value: 'failed' },
  { label: '部分失败', value: 'partial_failed' },
];

const JOB_STATUS_TEXT: Record<string, string> = {
  pending: '待处理',
  uploaded: '已上传',
  queued: '已入队',
  parsing: '解析中',
  ocr_processing: 'OCR处理中',
  chunking: '切块中',
  embedding: '向量化中',
  indexing: '索引写入中',
  completed: '已完成',
  failed: '失败',
  dead_letter: '死信',
  partial_failed: '部分失败',
};

const DOC_STATUS_TEXT: Record<string, string> = {
  queued: '已排队',
  uploaded: '已上传',
  active: '可检索',
  deleted: '已删除',
  failed: '失败',
  partial_failed: '部分失败',
};

function toLocalTime(isoText: string): string {
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
}

export function DocumentListPanel() {
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [items, setItems] = useState<DocumentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [previewStatus, setPreviewStatus] = useState<PanelStatus>('idle');
  const [previewError, setPreviewError] = useState('');
  const [previewData, setPreviewData] = useState<DocumentPreviewResponse | null>(null);
  const [previewDocId, setPreviewDocId] = useState('');
  const [deleteLoadingDocId, setDeleteLoadingDocId] = useState('');
  const [rebuildLoadingDocId, setRebuildLoadingDocId] = useState('');
  const [operationMessage, setOperationMessage] = useState('');
  const [operationError, setOperationError] = useState('');

  const [keyword, setKeyword] = useState('');
  const [departmentId, setDepartmentId] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [docStatus, setDocStatus] = useState<DocumentLifecycleStatus | ''>('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const fetchDocuments = async (targetPage: number, targetPageSize: number) => {
    setStatus('loading');
    setError('');
    try {
      const payload = await getDocuments({
        page: targetPage,
        page_size: targetPageSize,
        keyword: keyword.trim() || undefined,
        department_id: departmentId.trim() || undefined,
        category_id: categoryId.trim() || undefined,
        status: docStatus || undefined,
      });
      setItems(payload.items);
      setTotal(payload.total);
      setPage(payload.page);
      setPageSize(payload.page_size);
      setStatus('success');
    } catch (err) {
      setStatus('error');
      setError(formatApiError(err, '文档列表查询'));
    }
  };

  useEffect(() => {
    fetchDocuments(1, pageSize);  // 首次加载时拉取第一页。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchDocuments(1, pageSize);  // 新筛选条件从第一页开始。
  };

  const handleRefresh = () => {
    fetchDocuments(page, pageSize);
  };

  const handleResetFilters = () => {
    setKeyword('');
    setDepartmentId('');
    setCategoryId('');
    setDocStatus('');
    fetchDocuments(1, pageSize);
  };

  const handlePreview = async (docId: string) => {
    setPreviewStatus('loading');
    setPreviewError('');
    setPreviewDocId(docId);
    try {
      const payload = await getDocumentPreview(docId);
      setPreviewData(payload);
      setPreviewStatus('success');
    } catch (err) {
      setPreviewData(null);
      setPreviewStatus('error');
      setPreviewError(formatApiError(err, '文档预览'));
    }
  };

  const handleDelete = async (item: DocumentSummary) => {
    const confirmed = window.confirm(`确认删除文档「${item.filename}」吗？该操作会清理向量副本。`);
    if (!confirmed) {
      return;
    }
    setDeleteLoadingDocId(item.document_id);
    setOperationMessage('');
    setOperationError('');
    try {
      const result = await deleteDocument(item.document_id);
      setOperationMessage(`文档已删除：${result.doc_id}，已清理向量 ${result.vector_points_removed} 条。`);
      if (previewData?.doc_id === item.document_id) {
        setPreviewData(null);
        setPreviewStatus('idle');
        setPreviewDocId('');
      }
      await fetchDocuments(page, pageSize);
    } catch (err) {
      setOperationError(formatApiError(err, '删除文档'));
    } finally {
      setDeleteLoadingDocId('');
    }
  };

  const handleRebuild = async (item: DocumentSummary) => {
    if (item.status === 'deleted') {
      setOperationError('已删除文档不支持重建向量。');
      setOperationMessage('');
      return;
    }
    const confirmed = window.confirm(`确认重建文档「${item.filename}」的向量索引吗？`);
    if (!confirmed) {
      return;
    }
    setRebuildLoadingDocId(item.document_id);
    setOperationMessage('');
    setOperationError('');
    try {
      const result = await rebuildDocumentVectors(item.document_id);
      setOperationMessage(
        `已触发重建向量任务：${result.job_id}（文档 ${result.doc_id}，预清理向量 ${result.previous_vector_points_removed} 条）。`
      );
      await fetchDocuments(page, pageSize);
    } catch (err) {
      setOperationError(formatApiError(err, '重建向量'));
    } finally {
      setRebuildLoadingDocId('');
    }
  };

  const maxPage = Math.max(1, Math.ceil(total / pageSize));
  const canPrev = page > 1;
  const canNext = page < maxPage;

  return (
    <Card className="col-span-12">
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">文档列表</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        按主数据筛选并分页浏览文档，区分文档状态与最新 ingest 状态。
      </p>

      <form onSubmit={handleSearch} className="grid gap-3 mb-4">
        <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2 max-md:grid-cols-1">
          <Input
            label="关键字"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="文件名或 doc_id"
          />
          <Input
            label="部门"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
            placeholder="department_id"
          />
          <Input
            label="分类"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            placeholder="category_id"
          />
          <label className="grid gap-1.5 text-sm font-semibold text-ink">
            文档状态
            <select
              value={docStatus}
              onChange={(e) => setDocStatus(e.target.value as DocumentLifecycleStatus | '')}
              className="w-full rounded-2xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.label} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-2.5">
          <Button type="submit" loading={status === 'loading'}>
            查询列表
          </Button>
          <Button type="button" variant="ghost" onClick={handleRefresh}>
            <span className="flex items-center gap-2">
              <RefreshCw className="w-4 h-4" />
              刷新
            </span>
          </Button>
          <Button type="button" variant="ghost" onClick={handleResetFilters}>
            清空筛选
          </Button>
        </div>
      </form>

      <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : 'warn'}>
        {status === 'idle' && '待执行'}
        {status === 'loading' && '加载中'}
        {status === 'success' && `共 ${total} 条，当前第 ${page}/${maxPage} 页`}
        {status === 'error' && '查询失败'}
      </StatusPill>

      {status === 'error' ? (
        <div className="mt-3">
          <ResultBox>{error}</ResultBox>
        </div>
      ) : null}
      {operationMessage ? (
        <div className="mt-3">
          <StatusPill tone="ok">{operationMessage}</StatusPill>
        </div>
      ) : null}
      {operationError ? (
        <div className="mt-3">
          <ResultBox>{operationError}</ResultBox>
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-sm text-ink border-separate border-spacing-0">
          <thead>
            <tr>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">文件名</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">部门</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">分类</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">上传人</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">文档状态</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">入库状态</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">更新时间</th>
              <th className="text-left font-semibold p-2 border-b border-[rgba(23,32,42,0.12)]">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.document_id}>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">
                  <p className="m-0 font-semibold">{item.filename}</p>
                  <p className="m-0 mt-1 text-xs text-ink-soft break-all">{item.document_id}</p>
                </td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">{item.department_id || '-'}</td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">{item.category_id || '-'}</td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">{item.uploaded_by || '-'}</td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">
                  {DOC_STATUS_TEXT[item.status] || item.status}
                </td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">
                  {item.ingest_status ? (JOB_STATUS_TEXT[item.ingest_status] || item.ingest_status) : '-'}
                </td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">{toLocalTime(item.updated_at)}</td>
                <td className="p-2 border-b border-[rgba(23,32,42,0.08)] align-top">
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      loading={previewStatus === 'loading' && previewDocId === item.document_id}
                      onClick={() => handlePreview(item.document_id)}
                    >
                      预览
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      loading={deleteLoadingDocId === item.document_id}
                      onClick={() => handleDelete(item)}
                    >
                      删除
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      loading={rebuildLoadingDocId === item.document_id}
                      disabled={item.status === 'deleted'}
                      onClick={() => handleRebuild(item)}
                    >
                      重建向量
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {items.length === 0 && status !== 'loading' ? (
              <tr>
                <td className="p-4 text-center text-ink-soft" colSpan={8}>
                  没有匹配的数据
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <Button
          type="button"
          variant="ghost"
          disabled={!canPrev || status === 'loading'}
          onClick={() => fetchDocuments(page - 1, pageSize)}
        >
          上一页
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={!canNext || status === 'loading'}
          onClick={() => fetchDocuments(page + 1, pageSize)}
        >
          下一页
        </Button>
        <label className="ml-2 text-sm text-ink-soft flex items-center gap-2">
          每页
          <select
            value={pageSize}
            onChange={(e) => {
              const nextPageSize = Number(e.target.value);
              fetchDocuments(1, nextPageSize);
            }}
            className="rounded-xl border border-[rgba(23,32,42,0.12)] bg-[rgba(255,255,255,0.82)] px-2 py-1 text-sm text-ink"
          >
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
          </select>
        </label>
      </div>

      <div className="mt-5 grid gap-3">
        <h3 className="m-0 text-lg font-semibold text-ink">文档预览</h3>
        {previewStatus === 'idle' ? (
          <ResultBox>点击列表里的“预览”查看文档内容。</ResultBox>
        ) : null}
        {previewStatus === 'loading' ? (
          <StatusPill tone="warn">正在加载预览</StatusPill>
        ) : null}
        {previewStatus === 'error' ? (
          <ResultBox>{previewError}</ResultBox>
        ) : null}
        {previewStatus === 'success' && previewData ? (
          <div className="grid gap-3">
            <StatusPill tone="ok">
              {previewData.file_name} | {previewData.preview_type === 'pdf' ? 'PDF 预览' : '文本预览'} | 更新时间 {toLocalTime(previewData.updated_at)}
            </StatusPill>
            {previewData.preview_type === 'text' ? (
              <ResultBox>{previewData.text_content || '该文档暂无可展示文本内容。'}</ResultBox>
            ) : (
              <div className="grid gap-2">
                {previewData.preview_file_url ? (
                  <iframe
                    src={previewData.preview_file_url}
                    title={`preview-${previewData.doc_id}`}
                    className="w-full h-[460px] rounded-2xl border border-[rgba(23,32,42,0.12)] bg-white"
                  />
                ) : null}
                {previewData.text_content ? (
                  <ResultBox>{previewData.text_content}</ResultBox>
                ) : (
                  <ResultBox>PDF 解析文本暂不可用，请直接查看上方在线 PDF 预览。</ResultBox>
                )}
              </div>
            )}
            {previewData.text_truncated ? (
              <p className="m-0 text-xs text-ink-soft">预览内容已按长度截断，仅显示前 12000 个字符。</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
