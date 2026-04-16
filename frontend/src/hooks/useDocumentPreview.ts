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
  const [onlyofficeReady, setOnlyofficeReady] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const editorInstanceRef = useRef<{ destroyEditor?: () => void } | null>(null)
  const scriptLoadAttempted = useRef(false)

  // 加载 ONLYOFFICE 脚本（按需）- 使用相对路径
  const loadScript = useCallback((): Promise<void> => {
    if (window.DocsAPI) return Promise.resolve()

    return new Promise((resolve, reject) => {
      setIsLoading(true)
      const script = document.createElement('script')
      script.src = '/web-apps/apps/api/documents/api.js'
      script.onload = () => {
        setOnlyofficeReady(true)
        setIsLoading(false)
        resolve()
      }
      script.onerror = () => {
        setIsLoading(false)
        reject(new Error('无法连接到 ONLYOFFICE Document Server'))
      }
      document.head.appendChild(script)
    })
  }, [])

  // 面板打开时加载脚本
  useEffect(() => {
    if (!isPanelOpen || scriptLoadAttempted.current) return
    if (window.DocsAPI) {
      setOnlyofficeReady(true)
      return
    }
    scriptLoadAttempted.current = true
    loadScript().catch(err => {
      console.error('[DocumentPreview]', err.message)
      scriptLoadAttempted.current = false
    })
  }, [isPanelOpen, loadScript])

  // 创建/销毁编辑器 - 通过 office-config 获取配置
  const createEditor = useCallback(async (file: PreviewFile) => {
    if (!window.DocsAPI || !file) return

    // 销毁旧实例
    if (editorInstanceRef.current) {
      try { editorInstanceRef.current.destroyEditor?.() } catch { /* ignore */ }
      editorInstanceRef.current = null
    }

    try {
      const response = await api.get<OfficeConfigResponse>(`/documents/${file.id}/office-config`, {
        params: { mode: 'view' },
      })

      editorInstanceRef.current = new window.DocsAPI.DocEditor('onlyoffice-preview', response.data.config)
    } catch (err) {
      console.error('[DocumentPreview] 编辑器创建失败:', err)
    }
  }, [])

  // currentFile 变化时重建编辑器
  useEffect(() => {
    if (!currentFile || !onlyofficeReady || !isPanelOpen) return
    const timer = setTimeout(() => createEditor(currentFile), 50)
    return () => clearTimeout(timer)
  }, [currentFile, onlyofficeReady, isPanelOpen, createEditor])

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (editorInstanceRef.current) {
        try { editorInstanceRef.current.destroyEditor?.() } catch { /* ignore */ }
        editorInstanceRef.current = null
      }
    }
  }, [])

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
    if (editorInstanceRef.current) {
      try { editorInstanceRef.current.destroyEditor?.() } catch { /* ignore */ }
      editorInstanceRef.current = null
    }
    setPreviewFiles([])
    setCurrentFileState(null)
  }, [])

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
