import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SetupPage } from '../SetupPage';

vi.mock('@ai-cs/shared/api', () => ({
  fetchSetupStatus: vi.fn(),
  initializeSetup: vi.fn(),
}));

import { fetchSetupStatus, initializeSetup } from '@ai-cs/shared/api';

describe('SetupPage 首次初始化向导', () => {
  beforeEach(() => vi.clearAllMocks());

  it('未初始化时显示第一步且管理员密码有强度提示', async () => {
    (fetchSetupStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      initialized: false,
      setup_token_configured: true,
      agent_credentials_configured: false,
      version: 2,
    });
    render(<MemoryRouter><SetupPage /></MemoryRouter>);
    expect(await screen.findByText('站点与账号')).toBeInTheDocument();
    expect(screen.getByText('管理员密码（至少12位）')).toBeInTheDocument();
    expect(screen.getByText('客服用户名')).toBeInTheDocument();
    expect(screen.getByText('客服密码（至少12位）')).toBeInTheDocument();
    expect(screen.getByText('确认客服密码')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一步' })).toBeDisabled();
  });

  it('已经初始化时不再显示配置表单', async () => {
    (fetchSetupStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      initialized: true,
      setup_token_configured: true,
      agent_credentials_configured: true,
      version: 2,
    });
    render(<MemoryRouter><SetupPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('系统已完成初始化')).toBeInTheDocument());
    expect(screen.queryByText('一次性初始化 Token')).not.toBeInTheDocument();
  });

  it('初始化请求同时提交客服强凭据', async () => {
    (fetchSetupStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      initialized: false,
      setup_token_configured: true,
      agent_credentials_configured: false,
      version: 2,
    });
    (initializeSetup as ReturnType<typeof vi.fn>).mockResolvedValue({ initialized: true });
    render(<MemoryRouter><SetupPage /></MemoryRouter>);

    await screen.findByText('站点与账号');
    fireEvent.change(screen.getByLabelText('一次性初始化 Token'), { target: { value: 'setup-token' } });
    fireEvent.change(screen.getByLabelText('站点名称'), { target: { value: '示例企业' } });
    fireEvent.change(screen.getByLabelText('管理员密码（至少12位）'), { target: { value: 'admin-secure-password' } });
    fireEvent.change(screen.getByLabelText('客服用户名'), { target: { value: 'support' } });
    fireEvent.change(screen.getByLabelText('客服密码（至少12位）'), { target: { value: 'agent-secure-password' } });
    fireEvent.change(screen.getByLabelText('确认客服密码'), { target: { value: 'agent-secure-password' } });
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));

    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'model-secret' } });
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    fireEvent.change(screen.getByLabelText('API Token'), { target: { value: 'chatwoot-secret' } });
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    fireEvent.click(screen.getByRole('button', { name: '验证并初始化' }));

    await waitFor(() => expect(initializeSetup).toHaveBeenCalled());
    expect(initializeSetup).toHaveBeenCalledWith(
      expect.objectContaining({
        admin: { username: 'admin', password: 'admin-secure-password' },
        agent: { username: 'support', password: 'agent-secure-password' },
      }),
      'setup-token',
    );
  });
});
