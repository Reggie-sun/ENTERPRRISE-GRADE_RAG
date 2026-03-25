import { PortalDocumentCenter } from '@/portal/PortalDocumentCenter';

export function PortalLibraryPage() {
  return (
    <PortalDocumentCenter
      eyebrow="Knowledge Library"
      title="像浏览资料中心一样查看知识文档，而不是操作后台数据表。"
      description="知识库页提供搜索、筛选、预览和下载入口。普通用户只看到业务可消费的信息，不展示 ingest 状态、向量重建和删除操作。"
      scopeTitle="知识库浏览方式"
      scopeDescription="优先通过标题、部门、分类找到资料，再决定是否在线预览或下载原文。当前 V0 以可检索文档为主。"
      categoryLabel="分类"
      emptyText="当前没有找到匹配的知识资料。请换一个关键词或清空筛选条件后再试。"
      recordSource="library"
    />
  );
}
