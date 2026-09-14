import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        // 主进程入口
        entry: '../electron/main.ts',
        onstart(args) {
          // 开发模式下启动 Electron
          args.startup()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              external: ['electron'],
            },
          },
        },
      },
      {
        // 预加载脚本
        entry: '../electron/preload.ts',
        onstart(args) {
          args.reload()
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              external: ['electron'],
            },
          },
        },
      },
    ]),
    // electronRenderer() 已摘除：渲染进程零 Node API（全走 WS/preload），
    // 它的依赖预打包器还会把 pixi 引用的 'url' 外部化成 require() 导致崩溃
  ],
  // 后端 REST（/api/avatars 等）反代到 Python 后端：渲染进程与后端同源，
  // 避免跨端口 CORS。缺了这段，/api/* 会被 Vite 的 SPA 兜底成 index.html，
  // 前端 JSON 解析直接失败（实测："Unexpected token '<'"）。
  // WebSocket 仍由前端直连 ws://127.0.0.1:8765/ws，不经代理。
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // pixi.js@6 引用 Node 'url'；electron-renderer 插件会把它外部化成
      // require("url")，nodeIntegration:false 下 require 不存在 → 崩。
      // 指到 browserify shim（alias 优先级高于插件外部化）。
      url: path.resolve(__dirname, 'node_modules/url/url.js'),
    },
  },
})
