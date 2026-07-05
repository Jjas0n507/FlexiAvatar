import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// ponytail: web-only config, no Electron plugins. Used by dev:web script.
// live2d-renderer's require("path") is patched directly in node_modules.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
