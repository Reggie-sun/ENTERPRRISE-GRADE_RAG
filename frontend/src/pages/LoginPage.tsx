import { Building2, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, HeroCard, Input, Layout } from '@/components';
import { formatAuthError, normalizeNextPath, useAuth, useAuthReasonText } from '@/auth';

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthenticated, login, clearLogoutReason } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const reason = searchParams.get('reason');
  const nextPath = useMemo(
    () => normalizeNextPath(searchParams.get('next')),
    [searchParams],
  );
  const reasonText = useAuthReasonText(reason);

  if (isAuthenticated) {
    return <Navigate to={nextPath} replace />;
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    clearLogoutReason();
    try {
      await login(username, password);
      navigate(nextPath, { replace: true });
    } catch (err) {
      setError(formatAuthError(err, '登录'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
      <div className="grid min-h-[70vh] place-items-center">
        <div className="grid w-full max-w-[1080px] gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <HeroCard>
            <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
              企业知识服务入口
            </div>
            <h1 className="m-0 mt-5 font-serif text-4xl leading-tight text-ink md:text-5xl">
              欢迎使用伟立机器人知识服务平台
            </h1>
            <p className="m-0 mt-4 max-w-[60ch] text-base leading-relaxed text-ink-soft">
              登录后即可按账号权限查看所属部门资料、发起智能问答，并进入标准流程服务与管理入口。
            </p>

            <div className="mt-6 grid gap-3 text-sm leading-relaxed text-ink-soft">
              <div className="flex items-start gap-3 rounded-3xl bg-[rgba(255,255,255,0.72)] p-4">
                <ShieldCheck className="mt-0.5 h-5 w-5 text-accent-deep" />
                <div>
                  <strong className="block text-ink">安全权限控制</strong>
                  系统会根据账号权限自动匹配可查看的资料范围和可使用的服务入口。
                </div>
              </div>
              <div className="flex items-start gap-3 rounded-3xl bg-[rgba(255,255,255,0.72)] p-4">
                <Building2 className="mt-0.5 h-5 w-5 text-accent-deep" />
                <div>
                  <strong className="block text-ink">按角色展示功能</strong>
                  员工、部门负责人和平台管理员会看到各自需要的入口，界面更清晰、更聚焦。
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-3xl bg-[rgba(255,255,255,0.72)] px-5 py-4 text-sm leading-relaxed text-ink-soft">
              登录成功后会直接进入智能问答页；如果当前账号具备管理权限，页面中还会显示对应的管理入口。
            </div>
          </HeroCard>

          <Card className="border-[rgba(182,70,47,0.14)] bg-[rgba(255,248,240,0.88)] shadow-[0_24px_54px_rgba(77,42,16,0.12)]">
            <div className="inline-flex rounded-3xl bg-[rgba(182,70,47,0.1)] p-4 text-accent-deep">
              <LockKeyhole className="h-6 w-6" />
            </div>
            <h2 className="m-0 mt-5 text-2xl font-semibold text-ink">账号登录</h2>
            <p className="m-0 mt-2 text-sm leading-relaxed text-ink-soft">
              请输入已开通的账号信息。登录成功后，系统会自动回到你刚才准备访问的页面。
            </p>

            {reasonText ? (
              <div className="mt-4 rounded-2xl border border-[rgba(182,70,47,0.12)] bg-[rgba(255,255,255,0.8)] px-4 py-3 text-sm leading-relaxed text-accent-deep">
                {reasonText}
              </div>
            ) : null}

            {error ? (
              <div className="mt-4 rounded-2xl border border-[rgba(182,70,47,0.12)] bg-[rgba(255,255,255,0.8)] px-4 py-3 text-sm leading-relaxed text-accent-deep">
                {error}
              </div>
            ) : null}

            <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
              <Input
                label="用户名"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入用户名"
                autoComplete="username"
              />
              <Input
                label="密码"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="输入密码"
                autoComplete="current-password"
              />
              <Button type="submit" loading={submitting}>
                登录并进入系统
              </Button>
            </form>

            <div className="mt-5 rounded-2xl bg-[rgba(255,255,255,0.74)] p-4 text-sm leading-relaxed text-ink-soft">
              如需开通账号、重置密码或调整权限，请联系平台管理员。
            </div>
          </Card>
        </div>
      </div>
    </Layout>
  );
}
