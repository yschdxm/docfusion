import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const onlyofficeTarget = 'http://localhost:8088'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // ONLYOFFICE Document Server
      '/web-apps': {
        target: onlyofficeTarget,
        changeOrigin: true,
        ws: true,
      },
      '/sdk': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      '/info': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      '/cache': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      '/coauthoring': {
        target: onlyofficeTarget,
        changeOrigin: true,
        ws: true,
      },
      '/command': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      // ONLYOFFICE 带版本号哈希的路径，如 /9.3.1-9293e4497d/web-apps/...
      '^/[^/]+-[a-f0-9]+/': {
        target: onlyofficeTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

