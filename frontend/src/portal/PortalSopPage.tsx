import { Eye, FileDown, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, Input, ResultBox, StatusPill } from '@/components';
import {
  downloadSopFile,
  formatApiError,
  getSopDetail,
  getSopPreview,
  getSops,
  type SopDetailResponse,
  type SopDownloadFormat,
  type SopPreviewResponse,
  type SopStatus,
  type SopSummary,
} from '@/api';
import { PortalSopGeneratePanel } from './PortalSopGeneratePanel';

type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

function toLocalTime(isoText: string): string {
  const value = new Date(isoText);
  if (Number.isNaN(value.getTime())) {
    return isoText;
  }
  return value.toLocaleString('zh-CN', { hour12: false });
}

export function PortalSopPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const [searchParams, setSearchParams] = useSearchParams();
  const accessibleDepartmentIds = profile?.accessible_department_ids || [];
  const lockedDepartmentId = accessibleDepartmentIds.length === 1 ? accessibleDepartmentIds[0] : '';
  const initialDepartmentId = searchParams.get('department') || lockedDepartmentId;
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [error, setError] = useState('');
  const [sops, setSops] = useState<SopSummary[]>([]);
  const [keyword, setKeyword] = useState(searchParams.get('keyword') || '');
  const [departmentId, setDepartmentId] = useState(initialDepartmentId);
  const [processName, setProcessName] = useState(searchParams.get('process') || '');
  const [scenarioName, setScenarioName] = useState(searchParams.get('scenario') || '');
  const [statusFilter, setStatusFilter] = useState<SopStatus | ''>(
    (searchParams.get('status') as SopStatus | '') || 'active',
  );
  const [selectedSopId, setSelectedSopId] = useState(searchParams.get('sop_id') || '');
  const [detailStatus, setDetailStatus] = useState<PanelStatus>('idle');
  const [detailError, setDetailError] = useState('');
  const [detailData, setDetailData] = useState<SopDetailResponse | null>(null);
  const [previewStatus, setPreviewStatus] = useState<PanelStatus>('idle');
  const [previewError, setPreviewError] = useState('');
  const [previewData, setPreviewData] = useState<SopPreviewResponse | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<PanelStatus>('idle');
  const [downloadError, setDownloadError] = useState('');
  const [downloadingFormat, setDownloadingFormat] = useState<SopDownloadFormat | ''>('');

  useEffect(() => {
    if (lockedDepartmentId && departmentId !== lockedDepartmentId) {
      setDepartmentId(lockedDepartmentId);
    }
  }, [departmentId, lockedDepartmentId]);

  useEffect(() => {
    const loadSops = async () => {
      setStatus('loading');
      setError('');
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
        setStatus('success');
      } catch (err) {
        setStatus('error');
        setError(formatApiError(err, 'SOP 列表查询'));
      }
    };

    void loadSops();
  }, [lockedDepartmentId]);

  const filteredSops = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    const visibleDepartmentIds = accessibleDepartmentIds.length ? new Set(accessibleDepartmentIds) : null;

    return sops.filter((item) => {
      const matchesKeyword = !normalizedKeyword || [
        item.title,
        item.department_name,
        item.process_name || '',
        item.scenario_name || '',
      ].some((value) => value.toLowerCase().includes(normalizedKeyword));
      const matchesDepartment = !departmentId || item.department_id === departmentId;
      const matchesProcess = !processName || item.process_name === processName;
      const matchesScenario = !scenarioName || item.scenario_name === scenarioName;
      const matchesStatus = !statusFilter || item.status === statusFilter;
      const matchesScope = !visibleDepartmentIds || visibleDepartmentIds.has(item.department_id);
      return matchesKeyword && matchesDepartment && matchesProcess && matchesScenario && matchesStatus && matchesScope;
    });
  }, [accessibleDepartmentIds, departmentId, keyword, processName, scenarioName, sops, statusFilter]);

  useEffect(() => {
    if (!filteredSops.length) {
      setSelectedSopId('');
      return;
    }
    if (!selectedSopId || !filteredSops.some((item) => item.sop_id === selectedSopId)) {
      setSelectedSopId(filteredSops[0].sop_id);
    }
  }, [filteredSops, selectedSopId]);

  useEffect(() => {
    if (!selectedSopId) {
      setDetailStatus('idle');
      setDetailError('');
      setDetailData(null);
      setPreviewStatus('idle');
      setPreviewError('');
      setPreviewData(null);
      setDownloadStatus('idle');
      setDownloadError('');
      setDownloadingFormat('');
      return;
    }

    setDownloadStatus('idle');
    setDownloadError('');
    setDownloadingFormat('');

    const loadSopSidePanel = async () => {
      setDetailStatus('loading');
      setDetailError('');
      setPreviewStatus('loading');
      setPreviewError('');
      try {
        const [detailPayload, previewPayload] = await Promise.all([
          getSopDetail(selectedSopId),
          getSopPreview(selectedSopId),
        ]);
        setDetailData(detailPayload);
        setPreviewData(previewPayload);
        setDetailStatus('success');
        setPreviewStatus('success');
      } catch (err) {
        const message = formatApiError(err, 'SOP 详情与预览');
        setDetailData(null);
        setPreviewData(null);
        setDetailStatus('error');
        setDetailError(message);
        setPreviewStatus('error');
        setPreviewError(message);
      }
    };

    void loadSopSidePanel();
  }, [selectedSopId]);

  const departmentOptions = useMemo(
    () => Array.from(new Set(sops.map((item) => item.department_id)))
      .map((item) => ({
        department_id: item,
        department_name: sops.find((sop) => sop.department_id === item)?.department_name || item,
      }))
      .sort((left, right) => left.department_name.localeCompare(right.department_name, 'zh-CN')),
    [sops],
  );

  const processOptions = useMemo(
    () => Array.from(
      new Set(sops.map((item) => item.process_name).filter((item): item is string => Boolean(item))),
    ).sort((a, b) => a.localeCompare(b, 'zh-CN')),
    [sops],
  );

  const scenarioOptions = useMemo(
    () => Array.from(
      new Set(sops.map((item) => item.scenario_name).filter((item): item is string => Boolean(item))),
    ).sort((a, b) => a.localeCompare(b, 'zh-CN')),
    [sops],
  );

  useEffect(() => {
    const nextParams = new URLSearchParams();
    if (keyword.trim()) {
      nextParams.set('keyword', keyword.trim());
    }
    if (departmentId) {
      nextParams.set('department', departmentId);
    }
    if (processName) {
      nextParams.set('process', processName);
    }
    if (scenarioName) {
      nextParams.set('scenario', scenarioName);
    }
    if (statusFilter) {
      nextParams.set('status', statusFilter);
    }
    if (selectedSopId) {
      nextParams.set('sop_id', selectedSopId);
    }
    setSearchParams(nextParams, { replace: true });
  }, [departmentId, keyword, processName, scenarioName, selectedSopId, setSearchParams, statusFilter]);

  const handleDownload = async (format: 'docx' | 'pdf') => {
    if (!selectedSopId) {
      return;
    }
    setDownloadStatus('loading');
    setDownloadError('');
    setDownloadingFormat(format);
    try {
      await downloadSopFile(selectedSopId, format);
      setDownloadStatus('success');
    } catch (err) {
      setDownloadStatus('error');
      setDownloadError(formatApiError(err, `SOP ${format.toUpperCase()} 下载`));
    } finally {
      setDownloadingFormat('');
    }
  };

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-12 gap-5">
        <HeroCard className="col-span-8 max-lg:col-span-12">
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(194,65,12,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            SOP Center
          </div>
          <h2 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
            先基于文档直接生成 SOP，再统一查看标准 SOP。
          </h2>
          <p className="m-0 mt-3 max-w-[64ch] text-base leading-relaxed text-ink-soft">
            员工端主流程已经收敛成“上传文档 → 生成 SOP 草稿 → 下载本地修改”。下方仍保留已沉淀 SOP 的统一查看、预览和格式下载入口。
          </p>
        </HeroCard>

        <Card className="col-span-4 max-lg:col-span-12 bg-panel border-[rgba(194,65,12,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前使用方式</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            {experience.sopScopeDescription}
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
              <p className="m-0 mt-2">{filteredSops.length} 条</p>
            </div>
          </div>
        </Card>
      </section>

      <PortalSopGeneratePanel />

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-lg:col-span-12">
          <div className="mb-4">
            <h3 className="m-0 text-xl font-semibold text-ink">已沉淀 SOP 资产</h3>
            <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
              这里保留已经沉淀到系统里的 SOP 资产，适合按部门、工序、场景继续查阅、预览和下载。
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <Input
              label="搜索 SOP"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="输入标题、工序或场景"
            />
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              部门
              <select
                value={departmentId}
                onChange={(event) => setDepartmentId(event.target.value)}
                disabled={Boolean(lockedDepartmentId)}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink disabled:cursor-not-allowed disabled:bg-[rgba(15,23,42,0.05)]"
              >
                {!lockedDepartmentId ? <option value="">全部部门</option> : null}
                {departmentOptions.map((item) => (
                  <option key={item.department_id} value={item.department_id}>{item.department_name}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              工序
              <select
                value={processName}
                onChange={(event) => setProcessName(event.target.value)}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink"
              >
                <option value="">全部工序</option>
                {processOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              场景
              <select
                value={scenarioName}
                onChange={(event) => setScenarioName(event.target.value)}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink"
              >
                <option value="">全部场景</option>
                {scenarioOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-semibold text-ink">
              状态
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as SopStatus | '')}
                className="w-full rounded-2xl border border-[rgba(15,23,42,0.12)] bg-[rgba(255,255,255,0.82)] px-4 py-3 text-sm text-ink"
              >
                <option value="">全部状态</option>
                <option value="active">生效中</option>
                <option value="draft">草稿</option>
                <option value="archived">已归档</option>
              </select>
            </label>
          </div>

          <div className="mt-3 text-sm leading-relaxed text-ink-soft">
            {lockedDepartmentId
              ? `当前部门范围已锁定为 ${profile?.department.department_name || lockedDepartmentId}，不需要手动切换部门。`
              : '你当前拥有更大范围的访问权限，建议先按部门、工序或场景缩小结果范围。'}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <StatusPill tone={status === 'error' ? 'error' : status === 'success' ? 'ok' : 'warn'}>
              {status === 'loading' && 'SOP 加载中'}
              {status === 'success' && `当前命中 ${filteredSops.length} 条`}
              {status === 'error' && 'SOP 加载失败'}
              {status === 'idle' && '待加载'}
            </StatusPill>
            <div className="flex items-center gap-2 text-sm text-ink-soft">
              <Search className="h-4 w-4" />
              先定位标准流程，再进入详情、预览和下载
            </div>
          </div>

          {status === 'error' ? (
            <div className="mt-4">
              <ResultBox>{error}</ResultBox>
            </div>
          ) : null}

          <div className="mt-4 grid max-h-[720px] gap-3 overflow-auto pr-1">
            {filteredSops.map((item) => (
              <article
                key={item.sop_id}
                className={`
                  rounded-xl border p-4 transition-all duration-200
                  ${selectedSopId === item.sop_id
                    ? 'border-[rgba(194,65,12,0.18)] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_36px_rgba(77,42,16,0.08)]'
                    : 'border-[rgba(15,23,42,0.08)] bg-[rgba(255,255,255,0.72)]'}
                `}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="m-0 font-semibold text-ink break-all">{item.title}</p>
                    <p className="m-0 mt-2 text-sm text-ink-soft">
                      {item.department_name} / {item.process_name || '未标注工序'} / {item.scenario_name || '未标注场景'}
                    </p>
                    <p className="m-0 mt-1 text-xs text-ink-soft">
                      版本 v{item.version} · 更新时间：{toLocalTime(item.updated_at)}
                    </p>
                  </div>
                  <StatusPill tone={item.status === 'active' ? 'ok' : item.status === 'draft' ? 'warn' : 'error'}>
                    {item.status === 'active' ? '生效中' : item.status === 'draft' ? '草稿' : '已归档'}
                  </StatusPill>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setSelectedSopId(item.sop_id)}
                    className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-accent to-[#d16837] px-5 py-3 text-sm font-bold text-white transition-all duration-200 hover:-translate-y-0.5"
                  >
                    <Eye className="h-4 w-4" />
                    查看详情
                  </button>
                  <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(15,23,42,0.06)] px-5 py-3 text-sm font-bold text-ink">
                    <FileDown className="h-4 w-4" />
                    {item.downloadable_formats.join(' / ').toUpperCase() || '待补下载'}
                  </div>
                </div>
              </article>
            ))}

            {!filteredSops.length && status === 'success' ? (
              <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-5 text-sm leading-relaxed text-ink-soft">
                当前筛选条件下没有匹配的 SOP。请尝试切换部门、工序、场景或关键词。
              </div>
            ) : null}
          </div>
        </Card>

        <Card className="col-span-5 max-lg:col-span-12 bg-panel border-[rgba(194,65,12,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">SOP 详情与预览</h3>
          <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
            当前右侧已经接入真实详情、文本预览和格式下载。下载逻辑仍保持独立，不反向侵入文档主链路。
          </p>

          <div className="mt-4">
            {!selectedSopId ? (
              <ResultBox>从左侧选择一份 SOP，这里会显示主数据概览。</ResultBox>
            ) : detailStatus === 'loading' || previewStatus === 'loading' ? (
              <StatusPill tone="warn">正在加载详情与预览</StatusPill>
            ) : detailStatus === 'error' || previewStatus === 'error' ? (
              <ResultBox>{detailError || previewError}</ResultBox>
            ) : detailData && previewData ? (
              <div className="grid gap-3">
                <div className="rounded-2xl bg-[rgba(255,255,255,0.72)] p-4">
                  <p className="m-0 font-semibold text-ink">{detailData.title}</p>
                  <div className="mt-4 grid gap-3 text-sm text-ink-soft">
                    <div>
                      <strong className="block text-ink">部门</strong>
                      <p className="m-0 mt-1">{detailData.department_name}</p>
                    </div>
                    <div>
                      <strong className="block text-ink">工序 / 场景</strong>
                      <p className="m-0 mt-1">{detailData.process_name || '未标注工序'} / {detailData.scenario_name || '未标注场景'}</p>
                    </div>
                    <div>
                      <strong className="block text-ink">当前版本</strong>
                      <p className="m-0 mt-1">v{detailData.version}</p>
                    </div>
                    <div>
                      <strong className="block text-ink">资源准备情况</strong>
                      <p className="m-0 mt-1">
                        预览：{detailData.preview_resource_path ? '已准备' : '待补'} / 下载：
                        {detailData.download_docx_available && detailData.download_pdf_available
                          ? ' DOCX / PDF'
                          : detailData.download_docx_available
                            ? ' DOCX'
                            : detailData.download_pdf_available
                              ? ' PDF'
                              : ' 待补'}
                      </p>
                    </div>
                    <div>
                      <strong className="block text-ink">最近更新时间</strong>
                      <p className="m-0 mt-1">{toLocalTime(detailData.updated_at)}</p>
                    </div>
                    <div>
                      <strong className="block text-ink">维护人</strong>
                      <p className="m-0 mt-1">{detailData.updated_by || detailData.created_by || '未标注'}</p>
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleDownload('docx')}
                    disabled={!detailData.download_docx_available || downloadStatus === 'loading'}
                    className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-accent to-[#d16837] px-5 py-3 text-sm font-bold text-white transition-all duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:translate-y-0"
                  >
                    <FileDown className="h-4 w-4" />
                    {downloadingFormat === 'docx' ? '下载中...' : '下载 DOCX'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDownload('pdf')}
                    disabled={!detailData.download_pdf_available || downloadStatus === 'loading'}
                    className="inline-flex items-center gap-2 rounded-full bg-[rgba(15,23,42,0.06)] px-5 py-3 text-sm font-bold text-ink transition-all duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:translate-y-0"
                  >
                    <FileDown className="h-4 w-4" />
                    {downloadingFormat === 'pdf' ? '下载中...' : '下载 PDF'}
                  </button>
                </div>

                {downloadStatus === 'success' ? (
                  <div className="text-sm text-ink-soft">
                    已触发下载，可继续切换 SOP 或格式。
                  </div>
                ) : null}

                {downloadStatus === 'error' ? (
                  <ResultBox>{downloadError}</ResultBox>
                ) : null}

                {previewData.preview_type === 'text' && previewData.text_content ? (
                  <ResultBox>{previewData.text_content}</ResultBox>
                ) : previewData.preview_file_url ? (
                  <a
                    href={previewData.preview_file_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-[rgba(15,23,42,0.06)] px-5 py-3 text-sm font-bold text-ink no-underline"
                  >
                    <Eye className="h-4 w-4" />
                    打开预览资源
                  </a>
                ) : (
                  <ResultBox>当前 SOP 暂无可展示的预览内容。</ResultBox>
                )}
              </div>
            ) : (
              <ResultBox>当前 SOP 详情暂不可用，请稍后重试。</ResultBox>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
