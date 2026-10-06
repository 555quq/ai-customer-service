import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../Button';

describe('Button 组件', () => {
  it('渲染 children 内容', () => {
    render(<Button>提交</Button>);
    expect(screen.getByText('提交')).toBeInTheDocument();
  });

  it('点击触发 onClick 回调', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>点击</Button>);
    fireEvent.click(screen.getByText('点击'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('disabled 时点击不触发 onClick', () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        禁用
      </Button>
    );
    const btn = screen.getByText('禁用');
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
    expect(btn).toBeDisabled();
  });

  it('loading 状态下禁用按钮', () => {
    render(<Button loading>加载中</Button>);
    expect(screen.getByText('加载中')).toBeDisabled();
  });

  it('应用 primary 变体背景色', () => {
    render(<Button variant="primary">主要</Button>);
    expect(screen.getByText('主要')).toHaveStyle({ backgroundColor: '#6366f1' });
  });

  it('正确设置 type 属性', () => {
    render(<Button type="submit">提交表单</Button>);
    expect(screen.getByText('提交表单')).toHaveAttribute('type', 'submit');
  });
});
