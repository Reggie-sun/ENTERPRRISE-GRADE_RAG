import {
  Activity,
  BookOpenText,
  Building2,
  Files,
  Gauge,
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
    description: '查看当前账号范围、常用入口与处理进度',
    icon: LayoutDashboard,
  },
  {
    to: '/workspace/documents',
    label: '文档中心',
    description: '维护企业资料、分类与版本',
    icon: Files,
  },
  {
    to: '/workspace/retrieval',
    label: '知识检索',
    description: '查看资料命中效果与内容范围',
    icon: Search,
  },
  {
    to: '/workspace/chat',
    label: '智能问答',
    description: '检查问答结果与引用内容',
    icon: MessageSquare,
  },
  {
    to: '/workspace/logs',
    label: '操作记录',
    description: '查看关键操作记录与处理轨迹',
    icon: Activity,
  },
  {
    to: '/workspace/ops',
    label: '平台状态',
    description: '查看服务状态、任务积压与异常提醒',
    icon: Gauge,
  },
  {
    to: '/workspace/sop',
    label: 'SOP 中心',
    description: '生成、编辑、发布标准作业流程',
    icon: BookOpenText,
  },
];

const adminNavItem = {
  to: '/workspace/admin',
  label: '管理后台',
  description: '统一管理账号、权限与平台配置',
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
              管理中心
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
                <p className="m-0 text-sm text-ink-soft">当前处理内容</p>
                <strong className="block mt-1 text-xl font-serif text-ink">
                  {currentDocumentName || '未选择资料'}
                </strong>
              </div>
              <div className="flex items-center gap-2 text-sm text-ink-soft">
                <Building2 className="h-4 w-4" />
                {profile?.department.department_name || '管理视角'}
              </div>
            </div>

            <div className="mt-4">
              <StatusPill tone={currentJobTone}>{currentJobStageText}</StatusPill>
            </div>

            <div className="mt-4 grid gap-2 text-sm text-ink-soft">
              <p className="m-0 break-all">
                {currentDocId ? `资料编号：${currentDocId}` : '资料编号：-'}
              </p>
              <p className="m-0 break-all">{`任务编号：${currentJobIdText}`}</p>
              <p className="m-0 leading-relaxed">
                页面切换时会保留当前资料与任务进度，方便在不同功能页之间继续处理。
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
