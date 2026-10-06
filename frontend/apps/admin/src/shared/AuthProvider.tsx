import { createContext, useContext, ReactNode } from 'react';
import type { Role, User } from '@ai-cs/shared/types';
import { useAuth as useSharedAuth } from '@ai-cs/shared/hooks';

interface AuthContextType {
  isAuthenticated: boolean;
  role: Role;
  user?: User;
  isLoading: boolean;
  accessToken: string | null;
  error: string | null;
  errorCode: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * 管理后台认证 Provider。
 * 复用共享包的 useAuth（真实调用 Bridge Service POST /api/auth/login），
 * access token 仅保存在内存中，刷新会话由 HttpOnly Cookie 承载。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const auth = useSharedAuth('admin');

  return (
    <AuthContext.Provider value={auth}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
