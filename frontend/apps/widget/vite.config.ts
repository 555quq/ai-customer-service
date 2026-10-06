import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  resolve: {
    alias: {
      '@ai-cs/shared': path.resolve(__dirname, '../../packages/shared/src'),
    },
  },
  build: {
    lib: {
      entry: './src/index.ts',
      name: 'AICustomerService',
      fileName: () => 'widget.js',
      formats: ['iife'],
    },
    cssCodeSplit: false,
    outDir: 'dist',
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
