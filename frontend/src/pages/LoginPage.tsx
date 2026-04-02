import { useMemo, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, Input, Layout } from '@/components';
import { formatAuthError, normalizeNextPath, useAuth } from '@/auth';

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthenticated, login, clearLogoutReason } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const nextPath = useMemo(
    () => normalizeNextPath(searchParams.get('next')),
    [searchParams],
  );

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
        <Card className="w-full max-w-[560px] border-[rgba(182,70,47,0.14)] bg-[rgba(255,248,240,0.88)] shadow-[0_24px_54px_rgba(77,42,16,0.12)]">
          <div className="mb-2 flex justify-center">
            <img
              src="/welli-login-logo-v2.png"
              alt="WELLI 伟立知识库"
              className="h-auto w-full max-w-[360px] rounded-2xl"
            />
          </div>

          {error ? (
            <div className="mt-4 rounded-2xl border border-[rgba(182,70,47,0.12)] bg-[rgba(255,255,255,0.8)] px-4 py-3 text-sm leading-relaxed text-accent-deep">
              {error}
            </div>
          ) : null}

          <form className="mt-3 grid gap-4" onSubmit={handleSubmit}>
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
            如需开通账号、重置密码或调整权限，请联系数字化部孙瑞杰。
          </div>
        </Card>
      </div>
    </Layout>
  );
}
