import {
  BookOpenText,
  Building2,
  Files,
  LayoutDashboard,
  MessageSquare,
  Search,
  Shield,
} from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { Card, HeroCard, Layout, StatusPill } from '@/components';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

const navItems = [
  {
    to: '/',
    label: '总览',
    description: '健康检查与入口导航',
    icon: LayoutDashboard,
  },
  {
    to: '/documents',
    label: '文档中心',
    description: '上传、列表、预览、重建',
    icon: Files,
  },
  {
    to: '/retrieval',
    label: '检索验证',
    description: '看召回结果与 chunk 命中',
    icon: Search,
  },
  {
    to: '/chat',
    label: '问答验证',
    description: '流式回答与引用回显',
    icon: MessageSquare,
  },
  {
    to: '/sop',
    label: 'SOP 中心',
    description: '预留分类、预览、下载页',
    icon: BookOpenText,
  },
  {
    to: '/admin',
    label: '管理后台',
    description: '预留身份、权限、配置页',
    icon: Shield,
  },
];

export function AppShell() {
  const {
    currentDocumentName,
    currentDocId,
    currentJobIdText,
    currentJobStageText,
    currentJobTone,
  } = useUploadWorkspace();

  return (
    <Layout>
      <div className="grid grid-cols-[300px_minmax(0,1fr)] gap-5 items-start max-[1100px]:grid-cols-1">
        <aside className="grid gap-4 min-w-0">
          <HeroCard className="sticky top-4 max-[1100px]:static">
            <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
              Enterprise RAG
            </div>
            <h1 className="m-0 text-3xl font-serif leading-tight text-ink">
              企业知识库工作台
            </h1>
            <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
              先把单页 demo 拆成稳定的企业页面骨架，后面再叠登录、SOP 和权限，不继续往一个组件里堆。
            </p>

            <nav className="mt-5 grid gap-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) => `
                      rounded-2xl border px-4 py-3 transition-all duration-200
                      ${isActive
                        ? 'border-[rgba(182,70,47,0.18)] bg-white shadow-[0_18px_36px_rgba(77,42,16,0.08)]'
                        : 'border-transparent bg-[rgba(255,255,255,0.42)] hover:bg-white'}
                    `}
                  >
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 rounded-2xl bg-[rgba(182,70,47,0.1)] p-2 text-accent-deep">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="m-0 font-semibold text-ink">{item.label}</p>
                        <p className="m-0 mt-1 text-xs leading-relaxed text-ink-soft">
                          {item.description}
                        </p>
                      </div>
                    </div>
                  </NavLink>
                );
              })}
            </nav>
          </HeroCard>

          <Card className="bg-panel border-[rgba(182,70,47,0.12)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="m-0 text-sm text-ink-soft">当前工作上下文</p>
                <strong className="block mt-1 text-xl font-serif text-ink">
                  {currentDocumentName || '未锁定文档'}
                </strong>
              </div>
              <div className="flex items-center gap-2 text-sm text-ink-soft">
                <Building2 className="h-4 w-4" />
                企业页骨架
              </div>
            </div>

            <div className="mt-4">
              <StatusPill tone={currentJobTone}>{currentJobStageText}</StatusPill>
            </div>

            <div className="mt-4 grid gap-2 text-sm text-ink-soft">
              <p className="m-0 break-all">
                {currentDocId ? `doc_id: ${currentDocId}` : 'doc_id: -'}
              </p>
              <p className="m-0 break-all">{`job_id: ${currentJobIdText}`}</p>
              <p className="m-0 leading-relaxed">
                页面切换不会丢掉当前上传上下文；检索和问答页会直接复用这里的当前文档。
              </p>
            </div>
          </Card>
        </aside>

        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </Layout>
  );
}
