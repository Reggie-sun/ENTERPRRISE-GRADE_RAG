import { LockKeyhole, ShieldAlert } from 'lucide-react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Button, Card, HeroCard, Layout } from '@/components';
import { useAuth } from '@/auth/AuthContext';
import type { UserRole } from '@/api';

function FullPageState({
  eyebrow,
  title,
  description,
  icon = 'lock',
  embedded = false,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon?: 'lock' | 'denied';
  embedded?: boolean;
}) {
  const Icon = icon === 'denied' ? ShieldAlert : LockKeyhole;
  const content = (
    <>
      <div className="grid w-full max-w-[920px] gap-5">
        <HeroCard>
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            {eyebrow}
          </div>
          <div className="mt-5 inline-flex rounded-3xl bg-[rgba(182,70,47,0.1)] p-4 text-accent-deep">
            <Icon className="h-7 w-7" />
          </div>
          <h1 className="m-0 mt-5 font-serif text-3xl leading-tight text-ink">{title}</h1>
          <p className="m-0 mt-3 max-w-[62ch] text-base leading-relaxed text-ink-soft">
            {description}
          </p>
        </HeroCard>
      </div>
    </>
  );

  if (embedded) {
    return (
      <div className="grid min-h-[70vh] place-items-center">
        {content}
      </div>
    );
  }

  return (
    <Layout>
      <div className="grid min-h-[70vh] place-items-center">
        {content}
      </div>
    </Layout>
  );
}

function roleLabel(roleId: UserRole | null): string {
  if (roleId === 'employee') {
    return '普通员工';
  }
  if (roleId === 'department_admin') {
    return '部门管理员';
  }
  if (roleId === 'sys_admin') {
    return '系统管理员';
  }
  return '未识别角色';
}

function AccessDeniedPage({ allowedRoles, embedded = false }: { allowedRoles: UserRole[]; embedded?: boolean }) {
  const { profile } = useAuth();

  const content = (
    <>
      <div className="grid w-full max-w-[920px] gap-5">
        <HeroCard>
          <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
            Access Denied
          </div>
          <div className="mt-5 inline-flex rounded-3xl bg-[rgba(182,70,47,0.1)] p-4 text-accent-deep">
            <ShieldAlert className="h-7 w-7" />
          </div>
          <h1 className="m-0 mt-5 font-serif text-3xl leading-tight text-ink">
            当前账号没有这个页面的访问权限
          </h1>
          <p className="m-0 mt-3 max-w-[62ch] text-base leading-relaxed text-ink-soft">
            当前角色是 {roleLabel(profile?.user.role_id || null)}。该入口仅对 {allowedRoles.map(roleLabel).join(' / ')} 开放。
          </p>
        </HeroCard>

        <Card className="flex flex-wrap items-center gap-3">
          <Button type="button" onClick={() => window.location.assign('/portal')}>
            返回门户首页
          </Button>
          <Button type="button" variant="ghost" onClick={() => window.history.back()}>
            返回上一页
          </Button>
        </Card>
      </div>
    </>
  );

  if (embedded) {
    return (
      <div className="grid min-h-[70vh] place-items-center">
        {content}
      </div>
    );
  }

  return (
    <Layout>
      <div className="grid min-h-[70vh] place-items-center">
        {content}
      </div>
    </Layout>
  );
}

export function RequireAuth({ allowedRoles, embedded = false }: { allowedRoles?: UserRole[]; embedded?: boolean }) {
  const { status, isAuthenticated, roleId } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    return (
      <FullPageState
        eyebrow="Session Restore"
        title="正在恢复登录态"
        description="系统正在校验当前浏览器中的会话信息，确认身份后会自动进入对应页面。"
        embedded={embedded}
      />
    );
  }

  if (!isAuthenticated) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?reason=login-required&next=${next}`} replace />;
  }

  if (allowedRoles && (!roleId || !allowedRoles.includes(roleId))) {
    return <AccessDeniedPage allowedRoles={allowedRoles} embedded={embedded} />;
  }

  return <Outlet />;
}
