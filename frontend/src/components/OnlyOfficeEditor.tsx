import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from 'react'
import api from '../services/api'
import { useI18n } from '../hooks/useI18n'
import { getTheme } from '../services/theme'

interface OfficeConfigResponse {
  serverUrl: string
  config: Record<string, unknown>
}

interface RefreshUrlResponse {
  url: string
  expires: number
}

export interface FillTableData {
  headers: string[]
  data: Record<string, any>[]
  fill_mode: 'overwrite' | 'append'
  target_table_index: number
  file_type: string
}

export interface OnlyOfficeEditorHandle {
  fillTableViaPlugin: (fillData: FillTableData) => Promise<boolean>
}

interface OnlyOfficeEditorProps {
  documentId: string
  mode?: 'view' | 'edit'
  onAIAction?: (action: string, params: any) => void
}

const OnlyOfficeEditor = forwardRef<OnlyOfficeEditorHandle, OnlyOfficeEditorProps>(
  ({ documentId, mode = 'edit', onAIAction }, ref) => {
    const { language } = useI18n()
    const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

    const containerRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<any>(null)
    const loadedScriptRef = useRef<string>('')
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')

    // 获取当前主题
    const currentTheme = getTheme()
    const isDarkMode = currentTheme === 'night-mode'

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

    // 通过 OnlyOffice 插件实时填表（不修改文件，不刷新编辑器）
    // 通过后端 API 与插件通信：前端提交请求 → 后端存储 → 插件轮询 → 插件提交结果 → 后端返回前端
    const fillTableViaPlugin = useCallback(async (fillData: FillTableData): Promise<boolean> => {
      try {
        const response = await api.post('/fill-table-plugin/submit', {
          headers: fillData.headers,
          data: fillData.data,
          fill_mode: fillData.fill_mode,
          target_table_index: fillData.target_table_index,
          file_type: fillData.file_type,
        })

        if (response.data.success) {
          console.log('[OnlyOfficeEditor] 填表成功:', response.data.result)
          return true
        } else {
          console.error('[OnlyOfficeEditor] 填表失败:', response.data.error)
          return false
        }
      } catch (err) {
        console.error('[OnlyOfficeEditor] 填表请求失败:', err)
        return false
      }
    }, [])

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
      fillTableViaPlugin,
    }), [fillTableViaPlugin])

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
            // 主题和品牌配置
            customization: {
              ...(response.data.config.editorConfig as any)?.customization,
              forcesave: false,
              compactHeader: true,
              toolbarNoTabs: false,
              // 设置主题 - 使用uiTheme属性
              uiTheme: isDarkMode ? 'theme-docfusion-dark' : 'theme-docfusion-light',
              // 顶栏 Logo（允许自定义）
              logo: {
                image: '/logo.png',
                imageDark: '/logo.png',
                url: '/',
                visible: true
              },
              // 关于页面客户信息（允许自定义）
              customer: {
                name: '知融云枢',
                address: '中国',
                www: 'docfusion.example.com',
                logo: '/logo.png',
                logoDark: '/logo.png',
              },
              // 隐藏反馈按钮
              feedback: { visible: false },
            }
          },
          // 插件配置通过 web-apps/plugins.json 文件加载，不在这里传入
          events: {
            onRequestRefreshToken: async () => {
              const newUrl = await refreshDocumentUrl()
              if (newUrl && editorRef.current) {
                editorRef.current.refreshHistory?.()
              }
            },
            // 监听插件事件
            onPluginEvent: (event: any) => {
              if (event.type === 'onClick') {
                // 处理右键菜单点击
                handlePluginEvent(event)
              }
            }
          },
        }
        editorRef.current = new window.DocsAPI.DocEditor(`onlyoffice-editor-${documentId}`, config)

        // 编辑器加载完成后禁用主题选择
        handleEditorReady()
      } catch (err) {
        const message = err instanceof Error ? err.message : 'OnlyOffice load failed'
        setError(message)
      } finally {
        setLoading(false)
      }
    }

    // 处理插件事件
    const handlePluginEvent = (event: any) => {
      if (onAIAction) {
        onAIAction(event.action, event.params)
      }
    }

    useEffect(() => {
      mountEditor()

      return () => {
        destroyEditor()
      }
    }, [documentId, mode])

    // 监听主题变化，通过 postMessage 同步到 OnlyOffice iframe
    useEffect(() => {
      const observer = new MutationObserver(() => {
        const theme = getTheme()
        const isDark = theme === 'night-mode'
        const themeId = isDark ? 'theme-docfusion-dark' : 'theme-docfusion-light'

        // 通过 postMessage 通知 OnlyOffice iframe 切换主题
        const iframe = containerRef.current?.querySelector('iframe') as HTMLIFrameElement
        if (iframe && iframe.contentWindow) {
          iframe.contentWindow.postMessage({
            type: 'set-theme',
            themeId: themeId
          }, '*')
        }
      })

      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
      })

      return () => observer.disconnect()
    }, [])

    // 编辑器加载完成后禁用主题选择
    const handleEditorReady = useCallback(() => {
      setTimeout(() => {
        const iframe = containerRef.current?.querySelector('iframe') as HTMLIFrameElement
        if (iframe && iframe.contentWindow) {
          iframe.contentWindow.postMessage({
            type: 'disable-theme-switch'
          }, '*')
        }
      }, 2000) // 延迟 2 秒确保编辑器完全加载
    }, [])

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
)

OnlyOfficeEditor.displayName = 'OnlyOfficeEditor'

export default OnlyOfficeEditor
