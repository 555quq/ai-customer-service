import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChatBubble } from '../ChatBubble';
import type { Message } from '../../../types';

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: 'm1',
    conversationId: 'c1',
    senderType: 'user',
    senderName: '访客',
    contentType: 'text',
    content: '你好',
    status: 'sent',
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe('ChatBubble 组件', () => {
  it('渲染消息内容', () => {
    render(<ChatBubble message={makeMessage({ content: '请问营业时间？' })} />);
    expect(screen.getByText('请问营业时间？')).toBeInTheDocument();
  });

  it('用户消息右对齐', () => {
    const { container } = render(<ChatBubble message={makeMessage({ senderType: 'user' })} />);
    expect(container.querySelector('.justify-end')).toBeInTheDocument();
  });

  it('AI 消息左对齐', () => {
    const { container } = render(<ChatBubble message={makeMessage({ senderType: 'ai', senderName: 'AI客服' })} />);
    expect(container.querySelector('.justify-start')).toBeInTheDocument();
  });

  it('AI 消息显示头像首字符', () => {
    render(<ChatBubble message={makeMessage({ senderType: 'ai', senderName: 'AI客服' })} />);
    expect(screen.getByText('A')).toBeInTheDocument();
  });

  it('showAvatar=false 时不渲染头像', () => {
    const { container } = render(
      <ChatBubble message={makeMessage({ senderType: 'ai', senderName: 'AI客服' })} showAvatar={false} />
    );
    expect(container.querySelector('.rounded-full')).not.toBeInTheDocument();
  });
});
