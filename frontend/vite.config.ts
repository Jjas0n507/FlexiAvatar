import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import electronRenderer from 'vite-plugin-electron-renderer'
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
    electronRenderer(),
  ],
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
