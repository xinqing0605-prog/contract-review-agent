import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 显式绑定 IPv4：Windows 上 localhost 可能只解析到 ::1，导致 127.0.0.1 连不上
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // 本地开发把 /api 转发到 run_local.ps1 起的 8103，避免跨域
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8103',
        changeOrigin: false,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
