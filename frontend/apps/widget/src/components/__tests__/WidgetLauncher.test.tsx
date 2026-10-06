import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { WidgetLauncher } from '../WidgetLauncher';
import type { WidgetConfig } from '@ai-cs/shared/types';

const baseConfig: WidgetConfig = {
  apiUrl: 'http://localhost:8000',
  brandName: '在线客服',
  position: 'right',
  zIndex: 9999,
};

describe('WidgetLauncher 启动按钮', () => {
  it('关闭状态下 aria-label 为"打开 AI 助手"，无 open 样式类', () => {
    render(<WidgetLauncher config={baseConfig} isOpen={false} onClick={() => {}} />);
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-label', '打开 AI 助手');
    expect(btn.className).not.toContain('kiki-launcher--open');
  });

  it('打开状态下 aria-label 为"关闭 AI 助手"且带 open 样式类', () => {
    render(<WidgetLauncher config={baseConfig} isOpen onClick={() => {}} />);
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-label', '关闭 AI 助手');
    expect(btn.className).toContain('kiki-launcher--open');
  });

  it('点击触发 onClick', () => {
    const onClick = vi.fn();
    render(<WidgetLauncher config={baseConfig} isOpen={false} onClick={onClick} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('position 控制左右定位', () => {
    const { rerender } = render(<WidgetLauncher config={baseConfig} isOpen={false} onClick={() => {}} />);
    expect(screen.getByRole('button')).toHaveStyle({ right: '24px' });

    rerender(
      <WidgetLauncher
        config={{ ...baseConfig, position: 'left' }}
        isOpen={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByRole('button')).toHaveStyle({ left: '24px' });
  });
});
