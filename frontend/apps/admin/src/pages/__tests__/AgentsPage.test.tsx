import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AgentsPage } from '../AgentsPage';

// 桩掉共享 API 与认证，聚焦页面行为
vi.mock('@ai-cs/shared/api', () => ({
  fetchAgentUsers: vi.fn(),
  updateAgentStatus: vi.fn(),
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

import { fetchAgentUsers, updateAgentStatus } from '@ai-cs/shared/api';

const mockAgents = [
  { id: '1', name: '张三', email: 'zhang@test.com', status: 'online', role: 'administrator' },
  { id: '2', name: '李四', email: 'li@test.com', status: 'offline', role: 'agent' },
];

describe('AgentsPage 客服管理', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchAgentUsers as ReturnType<typeof vi.fn>).mockResolvedValue(mockAgents);
  });

  it('渲染客服列表与在线/离线状态徽章', async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('张三')).toBeInTheDocument();
    expect(screen.getByText('李四')).toBeInTheDocument();
    // 状态徽章：筛选按钮(在线/离线) + 各状态徽章各 1 个
    expect(screen.getAllByText('在线').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('离线').length).toBeGreaterThanOrEqual(1);
  });

  it('加载失败或空数据时显示空态', async () => {
    (fetchAgentUsers as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('暂无客服数据')).toBeInTheDocument();
  });

  it('按姓名/邮箱搜索过滤客服', async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );
    await screen.findByText('张三');

    const input = screen.getByPlaceholderText('搜索客服姓名或邮箱...');
    fireEvent.change(input, { target: { value: '李四' } });

    expect(screen.getByText('李四')).toBeInTheDocument();
    expect(screen.queryByText('张三')).not.toBeInTheDocument();
  });

  it('点击"设为在线"调用 API 并更新徽章', async () => {
    (updateAgentStatus as ReturnType<typeof vi.fn>).mockResolvedValue({});
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );
    await screen.findByText('李四');

    fireEvent.click(screen.getByText('设为在线'));

    await waitFor(() => expect(updateAgentStatus).toHaveBeenCalledWith('李四', 'online'));
    // 状态翻转后两名客服都在线 → 两个"设为离线"按钮
    await waitFor(() => expect(screen.getAllByText('设为离线').length).toBe(2));
  });
});
