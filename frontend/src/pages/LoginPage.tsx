import { useMemo, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Input } from '@/components';
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
    <div className="login-enterprise-root">
      <div className="login-enterprise-card">
        {/* Logo */}
        <div className="login-enterprise-logo">
          <img
            src="/welli-login-logo-v2.png"
            alt="WELLI 伟立知识库"
            className="h-auto w-full max-w-[280px]"
          />
        </div>

        {/* Error */}
        {error ? (
          <div className="login-enterprise-error">
            {error}
          </div>
        ) : null}

        {/* Form */}
        <form className="login-enterprise-form" onSubmit={handleSubmit}>
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
          <Button type="submit" loading={submitting} className="login-enterprise-submit">
            登录并进入系统
          </Button>
        </form>

        {/* Footer note */}
        <div className="login-enterprise-note">
          如需开通账号、重置密码或调整权限，请联系数字化部孙瑞杰。
        </div>
      </div>
    </div>
  );
}
