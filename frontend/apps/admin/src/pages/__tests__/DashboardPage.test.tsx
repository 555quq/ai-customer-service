import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DashboardPage } from '../DashboardPage';

// 桩掉共享 API 与认证
vi.mock('@ai-cs/shared/api', () => ({
  fetchAnalyticsSummary: vi.fn(),
  fetchAgentConversations: vi.fn(),
  fetchAgentUsers: vi.fn(),
  fetchConversationTrend: vi.fn(),
}));
vi.mock('../../shared/AuthProvider', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    role: 'admin',
    user: { username: 'admin' },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import {
  fetchAnalyticsSummary,
  fetchAgentConversations,
  fetchAgentUsers,
  fetchConversationTrend,
} from '@ai-cs/shared/api';

const summary = {
  total_conversations: 20,
  open_count: 3,
  ai_resolution_rate: 0.5,
  ai_resolved: 8,
  avg_messages_per_conversation: 2.5,
};
const convRes = {
  conversations: [
    { id: '1', contact: { name: '王小明' }, status: 'open', assigneeName: 'Admin', lastMessage: '你好', lastMessageAt: null },
    { id: '2', contact: { name: '李四' }, status: 'resolved', assigneeName: 'Admin', lastMessage: '谢谢', lastMessageAt: null },
  ],
};
const agents = [{ id: '1', name: 'Admin', email: 'a@x.com' }];
const trendRes = { points: [{ date: '2026-08-09', total: 5 }, { date: '2026-08-10', total: 8 }] };

describe('DashboardPage 仪表盘', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchAnalyticsSummary as ReturnType<typeof vi.fn>).mockResolvedValue(summary);
    (fetchAgentConversations as ReturnType<typeof vi.fn>).mockResolvedValue(convRes);
    (fetchAgentUsers as ReturnType<typeof vi.fn>).mockResolvedValue(agents);
    (fetchConversationTrend as ReturnType<typeof vi.fn>).mockResolvedValue(trendRes);
  });

  it('渲染统计卡片', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('系统运行正常')).toBeInTheDocument();
    expect(screen.getByText('20')).toBeInTheDocument(); // 总会话数
    // 解决率 50%（统计卡 + 客服绩效聚合各一处）
    expect(screen.getAllByText('50%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('8').length).toBeGreaterThanOrEqual(1); // AI 解决数
  });

  it('渲染最近会话与状态徽章', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('王小明')).toBeInTheDocument();
    expect(screen.getByText('李四')).toBeInTheDocument();
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('已解决')).toBeInTheDocument();
  });

  it('按 assigneeName 聚合客服绩效', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    // Admin 有 2 个会话、1 个已解决
    await screen.findByText('王小明');
    expect(screen.getByText('会话: 2')).toBeInTheDocument();
    expect(screen.getByText('1 已解决')).toBeInTheDocument();
  });

  it('切换趋势周期调用 fetchConversationTrend(30)', async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );
    await screen.findByText('系统运行正常');

    fireEvent.click(screen.getByText('本月'));
    await waitFor(() => expect(fetchConversationTrend).toHaveBeenCalledWith(30));
  });
});
