import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, ChevronLeft, ChevronRight, Plus, Check, Eye, X, Square, Search, FileOutput, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import { getAuthUser, getAuthToken } from '../services/auth'
import { parseDownloadFilename, triggerFileDownload } from '../utils/download'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'
import AgentThinkingPanel from '../components/AgentThinkingPanel'
import TaskStatsBadge from '../components/TaskStatsBadge'
import agentStreamService, { AgentStep, TaskStats } from '../services/agentStreamService'
import { useDocumentPreview, getFileType } from '../hooks/useDocumentPreview'
import type { PreviewFile } from '../hooks/useDocumentPreview'
import DocumentPreviewPanel from '../components/DocumentPreviewPanel'
import ConversationOutputsPanel from '../components/ConversationOutputsPanel'
import { useI18n } from '../hooks/useI18n'
import { getTheme } from '../services/theme'
import { getStoredLanguage } from '../services/i18n'

// 自定义 Markdown 链接组件：对 API 下载链接使用带 token 的请求
function DownloadLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const isDownloadLink = href && (
    href.includes('/documents/') && href.includes('/download')
  )

  // 规范化下载链接：提取相对路径部分
  const normalizeDownloadHref = (url: string): string => {
    if (!url) return url

    // 情况1: 完整URL（如 https://www1.fylm.xyz:9200/api/v1/documents/...）
    try {
      const urlObj = new URL(url)
      // 提取路径部分，忽略域名
      return urlObj.pathname
    } catch {
      // 不是完整URL，继续处理
    }

    // 情况2: 错误格式 http://api/v1/... （域名是 "api"）
    const wrongDomainMatch = url.match(/^https?:\/\/api(\/.*)$/i)
    if (wrongDomainMatch) {
      return wrongDomainMatch[1]  // 返回 /v1/documents/... 部分
    }

    // 情况3: 正确的相对路径（如 /api/v1/documents/...）
    return url
  }

  const handleClick = async (e: React.MouseEvent) => {
    if (!isDownloadLink || !href) return
    e.preventDefault()
    try {
      const normalizedPath = normalizeDownloadHref(href)
      const response = await api.get(normalizedPath.replace(/^\/api\/v1/, ''), { responseType: 'blob' })
      const contentDisposition = response.headers['content-disposition'] as string | undefined
      let filename = 'download'
      if (contentDisposition) {
        // RFC 5987: filename*=UTF-8''%E8%A7%86%E9%A2%91%E7%A8%BF.docx
        const rfc5987Match = contentDisposition.match(/filename\*=(?:UTF-8'')(.+)/i)
        if (rfc5987Match) {
          filename = decodeURIComponent(rfc5987Match[1])
        } else {
          // 普通格式: filename="edited_xxx.docx"
          const plainMatch = contentDisposition.match(/filename="?([^";\s]+)"?/)
          if (plainMatch) filename = plainMatch[1]
        }
      }
      const blob = response.data instanceof Blob
        ? response.data
        : new Blob([response.data], { type: (response.headers['content-type'] as string) || 'application/octet-stream' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch {
      const lang = getStoredLanguage()
      toast.error(lang === 'zh-CN' ? '下载失败' : lang === 'ja-JP' ? 'ダウンロードに失敗しました' : 'Download failed')
    }
  }

  if (isDownloadLink) {
    return <a href={href} onClick={handleClick} className="text-blue-600 hover:text-blue-800 underline cursor-pointer">{children}</a>
  }
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
}

const markdownComponents = { a: DownloadLink }

// 消息已带"完成"卡片（自带下载按钮）时，剥掉正文中重复的下载链接，只保留卡片一个下载入口
const COMPLETED_DOWNLOAD_RE = /\s*\[[^\]]*\]\([^)]*\/documents\/[^)]*\/download[^)]*\)/g
function displayContent(message: Message): string {
  const hasCompletedCard = message.action?.action_type === 'completed'
    && !!(message.action.filled_file_url || message.action.result?.filled_file_url)
  return hasCompletedCard ? message.content.replace(COMPLETED_DOWNLOAD_RE, '') : message.content
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  action?: ActionData
  timestamp: number
  steps?: AgentStep[]
  isStreaming?: boolean
  task_stats?: TaskStats
}

interface PreviewItem {
  op: string
  paragraph_index: number
  before: string
  after: string
  reason?: string
}

interface PreviewState {
  title: string
  description: string
  outputFilename?: string
  totalChanges: number
  items: PreviewItem[]
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [query])
  return matches
}

export default function DocumentOperation() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const isMobile = useMediaQuery('(max-width: 767px)')
  const { documents, fetchDocuments } = useDocumentStore()
  const {
    sessions,
    activeSessionId,
    createSession,
    setActiveSession,
    deleteSession,
    updateSessionFiles,
    updateMessage,
    loadSessions,
    setMinimized,
  } = useChatStore()

  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')
  const [outputsOpen, setOutputsOpen] = useState(false)
  const [outputsRefreshKey, setOutputsRefreshKey] = useState(0)

  // 监听主题变化
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showDocDropdown, setShowDocDropdown] = useState(false)
  const [showTemplateDropdown, setShowTemplateDropdown] = useState(false)
  const [docSearchKeyword, setDocSearchKeyword] = useState('')
  const [templateSearchKeyword, setTemplateSearchKeyword] = useState('')
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  // localMessages 的 ref 镜像，供 SSE 回调（闭包外）读取最新值做幂等判断
  const localMessagesRef = useRef<Message[]>([])
  useEffect(() => {
    localMessagesRef.current = localMessages
  }, [localMessages])
  const [pendingActions, setPendingActions] = useState<ActionData[]>([])
  // 悬浮确认卡的横向翻页索引（多表分别确认时通过左右按钮切换）
  const [pendingIndex, setPendingIndex] = useState(0)
  const [previewState, setPreviewState] = useState<PreviewState | null>(null)
  // AI 自动复核开关：关闭后填表 dry_run 结果需用户确认才写入（持久化到 localStorage）
  const [autoReview, setAutoReview] = useState<boolean>(() => {
    try { return localStorage.getItem('agent_auto_review') !== 'false' } catch { return true }
  })
  const toggleAutoReview = () => {
    setAutoReview(prev => {
      const next = !prev
      try { localStorage.setItem('agent_auto_review', String(next)) } catch { /* */ }
      return next
    })
  }

  // SSE 流式状态
  const [currentSteps, setCurrentSteps] = useState<AgentStep[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingStats, setStreamingStats] = useState<TaskStats | null>(null)
  const [streamingDuration, setStreamingDuration] = useState(0)
  const streamingContentRef = useRef('')
  const taskStartTimeRef = useRef<number>(0)
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const currentConnectionRef = useRef<string | null>(null)
  const currentConnectionSessionRef = useRef<string | null>(null)
  // 发送锁：挡住"点击 → isLoading 状态生效前"的竞态窗口（双击/回车连发）
  // handleSend 与 handleConfirmAction 复用同一把锁，startStream 调用后立即释放（此后由 isLoading 接管）
  const sendingRef = useRef(false)
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const [isCompactToolbar, setIsCompactToolbar] = useState(false)

  // 预览面板宽度与拖动
  const PREVIEW_DEFAULT = 640
  const PREVIEW_MIN = 320
  const HANDLE_WIDTH = 16
  const [previewWidth, setPreviewWidth] = useState(PREVIEW_DEFAULT)
  const previewWidthRef = useRef(PREVIEW_DEFAULT)
  const [showMobilePreview, setShowMobilePreview] = useState(false)
  const dragStartRef = useRef<{ x: number; width: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  // 文档预览面板
  const {
    isPanelOpen,
    togglePanel: togglePanelRaw,
    previewFiles,
    currentFile: previewCurrentFile,
    setCurrentFile: setPreviewCurrentFile,
    addOperatedFile,
    removePreviewFile,
    clearPreview,
    requestPreview,
    ensureEditor,
    isLoading: previewIsLoading,
  } = useDocumentPreview()

  // 输出文件预览（下载卡片的"预览"按钮）：加入预览列表并打开边栏
  const handlePreviewOutput = useCallback((fileId: string, filename: string) => {
    addOperatedFile({ id: fileId, name: filename, fileType: getFileType(filename), source: 'operated' })
    if (isMobile) {
      requestPreview()
      setShowMobilePreview(true)
      setOutputsOpen(false)
    }
  }, [addOperatedFile, isMobile, requestPreview])

  const togglePanel = useCallback(() => {
    togglePanelRaw()
    if (!isPanelOpen) {
      previewWidthRef.current = PREVIEW_DEFAULT
      setPreviewWidth(PREVIEW_DEFAULT)
    }
  }, [isPanelOpen, togglePanelRaw])

  // 预览/产出面板互斥：预览打开时（含 addOperatedFile 自动打开）关闭产出面板
  useEffect(() => {
    if (isPanelOpen) setOutputsOpen(false)
  }, [isPanelOpen])

  // 产出面板开关：与预览面板行为一致（同一宽度动画容器），打开时收起预览。
  // 预览面板只是宽度收起、保持挂载——OnlyOffice 编辑器实例挂在其 DOM 节点上，卸载会丢。
  // 移动端：产出为全屏 overlay，打开时收起移动端预览 overlay。
  const toggleOutputs = useCallback(() => {
    const next = !outputsOpen
    setOutputsOpen(next)
    if (next && isPanelOpen) togglePanelRaw()
    if (next) setShowMobilePreview(false)
  }, [outputsOpen, isPanelOpen, togglePanelRaw])

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')

  // 根据搜索关键词过滤文档列表
  const filteredSourceDocs = sourceDocs.filter((d) =>
    d.original_filename.toLowerCase().includes(docSearchKeyword.toLowerCase())
  )
  const filteredTemplateDocs = templateDocs.filter((d) =>
    d.original_filename.toLowerCase().includes(templateSearchKeyword.toLowerCase())
  )

  useEffect(() => {
    fetchDocuments()
    loadSessions()
    setMinimized(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 组件卸载时断开 SSE 连接
  useEffect(() => {
    return () => {
      if (currentConnectionSessionRef.current) {
        agentStreamService.cancelSession(currentConnectionSessionRef.current)
      }
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current)
      }
    }
  }, [])

  // 实时计时器
  useEffect(() => {
    if (isStreaming && taskStartTimeRef.current > 0) {
      durationTimerRef.current = setInterval(() => {
        setStreamingDuration(Date.now() - taskStartTimeRef.current)
      }, 100)
    } else {
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current)
        durationTimerRef.current = null
      }
    }
    return () => {
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current)
      }
    }
  }, [isStreaming])

  useEffect(() => {
    if (activeSessionId) {
      const sessionId = activeSessionId
      let cancelled = false  // 防止异步回调中的竞态条件

      // 如果有活跃的 SSE 连接（handleSend 刚创建了新会话并开始流式），不重置流式状态
      const hasActiveConn = agentStreamService.hasActiveConnection(sessionId)

      setStreamingContent('')
      streamingContentRef.current = ''
      setCurrentSteps([])
      if (!hasActiveConn) {
        setIsStreaming(false)
        setIsLoading(false)
      }

      const { loadSessionMessages } = useChatStore.getState()
      const runningTaskId = agentStreamService.getRunningTaskId(sessionId)

      loadSessionMessages(sessionId, true).then(() => {
        if (cancelled) return  // session已切换，丢弃结果
        if (useChatStore.getState().activeSessionId !== sessionId) return
        const updatedSession = useChatStore.getState().sessions.find(s => s.id === sessionId)
        if (updatedSession) {
          if (!runningTaskId || localMessages.length === 0) {
            setLocalMessages(
              updatedSession.messages.map(m => ({
                role: m.role,
                content: m.content,
                action: m.action_data,
                timestamp: m.timestamp,
                steps: m.steps,
                task_stats: m.task_stats,
              }))
            )
          }
          if (updatedSession.fileIds && updatedSession.fileIds.length > 0) {
            setSelectedDocIds([...updatedSession.fileIds])
          }
          if (updatedSession.templateId) {
            setSelectedTemplateId(updatedSession.templateId)
          }
          // 自动重连正在运行的任务
          if (runningTaskId && !agentStreamService.hasActiveConnection(sessionId)) {
            reconnectToTask(runningTaskId, updatedSession)
          }
        }
      })

      return () => { cancelled = true }
    } else {
      setLocalMessages([])
      setPendingActions([])
    }
  }, [activeSessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  // 手机端 overlay 打开后触发编辑器创建（DOM 元素已就绪）
  useEffect(() => {
    if (isMobile && showMobilePreview) {
      const timer = setTimeout(() => ensureEditor(), 100)
      return () => clearTimeout(timer)
    }
  }, [isMobile, showMobilePreview, ensureEditor])

  // 监听聊天区域宽度，窄时切换紧凑工具栏
  useEffect(() => {
    const el = chatContainerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      setIsCompactToolbar(w < 600)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (docDropdownRef.current && !docDropdownRef.current.contains(event.target as Node)) {
        setShowDocDropdown(false)
        setDocSearchKeyword('')
      }
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(event.target as Node)) {
        setShowTemplateDropdown(false)
        setTemplateSearchKeyword('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages, currentSteps])

  // 预览面板拖动调整宽度（支持鼠标 + 触摸）
  const handleDragStart = useCallback((clientX: number) => {
    setIsDragging(true)
    dragStartRef.current = { x: clientX, width: previewWidthRef.current }

    const handleMove = (ev: MouseEvent | TouchEvent) => {
      if (!dragStartRef.current) return
      const x = 'touches' in ev ? ev.touches[0].clientX : ev.clientX
      const container = document.querySelector('[data-doc-op-container]')
      if (!container) return
      const containerWidth = container.clientWidth
      const historyWidth = showHistory ? 256 : 0
      const availableWidth = containerWidth - historyWidth - HANDLE_WIDTH
      const chatMinWidth = availableWidth / 3
      const maxPreview = availableWidth - chatMinWidth
      const delta = dragStartRef.current.x - x
      const newWidth = Math.min(maxPreview, Math.max(PREVIEW_MIN, dragStartRef.current.width + delta))
      previewWidthRef.current = newWidth
      setPreviewWidth(newWidth)
    }

    const handleEnd = () => {
      setIsDragging(false)
      dragStartRef.current = null
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleEnd)
      document.removeEventListener('touchmove', handleMove)
      document.removeEventListener('touchend', handleEnd)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleEnd)
    document.addEventListener('touchmove', handleMove, { passive: false })
    document.addEventListener('touchend', handleEnd)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [showHistory])

  // ===== SSE 流式相关 =====

  // 断开当前连接
  const disconnectCurrentConnection = useCallback(() => {
    if (currentConnectionSessionRef.current) {
      agentStreamService.cancelSession(currentConnectionSessionRef.current)
    }
    currentConnectionRef.current = null
    currentConnectionSessionRef.current = null
    setIsStreaming(false)
    setIsLoading(false)
    setStreamingContent('')
    streamingContentRef.current = ''
    setCurrentSteps([])
  }, [])

  // SSE 回调工厂
  const createStreamCallbacks = useCallback((
    sessionId: string,
    latestStepsRef: { current: AgentStep[] },
  ) => {
    const onEvent = (event: any, steps: AgentStep[]) => {
      if (currentConnectionSessionRef.current !== sessionId) return

      if (event.event_type === 'assistant_message') {
        const message = event.data.message || ''
        if (message) {
          if (event.data.agent_name) return
          // 幂等保护：页面级重连会全量回放事件，已持久化到 DB 并加载的消息不重复添加
          const exists = localMessagesRef.current.some(m => m.role === 'assistant' && m.content === message)
          if (exists) {
            latestStepsRef.current = []
            setCurrentSteps([])
            setStreamingContent(''); streamingContentRef.current = ''
            return
          }
          const messagesToAdd: Message[] = []
          // 不再保存 streamingContent — 它与 assistant_message 内容相同（来自 content_chunk 累积）
          if (latestStepsRef.current.length > 0) {
            messagesToAdd.push({ role: 'assistant', content: '', timestamp: Date.now(), steps: [...latestStepsRef.current] })
          }
          messagesToAdd.push({ role: 'assistant', content: message, timestamp: Date.now() })
          if (messagesToAdd.length > 0) setLocalMessages(msgs => [...msgs, ...messagesToAdd])
          latestStepsRef.current = []
          setCurrentSteps([])
          setStreamingContent(''); streamingContentRef.current = ''
        }
        return
      }

      latestStepsRef.current = steps
      setCurrentSteps([...steps])

      if (event.event_type === 'tool_result') {
        const toolName = event.data.tool_name
        const result = event.data.result
        const editTools = [
          'edit_paragraph', 'format_paragraph', 'edit_xlsx_cells',
          'edit_docx_cell', 'find_replace_all', 'convert',
          'create_word_document'
        ]
        const isEditOrFill = editTools.includes(toolName)
          || toolName === 'fill_table' || toolName === 'fill_form'
          || (toolName === 'fill_table_execute' && result && result.download_url)
        if (isEditOrFill && result && result.download_url) {
          const filename = result.output_filename || result.output_file || 'output'
          const file: PreviewFile = {
            id: result.output_file_id || filename,
            name: filename,
            fileType: getFileType(filename),
            source: 'operated',
          }
          addOperatedFile(file)
          setOutputsRefreshKey(k => k + 1)
        }
      }

      if (event.event_type === 'stats_update' && event.data.stats) {
        setStreamingStats(event.data.stats)
      }

      // 人工确认模式：dry_run 完成，渲染确认卡片等待用户确认/取消
      if (event.event_type === 'action_required') {
        const summary = event.data.message || ''
        const actionData = event.data.action_data || {}
        const actionId = actionData.action_id
        // 幂等守卫：页面级重连全量回放时同一 action_id 不重复建卡
        if (actionId && localMessagesRef.current.some(m => m.action?.action_id === actionId)) {
          return
        }
        const action: ActionData = {
          action_type: 'confirm_fill',
          action_id: actionId,
          status: 'pending',
          title: tr('写入前请确认', 'Confirm before writing', '書き込み前に確認してください'),
          description: summary || tr('AI 已完成填写校验，确认无误后执行写入。', 'Validation finished. Confirm to apply the writes.', '検証が完了しました。確認後に書き込みます。'),
          dry_run_report: actionData.dry_run_report,
          preview: actionData.preview,
        }
        setPendingActions(prev => (actionId && prev.some(a => a.action_id === actionId)) ? prev : [...prev, action])
        setLocalMessages(prev => [...prev, {
          role: 'assistant', content: '', timestamp: Date.now(), action,
        }])
        return
      }

      if (event.event_type === 'content_chunk' && event.data.content) {
        if (event.data.agent_name) return
        setStreamingContent(prev => {
          const next = prev + event.data.content
          streamingContentRef.current = next
          return next
        })
      }
    }

    const onComplete = (result: any) => {
      if (currentConnectionSessionRef.current !== sessionId) return
      setIsStreaming(false); setIsLoading(false); setStreamingContent(''); streamingContentRef.current = ''
      currentConnectionRef.current = null; currentConnectionSessionRef.current = null

      if (result.fromStatusQuery) {
        // 任务在断连期间完成（结果来自状态查询）：消息已在 DB 中并已从 DB 加载，不重复添加
        setCurrentSteps([])
        return
      }

      setStreamingStats(null)
      if (result.message || result.download_url || latestStepsRef.current.length > 0) {
        // 幂等保护：断连期间任务完成，消息已从 DB 加载，completed 事件重放时不重复添加
        const lastAssistant = [...localMessagesRef.current].reverse().find(m => m.role === 'assistant')
        if (result.message && lastAssistant?.content === result.message) {
          setCurrentSteps([])
          return
        }
        const aiMsg: Message = {
          role: 'assistant',
          content: result.message || '',
          timestamp: Date.now(),
          steps: latestStepsRef.current.length > 0 ? [...latestStepsRef.current] : undefined,
          task_stats: result.task_stats,
        }
        if (result.download_url) {
          aiMsg.action = { action_type: 'completed', filled_file_url: result.download_url, filled_file_id: result.output_file_id, filled_filename: result.output_filename }
          setOutputsRefreshKey(k => k + 1)
        }
        setLocalMessages(prev => [...prev, aiMsg])
      }
      setCurrentSteps([])
    }

    const onError = (error: any) => {
      if (currentConnectionSessionRef.current !== sessionId) return
      setIsStreaming(false); setIsLoading(false); setStreamingContent(''); streamingContentRef.current = ''
      setStreamingStats(null)
      currentConnectionRef.current = null; currentConnectionSessionRef.current = null
      if (error?.toString().includes('abort') || error?.toString().includes('AbortError')) return
      toast.error(error)
    }

    return { onEvent, onComplete, onError }
  }, [addOperatedFile])

  // 断线重连
  const reconnectToTask = useCallback((taskId: string, session: any) => {
    setIsStreaming(true)
    setIsLoading(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''
    currentConnectionSessionRef.current = session.id

    // 恢复任务开始时间，使计时器从断点继续
    const savedStartTime = agentStreamService.getTaskStartTime(session.id)
    if (savedStartTime) {
      taskStartTimeRef.current = savedStartTime
      setStreamingDuration(Date.now() - savedStartTime)
    }

    const latestStepsRef: { current: AgentStep[] } = { current: [] }
    const { onEvent, onComplete, onError } = createStreamCallbacks(session.id, latestStepsRef)

    const connId = agentStreamService.startStream(
      session.id,
      {
        message: '',
        file_ids: session.fileIds || [],
        template_id: session.templateId || undefined,
        conversation_id: session.id,
      },
      onEvent, onComplete, onError,
      taskId
    )
    currentConnectionRef.current = connId
  }, [createStreamCallbacks])

  // ===== fro 原有函数 =====

  // 导出对话（Markdown 留档/debug）
  const [exporting, setExporting] = useState(false)
  const handleExportConversation = async () => {
    if (!activeSessionId || exporting) return
    setExporting(true)
    try {
      const resp = await api.get(`/conversations/${activeSessionId}/export`, { responseType: 'blob' })
      const filename = parseDownloadFilename(
        resp.headers['content-disposition'],
        `conversation-${new Date().toISOString().slice(0, 10)}.md`
      )
      triggerFileDownload(new Blob([resp.data], { type: 'text/markdown;charset=utf-8' }), filename)
      toast.success(tr('对话已导出', 'Conversation exported', '会話をエクスポートしました'))
    } catch (e) {
      console.error('导出对话失败:', e)
      toast.error(tr('导出失败', 'Export failed', 'エクスポートに失敗しました'))
    } finally {
      setExporting(false)
    }
  }

  const handleNewChat = async () => {
    disconnectCurrentConnection()
    setSelectedDocIds([])
    setSelectedTemplateId(null)
    clearPreview()

    const sessionId = await createSession(null, tr('通用对话', 'General Chat', '一般チャット'), [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingActions([])
    toast.success(tr('已创建新对话', 'New chat created', '新しい会話を作成しました'))
  }

  const toggleDocSelection = (docId: string) => {
    setSelectedDocIds((prev) => {
      const next = prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
      if (next.length > 0) {
        const lastDocId = next[next.length - 1]
        const doc = documents.find(d => d.id === lastDocId)
        if (doc) previewDocument(doc)
      }
      return next
    })
  }

  const handleTemplateSelect = (docId: string) => {
    setSelectedTemplateId(selectedTemplateId === docId ? null : docId)
    setShowTemplateDropdown(false)
    if (docId) {
      const doc = templateDocs.find(d => d.id === docId)
      if (doc) previewDocument(doc)
    }
  }

  const previewDocument = useCallback((doc: { id: string; original_filename: string; file_type: string }) => {
    const file: PreviewFile = {
      id: doc.id,
      name: doc.original_filename,
      fileType: doc.file_type || getFileType(doc.original_filename),
      source: 'selected',
    }
    addOperatedFile(file)
  }, [addOperatedFile])

  const handleSend = async (actionConfirmed = false) => {
    if (sendingRef.current) return
    const userMessage = inputValue.trim()
    if (!userMessage && !actionConfirmed) return

    if (!actionConfirmed && pendingActions.length > 0) {
      toast.error(tr('请先处理待确认的操作', 'Please handle the pending action first', '保留中の操作を先に処理してください'))
      return
    }

    // 检查用户是否已选择模型
    const user = getAuthUser()
    if (!user?.selected_model) {
      toast.error(tr('请先在左下角选择一个模型', 'Please select a model first', 'まず左下でモデルを選択してください'))
      return
    }
    sendingRef.current = true
    try {

    let currentSessionId = activeSessionId
    const isNewSession = !currentSessionId
    if (!currentSessionId) {
      const firstDoc = documents.find((d) => d.id === selectedDocIds[0] || d.id === selectedTemplateId)
      const docCount = selectedDocIds.length + (selectedTemplateId ? 1 : 0)
      const sessionName =
        docCount === 0
          ? tr('通用对话', 'General Chat', '一般チャット')
          : docCount === 1
            ? firstDoc?.original_filename || tr('新对话', 'New Chat', '新しい会話')
            : `${firstDoc?.original_filename || tr('文档', 'Document', 'ドキュメント')} ${tr('等', 'and', 'など')} ${docCount} ${tr('个文件', 'files', '件')}`
      currentSessionId = await createSession(
        selectedDocIds[0] || selectedTemplateId || null,
        sessionName,
        selectedDocIds,
        selectedTemplateId
      )
    } else {
      await updateSessionFiles(currentSessionId, selectedDocIds, selectedTemplateId)
    }

    const isFirstMessage = isNewSession || localMessages.length === 0

    const userMsg: Message = {
      role: 'user',
      content: userMessage,
      timestamp: Date.now(),
    }
    setLocalMessages((prev) => [...prev, userMsg])
    setInputValue('')
    setIsLoading(true)
    setIsStreaming(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''
    taskStartTimeRef.current = Date.now()
    agentStreamService.persistTaskStartTime(currentSessionId, Date.now())
    setStreamingDuration(0)
    setStreamingStats(null)

    if (isFirstMessage) {
      api.post('/agent/generate-title', { message: userMessage })
        .then(async (res) => {
          const newTitle = res.data.title || tr('通用对话', 'General Chat', '一般チャット')
          await api.put(`/conversations/${currentSessionId}`, { title: newTitle })
          useChatStore.getState().loadSessions()
        })
        .catch((e) => console.error('Failed to generate title:', e))
    }

    // SSE 流式连接
    const latestStepsRef: { current: AgentStep[] } = { current: [] }
    const { onEvent, onComplete, onError } = createStreamCallbacks(currentSessionId, latestStepsRef)

    currentConnectionSessionRef.current = currentSessionId

    const connId = agentStreamService.startStream(
      currentSessionId,
      {
        message: userMessage,
        file_ids: selectedDocIds,
        template_id: selectedTemplateId || undefined,
        conversation_id: currentSessionId,
        auto_review: autoReview,
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
    } finally {
      sendingRef.current = false
    }
  }

  // 停止生成
  const handleStop = async () => {
    const sessionId = currentConnectionSessionRef.current
    if (!sessionId) return

    const contentToSave = streamingContentRef.current
    const stepsToSave = currentSteps.length > 0 ? [...currentSteps] : []
    const messagesToAdd: Message[] = []
    if (contentToSave) {
      messagesToAdd.push({ role: 'assistant', content: contentToSave, timestamp: Date.now() })
    }
    if (stepsToSave.length > 0) {
      messagesToAdd.push({ role: 'assistant', content: '', timestamp: Date.now(), steps: stepsToSave })
    }
    if (messagesToAdd.length > 0) {
      setLocalMessages(prev => [...prev, ...messagesToAdd])
    }

    setIsStreaming(false)
    setIsLoading(false)
    setStreamingContent('')
    streamingContentRef.current = ''
    setCurrentSteps([])

    await agentStreamService.stopTask(sessionId)
    currentConnectionRef.current = null
    currentConnectionSessionRef.current = null

    toast(tr('已停止生成', 'Generation stopped', '生成を停止しました'), { icon: '⏹️' })
  }

  // 确认写入：走 action_response 通道（内部指令驱动 Agent commit，不产生用户消息气泡）
  // 支持从持久化恢复的卡片直接确认（此时 pendingActions 队列为空，用卡片自身的 action）
  const handleConfirmAction = async (cardAction?: ActionData) => {
    if (sendingRef.current) return
    const actionToConfirm = cardAction || pendingActions[0]
    if (!actionToConfirm || !actionToConfirm.action_id) return
    sendingRef.current = true
    try {

    const currentPendingAction = { ...actionToConfirm }
    const confirmSessionId = activeSessionId!

    // 卡片状态置为已确认（持久化由后端在接收 action_response 时完成）
    setLocalMessages((prev) => {
      const newMessages = [...prev]
      const cardIndex = newMessages.map((m, i) => m.action?.action_id === actionToConfirm.action_id ? i : -1).filter(i => i >= 0).pop()
      if (cardIndex !== undefined) {
        newMessages[cardIndex] = {
          ...newMessages[cardIndex],
          action: { ...newMessages[cardIndex].action!, status: 'confirmed' }
        }
      }
      return newMessages
    })

    setPendingActions(prev => prev.filter(a => a.action_id !== actionToConfirm.action_id))

    setIsLoading(true)
    setIsStreaming(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''

    const latestStepsRef: { current: AgentStep[] } = { current: [] }
    const { onEvent, onComplete: rawOnComplete, onError } = createStreamCallbacks(confirmSessionId, latestStepsRef)

    const onComplete = (result: any) => {
      rawOnComplete(result)

      const msgId = (currentPendingAction as any)._messageId
      if (msgId) {
        updateMessage(confirmSessionId, msgId, {
          role: 'assistant',
          content: result.message,
          action_data: result.download_url ? {
            action_type: 'completed',
            filled_file_url: result.download_url,
            filled_file_id: result.output_file_id
          } : undefined,
        })
      }

      if (result.success) {
        toast.success(tr('操作完成！', 'Operation completed!', '操作が完了しました！'))
      }
    }

    currentConnectionSessionRef.current = confirmSessionId

    const connId = agentStreamService.startStream(
      confirmSessionId,
      {
        message: '',
        file_ids: selectedDocIds,
        template_id: selectedTemplateId || undefined,
        conversation_id: confirmSessionId,
        auto_review: autoReview,
        action_response: { action_id: currentPendingAction.action_id, decision: 'confirm' },
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
    } finally {
      sendingRef.current = false
    }
  }

  // 取消写入：REST 标记终态 + 卡片置为已取消（不启动 Agent，不产生用户消息）
  const handleCancelAction = async (cardAction?: ActionData) => {
    const actionToCancel = cardAction || pendingActions[0]
    if (!actionToCancel) return
    const actionId = actionToCancel.action_id
    const sessionId = activeSessionId

    setLocalMessages((prev) => {
      const newMessages = [...prev]
      const cardIndex = newMessages
        .map((m, i) => (m.action?.action_id && m.action.action_id === actionId ? i : -1))
        .filter((i) => i >= 0)
        .pop()
      if (cardIndex !== undefined) {
        newMessages[cardIndex] = {
          ...newMessages[cardIndex],
          action: { ...newMessages[cardIndex].action!, status: 'cancelled' },
        }
      }
      return newMessages
    })
    setPendingActions(prev => prev.filter(a => a.action_id !== actionToCancel.action_id))

    if (actionId && sessionId) {
      try {
        const token = getAuthToken()
        await fetch('/api/v1/agent/action/cancel', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ action_id: actionId, conversation_id: sessionId }),
        })
      } catch (e) {
        console.warn('[ActionCard] 取消操作同步失败:', e)
      }
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await agentStreamService.stopTask(sessionId)
    if (currentConnectionSessionRef.current === sessionId) {
      currentConnectionRef.current = null
      currentConnectionSessionRef.current = null
      setIsStreaming(false)
      setIsLoading(false)
      setStreamingContent('')
      streamingContentRef.current = ''
      setCurrentSteps([])
    }
    await deleteSession(sessionId)
    if (activeSessionId === sessionId) {
      setLocalMessages([])
      setSelectedDocIds([])
      setSelectedTemplateId(null)
      setPendingActions([])
    }
  }

  const handleRestoreSession = async (sessionId: string) => {
    disconnectCurrentConnection()
    setShowHistory(false)
    setPendingActions([])
    setActiveSession(sessionId)
    clearPreview()

    const { sessions } = useChatStore.getState()
    const session = sessions.find((s) => s.id === sessionId)

    if (session) {
      if (session.fileIds && session.fileIds.length > 0) {
        setSelectedDocIds([...session.fileIds])
      } else {
        setSelectedDocIds([])
      }

      if (session.templateId) {
        setSelectedTemplateId(session.templateId)
      } else {
        setSelectedTemplateId(null)
      }

      setLocalMessages(
        session.messages.map((m) => ({
          role: m.role,
          content: m.content,
          action: m.action_data,
          timestamp: m.timestamp,
          steps: m.steps,
          task_stats: m.task_stats,
        }))
      )
    }
  }

  const getSelectionHint = () => {
    const docCount = selectedDocIds.length
    const templateCount = selectedTemplateId ? 1 : 0
    const total = docCount + templateCount

    if (total === 0) return tr('可直接开始对话；选择文档后可执行定向操作。', 'Start chatting directly, or select documents for targeted actions.', 'そのまま会話を開始できます。文書を選択すると対象操作が可能です。')

    const parts: string[] = []
    if (docCount > 0) parts.push(`${docCount} ${tr('个源文档', 'source docs', '件のソース文書')}`)
    if (templateCount > 0) parts.push(`1 ${tr('个模板', 'template', '件のテンプレート')}`)

    return `${tr('已选择：', 'Selected: ', '選択済み: ')}${parts.join(' + ')}`
  }

  const openPreview = (action: ActionData) => {
    const preview = action.result?.preview
    const items = Array.isArray(preview?.items) ? preview.items : []

    if (items.length === 0) {
      toast.error(tr('当前结果暂无可预览的修改内容', 'No previewable changes in current result', '現在の結果にプレビュー可能な差分はありません'))
      return
    }

    setPreviewState({
      title: action.title || tr('文档修改预览', 'Document Change Preview', '文書変更プレビュー'),
      description: action.description || tr('查看本次文档修改前后的差异。', 'Review before/after differences for this change.', '今回の変更の前後差分を確認します。'),
      outputFilename: action.result?.output_filename,
      totalChanges: preview?.total_changes ?? items.length,
      items,
    })
  }

  return (
    <div data-doc-op-container className="relative flex h-full">
      {/* 左侧历史会话面板 */}
      {isMobile ? (
        /* 移动端：全屏 overlay */
        showHistory && (
          <>
            <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={() => setShowHistory(false)} />
            <div className="fixed inset-y-0 left-0 z-50 w-72 flex flex-col glass shadow-2xl animate-fade-in">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
                <p className="text-sm font-semibold text-slate-900">{tr('历史记录', 'History', '履歴')}</p>
                <button onClick={() => setShowHistory(false)} title={tr('关闭历史', 'Close history', '履歴を閉じる')} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto scrollbar-thin">
                {sessions.map(session => (
                  <div
                    key={session.id}
                    onClick={() => handleRestoreSession(session.id)}
                    className={`p-3 cursor-pointer border-b flex items-center justify-between group transition-all ${
                      isDarkMode
                        ? `hover:bg-slate-700/80 border-slate-700 ${activeSessionId === session.id ? 'bg-blue-900/40 border-l-4 border-l-blue-500' : ''}`
                        : `hover:bg-slate-50 border-slate-100 ${activeSessionId === session.id ? 'bg-primary-50 border-l-4 border-l-primary-500' : ''}`
                    }`}
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Clock className="w-4 h-4 text-slate-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium truncate ${isDarkMode ? 'text-slate-200' : 'text-slate-900'}`}>
                          {(session as any).title || session.documentName || tr('新对话', 'New Chat', '新しい会話')}
                        </p>
                        <p className="text-xs text-slate-500">
                          {new Date(session.updatedAt).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={(e) => handleDeleteSession(session.id, e)}
                      title={tr('删除对话', 'Delete chat', '会話を削除')}
                      className="p-1 text-slate-400 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </>
        )
      ) : (
        /* 桌面端：侧边折叠面板 */
        <div className={`${showHistory ? 'w-64 mr-4' : 'w-0'} transition-all duration-300 overflow-hidden flex flex-col glass shrink-0`}>
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {sessions.map(session => (
              <div
                key={session.id}
                onClick={() => handleRestoreSession(session.id)}
                className={`p-3 cursor-pointer border-b flex items-center justify-between group transition-all ${
                  isDarkMode
                    ? `hover:bg-slate-700/80 border-slate-700 ${activeSessionId === session.id ? 'bg-blue-900/40 border-l-4 border-l-blue-500' : ''}`
                    : `hover:bg-slate-50 border-slate-100 ${activeSessionId === session.id ? 'bg-primary-50 border-l-4 border-l-primary-500' : ''}`
                }`}
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <Clock className="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-medium truncate ${isDarkMode ? 'text-slate-200' : 'text-slate-900'}`}>
                      {(session as any).title || session.documentName || tr('新对话', 'New Chat', '新しい会話')}
                    </p>
                    <p className="text-xs text-slate-500">
                      {new Date(session.updatedAt).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <button
                  onClick={(e) => handleDeleteSession(session.id, e)}
                  title={tr('删除对话', 'Delete chat', '会話を削除')}
                  className="p-1 text-slate-400 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 主聊天区域 */}
      <div ref={chatContainerRef} className="glass relative flex flex-col flex-1 min-w-0">
      <div className="p-3 sm:p-4 border-b border-slate-200">
        {/* 窄屏：历史按钮+操作按钮一行，选择器各占一行 */}
        {isMobile || isCompactToolbar ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={() => setShowHistory(!showHistory)}
                aria-label={tr('切换历史记录', 'Toggle history', '履歴を切替')}
                title={tr('历史记录', 'History', '履歴')}
                className={`p-2 rounded-lg transition-colors shrink-0 ${showHistory ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
              >
                <History className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-2">
                <button onClick={handleNewChat} title={tr('新建对话', 'New Chat', '新しい会話')} className="btn-secondary px-3 py-1.5 text-xs h-8">
                  <Plus className="w-3 h-3" />
                  {tr('新建', 'New', '新規')}
                </button>
                <button
                  onClick={() => {
                    if (isMobile) {
                      requestPreview()
                      setShowMobilePreview(true)
                      setOutputsOpen(false)
                    } else {
                      togglePanel()
                    }
                  }}
                  className={`p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center ${isPanelOpen && !isMobile ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                  title={tr('文档预览', 'Preview', 'プレビュー')}
                >
                  <Eye className="w-4 h-4" />
                </button>
                <button
                  onClick={toggleOutputs}
                  className={`p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center ${outputsOpen ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                  title={tr('会话产出', 'Session outputs', 'セッション成果物')}
                >
                  <FileOutput className="w-4 h-4" />
                </button>
                <button
                  onClick={handleExportConversation}
                  disabled={!activeSessionId || exporting}
                  className="p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center hover:bg-slate-100 text-slate-500 border border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
                  title={tr('导出对话', 'Export conversation', '会話をエクスポート')}
                >
                  {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="relative" ref={docDropdownRef}>
              <button
                onClick={() => {
                  const nextOpen = !showDocDropdown
                  setShowDocDropdown(nextOpen)
                  setShowTemplateDropdown(false)
                  if (!nextOpen) setDocSearchKeyword('')
                  setTemplateSearchKeyword('')
                }}
                title={tr('选择文档', 'Select Documents', '文書を選択')}
                className="w-full flex items-center gap-2 px-3 py-2.5 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                <span className="text-sm text-slate-900 truncate flex-1 text-left">
                  {selectedDocIds.length > 0 ? `${tr('已选', 'Sel.', '選済')} ${selectedDocIds.length} ${tr('个源文档', 'docs', '件')}` : tr('选择源文档（可多选）', 'Select source docs', 'ソース文書を選択')}
                </span>
                <ChevronDown className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${showDocDropdown ? 'rotate-180' : ''}`} />
              </button>
              {showDocDropdown && (
                <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                  <div className="sticky top-0 bg-white p-2 border-b border-slate-100">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        type="text"
                        value={docSearchKeyword}
                        onChange={(e) => setDocSearchKeyword(e.target.value)}
                        placeholder={tr('搜索文档...', 'Search docs...', '文書を検索...')}
                        className="w-full pl-7 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-primary-400"
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                  </div>
                  {filteredSourceDocs.length > 0 ? (
                    filteredSourceDocs.map((doc) => (
                      <div key={doc.id} onClick={() => toggleDocSelection(doc.id)} className={`dropdown-item ${selectedDocIds.includes(doc.id) ? 'dropdown-item-active' : ''}`}>
                        <div className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 ${selectedDocIds.includes(doc.id) ? 'bg-primary-500 border-primary-500' : 'border-slate-300'}`}>
                          {selectedDocIds.includes(doc.id) && <Check className="w-3 h-3 text-white" />}
                        </div>
                        <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-900 truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">{docSearchKeyword ? tr('未找到匹配文档', 'No matching docs', '一致する文書がありません') : tr('暂无源文档', 'No source docs', 'ソース文書なし')}</div>
                  )}
                </div>
              )}
            </div>

            <div className="relative" ref={templateDropdownRef}>
              <button
                onClick={() => {
                  const nextOpen = !showTemplateDropdown
                  setShowTemplateDropdown(nextOpen)
                  setShowDocDropdown(false)
                  if (!nextOpen) setTemplateSearchKeyword('')
                  setDocSearchKeyword('')
                }}
                title={tr('选择模板', 'Select Template', 'テンプレートを選択')}
                className="w-full flex items-center gap-2 px-3 py-2.5 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <Table className="w-4 h-4 text-green-400 shrink-0" />
                <span className="text-sm text-slate-900 truncate flex-1 text-left">
                  {templateDocs.find((d) => d.id === selectedTemplateId)?.original_filename || tr('选择模板（可选）', 'Select template', 'テンプレートを選択')}
                </span>
                <ChevronDown className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${showTemplateDropdown ? 'rotate-180' : ''}`} />
              </button>
              {showTemplateDropdown && (
                <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                  <div className="sticky top-0 bg-white p-2 border-b border-slate-100">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        type="text"
                        value={templateSearchKeyword}
                        onChange={(e) => setTemplateSearchKeyword(e.target.value)}
                        placeholder={tr('搜索模板...', 'Search templates...', 'テンプレートを検索...')}
                        className="w-full pl-7 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-primary-400"
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                  </div>
                  {filteredTemplateDocs.length > 0 ? (
                    filteredTemplateDocs.map((doc) => (
                      <div key={doc.id} onClick={() => handleTemplateSelect(doc.id)} className={`dropdown-item ${selectedTemplateId === doc.id ? 'dropdown-item-active' : ''}`}>
                        <Table className="w-4 h-4 text-green-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-900 truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                        </div>
                        {selectedTemplateId === doc.id && <Check className="w-4 h-4 text-green-400 shrink-0" />}
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">{templateSearchKeyword ? tr('未找到匹配模板', 'No matching templates', '一致するテンプレートがありません') : tr('暂无模板', 'No templates', 'テンプレートなし')}</div>
                  )}
                </div>
              )}
            </div>
            <p className="text-[11px] text-slate-500">{getSelectionHint()}</p>
          </div>
        ) : (
        /* 桌面端/平板端 */
        <div>
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <button
                onClick={() => setShowHistory(!showHistory)}
                aria-label={tr('切换历史记录', 'Toggle history', '履歴を切替')}
                className={`p-2 rounded-lg transition-colors shrink-0 ${showHistory ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                title={tr('历史记录', 'History', '履歴')}
              >
                <History className="w-4 h-4" />
              </button>
              <div className="relative min-w-0 flex-1" ref={docDropdownRef}>
                <button
                  onClick={() => {
                    const nextOpen = !showDocDropdown
                    setShowDocDropdown(nextOpen)
                    setShowTemplateDropdown(false)
                    if (!nextOpen) setDocSearchKeyword('')
                    setTemplateSearchKeyword('')
                  }}
                  title={tr('选择文档', 'Select Documents', '文書を選択')}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
                >
                  <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                  <span className="text-sm text-slate-900 truncate flex-1 text-left">
                    {selectedDocIds.length > 0 ? `${tr('已选', 'Selected', '選択済み')} ${selectedDocIds.length} ${tr('个源文档', 'source docs', '件のソース文書')}` : tr('选择源文档（可多选）', 'Select source docs (multi-select)', 'ソース文書を選択（複数可）')}
                  </span>
                  <ChevronDown className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${showDocDropdown ? 'rotate-180' : ''}`} />
                </button>
                {showDocDropdown && (
                  <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                    <div className="sticky top-0 bg-white p-2 border-b border-slate-100">
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                        <input
                          type="text"
                          value={docSearchKeyword}
                          onChange={(e) => setDocSearchKeyword(e.target.value)}
                          placeholder={tr('搜索文档...', 'Search docs...', '文書を検索...')}
                          className="w-full pl-7 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-primary-400"
                          onClick={(e) => e.stopPropagation()}
                        />
                      </div>
                    </div>
                    {filteredSourceDocs.length > 0 ? (
                      filteredSourceDocs.map((doc) => (
                        <div key={doc.id} onClick={() => toggleDocSelection(doc.id)} className={`dropdown-item ${selectedDocIds.includes(doc.id) ? 'dropdown-item-active' : ''}`}>
                          <div className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 ${selectedDocIds.includes(doc.id) ? 'bg-primary-500 border-primary-500' : 'border-slate-300'}`}>
                            {selectedDocIds.includes(doc.id) && <Check className="w-3 h-3 text-white" />}
                          </div>
                          <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-slate-900 truncate">{doc.original_filename}</p>
                            <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="px-4 py-3 text-sm text-slate-500 text-center">{docSearchKeyword ? tr('未找到匹配文档', 'No matching docs', '一致する文書がありません') : tr('暂无源文档', 'No source documents', 'ソース文書がありません')}</div>
                    )}
                  </div>
                )}
              </div>

              <div className="relative min-w-0 flex-1" ref={templateDropdownRef}>
                <button
                  onClick={() => {
                    const nextOpen = !showTemplateDropdown
                    setShowTemplateDropdown(nextOpen)
                    setShowDocDropdown(false)
                    if (!nextOpen) setTemplateSearchKeyword('')
                    setDocSearchKeyword('')
                  }}
                  title={tr('选择模板', 'Select Template', 'テンプレートを選択')}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
                >
                  <Table className="w-4 h-4 text-green-400 shrink-0" />
                  <span className="text-sm text-slate-900 truncate flex-1 text-left">
                    {templateDocs.find((d) => d.id === selectedTemplateId)?.original_filename || tr('选择模板（可选）', 'Select template (optional)', 'テンプレートを選択（任意）')}
                  </span>
                  <ChevronDown className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${showTemplateDropdown ? 'rotate-180' : ''}`} />
                </button>
                {showTemplateDropdown && (
                  <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                    <div className="sticky top-0 bg-white p-2 border-b border-slate-100">
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                        <input
                          type="text"
                          value={templateSearchKeyword}
                          onChange={(e) => setTemplateSearchKeyword(e.target.value)}
                          placeholder={tr('搜索模板...', 'Search templates...', 'テンプレートを検索...')}
                          className="w-full pl-7 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-primary-400"
                          onClick={(e) => e.stopPropagation()}
                        />
                      </div>
                    </div>
                    {filteredTemplateDocs.length > 0 ? (
                      filteredTemplateDocs.map((doc) => (
                        <div key={doc.id} onClick={() => handleTemplateSelect(doc.id)} className={`dropdown-item ${selectedTemplateId === doc.id ? 'dropdown-item-active' : ''}`}>
                          <Table className="w-4 h-4 text-green-400 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-slate-900 truncate">{doc.original_filename}</p>
                            <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                          </div>
                          {selectedTemplateId === doc.id && <Check className="w-4 h-4 text-green-400 shrink-0" />}
                        </div>
                      ))
                    ) : (
                      <div className="px-4 py-3 text-sm text-slate-500 text-center">{templateSearchKeyword ? tr('未找到匹配模板', 'No matching templates', '一致するテンプレートがありません') : tr('暂无模板', 'No templates', 'テンプレートがありません')}</div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button onClick={handleNewChat} title={tr('新建对话', 'New Chat', '新しい会話')} className="btn-secondary px-3 py-1.5 text-xs h-8">
                <Plus className="w-3 h-3" />
                {tr('新建对话', 'New Chat', '新しい会話')}
              </button>
              <button
                onClick={togglePanel}
                className={`p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center ${isPanelOpen ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                title={tr('文档预览', 'Document Preview', '文書プレビュー')}
              >
                <Eye className="w-4 h-4" />
              </button>
              <button
                onClick={toggleOutputs}
                className={`p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center ${outputsOpen ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                title={tr('会话产出', 'Session outputs', 'セッション成果物')}
              >
                <FileOutput className="w-4 h-4" />
              </button>
              <button
                onClick={handleExportConversation}
                disabled={!activeSessionId || exporting}
                className="p-2 rounded-lg transition-colors h-8 w-8 flex items-center justify-center hover:bg-slate-100 text-slate-500 border border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
                title={tr('导出对话', 'Export conversation', '会話をエクスポート')}
              >
                {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <p className="text-xs text-slate-500">{getSelectionHint()}</p>
        </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {localMessages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <FileText className="w-16 h-16 mx-auto mb-4 text-slate-400" />
              <p className="text-slate-600">{tr('我是你的智能文档助手', 'I am your smart document assistant', '私はあなたの文書アシスタントです')}</p>
              <p className="text-sm text-slate-500 mt-2">{tr('你可以提问、提取信息、改写内容，或发起基于模板的自动填写任务。', 'You can ask questions, extract info, rewrite content, or start template-based auto fill tasks.', '質問、情報抽出、リライト、テンプレート自動入力を実行できます。')}</p>
            </div>
          </div>
        )}

        {localMessages.map((message, index) => (
          <div key={index}>
            {/* Agent 步骤（历史） */}
            {message.role === 'assistant' && message.steps && message.steps.length > 0 &&
             !(isStreaming && index === localMessages.length - 1) && (
              <div className="flex justify-start mb-2">
                <div className="max-w-[80%]">
                  <AgentThinkingPanel steps={message.steps} isActive={false} />
                </div>
              </div>
            )}

            {/* 消息气泡 */}
            {message.content ? (
              <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] p-4 rounded-2xl ${
                  message.role === 'user'
                    ? isDarkMode ? 'bg-blue-900/30 text-slate-200' : 'bg-primary-500/15 text-slate-900'
                    : isDarkMode ? 'bg-slate-800/80 text-slate-200' : 'bg-slate-50 text-slate-700'
                }`}>
                  {message.role === 'assistant' ? (
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {displayContent(message)}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <p className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</p>
                  )}
                  <span className={`text-xs mt-2 block ${message.role === 'user' ? 'text-primary-500/60' : 'text-slate-400'}`}>
                    {new Date(message.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ) : null}

            {/* 操作卡片 */}
            {message.role === 'assistant' && message.action && (
              <div className="ml-0 max-w-[80%]">
                <ActionCard action={message.action} onConfirm={() => handleConfirmAction(message.action)} onCancel={() => handleCancelAction(message.action)} onPreview={handlePreviewOutput} />
                {message.action.action_type === 'completed' && message.action.result?.preview && (
                  <div className="mt-2 flex">
                    <button
                      onClick={() => openPreview(message.action!)}
                      title={tr('预览修改结果', 'Preview changes', '変更をプレビュー')}
                      className={`btn-secondary px-3 py-2 text-sm ${
                        isDarkMode
                          ? 'text-blue-300 border-blue-500/50 hover:bg-blue-900/30'
                          : 'text-blue-700 border-blue-300 hover:bg-blue-50'
                      }`}
                    >
                      <Eye className="w-4 h-4" />
                      {tr('预览修改结果', 'Preview Changes', '変更プレビュー')}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 任务统计 */}
            {message.role === 'assistant' && message.task_stats && (
              <div className="flex justify-start mt-1">
                <TaskStatsBadge stats={message.task_stats} />
              </div>
            )}
          </div>
        ))}

        {/* 当前 Agent 步骤 */}
        {isStreaming && currentSteps.length > 0 && (
          <div className="flex justify-start">
            <div className="max-w-[80%] w-full">
              <AgentThinkingPanel steps={currentSteps} isActive={isStreaming} />
            </div>
          </div>
        )}

        {/* 流式内容 */}
        {isStreaming && streamingContent && (
          <div className="flex justify-start">
            <div className={`max-w-[80%] p-4 rounded-2xl ${
              isDarkMode ? 'bg-slate-800/80 text-slate-200' : 'bg-slate-50 text-slate-700'
            }`}>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {streamingContent}
                </ReactMarkdown>
              </div>
              <span className="text-xs mt-2 block text-slate-400">
                {new Date().toLocaleTimeString()}
              </span>
            </div>
          </div>
        )}

        {/* 实时统计显示 — AI开始回复时即显示，用零值填充尚未收到的字段 */}
        {isStreaming && (
          <div className="flex justify-start">
            <TaskStatsBadge
              stats={streamingStats || { duration_ms: 0, total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, cached_tokens: 0, reasoning_tokens: 0, llm_calls: 0, iterations: 0 }}
              isLive={true}
              liveDuration={streamingDuration}
            />
          </div>
        )}

        {isLoading && !isStreaming && (
          <div className="flex justify-start">
            <div className={`p-4 rounded-2xl ${isDarkMode ? 'bg-slate-800/80' : 'bg-slate-50'}`}>
              <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {previewState && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-6 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="doc-op-preview-title" className={`max-h-[85vh] max-h-[85dvh] w-full max-w-5xl overflow-hidden rounded-xl border shadow-2xl ${
            isDarkMode ? 'border-slate-600 bg-slate-800' : 'border-slate-200 bg-white'
          }`}>
            <div className={`flex items-start justify-between border-b px-6 py-4 ${
              isDarkMode ? 'border-slate-600' : 'border-slate-200'
            }`}>
              <div>
                <h3 id="doc-op-preview-title" className={`text-lg font-semibold ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>{previewState.title}</h3>
                <p className={`mt-1 text-sm ${isDarkMode ? 'text-slate-300' : 'text-slate-600'}`}>{previewState.description}</p>
                <p className="mt-2 text-xs text-slate-500">
                  {tr('共', 'Total', '合計')} {previewState.totalChanges} {tr('处修改', 'changes', '件の変更')}{previewState.outputFilename ? ` · ${previewState.outputFilename}` : ''}
                </p>
              </div>
              <button onClick={() => setPreviewState(null)} aria-label={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} title={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} className={`rounded-lg p-2 transition-colors ${
                isDarkMode
                  ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                  : 'text-slate-400 hover:bg-slate-100 hover:text-slate-900'
              }`}>
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(85vh-88px)] max-h-[calc(85dvh-88px)] space-y-4 overflow-y-auto p-6 scrollbar-thin">
              {previewState.items.map((item, index) => (
                <div key={`${item.op}-${item.paragraph_index}-${index}`} className={`rounded-xl border p-4 ${
                  isDarkMode ? 'border-slate-600 bg-slate-700/80' : 'border-slate-200 bg-slate-50'
                }`}>
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full bg-primary-500/20 px-2.5 py-1 text-primary-700">{item.op}</span>
                    <span className={`rounded-full px-2.5 py-1 ${isDarkMode ? 'bg-slate-600 text-slate-300' : 'bg-white text-slate-600'}`}>{tr('段落', 'Paragraph', '段落')} {item.paragraph_index >= 0 ? item.paragraph_index : '-'}</span>
                    {item.reason && <span className="text-slate-500">{item.reason}</span>}
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className={`rounded-xl border p-4 ${
                      isDarkMode ? 'border-red-500/40 bg-red-900/30' : 'border-red-200 bg-red-50'
                    }`}>
                      <div className={`mb-2 text-xs font-medium uppercase tracking-wide ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>{tr('修改前', 'Before', '変更前')}</div>
                      <pre className={`whitespace-pre-wrap break-words font-sans text-sm leading-6 ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>{item.before || tr('无', 'None', 'なし')}</pre>
                    </div>
                    <div className={`rounded-xl border p-4 ${
                      isDarkMode ? 'border-green-500/40 bg-green-900/30' : 'border-green-200 bg-green-50'
                    }`}>
                      <div className={`mb-2 text-xs font-medium uppercase tracking-wide ${isDarkMode ? 'text-green-300' : 'text-green-700'}`}>{tr('修改后', 'After', '変更後')}</div>
                      <pre className={`whitespace-pre-wrap break-words font-sans text-sm leading-6 ${isDarkMode ? 'text-slate-200' : 'text-slate-800'}`}>{item.after || tr('无', 'None', 'なし')}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className={`p-3 sm:p-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:pb-[max(1rem,env(safe-area-inset-bottom))] border-t ${isDarkMode ? 'border-slate-700' : 'border-slate-200'}`}>
        {/* 待确认操作悬浮条：确认卡片会被后续 AI 回复顶上去了，这里在输入区上方镜像一份，
            用户无需回滚即可确认/取消；消息流中的卡片保留为最终状态记录。
            多张待确认卡（多表分别确认）横向堆叠，通过左右按钮切换 */}
        {(() => {
          const pendingCards = pendingActions.filter(a => !a.status || a.status === 'pending')
          if (pendingCards.length === 0) return null
          const idx = Math.min(pendingIndex, pendingCards.length - 1)
          const card = pendingCards[idx]
          return (
            <div className="mb-2 flex items-stretch gap-1.5">
              {pendingCards.length > 1 && (
                <button
                  onClick={() => setPendingIndex(Math.max(0, idx - 1))}
                  disabled={idx === 0}
                  className={`self-center p-1.5 rounded-lg transition-colors disabled:opacity-30 ${
                    isDarkMode ? 'hover:bg-slate-700 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
                  }`}
                  title={tr('上一个待确认', 'Previous pending', '前の確認')}
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
              )}
              <div className="flex-1 min-w-0">
                <ActionCard
                  key={card.action_id}
                  action={card}
                  onConfirm={() => handleConfirmAction(card)}
                  onCancel={() => handleCancelAction(card)}
                  onPreview={handlePreviewOutput}
                />
                {pendingCards.length > 1 && (
                  <div className={`mt-1 text-center text-xs ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                    {tr(`第 ${idx + 1} / ${pendingCards.length} 个待确认`, `${idx + 1} / ${pendingCards.length} pending`, `${idx + 1} / ${pendingCards.length} 件確認待ち`)}
                  </div>
                )}
              </div>
              {pendingCards.length > 1 && (
                <button
                  onClick={() => setPendingIndex(Math.min(pendingCards.length - 1, idx + 1))}
                  disabled={idx >= pendingCards.length - 1}
                  className={`self-center p-1.5 rounded-lg transition-colors disabled:opacity-30 ${
                    isDarkMode ? 'hover:bg-slate-700 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
                  }`}
                  title={tr('下一个待确认', 'Next pending', '次の確認')}
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              )}
            </div>
          )
        })()}
        <div className="flex gap-2 sm:gap-3">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={pendingActions.length > 0 ? tr('操作待确认，请先点击上方卡片完成确认。', 'Action pending confirmation, please confirm above first.', '操作は確認待ちです。先に上のカードで確認してください。') : tr('输入你的问题或指令...', 'Enter your question or instruction...', '質問または指示を入力してください...')}
            className="input flex-1 min-w-0"
            disabled={isLoading}
          />
          {isStreaming ? (
            <button onClick={handleStop} title={tr('停止生成', 'Stop generation', '生成を停止')} className={`btn-secondary px-4 py-2 ${
              isDarkMode
                ? 'text-red-400 border-red-500/50 hover:bg-red-900/30'
                : 'text-red-500 border-red-300 hover:bg-red-50'
            }`}>
              <Square className="w-5 h-5" />
              {tr('停止', 'Stop', '停止')}
            </button>
          ) : (
            <button onClick={() => handleSend()} title={tr('发送', 'Send', '送信')} disabled={isLoading || (!inputValue.trim() && pendingActions.length === 0)} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed">
              {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
            </button>
          )}
        </div>
        {/* 自动审核开关 + 快捷提示（同一行，开关固定在最左） */}
        <div className="flex items-center gap-2 mt-2 overflow-x-auto pb-1 scrollbar-thin">
          <button
            onClick={toggleAutoReview}
            title={autoReview
              ? tr('AI 自动复核已开启：校验通过后直接写入。点击关闭，改为人工确认', 'Auto-review on: writes apply after validation passes. Click to require manual confirmation', 'AI自動レビュー中：検証通過後そのまま書き込みます。クリックで手動確認に切替')
              : tr('人工确认模式：写入前会显示校验报告供你确认。点击开启 AI 自动复核', 'Manual confirmation: a validation report is shown before writes. Click to enable auto-review', '手動確認モード：書き込み前に検証レポートを表示します。クリックで自動レビューに切替')}
            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
              autoReview ? 'bg-primary-500' : isDarkMode ? 'bg-slate-600' : 'bg-slate-300'
            }`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
              autoReview ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`} />
          </button>
          <span className={`text-xs whitespace-nowrap shrink-0 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
            {tr('自动审核', 'Auto-review', '自動レビュー')}
          </span>
          <button onClick={() => setInputValue(tr('帮我分析这些文档', 'Help me analyze these documents', 'これらの文書を分析してください'))} title={tr('分析文档', 'Analyze docs', '文書分析')} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('分析文档', 'Analyze docs', '文書分析')}
          </button>
          <button onClick={() => setInputValue(tr('填写汇总表', 'Fill summary table', 'まとめ表を記入'))} title={tr('填写表格', 'Fill table', '表記入')} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('填写表格', 'Fill table', '表記入')}
          </button>
          <button onClick={() => setInputValue(tr('查询关键信息', 'Query key information', '重要情報を検索'))} title={tr('查询信息', 'Query info', '情報検索')} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('查询信息', 'Query info', '情報検索')}
          </button>
        </div>
      </div>
      </div>

      {/* 拖动手柄 + 右侧面板容器（预览/产出互斥，共用同一宽度动画；移动端隐藏） */}
      {!isMobile && (
        <>
          {(isPanelOpen || outputsOpen) && (
            <div
              onMouseDown={(e) => handleDragStart(e.clientX)}
              onTouchStart={(e) => handleDragStart(e.touches[0].clientX)}
              className="shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-primary-100/50 transition-colors"
              style={{ width: HANDLE_WIDTH }}
              title={tr('拖动调整宽度', 'Drag to resize', 'ドラッグしてリサイズ')}
            >
              <div className="w-1 h-8 rounded-full bg-slate-300 group-hover:bg-primary-400 transition-colors" />
            </div>
          )}
          {/* 拖动时的透明遮罩，防止 iframe 抢夺事件 */}
          {isDragging && (
            <div className="fixed inset-0 z-30 cursor-col-resize" />
          )}
          <div
            className={`relative shrink-0 overflow-hidden ${isDragging ? '' : 'transition-[width] duration-300 ease-in-out'}`}
            style={{ width: isPanelOpen || outputsOpen ? previewWidth : 0 }}
          >
            {/* 预览面板始终保持挂载：OnlyOffice 编辑器实例挂在其 DOM 节点上，
                切到产出面板时仅被覆盖不卸载，切回编辑器无需重建 */}
            <DocumentPreviewPanel
              previewFiles={previewFiles}
              currentFile={previewCurrentFile}
              onFileSelect={setPreviewCurrentFile}
              onFileRemove={removePreviewFile}
              isLoading={previewIsLoading}
            />
            {/* 产出面板：覆盖在预览面板之上，行为/样式/动画与预览一致（同一容器驱动） */}
            {outputsOpen && (
              <div className="absolute inset-0">
                <ConversationOutputsPanel
                  sessionId={activeSessionId}
                  refreshKey={outputsRefreshKey}
                  isDarkMode={isDarkMode}
                  onOpenFile={(file) => {
                    addOperatedFile(file)
                  }}
                  onClose={() => setOutputsOpen(false)}
                />
              </div>
            )}
          </div>
        </>
      )}

      {/* 手机端全屏文档预览 */}
      {isMobile && showMobilePreview && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={() => setShowMobilePreview(false)} />
          <div className="fixed inset-0 z-50 flex flex-col animate-fade-in">
            <div className={`flex items-center justify-end px-3 py-2 backdrop-blur-sm border-b ${isDarkMode ? 'bg-slate-800/90 border-slate-700' : 'bg-white/90 border-slate-200'}`}>
              <button onClick={() => setShowMobilePreview(false)} title={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} className={`p-1.5 rounded-lg ${isDarkMode ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}>
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <DocumentPreviewPanel
                previewFiles={previewFiles}
                currentFile={previewCurrentFile}
                onFileSelect={setPreviewCurrentFile}
                onFileRemove={removePreviewFile}
                isLoading={previewIsLoading}
              />
            </div>
          </div>
        </>
      )}

      {/* 手机端全屏会话产出（与预览 overlay 结构一致，互斥开一关一） */}
      {isMobile && outputsOpen && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={() => setOutputsOpen(false)} />
          <div className="fixed inset-0 z-50 flex flex-col animate-fade-in p-3">
            <ConversationOutputsPanel
              sessionId={activeSessionId}
              refreshKey={outputsRefreshKey}
              isDarkMode={isDarkMode}
              onOpenFile={(file) => {
                addOperatedFile(file)
                setOutputsOpen(false)
                setShowMobilePreview(true)
              }}
              onClose={() => setOutputsOpen(false)}
            />
          </div>
        </>
      )}

    </div>
  )
}

