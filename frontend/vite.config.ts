import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { execSync } from 'child_process'

function detectOnlyOfficeUrl(): string {
  // 1. 环境变量优先
  if (process.env.VITE_ONLYOFFICE_URL) return process.env.VITE_ONLYOFFICE_URL

  // 2. 自动检测宿主机 IP（WSL2 场景）
  try {
    const ips = execSync("hostname -I 2>/dev/null", { encoding: 'utf-8' }).trim().split(/\s+/)
    const hostIp = ips.find(ip => /^192\.168\./.test(ip))
    if (hostIp) return `http://${hostIp}:8088`
  } catch {}

  // 3. 默认 localhost
  return 'http://localhost:8088'
}

const onlyofficeTarget = detectOnlyOfficeUrl()
console.log(`[vite] OnlyOffice target: ${onlyofficeTarget}`)

export default defineConfig({
  appType: 'spa',
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
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://localhost:8000',
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
      '/doc/': {
        target: onlyofficeTarget,
        changeOrigin: true,
        ws: true,
      },
      '/command': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      '/document_editor_service_worker.js': {
        target: onlyofficeTarget,
        changeOrigin: true,
      },
      // OnlyOffice 字体文件（allfontsgen 生成的二进制字体数据）
      '/fonts': {
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
