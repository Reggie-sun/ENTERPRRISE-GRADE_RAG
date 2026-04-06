import { BookOpenText, Library, LogOut, MessageSquare, Shield, UserRound } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { getRoleExperience, useAuth } from '@/auth';
import { Layout } from '@/components';

const navItems = [
  { to: '/portal', label: '智能问答', icon: MessageSquare },
  { to: '/portal/sop', label: 'SOP 中心', icon: BookOpenText },
  { to: '/portal/library', label: '文档中心', icon: Library },
  { to: '/portal/me', label: '我的', icon: UserRound },
];

export function PortalShell() {
  const { profile, canAccessWorkspace, logout } = useAuth();
  const experience = getRoleExperience(profile)

  return (
    <Layout>
      <div className="grid gap-5">
        {/* Header - Clean White with Subtle Border */}
        <header className="rounded-2xl border border-[rgba(15,23,42,0.06)] bg-white/95 px-6 py-4 shadow-[0_1px_3px_rgba(15,23,42,0.04), backdrop-blur-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            {/* Navigation Tabs */}
            <nav className="flex flex-wrap gap-2">
              {navItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/portal'}
                    className={({ isActive }) => `
                      inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-semibold transition-all duration-150
                      ${isActive
                        ? 'bg-gradient-to-r from-accent to-accent-deep text-white shadow-[0_4px_12px_rgba(194,65,12, 0.15)]'
                        : 'text-ink-soft hover:bg-[rgba(15,23,42,0.04)] hover:text-ink'}
                    `}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </NavLink>
                )
              })}
            </nav>

            {/* User Info & Actions */}
            <div className="flex flex-wrap items-center justify-end gap-3">
              <div className="rounded-xl border border-[rgba(15,23,42,0.06)] bg-[rgba(15,23,42,0.02)] px-4 py-2.5 text-sm">
                <p className="m-0 whitespace-nowrap font-medium text-ink">
                  {profile?.user.display_name || profile?.user.username}
                  <span className="text-ink-soft">
                    {' '}· {experience.roleLabel} / {profile?.department.department_name}
                  </span>
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                {canAccessWorkspace ? (
                  <NavLink
                    to="/workspace"
                    className="inline-flex items-center gap-2 rounded-full bg-[rgba(15,23,42,0.05)] px-4 py-2.5 text-sm font-semibold text-ink no-underline transition-all duration-150 hover:bg-[rgba(15,23,42,0.08)] hover:shadow-sm"
                  >
                    <Shield className="h-4 w-4" />
                    {experience.workspaceEntryLabel}
                  </NavLink>
                ) : null}
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="inline-flex items-center gap-2 rounded-full border border-[rgba(194,65,12,0.12)] bg-[rgba(194,65,12, 0.04)] px-4 py-2.5 text-sm font-semibold text-accent-deep transition-all duration-150 hover:bg-[rgba(194,65,12, 0.08)]"
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
  )
}
