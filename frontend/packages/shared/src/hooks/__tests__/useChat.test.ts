import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockedClient = vi.hoisted(() => {
  const getOrCreateVisitorId = vi.fn((scope: string) => {
    const key = `ai-cs:${scope}:visitor-id`;
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    const created = `${scope}-new-id`;
    localStorage.setItem(key, created);
    return created;
  });
  return {
    createWidgetSession: vi.fn(),
    sendBridgeMessage: vi.fn(),
    getOrCreateVisitorId,
    resetVisitorId: vi.fn((scope: string) => {
      localStorage.removeItem(`ai-cs:${scope}:visitor-id`);
      return getOrCreateVisitorId(scope);
    }),
  };
});

vi.mock('../../api/client', () => mockedClient);

import { useChat } from '../useChat';


describe('useChat widget session recovery', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ai-cs:chat:visitor-id', 'visitor-123');
    localStorage.setItem('ai-cs:conversation:visitor-id', 'conversation-123');
    vi.clearAllMocks();
    mockedClient.getOrCreateVisitorId.mockImplementation((scope: string) => {
      const key = `ai-cs:${scope}:visitor-id`;
      const existing = localStorage.getItem(key);
      if (existing) return existing;
      const created = `${scope}-new-id`;
      localStorage.setItem(key, created);
      return created;
    });
    mockedClient.resetVisitorId.mockImplementation((scope: string) => {
      localStorage.removeItem(`ai-cs:${scope}:visitor-id`);
      return mockedClient.getOrCreateVisitorId(scope);
    });
  });

  it('restores a handed-off session on mount without persisting the token', async () => {
    mockedClient.createWidgetSession.mockResolvedValue({
      capability_token: 'handoff-capability',
      expires_at: 123,
      handoff: true,
      chatwoot_conversation_id: '42',
    });

    const { result } = renderHook(() => useChat({ apiUrl: 'http://bridge', siteToken: 'site' }));

    await waitFor(() => expect(result.current.handoffActive).toBe(true));
    expect(result.current.chatwootConversationId).toBe('42');
    expect(result.current.capabilityToken).toBe('handoff-capability');
    expect(mockedClient.createWidgetSession).toHaveBeenCalledWith(
      'http://bridge',
      'site',
      'conversation-123',
      'visitor-123',
    );
    expect(Object.values(localStorage)).not.toContain('handoff-capability');
  });

  it('uses one mount session when sending the first normal message', async () => {
    mockedClient.createWidgetSession.mockResolvedValue({
      capability_token: 'normal-capability',
      expires_at: 123,
      handoff: false,
      chatwoot_conversation_id: null,
    });
    mockedClient.sendBridgeMessage.mockResolvedValue({
      reply: '您好',
      intent: 'question',
      confidence: 0.9,
      conversation_id: 'conversation-123',
      response_time_ms: 5,
    });
    const { result } = renderHook(() => useChat({ apiUrl: 'http://bridge', siteToken: 'site' }));
    await waitFor(() => expect(result.current.capabilityToken).toBe('normal-capability'));

    await act(async () => {
      await result.current.sendMessage('你好');
    });

    expect(mockedClient.createWidgetSession).toHaveBeenCalledTimes(1);
    expect(mockedClient.sendBridgeMessage).toHaveBeenCalledWith(
      expect.objectContaining({ capabilityToken: 'normal-capability' }),
    );
    expect(result.current.handoffActive).toBe(false);
  });

  it('exposes an explicit error for a legacy handoff that cannot be restored', async () => {
    mockedClient.createWidgetSession.mockRejectedValue(
      Object.assign(new Error('legacy handoff'), {
        code: 'HANDOFF_SESSION_NOT_RESTORABLE',
        status: 409,
      }),
    );

    const { result } = renderHook(() => useChat({ apiUrl: 'http://bridge', siteToken: 'site' }));

    await waitFor(() => {
      expect(result.current.sessionErrorCode).toBe('HANDOFF_SESSION_NOT_RESTORABLE');
    });
    expect(result.current.capabilityToken).toBeNull();
  });

  it('starts a new session only after explicit confirmation', async () => {
    mockedClient.createWidgetSession
      .mockRejectedValueOnce(
        Object.assign(new Error('legacy handoff'), {
          code: 'HANDOFF_SESSION_NOT_RESTORABLE',
          status: 409,
        }),
      )
      .mockResolvedValueOnce({
        capability_token: 'new-capability',
        expires_at: 456,
        handoff: false,
        chatwoot_conversation_id: null,
      });

    const { result } = renderHook(() => useChat({ apiUrl: 'http://bridge', siteToken: 'site' }));
    await waitFor(() => expect(result.current.sessionErrorCode).not.toBeNull());

    await act(async () => {
      await result.current.startNewConversation();
    });

    await waitFor(() => expect(result.current.capabilityToken).toBe('new-capability'));
    expect(result.current.sessionErrorCode).toBeNull();
    expect(mockedClient.createWidgetSession).toHaveBeenLastCalledWith(
      'http://bridge',
      'site',
      'conversation-new-id',
      'visitor-123',
    );
  });
});
