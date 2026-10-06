import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ProtectedRoute } from '../ProtectedRoute';
import { AuthProvider } from '../AuthProvider';

const auth = vi.hoisted(() => ({
  current: {
    isAuthenticated: false,
    role: 'guest',
    isLoading: false,
    accessToken: null,
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock('@ai-cs/shared/hooks', () => ({
  useAuth: () => auth.current,
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>登录页</div>} />
          <Route
            path="/workspace"
            element={
              <ProtectedRoute>
                <div>受保护的工作台</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe('ProtectedRoute 路由权限', () => {
  beforeEach(() => {
    auth.current = {
      isAuthenticated: false,
      role: 'guest',
      isLoading: false,
      accessToken: null,
      login: vi.fn(),
      logout: vi.fn(),
    };
  });

  it('未认证时重定向到登录页', () => {
    renderAt('/workspace');
    expect(screen.getByText('登录页')).toBeInTheDocument();
    expect(screen.queryByText('受保护的工作台')).not.toBeInTheDocument();
  });

  it('已认证时渲染受保护内容', () => {
    auth.current = {
      ...auth.current,
      isAuthenticated: true,
      role: 'agent',
      user: { id: '1', username: 'agent', role: 'agent' },
    } as typeof auth.current;
    renderAt('/workspace');
    expect(screen.getByText('受保护的工作台')).toBeInTheDocument();
  });
});
