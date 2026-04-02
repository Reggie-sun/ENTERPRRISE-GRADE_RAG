import { BookOpenText, LogOut, MessageSquare, Shield } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Layout } from '@/components';

const navItems = [
  { to: '/portal', label: '智能问答', icon: MessageSquare },
  { to: '/portal/sop', label: 'SOP 中心', icon: BookOpenText },
];

export function PortalShell() {
  const { profile, canAccessWorkspace, logout } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);

  return (
    <Layout>
      <div className="grid gap-4">
        <header className="rounded-[28px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,248,240,0.84)] px-5 py-4 shadow-[0_18px_40px_rgba(77,42,16,0.1)] backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <nav className="flex flex-wrap gap-2">
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

            <div className="flex flex-wrap items-center justify-end gap-3">
              <div className="rounded-2xl bg-[rgba(255,255,255,0.74)] px-4 py-3 text-sm text-ink-soft">
                <p className="m-0 font-semibold text-ink">{profile?.user.display_name || profile?.user.username}</p>
                <p className="m-0 mt-1">
                  {experience.roleLabel} / {profile?.department.department_name}
                </p>
                <p className="m-0 mt-2 max-w-[44ch] leading-relaxed">
                  {scopeSummary}
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
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
        </header>

        <Outlet />
      </div>
    </Layout>
  );
}
