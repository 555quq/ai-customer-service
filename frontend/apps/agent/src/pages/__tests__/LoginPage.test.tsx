import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../LoginPage';

vi.mock('../../shared/AuthProvider', () => ({
  useAuth: () => ({
    login: vi.fn(),
    errorCode: 'AGENT_CREDENTIALS_NOT_CONFIGURED',
  }),
}));

describe('Agent LoginPage', () => {
  it('不暴露默认账号并提示管理员先配置凭据', async () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>);

    expect(screen.queryByText(/agent123/)).not.toBeInTheDocument();
    expect(await screen.findByText('请联系管理员先配置客服账号')).toBeInTheDocument();
  });
});
