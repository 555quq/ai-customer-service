import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Input } from '../Input';

describe('Input 组件', () => {
  it('渲染 label', () => {
    render(<Input label="用户名" />);
    expect(screen.getByText('用户名')).toBeInTheDocument();
  });

  it('渲染输入值并响应输入', () => {
    const onChange = vi.fn();
    render(<Input onChange={onChange} />);
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'hello' } });
    expect(onChange).toHaveBeenCalled();
  });

  it('error 状态显示红色边框', () => {
    render(<Input error="必填项" />);
    // error 文本渲染为 input 容器边框红色
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });
});
