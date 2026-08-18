import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { execSync } from 'child_process'

// 加载项目根目录的 .env（与后端/docker-compose 共享同一份配置）
// 空前缀 = 读取全部变量（仅用于本配置的代理目标，不会注入前端 bundle）
const rootEnv = loadEnv('development', path.resolve(__dirname, '..'), '')

// OnlyOffice 宿主机端口（Windows 常占用 8088）。优先级：
// VITE_ONLYOFFICE_PORT（shell 环境） > 根 .env 的 ONLYOFFICE_PORT > 默认 8088
const ONLYOFFICE_PORT =
  process.env.VITE_ONLYOFFICE_PORT || rootEnv.ONLYOFFICE_PORT || '8088'

function detectOnlyOfficeUrl(): string {
  // 1. 完整地址覆盖优先（shell 环境或根 .env 均可）
  if (process.env.VITE_ONLYOFFICE_URL || rootEnv.VITE_ONLYOFFICE_URL) {
    return process.env.VITE_ONLYOFFICE_URL || rootEnv.VITE_ONLYOFFICE_URL
  }

  // 2. 自动检测宿主机 IP（WSL2 场景）
  try {
    const ips = execSync("hostname -I 2>/dev/null", { encoding: 'utf-8' }).trim().split(/\s+/)
    const hostIp = ips.find(ip => /^192\.168\./.test(ip))
    if (hostIp) return `http://${hostIp}:${ONLYOFFICE_PORT}`
  } catch {}

  // 3. 默认 localhost
  return `http://localhost:${ONLYOFFICE_PORT}`
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
      '/themes.json': {
        target: onlyofficeTarget,
        changeOrigin: true,
        rewrite: (path) => '/web-apps' + path,
      },
      '/plugins.json': {
        target: onlyofficeTarget,
        changeOrigin: true,
        rewrite: (path) => '/web-apps' + path,
      },
      '/sdkjs-plugins': {
        target: onlyofficeTarget,
        changeOrigin: true,
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
