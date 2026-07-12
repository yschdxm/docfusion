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
  const createRequestIdRef = useRef(0)
  const mountedRef = useRef(true)
  const mountNodeSeqRef = useRef(0)

  const getMountShell = useCallback(() => {
    return document.getElementById('onlyoffice-preview-shell')
  }, [])

  const clearMountShell = useCallback(() => {
    const shellNode = getMountShell()
    if (shellNode) {
      shellNode.replaceChildren()
    }
  }, [getMountShell])

  const createMountTarget = useCallback(() => {
    const shellNode = getMountShell()
    if (!shellNode) return null

    shellNode.replaceChildren()

    const mountNode = document.createElement('div')
    mountNodeSeqRef.current += 1
    mountNode.id = `onlyoffice-preview-${mountNodeSeqRef.current}`
    mountNode.className = 'absolute inset-0'
    shellNode.appendChild(mountNode)

    return mountNode.id
  }, [getMountShell])

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

  const destroyEditor = useCallback(() => {
    createRequestIdRef.current += 1
    if (editorInstanceRef.current) {
      try { editorInstanceRef.current.destroyEditor?.() } catch { /* ignore */ }
      editorInstanceRef.current = null
    }

    clearMountShell()
  }, [clearMountShell])

  // 创建/销毁编辑器 - 通过 office-config 获取配置
  const createEditor = useCallback(async (file: PreviewFile) => {
    if (!window.DocsAPI || !file) return

    const mountShell = getMountShell()
    if (!mountShell) return

    destroyEditor()
    setIsLoading(true)
    const requestId = createRequestIdRef.current

    try {
      const response = await api.get<OfficeConfigResponse>(`/documents/${file.id}/office-config`, {
        params: { mode: 'view' },
      })

      // 只允许最后一次请求生效，避免切换第二个文档时被第一个文档的异步返回覆盖
      if (!mountedRef.current || requestId !== createRequestIdRef.current) return

      const mountTargetId = createMountTarget()
      if (!mountTargetId) return

      editorInstanceRef.current = new window.DocsAPI.DocEditor(mountTargetId, response.data.config)
    } catch (err) {
      if (mountedRef.current && requestId === createRequestIdRef.current) {
        console.error('[DocumentPreview] 编辑器创建失败:', err)
      }
    } finally {
      if (mountedRef.current && requestId === createRequestIdRef.current) {
        setIsLoading(false)
      }
    }
  }, [createMountTarget, destroyEditor, getMountShell])

  // currentFile 变化时重建编辑器
  // 仅在桌面端预览面板真实打开时自动创建，避免隐藏容器上的 DOM 冲突
  useEffect(() => {
    if (!currentFile || !onlyofficeReady || !isPanelOpen) return
    const timer = setTimeout(() => createEditor(currentFile), 50)
    return () => clearTimeout(timer)
  }, [currentFile, onlyofficeReady, isPanelOpen, createEditor])

  // 组件卸载时清理
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
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

  // 独立请求预览（不依赖 isPanelOpen，用于手机端）
  const requestPreview = useCallback(() => {
    if (!window.DocsAPI && !scriptLoadAttempted.current) {
      scriptLoadAttempted.current = true
      loadScript().catch(err => {
        console.error('[DocumentPreview]', err.message)
        scriptLoadAttempted.current = false
      })
    } else if (window.DocsAPI) {
      setOnlyofficeReady(true)
    }
  }, [loadScript])

  // 手机端 overlay 打开后手动触发编辑器创建
  const ensureEditor = useCallback(() => {
    if (currentFile && window.DocsAPI && getMountShell()) {
      destroyEditor()
      createEditor(currentFile)
    }
  }, [currentFile, createEditor, destroyEditor, getMountShell])

  return {
    isPanelOpen,
    togglePanel,
    previewFiles,
    currentFile,
    setCurrentFile,
    addOperatedFile,
    clearPreview,
    requestPreview,
    ensureEditor,
    isLoading,
  }
}
