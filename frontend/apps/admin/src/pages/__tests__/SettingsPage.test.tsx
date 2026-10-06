import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from '../SettingsPage';

// 桩掉共享 API 与认证
vi.mock('@ai-cs/shared/api', () => ({
  fetchConfig: vi.fn(),
  updateConfigBatch: vi.fn(),
  fetchWidgetSnippet: vi.fn(),
  fetchAgentCredentials: vi.fn(),
  updateAgentCredentials: vi.fn(),
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
  fetchAgentCredentials,
  fetchConfig,
  fetchWidgetSnippet,
  updateAgentCredentials,
  updateConfigBatch,
} from '@ai-cs/shared/api';

const mockConfig = {
  cache: { ttl: 3600, enabled: true },
  rate_limit: { requests_per_minute: 30, burst: 10 },
  handoff: { keywords: ['人工', '转人工'], auto_assign: true },
  ai: { confidence_threshold: 0.7, max_retries: 2, timeout: 90 },
};

describe('SettingsPage 系统设置', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchConfig as ReturnType<typeof vi.fn>).mockResolvedValue(mockConfig);
    (updateConfigBatch as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 'ok', updated: 4 });
    (fetchWidgetSnippet as ReturnType<typeof vi.fn>).mockResolvedValue({ snippet: '<script data-site-token="public"></script>' });
    (fetchAgentCredentials as ReturnType<typeof vi.fn>).mockResolvedValue({ username: 'support', configured: true });
    (updateAgentCredentials as ReturnType<typeof vi.fn>).mockResolvedValue({ username: 'support', configured: true });
  });

  it('渲染基本设置 tab 并预填配置值', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('缓存过期时间（秒）')).toBeInTheDocument();
    expect(screen.getByText('缓存过期时间（秒）')).toBeInTheDocument();
    expect(screen.getByDisplayValue('3600')).toBeInTheDocument();
    // 启用缓存复选框（有 htmlFor 关联）
    expect(screen.getByLabelText('启用缓存')).toBeChecked();
  });

  it('切换到 AI 配置 tab 显示 AI 参数', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    await screen.findByText('缓存过期时间（秒）');

    fireEvent.click(screen.getByText('AI配置'));
    expect(screen.getByText('人工转接置信度阈值（0-1）')).toBeInTheDocument();
    expect(screen.getByDisplayValue('0.7')).toBeInTheDocument();
  });

  it('保存基本设置时调用 updateConfigBatch 提交点号路径配置', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    await screen.findByText('缓存过期时间（秒）');

    fireEvent.click(screen.getByText('保存设置'));

    await waitFor(() =>
      expect(updateConfigBatch).toHaveBeenCalledWith({
        'cache.ttl': 3600,
        'cache.enabled': true,
        'rate_limit.requests_per_minute': 30,
        'handoff.keywords': ['人工', '转人工'],
      })
    );
    expect(await screen.findByText('已保存 ✓')).toBeInTheDocument();
  });

  it('集成设置 tab 显示集成项', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    await screen.findByText('缓存过期时间（秒）');

    fireEvent.click(screen.getByText('集成设置'));
    expect(screen.getByText('微信公众号')).toBeInTheDocument();
    expect(screen.getByText('钉钉')).toBeInTheDocument();
    expect(screen.getByText('网页 Widget')).toBeInTheDocument();
  });

  it('生成并显示 Widget 嵌入代码', async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);
    await screen.findByText('缓存过期时间（秒）');
    fireEvent.click(screen.getByText('集成设置'));
    fireEvent.click(screen.getByText('生成代码'));
    expect(await screen.findByLabelText('Widget 嵌入代码')).toHaveValue('<script data-site-token="public"></script>');
  });

  it('校验并轮换客服登录凭据', async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);
    await screen.findByText('缓存过期时间（秒）');
    fireEvent.click(screen.getByText('登录安全'));

    expect(await screen.findByText('已配置强凭据')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('新密码（至少12位）'), { target: { value: 'new-secure-password' } });
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'new-secure-password' } });
    fireEvent.click(screen.getByRole('button', { name: '轮换凭据' }));

    await waitFor(() => expect(updateAgentCredentials).toHaveBeenCalledWith('support', 'new-secure-password'));
    expect(await screen.findByText('客服登录凭据已更新，旧刷新会话已撤销')).toBeInTheDocument();
  });
});
