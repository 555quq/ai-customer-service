import { useState, useCallback, useEffect } from 'react';
import type { AuthState, User } from '../types';
import {
  ApiError,
  login as apiLogin,
  logout as apiLogout,
  restoreSession,
  setAuthRole,
  setAuthToken,
  subscribeAuthToken,
} from '../api/client';
import type { AuthenticatedRole } from '../api/client';

export function useAuth(expectedRole: AuthenticatedRole) {
  setAuthRole(expectedRole);
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    role: 'guest',
  });
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    setIsLoading(true);
    setError(null);
    setErrorCode(null);

    try {
      const { token, user } = await apiLogin(username, password, expectedRole);
      if (user.role !== expectedRole) {
        setAuthToken(null);
        setError('登录角色与当前应用不匹配');
        setErrorCode('AUTH_ROLE_MISMATCH');
        return false;
      }

      const newState: AuthState = {
        isAuthenticated: true,
        role: user.role,
        user: user as User,
      };

      setAccessToken(token);
      setAuthState(newState);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
      setErrorCode(err instanceof ApiError ? err.code ?? null : null);
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [expectedRole]);

  const logout = useCallback(async () => {
    try {
      await apiLogout(expectedRole);
    } catch {
      // 忽略logout错误
    } finally {
      setAccessToken(null);
      const newState: AuthState = { isAuthenticated: false, role: 'guest' };
      setAuthState(newState);
    }
  }, [expectedRole]);

  useEffect(() => {
    // 清除旧版本遗留的可读长期凭据；刷新令牌仅保存在 HttpOnly Cookie。
    localStorage.removeItem('auth');
    localStorage.removeItem('agent-auth');

    let active = true;
    const unsubscribe = subscribeAuthToken((token) => {
      if (active) setAccessToken(token);
    });

    restoreSession(expectedRole)
      .then(({ token, user }) => {
        if (!active) return;
        if (user.role !== expectedRole) {
          setAuthToken(null);
          setAuthState({ isAuthenticated: false, role: 'guest' });
          return;
        }
        setAccessToken(token);
        setAuthState({
          isAuthenticated: true,
          role: user.role,
          user: user as User,
        });
      })
      .catch(() => {
        if (!active) return;
        setAccessToken(null);
        setAuthState({ isAuthenticated: false, role: 'guest' });
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [expectedRole]);

  return {
    ...authState,
    isLoading,
    accessToken,
    error,
    errorCode,
    login,
    logout,
  };
}
