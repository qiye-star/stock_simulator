import { defineConfig } from 'vite';

/**
 * 后端地址：开发时 Vite 代理到本地 FastAPI（默认 8000）。
 * 可用环境变量 VITE_BACKEND_URL 覆盖。
 * 注意：/api/v1/ws 必须声明在 /api 之前，且开启 ws: true。
 */
const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000';

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api/v1/ws': {
        target: backend,
        changeOrigin: true,
        ws: true,
      },
      '/api': {
        target: backend,
        changeOrigin: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api/v1/ws': { target: backend, changeOrigin: true, ws: true },
      '/api': { target: backend, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
});
