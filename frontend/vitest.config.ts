import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// Vitest 配置（前端单元测试）
// 对齐 apps/*/vite.config.ts 的 @ai-cs/shared alias
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@ai-cs/shared': path.resolve(__dirname, './packages/shared/src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
