import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// ponytail: web-only config, no Electron plugins. Used by dev:web script.
// live2d-renderer's require("path") is patched directly in node_modules.
export default defineConfig({
  plugins: [react()],
  // 后端 REST（/api/avatars 等）反代到 Python 后端：渲染进程与后端同源，
  // 避免跨端口 CORS；WebSocket 仍由前端直连 ws://127.0.0.1:8765/ws。
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
