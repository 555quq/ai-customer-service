import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthProvider';
import type { ReactNode } from 'react';

interface ProtectedRouteProps {
  children: ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, role } = useAuth();

  if (isLoading) {
    return <div aria-label="正在恢复登录会话">正在加载...</div>;
  }

  if (!isAuthenticated || !['agent', 'admin'].includes(role)) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
