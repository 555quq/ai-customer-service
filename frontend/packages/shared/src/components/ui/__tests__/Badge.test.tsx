import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '../Badge';

describe('Badge 组件', () => {
  it('渲染 children 内容', () => {
    render(<Badge>新会话</Badge>);
    expect(screen.getByText('新会话')).toBeInTheDocument();
  });

  it('默认变体使用 default 样式', () => {
    render(<Badge>默认</Badge>);
    expect(screen.getByText('默认')).toHaveStyle({ backgroundColor: '#f3f4f6' });
  });

  it('success 变体应用成功样式', () => {
    render(<Badge variant="success">成功</Badge>);
    expect(screen.getByText('成功')).toHaveStyle({ backgroundColor: '#d1fae5' });
  });

  it('error 变体应用错误样式', () => {
    render(<Badge variant="error">错误</Badge>);
    expect(screen.getByText('错误')).toHaveStyle({ backgroundColor: '#fee2e2' });
  });
});
