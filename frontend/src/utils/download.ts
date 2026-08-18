/**
 * 文件下载工具（从 Content-Disposition 解析文件名 + 触发浏览器下载）
 */

import api from '../services/api'

/** 解析 Content-Disposition 中的文件名（优先 RFC 5987 filename* 的 UTF-8 编码，支持中文文件名） */
export function parseDownloadFilename(contentDisposition?: string, fallbackName?: string) {
  if (!contentDisposition) return fallbackName ?? 'download'

  const utf8Match = contentDisposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const filenameMatch = contentDisposition.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i)
  const parsed = filenameMatch?.[1] ?? filenameMatch?.[2]
  return parsed?.trim() || fallbackName || 'download'
}

/** 触发浏览器下载（Blob → 临时 a[download] 点击） */
export function triggerFileDownload(blob: Blob, filename: string) {
  const objectUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(objectUrl)
}

/** 规范化下载链接为 API 相对路径（去掉域名与 /api/v1 前缀，供 axios baseURL 拼接） */
export function normalizeDownloadPath(url: string): string {
  try {
    const urlObj = new URL(url)
    url = urlObj.pathname
  } catch {
    // 不是完整 URL，原样继续
  }
  // 兼容错误格式 http://api/v1/...（域名是 "api"）
  const wrongDomainMatch = url.match(/^https?:\/\/api(\/.*)$/i)
  if (wrongDomainMatch) url = wrongDomainMatch[1]
  return url.replace(/^\/api\/v1/, '')
}

/** 是否是文档下载链接 */
export function isDocumentDownloadUrl(url?: string): boolean {
  return !!url && url.includes('/documents/') && url.includes('/download')
}

/**
 * 带鉴权的文件下载（普通 a[href] 不带 Bearer token，会得到 401 JSON）
 * 失败时抛错，由调用方决定提示方式
 */
export async function downloadWithAuth(url: string, fallbackName = 'download'): Promise<void> {
  const resp = await api.get(normalizeDownloadPath(url), { responseType: 'blob' })
  const filename = parseDownloadFilename(resp.headers['content-disposition'], fallbackName)
  const blob = resp.data instanceof Blob
    ? resp.data
    : new Blob([resp.data], { type: resp.headers['content-type'] || 'application/octet-stream' })
  triggerFileDownload(blob, filename)
}
