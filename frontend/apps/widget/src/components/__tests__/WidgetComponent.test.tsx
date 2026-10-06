import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { WidgetComponent } from '../WidgetComponent';
import type { WidgetConfig } from '@ai-cs/shared/types';

// WidgetWindow 依赖 useChat/API/WebSocket，这里 mock 为带"关闭"按钮的展示桩，聚焦开关交互
vi.mock('../WidgetWindow', () => ({
  WidgetWindow: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="widget-window">
      聊天窗口
      <button onClick={onClose}>关闭窗口</button>
    </div>
  ),
}));

const baseConfig: WidgetConfig = {
  apiUrl: 'http://localhost:8000',
  brandName: '在线客服',
  welcomeMessage: '你好！有什么可以帮到您？',
  position: 'right',
  zIndex: 9999,
};

describe('WidgetComponent 开关交互', () => {
  it('默认关闭，显示启动按钮，不渲染聊天窗口', () => {
    render(<WidgetComponent config={baseConfig} suggestions={[]} />);
    expect(screen.queryByTestId('widget-window')).not.toBeInTheDocument();
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', '打开 AI 助手');
  });

  it('点击启动按钮打开聊天窗口，启动按钮隐藏', () => {
    render(<WidgetComponent config={baseConfig} />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByTestId('widget-window')).toBeInTheDocument();
    // 窗口打开时启动按钮隐藏，避免被聊天窗遮挡形成点击死区
    expect(screen.queryByRole('button', { name: /AI 助手/ })).not.toBeInTheDocument();
  });

  it('通过窗口内关闭按钮关闭聊天窗口，启动按钮恢复', () => {
    render(<WidgetComponent config={baseConfig} />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByTestId('widget-window')).toBeInTheDocument();

    fireEvent.click(screen.getByText('关闭窗口'));
    expect(screen.queryByTestId('widget-window')).not.toBeInTheDocument();
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', '打开 AI 助手');
  });
});
