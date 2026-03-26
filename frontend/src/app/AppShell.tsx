import {
  BookOpenText,
  Building2,
  Files,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Search,
  Shield,
} from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, Layout, StatusPill } from '@/components';
import { useUploadWorkspace } from '@/app/UploadWorkspaceContext';

const baseNavItems = [
  {
    to: '/workspace',
    label: '总览',
    description: '健康检查、角色边界与入口导航',
    icon: LayoutDashboard,
  },
  {
    to: '/workspace/documents',
    label: '文档中心',
    description: '上传、列表、预览、重建',
    icon: Files,
  },
  {
    to: '/workspace/retrieval',
    label: '检索验证',
    description: '看召回结果与 chunk 命中',
    icon: Search,
  },
  {
    to: '/workspace/chat',
    label: '问答验证',
    description: '流式回答与引用回显',
    icon: MessageSquare,
  },
  {
    to: '/workspace/sop',
    label: 'SOP 中心',
    description: '生成、编辑、保存和版本管理',
    icon: BookOpenText,
  },
];

const adminNavItem = {
  to: '/workspace/admin',
  label: '管理后台',
  description: '身份、权限、配置总入口',
  icon: Shield,
};

export function AppShell() {
  const { profile, canAccessAdmin, logout } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);
  const {
    currentDocumentName,
    currentDocId,
    currentJobIdText,
    currentJobStageText,
    currentJobTone,
  } = useUploadWorkspace();
  const navItems = canAccessAdmin ? [...baseNavItems, adminNavItem] : baseNavItems;

  return (
    <Layout>
      <div className="grid grid-cols-[300px_minmax(0,1fr)] gap-5 items-start max-[1100px]:grid-cols-1">
        <aside className="grid gap-4 min-w-0">
          <HeroCard className="sticky top-4 max-[1100px]:static">
            <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
              Workspace
            </div>
            <h1 className="m-0 text-3xl font-serif leading-tight text-ink">
              {experience.workspaceTitle}
            </h1>
            <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
              {experience.workspaceDescription}
            </p>

            <div className="mt-5 rounded-3xl bg-[rgba(255,255,255,0.74)] px-4 py-4 text-sm text-ink-soft">
              <p className="m-0 font-semibold text-ink">
                {profile?.user.display_name || profile?.user.username}
              </p>
              <p className="m-0 mt-1">
                {experience.roleLabel} / {profile?.department.department_name}
              </p>
              <p className="m-0 mt-2 leading-relaxed">{scopeSummary}</p>
              <p className="m-0 mt-2 leading-relaxed">{experience.workspaceBoundary}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <NavLink
                  to="/portal"
                  className="inline-flex items-center gap-2 rounded-full bg-[rgba(23,32,42,0.06)] px-4 py-2 text-sm font-semibold text-ink no-underline transition-all duration-200 hover:-translate-y-0.5"
                >
                  返回门户
                </NavLink>
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="inline-flex items-center gap-2 rounded-full border-0 bg-[rgba(182,70,47,0.1)] px-4 py-2 text-sm font-semibold text-accent-deep transition-all duration-200 hover:-translate-y-0.5"
                >
                  <LogOut className="h-4 w-4" />
                  退出登录
                </button>
              </div>
            </div>

            <nav className="mt-5 grid gap-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/workspace'}
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
                {profile?.department.department_name || '内部入口'}
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
