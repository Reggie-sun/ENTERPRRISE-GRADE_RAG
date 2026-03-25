import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ApiError,
  formatApiError,
  getCurrentUserProfile,
  login as loginRequest,
  logout as logoutRequest,
  onApiUnauthorized,
  setApiAccessToken,
  type AuthProfileResponse,
  type LoginResponse,
  type UserRole,
} from '@/api';
import {
  clearStoredAuthSession,
  loadStoredAuthSession,
  persistAuthSession,
  type StoredAuthSession,
} from '@/auth/authStorage';

type AuthStatus = 'loading' | 'unauthenticated' | 'authenticated';
type LogoutReason = 'signed-out' | 'session-expired' | 'login-required' | null;

interface AuthContextValue {
  status: AuthStatus;
  profile: AuthProfileResponse | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  roleId: UserRole | null;
  canAccessWorkspace: boolean;
  canAccessAdmin: boolean;
  logoutReason: LogoutReason;
  login: (username: string, password: string) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  clearLogoutReason: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function buildStoredSession(payload: LoginResponse): StoredAuthSession {
  return {
    accessToken: payload.access_token,
    expiresAt: new Date(Date.now() + payload.expires_in_seconds * 1000).toISOString(),
    profile: {
      user: payload.user,
      role: payload.role,
      department: payload.department,
      accessible_department_ids: payload.accessible_department_ids,
    },
  };
}

function normalizeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith('/')) {
    return '/portal';
  }
  if (value.startsWith('/login')) {
    return '/portal';
  }
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [profile, setProfile] = useState<AuthProfileResponse | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [logoutReason, setLogoutReason] = useState<LogoutReason>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const restore = async () => {
      const stored = loadStoredAuthSession();
      if (!stored?.accessToken) {
        setApiAccessToken(null);
        setStatus('unauthenticated');
        setProfile(null);
        setAccessToken(null);
        return;
      }

      setApiAccessToken(stored.accessToken);
      setAccessToken(stored.accessToken);
      setProfile(stored.profile);

      try {
        const refreshedProfile = await getCurrentUserProfile();
        persistAuthSession({
          accessToken: stored.accessToken,
          expiresAt: stored.expiresAt,
          profile: refreshedProfile,
        });
        setProfile(refreshedProfile);
        setStatus('authenticated');
      } catch (error) {
        clearStoredAuthSession();
        setApiAccessToken(null);
        setAccessToken(null);
        setProfile(null);
        setStatus('unauthenticated');
        setLogoutReason(error instanceof ApiError && error.status === 401 ? 'session-expired' : null);
      }
    };

    void restore();
  }, []);

  useEffect(() => onApiUnauthorized(() => {
    clearStoredAuthSession();
    setApiAccessToken(null);
    setAccessToken(null);
    setProfile(null);
    setStatus('unauthenticated');
    setLogoutReason('session-expired');
    if (location.pathname !== '/login') {
      const next = normalizeNextPath(`${location.pathname}${location.search}`);
      navigate(`/login?reason=session-expired&next=${encodeURIComponent(next)}`, { replace: true });
    }
  }), [location.pathname, location.search, navigate]);

  const login = async (username: string, password: string) => {
    const payload = await loginRequest({ username, password });
    const storedSession = buildStoredSession(payload);
    persistAuthSession(storedSession);
    setApiAccessToken(storedSession.accessToken);
    setAccessToken(storedSession.accessToken);
    setProfile(storedSession.profile);
    setStatus('authenticated');
    setLogoutReason(null);
    return payload;
  };

  const logout = async () => {
    try {
      if (accessToken) {
        await logoutRequest();
      }
    } catch {
      // 后端会话已失效时，前端仍然直接清理本地状态。
    } finally {
      clearStoredAuthSession();
      setApiAccessToken(null);
      setAccessToken(null);
      setProfile(null);
      setStatus('unauthenticated');
      setLogoutReason('signed-out');
      if (location.pathname !== '/login') {
        const next = normalizeNextPath('/portal');
        navigate(`/login?reason=signed-out&next=${encodeURIComponent(next)}`, { replace: true });
      }
    }
  };

  const value = useMemo<AuthContextValue>(() => {
    const roleId = profile?.user.role_id || null;
    return {
      status,
      profile,
      accessToken,
      isAuthenticated: status === 'authenticated' && Boolean(profile) && Boolean(accessToken),
      roleId,
      canAccessWorkspace: roleId === 'department_admin' || roleId === 'sys_admin',
      canAccessAdmin: roleId === 'sys_admin',
      logoutReason,
      login,
      logout,
      clearLogoutReason: () => setLogoutReason(null),
    };
  }, [accessToken, login, logout, logoutReason, profile, status]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider.');
  }
  return context;
}

export function useAuthReasonText(reason: string | null): string {
  switch (reason) {
    case 'session-expired':
      return '当前会话已过期，请重新登录。';
    case 'signed-out':
      return '你已退出登录。';
    case 'login-required':
      return '请先登录后继续访问对应页面。';
    default:
      return '';
  }
}

export function formatAuthError(error: unknown, context: string): string {
  return formatApiError(error, context);
}

export { normalizeNextPath };
