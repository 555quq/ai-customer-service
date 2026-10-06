import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ConversationPage } from '../ConversationPage';

// —— 依赖桩 ——

// 1. useWebSocket 会真实 new WebSocket()，jsdom 下会挂起；改为捕获 onMessage 的无操作桩
const wsCaptures: { onMessage?: (data: unknown) => void } = {};
vi.mock('@ai-cs/shared/hooks', () => ({
  useWebSocket: (opts: { onMessage?: (data: unknown) => void }) => {
    wsCaptures.onMessage = opts?.onMessage;
    return { isConnected: false, send: vi.fn(), disconnect: vi.fn(), connect: vi.fn() };
  },
}));

// 2. 共享 API
vi.mock('@ai-cs/shared/api', () => ({
  getBridgeWebSocketUrl: vi.fn(() => 'ws://localhost:8000/ws/agent'),
  fetchAgentConversation: vi.fn(),
  fetchAgentUsers: vi.fn(),
  sendAgentReply: vi.fn(),
  assignAgentConversation: vi.fn(),
  transferAgentConversation: vi.fn(),
}));

// 3. 认证
vi.mock('../../shared/AuthProvider', () => ({
  useAuth: () => ({ isAuthenticated: true, role: 'agent', user: { username: 'agent' }, login: vi.fn(), logout: vi.fn() }),
}));

import {
  fetchAgentConversation,
  fetchAgentUsers,
  sendAgentReply,
  assignAgentConversation,
  transferAgentConversation,
} from '@ai-cs/shared/api';

const conversation = {
  id: '18',
  status: 'open',
  priority: 'medium',
  assigneeId: '1',
  assigneeName: 'Admin',
  labels: ['needs_human'],
  createdAt: '2026-08-10T10:00:00Z',
  lastMessageAt: null,
  contact: { id: '27', name: '王小明', channel: 'web', email: null, phone: null },
};

const messages = [
  { id: 'm1', conversationId: '18', senderType: 'user', contentType: 'text', content: '你好', status: 'sent', createdAt: '2026-08-10T10:00:00Z' },
  { id: 'm2', conversationId: '18', senderType: 'ai', contentType: 'text', content: '您好！有什么可以帮您？', status: 'sent', createdAt: '2026-08-10T10:00:01Z' },
];

const agents = [
  { id: '1', name: 'Admin', email: 'a@x.com', status: 'online', role: 'agent' },
  { id: '2', name: '客服B', email: 'b@x.com', status: 'online', role: 'agent' },
];

function renderPage(id = '18') {
  return render(
    <MemoryRouter initialEntries={[`/conversations/${id}`]}>
      <Routes>
        <Route path="/conversations/:id" element={<ConversationPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ConversationPage 客服会话详情', () => {
  beforeAll(() => {
    // jsdom 未实现 Element.scrollIntoView，页面 effect 会调用，需桩掉
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    (fetchAgentConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ conversation, messages });
    (fetchAgentUsers as ReturnType<typeof vi.fn>).mockResolvedValue(agents);
  });

  it('渲染会话详情、消息与分配信息', async () => {
    renderPage();

    // 联系人（侧栏 + ChatHeader 各一处）
    expect((await screen.findAllByText('王小明')).length).toBeGreaterThanOrEqual(1);
    // 消息
    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getByText('您好！有什么可以帮您？')).toBeInTheDocument();
    // 状态徽章、标签、当前客服
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('needs_human')).toBeInTheDocument();
    expect(screen.getByText('当前客服: Admin')).toBeInTheDocument();
  });

  it('发送回复调用 sendAgentReply 并追加消息', async () => {
    (sendAgentReply as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'm3', conversationId: '18', senderType: 'agent', contentType: 'text',
      content: '请稍等', status: 'sent', createdAt: new Date().toISOString(),
    });
    renderPage();
    await screen.findAllByText('王小明');

    const ta = screen.getByPlaceholderText('输入回复消息...');
    fireEvent.change(ta, { target: { value: '请稍等' } });
    fireEvent.keyDown(ta, { key: 'Enter' });

    await waitFor(() => expect(sendAgentReply).toHaveBeenCalledWith('18', '请稍等'));
    expect(await screen.findByText('请稍等')).toBeInTheDocument();
  });

  it('发送失败时追加失败提示消息', async () => {
    (sendAgentReply as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('网络错误'));
    renderPage();
    await screen.findAllByText('王小明');

    const ta = screen.getByPlaceholderText('输入回复消息...');
    fireEvent.change(ta, { target: { value: '你好' } });
    fireEvent.keyDown(ta, { key: 'Enter' });

    expect(await screen.findByText('回复发送失败，请重试')).toBeInTheDocument();
  });

  it('分配客服调用 assignAgentConversation', async () => {
    (assignAgentConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ ...conversation, assigneeId: '2', assigneeName: '客服B' });
    renderPage();
    await screen.findAllByText('王小明');

    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: '2' } });
    fireEvent.click(screen.getByText('分配'));

    await waitFor(() => expect(assignAgentConversation).toHaveBeenCalledWith('18', 2));
  });

  it('转接会话调用 transferAgentConversation', async () => {
    (transferAgentConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ ...conversation, assigneeId: '2', assigneeName: '客服B' });
    renderPage();
    await screen.findAllByText('王小明');

    fireEvent.click(screen.getByText('转接'));
    // 弹窗出现两个 select：左侧分配 + 弹窗转接
    const selects = screen.getAllByRole('combobox');
    fireEvent.change(selects[1], { target: { value: '2' } });
    fireEvent.change(screen.getByPlaceholderText('例如：用户要求优先处理'), { target: { value: '优先处理' } });
    fireEvent.click(screen.getByText('确认转接'));

    await waitFor(() => expect(transferAgentConversation).toHaveBeenCalledWith('18', 2, '优先处理'));
  });

  it('WebSocket 消息触发会话刷新', async () => {
    renderPage();
    await screen.findAllByText('王小明');

    const callsBefore = (fetchAgentConversation as ReturnType<typeof vi.fn>).mock.calls.length;
    wsCaptures.onMessage?.(JSON.stringify({ type: 'conversation_message', conversation_id: '18', sender: 'visitor', content: '新消息' }));

    await waitFor(() =>
      expect((fetchAgentConversation as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore)
    );
  });
});
