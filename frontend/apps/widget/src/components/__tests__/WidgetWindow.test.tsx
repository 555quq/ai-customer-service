import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  useChat: vi.fn(),
  fetchHandoffMessages: vi.fn(),
  startNewConversation: vi.fn(),
}));

vi.mock('@ai-cs/shared/hooks', () => ({ useChat: mocks.useChat }));
vi.mock('@ai-cs/shared/api', () => ({ fetchHandoffMessages: mocks.fetchHandoffMessages }));

import { WidgetWindow } from '../WidgetWindow';


describe('WidgetWindow handoff recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useChat.mockReturnValue({
      messages: [],
      isTyping: false,
      sendMessage: vi.fn(),
      addMessage: vi.fn(),
      conversationId: 'conversation-1',
      capabilityToken: null,
      handoffActive: false,
      chatwootConversationId: null,
      sessionErrorCode: 'HANDOFF_SESSION_NOT_RESTORABLE',
      startNewConversation: mocks.startNewConversation,
    });
  });

  it('requires explicit confirmation before replacing a legacy handoff', () => {
    render(
      <WidgetWindow
        config={{ apiUrl: 'http://bridge', siteToken: 'site', brandName: '客服' }}
        suggestions={[]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('原人工会话无法安全恢复');
    expect(screen.getByPlaceholderText('输入消息，Enter 发送...')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '开始新会话' }));
    expect(mocks.startNewConversation).toHaveBeenCalledTimes(1);
  });
});
