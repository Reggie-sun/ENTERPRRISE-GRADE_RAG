import type { AuthProfileResponse } from '@/api';

export interface StoredAuthSession {
  accessToken: string;
  expiresAt: string;
  profile: AuthProfileResponse;
}

const AUTH_SESSION_KEY = 'enterprise_rag_auth_session_v1';

export function loadStoredAuthSession(): StoredAuthSession | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<StoredAuthSession> | null;
    if (!parsed?.accessToken || !parsed?.expiresAt || !parsed?.profile) {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      expiresAt: parsed.expiresAt,
      profile: parsed.profile,
    };
  } catch {
    return null;
  }
}

export function persistAuthSession(session: StoredAuthSession) {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(session));
}

export function clearStoredAuthSession() {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem(AUTH_SESSION_KEY);
}
