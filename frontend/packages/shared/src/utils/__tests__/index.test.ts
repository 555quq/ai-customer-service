import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  formatTime,
  truncateText,
  getStatusColor,
  getPriorityColor,
  generateId,
  debounce,
  throttle,
} from '../index';

afterEach(() => {
  vi.useRealTimers();
});

describe('utils 工具函数', () => {
  describe('truncateText', () => {
    it('短文本原样返回', () => {
      expect(truncateText('你好', 10)).toBe('你好');
    });

    it('边界长度不截断', () => {
      expect(truncateText('abcd', 4)).toBe('abcd');
    });

    it('长文本截断并追加省略号', () => {
      expect(truncateText('这是一个很长很长的文本内容', 8)).toBe('这是一个很长很长...');
    });
  });

  describe('getStatusColor', () => {
    it('已知状态返回对应颜色', () => {
      expect(getStatusColor('open')).toBe('#22c55e');
      expect(getStatusColor('pending')).toBe('#eab308');
      expect(getStatusColor('resolved')).toBe('#6b7280');
      expect(getStatusColor('offline')).toBe('#6b7280');
    });

    it('未知状态返回默认灰色', () => {
      expect(getStatusColor('unknown')).toBe('#6b7280');
    });
  });

  describe('getPriorityColor', () => {
    it('已知优先级返回对应颜色', () => {
      expect(getPriorityColor('low')).toBe('#22c55e');
      expect(getPriorityColor('medium')).toBe('#eab308');
      expect(getPriorityColor('high')).toBe('#f97316');
      expect(getPriorityColor('urgent')).toBe('#ef4444');
    });

    it('未知优先级返回默认灰色', () => {
      expect(getPriorityColor('critical')).toBe('#6b7280');
    });
  });

  describe('formatTime', () => {
    it('1 分钟内返回「刚刚」', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
      expect(formatTime(new Date('2026-08-04T12:00:30Z').toISOString())).toBe('刚刚');
    });

    it('返回 N 分钟前', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
      expect(formatTime(new Date('2026-08-04T11:55:00Z').toISOString())).toBe('5分钟前');
    });

    it('返回 N 小时前', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
      expect(formatTime(new Date('2026-08-04T09:00:00Z').toISOString())).toBe('3小时前');
    });

    it('超过 7 天返回日期', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2026-08-04T12:00:00Z'));
      const result = formatTime(new Date('2026-07-01T12:00:00Z').toISOString());
      expect(result).not.toMatch(/(前)$/);
    });
  });

  describe('generateId', () => {
    it('生成非空唯一 ID', () => {
      const id1 = generateId();
      const id2 = generateId();
      expect(id1).toBeTruthy();
      expect(id2).toBeTruthy();
      expect(id1).not.toBe(id2);
    });
  });

  describe('debounce', () => {
    it('等待期内只调用一次', () => {
      vi.useFakeTimers();
      const fn = vi.fn();
      const debounced = debounce(fn, 100);

      debounced();
      debounced();
      debounced();

      expect(fn).not.toHaveBeenCalled();
      vi.advanceTimersByTime(150);
      expect(fn).toHaveBeenCalledTimes(1);
    });
  });

  describe('throttle', () => {
    it('限制期内只执行一次', () => {
      vi.useFakeTimers();
      const fn = vi.fn();
      const throttled = throttle(fn, 200);

      throttled();
      throttled();
      throttled();

      expect(fn).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(250);
      throttled();
      expect(fn).toHaveBeenCalledTimes(2);
    });
  });
});
