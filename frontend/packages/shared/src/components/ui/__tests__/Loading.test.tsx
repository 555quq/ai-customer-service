import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Loading } from '../Loading';

describe('Loading 组件', () => {
  it('渲染加载提示文本', () => {
    render(<Loading text="加载中..." />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('无文本时不渲染文本', () => {
    render(<Loading />);
    expect(screen.queryByText(/加载/)).not.toBeInTheDocument();
  });

  it('渲染 SVG 旋转图标', () => {
    render(<Loading />);
    const svg = document.querySelector('svg.animate-spin');
    expect(svg).toBeInTheDocument();
  });
});
