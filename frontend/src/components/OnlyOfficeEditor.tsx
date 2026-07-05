import { useEffect, useRef, useState, useCallback } from 'react'
import api from '../services/api'
import { useI18n } from '../hooks/useI18n'

interface OfficeConfigResponse {
  serverUrl: string
  config: Record<string, unknown>
}

interface RefreshUrlResponse {
  url: string
  expires: number
}

interface OnlyOfficeEditorProps {
  documentId: string
  mode?: 'view' | 'edit'
}

export default function OnlyOfficeEditor({ documentId, mode = 'edit' }: OnlyOfficeEditorProps) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

  const containerRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<any>(null)
  const loadedScriptRef = useRef<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const destroyEditor = () => {
    if (editorRef.current) {
      try {
        editorRef.current.destroyEditor()
      } catch {
        // ignore
      }
      editorRef.current = null
    }
  }

  const refreshDocumentUrl = useCallback(async () => {
    try {
      const response = await api.get<RefreshUrlResponse>(`/documents/onlyoffice/refresh-url/${documentId}`)
      return response.data.url
    } catch {
      return null
    }
  }, [documentId])

  const ensureOnlyOfficeScript = async () => {
    if (window.DocsAPI?.DocEditor) return
    const scriptUrl = '/web-apps/apps/api/documents/api.js'

    await new Promise<void>((resolve, reject) => {
      if (window.DocsAPI?.DocEditor) {
        resolve()
        return
      }

      const script = document.createElement('script')
      script.src = scriptUrl
      document.head.appendChild(script)
      loadedScriptRef.current = scriptUrl

      const startedAt = Date.now()
      const timer = window.setInterval(() => {
        if (window.DocsAPI?.DocEditor) {
          window.clearInterval(timer)
          resolve()
          return
        }
        if (Date.now() - startedAt > 60000) {
          window.clearInterval(timer)
          reject(new Error('OnlyOffice script load timeout'))
        }
      }, 200)

      script.onerror = () => {
        window.clearInterval(timer)
        reject(new Error('OnlyOffice script load failed'))
      }
    })
  }

  const mountEditor = async () => {
    if (!containerRef.current) return

    setLoading(true)
    setError('')
    destroyEditor()

    containerRef.current.innerHTML = ''

    // 创建编辑器容器
    const editorDiv = document.createElement('div')
    editorDiv.id = `onlyoffice-editor-${documentId}`
    editorDiv.style.width = '100%'
    editorDiv.style.height = '100%'
    containerRef.current.appendChild(editorDiv)

    try {
      const response = await api.get<OfficeConfigResponse>(`/documents/${documentId}/office-config`, {
        params: { mode },
      })

      await ensureOnlyOfficeScript()

      if (!window.DocsAPI?.DocEditor) {
        throw new Error('OnlyOffice component not loaded')
      }

      const config = {
        ...response.data.config,
        documentServerUrl: '',
        editorConfig: {
          ...response.data.config.editorConfig,
        },
        events: {
          onRequestRefreshToken: async () => {
            const newUrl = await refreshDocumentUrl()
            if (newUrl && editorRef.current) {
              editorRef.current.refreshHistory?.()
            }
          },
        },
      }
      editorRef.current = new window.DocsAPI.DocEditor(`onlyoffice-editor-${documentId}`, config)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'OnlyOffice load failed'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    mountEditor()

    return () => {
      destroyEditor()
    }
  }, [documentId, mode])

  return (
    <div className="h-full flex flex-col">
      {/* 编辑器容器 */}
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500 mx-auto mb-4"></div>
              <p className="text-sm text-slate-500">{tr('正在加载 OnlyOffice...', 'Loading OnlyOffice...', 'OnlyOffice を読み込み中...')}</p>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-white">
            <div className="text-center text-red-500">
              <p className="text-sm">{error}</p>
              <button
                onClick={mountEditor}
                className="mt-2 px-4 py-2 text-sm bg-red-50 hover:bg-red-100 rounded-lg"
              >
                {tr('重试', 'Retry', '再試行')}
              </button>
            </div>
          </div>
        )}
        <div ref={containerRef} className="h-full w-full" />
      </div>
    </div>
  )
}
