import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useAuth } from '../useAuth';
import * as client from '../../api/client';

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, public status: number, public code?: string) {
      super(message);
    }
  },
  login: vi.fn(),
  logout: vi.fn(),
  restoreSession: vi.fn(),
  setAuthRole: vi.fn(),
  setAuthToken: vi.fn(),
  subscribeAuthToken: vi.fn(() => () => undefined),
}));

const mockedClient = client as unknown as {
  login: ReturnType<typeof vi.fn>;
  logout: ReturnType<typeof vi.fn>;
  restoreSession: ReturnType<typeof vi.fn>;
  setAuthRole: ReturnType<typeof vi.fn>;
  setAuthToken: ReturnType<typeof vi.fn>;
  subscribeAuthToken: ReturnType<typeof vi.fn>;
};

describe('useAuth hook', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mockedClient.restoreSession.mockRejectedValue(new Error('no session'));
    mockedClient.subscribeAuthToken.mockReturnValue(() => undefined);
  });

  it('没有刷新会话时恢复为未认证', async () => {
    const { result } = renderHook(() => useAuth('agent'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.role).toBe('guest');
  });

  it('登录成功后更新为已认证', async () => {
    mockedClient.login.mockResolvedValue({
      token: 't1',
      user: { id: '1', username: 'agent', role: 'agent' },
      expires_in: 900,
    });

    const { result } = renderHook(() => useAuth('agent'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    let ok: boolean = false;
    await act(async () => {
      ok = await result.current.login('agent', 'agent123');
    });

    expect(ok).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.role).toBe('agent');
    expect(result.current.accessToken).toBe('t1');
    expect(localStorage.getItem('auth')).toBeNull();
    expect(mockedClient.login).toHaveBeenCalledWith('agent', 'agent123', 'agent');
  });

  it('登录失败返回 false 并设置错误信息', async () => {
    mockedClient.login.mockRejectedValue(new Error('密码错误'));

    const { result } = renderHook(() => useAuth('agent'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    let ok: boolean = true;
    await act(async () => {
      ok = await result.current.login('bad', 'bad');
    });

    expect(ok).toBe(false);
    expect(result.current.error).toBe('密码错误');
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('通过 HttpOnly 刷新会话恢复登录', async () => {
    mockedClient.restoreSession.mockResolvedValue({
      token: 't2',
      user: { id: '1', username: 'admin', role: 'admin' },
      expires_in: 900,
    });

    const { result } = renderHook(() => useAuth('admin'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.role).toBe('admin');
    expect(result.current.accessToken).toBe('t2');
    expect(mockedClient.restoreSession).toHaveBeenCalledWith('admin');
  });

  it('登出后清除内存认证状态', async () => {
    mockedClient.logout.mockResolvedValue(undefined);
    mockedClient.restoreSession.mockResolvedValue({
      token: 't3',
      user: { id: '1', username: 'agent', role: 'agent' },
      expires_in: 900,
    });

    const { result } = renderHook(() => useAuth('agent'));
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.role).toBe('guest');
    expect(result.current.accessToken).toBeNull();
    expect(mockedClient.logout).toHaveBeenCalledWith('agent');
  });

  it('拒绝恢复其他角色的会话', async () => {
    mockedClient.restoreSession.mockResolvedValue({
      token: 'admin-token',
      user: { id: '1', username: 'admin', role: 'admin' },
      expires_in: 900,
    });

    const { result } = renderHook(() => useAuth('agent'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.role).toBe('guest');
    expect(mockedClient.setAuthToken).toHaveBeenCalledWith(null);
  });
});
