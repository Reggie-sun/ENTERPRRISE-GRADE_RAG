import { BookOpenText, House, Library, LogOut, MessageSquare, Shield, UserRound } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Layout } from '@/components';

const navItems = [
  { to: '/portal', label: '首页', icon: House },
  { to: '/portal/chat', label: '智能问答', icon: MessageSquare },
  { to: '/portal/sop', label: 'SOP 中心', icon: BookOpenText },
  { to: '/portal/library', label: '知识库', icon: Library },
  { to: '/portal/me', label: '我的', icon: UserRound },
];

export function PortalShell() {
  const { profile, canAccessWorkspace, logout } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);

  return (
    <Layout>
      <div className="grid gap-5">
        <header className="rounded-[32px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,248,240,0.88)] px-6 py-6 shadow-[0_22px_54px_rgba(77,42,16,0.12)] backdrop-blur-xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-[760px]">
              <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
                DFMS Knowledge Portal
              </div>
              <h1 className="m-0 mt-4 font-serif text-3xl md:text-4xl leading-tight text-ink">
                面向企业用户的知识与 SOP 门户
              </h1>
              <p className="m-0 mt-3 max-w-[64ch] text-sm leading-relaxed text-ink-soft md:text-base">
                {experience.portalHeaderNote}
              </p>
            </div>
            <div className="rounded-3xl bg-[rgba(255,255,255,0.74)] px-4 py-4 text-sm text-ink-soft">
              <p className="m-0 font-semibold text-ink">{profile?.user.display_name || profile?.user.username}</p>
              <p className="m-0 mt-1">
                {experience.roleLabel} / {profile?.department.department_name}
              </p>
              <p className="m-0 mt-2 leading-relaxed">
                {scopeSummary}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {canAccessWorkspace ? (
                  <NavLink
                    to="/workspace"
                    className="inline-flex items-center gap-2 rounded-full bg-[rgba(23,32,42,0.06)] px-4 py-2 text-sm font-semibold text-ink no-underline transition-all duration-200 hover:-translate-y-0.5"
                  >
                    <Shield className="h-4 w-4" />
                    {experience.workspaceEntryLabel}
                  </NavLink>
                ) : null}
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
          </div>

          <nav className="mt-5 flex flex-wrap gap-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/portal'}
                  className={({ isActive }) => `
                    inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-semibold transition-all duration-200
                    ${isActive
                      ? 'bg-gradient-to-r from-accent to-[#d16837] text-white shadow-[0_16px_28px_rgba(182,70,47,0.24)]'
                      : 'bg-[rgba(255,255,255,0.72)] text-ink hover:-translate-y-0.5 hover:bg-white'}
                  `}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>
        </header>

        <Outlet />

        <footer className="rounded-[28px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.6)] px-5 py-4 text-sm leading-relaxed text-ink-soft">
          当前门户已经支持员工端问答、SOP 生成、SOP 查看和知识资料浏览；重建向量、系统健康检查等研发能力仍保留在内部工作台。
        </footer>
      </div>
    </Layout>
  );
}
