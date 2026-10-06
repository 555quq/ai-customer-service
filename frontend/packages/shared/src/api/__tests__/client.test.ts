import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  setAuthToken,
  getAuthToken,
  sendBridgeMessage,
  fetchHandoffMessages,
  fetchAgentUsers,
  fetchAgentConversations,
  getBridgeWebSocketUrl,
  createWidgetSession,
  ApiError,
  logout,
  restoreSession,
  setAuthRole,
} from '../client';

describe('api/client', () => {
  beforeEach(() => {
    setAuthToken(null);
    setAuthRole('agent');
    // 用类型断言模拟 fetch
    global.fetch = vi.fn() as unknown as typeof fetch;
  });

  describe('setAuthToken / getAuthToken', () => {
    it('设置并读取 token', () => {
      setAuthToken('token-123');
      expect(getAuthToken()).toBe('token-123');
      setAuthToken(null);
      expect(getAuthToken()).toBeNull();
    });
  });

  it('generates a websocket URL from the configured Bridge base', () => {
    expect(getBridgeWebSocketUrl('/ws/agent')).toBe('ws://localhost:8000/ws/agent');
  });

  it('刷新和退出显式携带固定角色', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          token: 'agent-token',
          user: { id: '1', username: 'agent', role: 'agent' },
          expires_in: 900,
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ok: true }) });
    global.fetch = fetchMock as unknown as typeof fetch;

    await restoreSession('agent');
    await logout('admin');

    expect(fetchMock.mock.calls[0][0]).toContain('/api/auth/refresh?role=agent');
    expect(fetchMock.mock.calls[1][0]).toContain('/api/auth/logout?role=admin');
  });

  describe('sendBridgeMessage', () => {
    it('发送消息并返回 AI 回复', async () => {
      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            reply: '你好呀！',
            confidence: 0.92,
            intent: 'greeting',
            conversation_id: 'c1',
          }),
      });

      const result = await sendBridgeMessage({
        message: '你好',
        conversationId: 'c1',
        userId: 'u1',
      });

      expect(result.reply).toBe('你好呀！');
      expect(result.confidence).toBe(0.92);
      expect(result.intent).toBe('greeting');
    });

    it('请求失败时抛出异常', async () => {
      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ detail: 'server error' }),
      });

      await expect(
        sendBridgeMessage({ message: 'hi', conversationId: 'c1', userId: 'u1' })
      ).rejects.toThrow();
    });

    it('公共聊天不会携带后台 access token', async () => {
      setAuthToken('secret');
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ reply: 'ok', confidence: 1, intent: 'general' }),
      });
      global.fetch = fetchMock as unknown as typeof fetch;

      await sendBridgeMessage({ message: 'hi', conversationId: 'c1', userId: 'u1' });

      const options = fetchMock.mock.calls[0][1] as RequestInit;
      const headers = options.headers as Headers;
      expect(headers.get('Authorization')).toBeNull();
      expect(options.credentials).toBe('include');
    });

    it('转人工请求携带会话能力令牌', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ handoff: true, messages: [] }),
      });
      global.fetch = fetchMock as unknown as typeof fetch;

      await fetchHandoffMessages('visitor-1', 'widget-capability');

      const headers = fetchMock.mock.calls[0][1].headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer widget-capability');
    });
  });

  it('保留 Widget Session 结构化错误码和 HTTP 状态', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({
        detail: { code: 'HANDOFF_SESSION_NOT_RESTORABLE' },
      }),
    });

    const request = createWidgetSession('http://bridge', 'site', 'conversation-1', 'visitor-1');
    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'HANDOFF_SESSION_NOT_RESTORABLE',
    } satisfies Partial<ApiError>);
  });

  describe('fetchAgentUsers', () => {
    it('获取客服列表', async () => {
      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [{ id: '1', name: 'Admin' }] }),
      });

      const agents = await fetchAgentUsers();
      expect(agents).toHaveLength(1);
      expect(agents[0].name).toBe('Admin');
    });
  });

  describe('fetchAgentConversations', () => {
    it('获取会话列表', async () => {
      (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ conversations: [{ id: 'conv-1', status: 'open' }] }),
      });

      const result = await fetchAgentConversations('open');
      expect(result.conversations).toHaveLength(1);
      expect(result.conversations[0].id).toBe('conv-1');
    });

    it('401 时只刷新一次并重放请求', async () => {
      setAuthToken('expired');
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: () => Promise.resolve({ detail: 'expired' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            token: 'renewed',
            user: { id: '1', username: 'agent', role: 'agent' },
            expires_in: 900,
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ conversations: [] }),
        });
      global.fetch = fetchMock as unknown as typeof fetch;

      await fetchAgentConversations('open');

      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(fetchMock.mock.calls[1][0]).toContain('/api/auth/refresh');
      const retriedHeaders = fetchMock.mock.calls[2][1].headers as Headers;
      expect(retriedHeaders.get('Authorization')).toBe('Bearer renewed');
    });
  });
});
