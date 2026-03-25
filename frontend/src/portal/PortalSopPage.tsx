import { PortalDocumentCenter } from '@/portal/PortalDocumentCenter';

export function PortalSopPage() {
  return (
    <PortalDocumentCenter
      eyebrow="SOP Center"
      title="按部门、工序和场景统一查看标准 SOP。"
      description="V0 先复用现有文档主数据，把 SOP 放进一个统一入口里。后续再补版本、审批和下载格式管理，不再分散在不同目录和系统中。"
      scopeTitle="SOP 使用方式"
      scopeDescription="建议先按部门或工序筛选，再进入在线预览。当前版本先使用部门和分类字段承接 SOP 分类语义。"
      categoryLabel="工序/场景"
      emptyText="当前筛选条件下没有匹配的 SOP 文档。请尝试切换部门、工序或关键词。"
      recordSource="sop"
    />
  );
}
