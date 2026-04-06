import { Download, Eye, FileText, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Button, Card, HeroCard, Input, ResultBox, StatusPill } from '@/components';
import {
  formatApiError,
  getDocumentDownloadUrl,
  getDocumentPreview,
  getDocuments,
  type DocumentPreviewResponse,
  type DocumentSummary,
} from '@/api';
import { rememberDocument, type RecentDocumentSource } from '@/portal/portalStorage';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

interface PortalDocumentCenterProps {
  eyebrow: string;
  title: string;
  description: string;
  scopeTitle: string;
  scopeDescription: string;
  categoryLabel: string;
  emptyText: string;
  recordSource: RecentDocumentSource;
}

const PREVIEWABLE_SUFFIXES = new Set(['.txt', '.md', '.markdown', '.doc', '.docx', '.pdf']);

function toLocalTime(isoText: string): string {
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
}

function getFileSuffix(filename: string): string {
  const normalized = filename.trim().toLowerCase();
  const dotIndex = normalized.lastIndexOf('.');
  if (dotIndex < 0) {
    return '';
  }
  return normalized.slice(dotIndex);
}

function supportsInlinePreview(filename: string): boolean {
  return PREVIEWABLE_SUFFIXES.has(getFileSuffix(filename));
}

export function PortalDocumentCenter({
  eyebrow,
  title,
  description,
  scopeTitle,
  scopeDescription,
  categoryLabel,
  emptyText,
  recordSource,
}: PortalDocumentCenterProps) {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [searchParams, setSearchParams] = useSearchParams();
  const accessibleDepartmentIds = profile?.accessible_department_ids || [];
  const lockedDepartmentId = accessibleDepartmentIds.length === 1 ? accessibleDepartmentIds[0] : '';
  const initialDepartmentId = searchParams.get('department') || lockedDepartmentId;
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [keyword, setKeyword] = useState(searchParams.get('keyword') || '');
  const [departmentId, setDepartmentId] = useState(initialDepartmentId);
  const [categoryId, setCategoryId] = useState(searchParams.get('category') || '');
  const [selectedDocId, setSelectedDocId] = useState(searchParams.get('doc_id') || '');
  const [previewStatus, setPreviewStatus] = useState<PanelStatus>('idle');
  const [previewError, setPreviewError] = useState('');
  const [previewData, setPreviewData] = useState<DocumentPreviewResponse | null>(null);

  useEffect(() => {
    if (lockedDepartmentId && departmentId !== lockedDepartmentId) {
      setDepartmentId(lockedDepartmentId);
    }
  }, [departmentId, lockedDepartmentId]);

  useEffect(() => {
    const loadDocuments = async () => {
      setStatus('loading');
      setError('');
      try {
        const payload = await getDocuments({
          page: 1,
          page_size: 200,
          status: 'active',
          department_id: lockedDepartmentId || undefined,
        });
        const sorted = [...payload.items].sort(
          (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
        );
        setDocuments(sorted);
        setStatus('success');
      } catch (err) {
        setStatus('error');
        setError(formatApiError(err, scopeTitle));
      }
    };

    void loadDocuments();
  }, [lockedDepartmentId, scopeTitle]);

  const filteredDocuments = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    const visibleDepartmentIds = accessibleDepartmentIds.length ? new Set(accessibleDepartmentIds) : null;

    return documents.filter((item) => {
      const matchesKeyword = !normalizedKeyword || [
        item.filename,
        item.document_id,
        item.department_id || '',
        item.category_id || '',
      ].some((value) => value.toLowerCase().includes(normalizedKeyword));
      const matchesDepartment = !departmentId || item.department_id === departmentId;
      const matchesCategory = !categoryId || item.category_id === categoryId;
      const matchesScope = !visibleDepartmentIds || !item.department_id || visibleDepartmentIds.has(item.department_id);
      return matchesKeyword && matchesDepartment && matchesCategory && matchesScope;
    });
  }, [accessibleDepartmentIds, categoryId, departmentId, documents, keyword]);

  const departmentOptions = useMemo(() => {
    const visibleDepartmentIds = accessibleDepartmentIds.length ? new Set(accessibleDepartmentIds) : null;
    return Array.from(
      new Set(
        documents
          .map((item) => item.department_id)
          .filter((item): item is string => Boolean(item) && (!visibleDepartmentIds || visibleDepartmentIds.has(item ?? ''))),
      ),
    ).sort();
  }, [accessibleDepartmentIds, documents]);

  const categoryOptions = useMemo(
    () => Array.from(
      new Set(
        documents
          .map((item) => item.category_id)
          .filter((item): item is string => Boolean(item)),
      ),
    ).sort(),
    [documents],
  );

  useEffect(() => {
    const nextDocId = searchParams.get('doc_id') || '';
    if (nextDocId && nextDocId !== selectedDocId) {
      setSelectedDocId(nextDocId);
    }
  }, [searchParams, selectedDocId]);

  useEffect(() => {
    if (!selectedDocId) {
      setPreviewData(null);
      setPreviewStatus('idle');
      setPreviewError('');
      return;
    }

    const currentDoc = documents.find((item) => item.document_id === selectedDocId);
    if (currentDoc && !supportsInlinePreview(currentDoc.filename)) {
      setPreviewData(null);
      setPreviewStatus('error');
      setPreviewError('当前文件类型暂不支持在线预览，请直接下载原文。支持的类型：DOCX、Markdown、TXT、PDF。');
      return;
    }

    const loadPreview = async () => {
      setPreviewStatus('loading');
      setPreviewError('');
      try {
        const payload = await getDocumentPreview(selectedDocId);
        setPreviewData(payload);
        setPreviewStatus('success');
        rememberDocument({
          docId: payload.doc_id,
          fileName: payload.file_name,
          departmentId: currentDoc?.department_id || null,
          categoryId: currentDoc?.category_id || null,
          source: recordSource,
        });
      } catch (err) {
        setPreviewData(null);
        setPreviewStatus('error');
        setPreviewError(formatApiError(err, '文档预览'));
      }
    };

    void loadPreview();
  }, [documents, recordSource, selectedDocId]);

  const handleOpenPreview = (docId: string) => {
    setSelectedDocId(docId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('doc_id', docId);
    if (keyword.trim()) {
      nextParams.set('keyword', keyword.trim());
    } else {
      nextParams.delete('keyword');
    }
    if (departmentId) {
      nextParams.set('department', departmentId);
    } else {
      nextParams.delete('department');
    }
    if (categoryId) {
      nextParams.set('category', categoryId);
    } else {
      nextParams.delete('category');
    }
    setSearchParams(nextParams);
  };

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(194,65,12,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            {eyebrow}
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            {title}
          </h2>
          <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
            {description}
          </p>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(194,65,12,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">{scopeTitle}</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            {scopeDescription}
          </p>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前角色</strong>
              <p className="m-0 mt-2">{experience.roleLabel}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前权限范围</strong>
              <p className="m-0 mt-2 leading-relaxed">{scopeSummary}</p>
            </div>
            <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
              <strong className="block text-ink">当前结果</strong>
              <p className="m-0 mt-2">{filteredDocuments.length} 条</p>
            </div>
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-lg:col-span-12">
          <div className="grid gap-3 md:grid-cols-3">
            <Input
              label="搜索资料"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="输入标题、部门或分类"
            />
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              部门
              <select
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
                disabled={Boolean(lockedDepartmentId)}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink disabled:cursor-not-allowed disabled:bg-[rgba(15,23,42,0.05)]"
              >
                {!lockedDepartmentId ? <option value="">全部部门</option> : null}
                {departmentOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              {categoryLabel}
              <select
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink"
              >
                <option value="">全部分类</option>
                {categoryOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-3 text-sm leading-relaxed text-ink-soft">
            {lockedDepartmentId
              ? `当前部门范围已锁定为 ${profile?.department.department_name || lockedDepartmentId}，不需要手动切换部门。`
              : `你当前拥有更大范围的访问权限，建议先按部门和分类缩小结果范围。`}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : 'warn'}>
              {status === 'loading' && '资料加载中'}
              {status === 'success' && `当前命中 ${filteredDocuments.length} 条`}
              {status === 'error' && '资料加载失败'}
              {status === 'idle' && '待加载'}
            </StatusPill>
            <div className="flex items-center gap-2 text-sm text-ink-soft">
              <Search className="h-4 w-4" />
              优先通过部门和分类缩小范围，再查看预览
            </div>
          </div>

          {status === 'error' ? (
            <div className="mt-4">
              <ResultBox>{error}</ResultBox>
            </div>
          ) : null}

          <div className="mt-4 grid max-h-[720px] gap-3 overflow-auto pr-1">
            {filteredDocuments.map((item) => (
              (() => {
                const canPreview = supportsInlinePreview(item.filename);
                return (
                  <article
                    key={item.document_id}
                    className={`
                      rounded-xl border p-4 transition-all duration-200
                      ${selectedDocId === item.document_id
                        ? 'border-[rgba(194,65,12,0.18)] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_36px_rgba(77,42,16,0.08)]'
                        : 'border-[rgba(15,23,42,0.08)] bg-[rgba(255,255,255,0.72)]'}
                    `}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="m-0 font-semibold text-ink break-all">{item.filename}</p>
                        <p className="m-0 mt-2 text-sm text-ink-soft">
                          {item.department_id || '未标注部门'} / {item.category_id || '未标注分类'}
                        </p>
                        <p className="m-0 mt-1 text-xs text-ink-soft">
                          更新时间：{toLocalTime(item.updated_at)}
                        </p>
                      </div>
                      <StatusPill tone={canPreview ? 'ok' : 'warn'}>
                        {canPreview ? '可预览' : '仅下载'}
                      </StatusPill>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button type="button" onClick={() => handleOpenPreview(item.document_id)} disabled={!canPreview}>
                        <span className="flex items-center gap-2">
                          <Eye className="h-4 w-4" />
                          {canPreview ? '在线预览' : '暂不支持预览'}
                        </span>
                      </Button>
                      <a
                        href={getDocumentDownloadUrl(item.document_id)}
                        className="inline-flex items-center gap-2 rounded-full bg-[rgba(15,23,42,0.06)] px-5 py-3 text-sm font-bold text-ink no-underline transition-all duration-200 hover:-translate-y-0.5"
                      >
                        <Download className="h-4 w-4" />
                        下载原文
                      </a>
                    </div>
                  </article>
                );
              })()
            ))}

            {!filteredDocuments.length && status === 'success' ? (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-5 text-sm leading-relaxed text-ink-soft">
                {emptyText}
              </div>
            ) : null}
          </div>
        </Card>

        <Card className="col-span-5 max-lg:col-span-12 bg-panel border-[rgba(194,65,12,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">在线预览</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            先预览，再决定是否下载，避免用户反复本地打开文档。
          </p>

          <div className="mt-4">
            {previewStatus === 'idle' ? (
              <ResultBox>从左侧选择一份资料，预览内容会显示在这里。</ResultBox>
            ) : null}
            {previewStatus === 'loading' ? (
              <StatusPill tone="warn">正在加载预览</StatusPill>
            ) : null}
            {previewStatus === 'error' ? (
              <ResultBox>{previewError}</ResultBox>
            ) : null}
            {previewStatus === 'success' && previewData ? (
              <div className="grid gap-3">
                <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                  <p className="m-0 font-semibold text-ink break-all">{previewData.file_name}</p>
                  <p className="m-0 mt-2 text-sm text-ink-soft">
                    更新时间：{toLocalTime(previewData.updated_at)}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <a
                      href={getDocumentDownloadUrl(previewData.doc_id)}
                      className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-accent to-[#d16837] px-4 py-2 text-sm font-semibold text-white no-underline"
                    >
                      <Download className="h-4 w-4" />
                      下载原文
                    </a>
                    {previewData.preview_file_url ? (
                      <a
                        href={previewData.preview_file_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 rounded-full bg-[rgba(15,23,42,0.06)] px-4 py-2 text-sm font-semibold text-ink no-underline"
                      >
                        <FileText className="h-4 w-4" />
                        新窗口打开
                      </a>
                    ) : null}
                  </div>
                </div>

                {previewData.preview_type === 'pdf' && previewData.preview_file_url ? (
                  <iframe
                    src={previewData.preview_file_url}
                    title={`portal-preview-${previewData.doc_id}`}
                    className="h-[420px] w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-white"
                  />
                ) : null}

                {previewData.text_content ? (
                  <ResultBox>{previewData.text_content}</ResultBox>
                ) : previewData.preview_type === 'pdf' ? (
                  <ResultBox>当前 PDF 暂无可直接展示的解析文本，请使用上方在线预览或下载原文。</ResultBox>
                ) : (
                  <ResultBox>该文档暂无可展示文本内容。</ResultBox>
                )}
              </div>
            ) : null}
          </div>
        </Card>
      </section>
    </div>
  );
}
