import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ContactsPage } from '../ContactsPage';

// 桩掉共享 API 与认证
vi.mock('@ai-cs/shared/api', () => ({
  fetchContacts: vi.fn(),
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

import { fetchContacts } from '@ai-cs/shared/api';

const mockContacts = [
  { id: '9', name: '王小明', email: 'wang@test.com', phone: '13800000000', channel: 'web', conversationCount: 3, lastActive: '2026-08-10T10:00:00Z' },
  { id: '10', name: 'Lisa', email: 'lisa@test.com', phone: null, channel: 'wechat', conversationCount: 1, lastActive: null },
];

describe('ContactsPage 客户管理', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchContacts as ReturnType<typeof vi.fn>).mockResolvedValue({ contacts: mockContacts });
  });

  it('渲染客户表格与渠道标签', async () => {
    render(
      <MemoryRouter>
        <ContactsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('王小明')).toBeInTheDocument();
    expect(screen.getByText('Lisa')).toBeInTheDocument();
    // 渠道映射: web→网页, wechat→微信
    expect(screen.getByText('网页')).toBeInTheDocument();
    expect(screen.getByText('微信')).toBeInTheDocument();
    // 会话数
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('空数据时显示空态', async () => {
    (fetchContacts as ReturnType<typeof vi.fn>).mockResolvedValue({ contacts: [] });
    render(
      <MemoryRouter>
        <ContactsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('暂无客户数据')).toBeInTheDocument();
  });

  it('按姓名/邮箱/手机号搜索过滤', async () => {
    render(
      <MemoryRouter>
        <ContactsPage />
      </MemoryRouter>
    );
    await screen.findByText('王小明');

    const input = screen.getByPlaceholderText('搜索客户姓名、邮箱或手机号...');
    fireEvent.change(input, { target: { value: '13800000000' } });

    expect(screen.getByText('王小明')).toBeInTheDocument();
    expect(screen.queryByText('Lisa')).not.toBeInTheDocument();
  });
});
