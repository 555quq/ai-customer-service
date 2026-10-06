import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Card } from '../Card';

describe('Card 组件', () => {
  it('渲染 children 内容', () => {
    render(<Card>卡片内容</Card>);
    expect(screen.getByText('卡片内容')).toBeInTheDocument();
  });

  it('点击触发 onClick', () => {
    const onClick = vi.fn();
    render(<Card onClick={onClick}>可点击卡片</Card>);
    fireEvent.click(screen.getByText('可点击卡片'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('hover 模式添加 cursor-pointer 类', () => {
    render(<Card hover>悬停卡片</Card>);
    expect(screen.getByText('悬停卡片')).toHaveClass('cursor-pointer');
  });
});
