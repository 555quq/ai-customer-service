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

export function AuthProvider({ children }: { children: ReactNode }) {
  const auth = useSharedAuth('agent');

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
