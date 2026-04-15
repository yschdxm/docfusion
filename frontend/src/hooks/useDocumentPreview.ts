import { useState, useRef, useCallback, useEffect } from 'react'
import api from '../services/api'

export interface PreviewFile {
  id: string
  name: string
  fileType: string
  source: 'operated' | 'selected'
}

export function getFileType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    doc: 'doc', docx: 'docx', xls: 'xls', xlsx: 'xlsx',
    ppt: 'ppt', pptx: 'pptx', csv: 'csv', pdf: 'pdf',
  }
  return map[ext] || ext
}

const OFFICE_EXTENSIONS = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv']

function isOfficeFile(fileType: string): boolean {
  return OFFICE_EXTENSIONS.includes(fileType)
}

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (elementId: string, config: Record<string, unknown>) => {
        destroyEditor?: () => void
      }
    }
  }
}

interface OfficeConfigResponse {
  config: Record<string, unknown>
  serverUrl: string
}

export function useDocumentPreview() {
  const [isPanelOpen, setIsPanelOpen] = useState(false)
  const [previewFiles, setPreviewFiles] = useState<PreviewFile[]>([])
  const [currentFile, setCurrentFileState] = useState<PreviewFile | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const editorInstanceRef = useRef<{ destroyEditor?: () => void } | null>(null)
  const loadedScriptRef = useRef<string | null>(null)

  const destroyEditor = useCallback(() => {
    if (editorInstanceRef.current) {
      try { editorInstanceRef.current.destroyEditor?.() } catch { /* ignore */ }
      editorInstanceRef.current = null
    }
  }, [])

  const ensureOnlyOfficeScript = useCallback(async (serverUrl: string): Promise<void> => {
    if (window.DocsAPI?.DocEditor) return

    const normalized = serverUrl.endsWith('/') ? serverUrl.slice(0, -1) : serverUrl
    const scriptUrl = `${normalized}/web-apps/apps/api/documents/api.js`

    if (loadedScriptRef.current && loadedScriptRef.current !== scriptUrl) {
      const oldScript = document.querySelector(`script[src="${loadedScriptRef.current}"]`)
      oldScript?.remove()
      loadedScriptRef.current = null
    }

    await new Promise<void>((resolve, reject) => {
      let script = document.querySelector(`script[src="${scriptUrl}"]`) as HTMLScriptElement | null
      if (!script) {
        script = document.createElement('script')
        script.src = scriptUrl
        document.head.appendChild(script)
        loadedScriptRef.current = scriptUrl
      }

      const startedAt = Date.now()
      const timer = window.setInterval(() => {
        if (window.DocsAPI?.DocEditor) {
          window.clearInterval(timer)
          resolve()
          return
        }
        if (Date.now() - startedAt > 60000) {
          window.clearInterval(timer)
          reject(new Error('OnlyOffice 脚本加载超时'))
        }
      }, 200)

      script.onerror = () => {
        window.clearInterval(timer)
        reject(new Error('OnlyOffice 脚本加载失败'))
      }
    })
  }, [])

  // 创建/销毁编辑器
  const createEditor = useCallback(async (file: PreviewFile) => {
    if (!file) return

    destroyEditor()
    setIsLoading(true)

    try {
      const fileType = getFileType(file.name)

      if (isOfficeFile(fileType)) {
        // Office 文件：通过后端 office-config 获取配置
        const response = await api.get<OfficeConfigResponse>(`/documents/${file.id}/office-config`, {
          params: { mode: 'view' },
        })

        await ensureOnlyOfficeScript(response.data.serverUrl)

        if (!window.DocsAPI?.DocEditor) {
          throw new Error('OnlyOffice 组件未正确加载')
        }

        editorInstanceRef.current = new window.DocsAPI.DocEditor('onlyoffice-preview', response.data.config)
      }
      // 非 Office 文件（txt, md, pdf 等）暂不在此 hook 中处理
    } catch (err) {
      console.error('[DocumentPreview] 预览失败:', err)
    } finally {
      setIsLoading(false)
    }
  }, [destroyEditor, ensureOnlyOfficeScript])

  // currentFile 变化时重建编辑器
  useEffect(() => {
    if (!currentFile || !isPanelOpen) return
    const timer = setTimeout(() => createEditor(currentFile), 50)
    return () => clearTimeout(timer)
  }, [currentFile, isPanelOpen, createEditor])

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      destroyEditor()
    }
  }, [destroyEditor])

  const togglePanel = useCallback(() => {
    setIsPanelOpen(prev => !prev)
  }, [])

  const addOperatedFile = useCallback((file: PreviewFile) => {
    setPreviewFiles(prev => {
      const exists = prev.find(f => f.id === file.id)
      if (exists) {
        return prev.map(f => f.id === file.id ? { ...f, ...file } : f)
      }
      return [...prev, file]
    })
    setCurrentFileState(file)
    setIsPanelOpen(true)
  }, [])

  const setCurrentFile = useCallback((file: PreviewFile) => {
    setCurrentFileState(file)
  }, [])

  const clearPreview = useCallback(() => {
    destroyEditor()
    setPreviewFiles([])
    setCurrentFileState(null)
  }, [destroyEditor])

  return {
    isPanelOpen,
    togglePanel,
    previewFiles,
    currentFile,
    setCurrentFile,
    addOperatedFile,
    clearPreview,
    isLoading,
  }
}
