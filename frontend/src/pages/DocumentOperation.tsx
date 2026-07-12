import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, Plus, Check, Eye, X, Square, Mail, Mic, Globe } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'
import AgentThinkingPanel from '../components/AgentThinkingPanel'
import TaskStatsBadge from '../components/TaskStatsBadge'
import agentStreamService, { AgentStep, TaskStats } from '../services/agentStreamService'
import { useDocumentPreview, getFileType } from '../hooks/useDocumentPreview'
import type { PreviewFile } from '../hooks/useDocumentPreview'
import DocumentPreviewPanel from '../components/DocumentPreviewPanel'
import { useI18n } from '../hooks/useI18n'
import { getTheme } from '../services/theme'

// 自定义 Markdown 链接组件：对 API 下载链接使用带 token 的请求
function DownloadLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const isDownloadLink = href && (
    href.includes('/documents/') && href.includes('/download')
  )

  // 规范化下载链接：提取相对路径部分
  const normalizeDownloadHref = (url: string): string => {
    // 如果是完整URL（包含域名），提取路径部分
    try {
      const urlObj = new URL(url)
      return urlObj.pathname  // 返回路径部分，如 /api/v1/documents/xxx/download
    } catch {
      // 不是完整URL，直接返回原值
      return url
    }
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
      toast.error('下载失败')
    }
  }

  if (isDownloadLink) {
    return <a href={href} onClick={handleClick} className="text-blue-600 hover:text-blue-800 underline cursor-pointer">{children}</a>
  }
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
}

const markdownComponents = { a: DownloadLink }

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

interface EmailFormState {
  to_email: string
  subject: string
  body: string
}

type BrowserSpeechRecognition = {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  onstart: (() => void) | null
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition

const getSpeechRecognitionConstructor = (): BrowserSpeechRecognitionConstructor | null => {
  const speechApi = window as typeof window & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor
  }

  return speechApi.SpeechRecognition || speechApi.webkitSpeechRecognition || null
}

const mergeInputWithTranscript = (baseText: string, transcript: string) => {
  if (!transcript.trim()) return baseText
  if (!baseText.trim()) return transcript.trim()
  return /[\s。！？.!?，,]$/.test(baseText) ? `${baseText}${transcript.trim()}` : `${baseText} ${transcript.trim()}`
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
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [pendingAction, setPendingAction] = useState<ActionData | null>(null)
  const [previewState, setPreviewState] = useState<PreviewState | null>(null)
  const [showEmailModal, setShowEmailModal] = useState(false)
  const [isSendingEmail, setIsSendingEmail] = useState(false)
  const [emailForm, setEmailForm] = useState<EmailFormState>({
    to_email: '',
    subject: '',
    body: '',
  })
  const [speechSupported, setSpeechSupported] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [webSearchEnabled, setWebSearchEnabled] = useState(true)

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
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const speechBaseInputRef = useRef('')
  const finalTranscriptRef = useRef('')
  const speechStopRequestedRef = useRef(false)
  const [isCompactToolbar, setIsCompactToolbar] = useState(false)

  const assistantName = tr('小知', 'XiaoZhi', '小知')
  const speechLang = language === 'zh-CN' ? 'zh-CN' : language === 'ja-JP' ? 'ja-JP' : 'en-US'

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
    clearPreview,
    requestPreview,
    ensureEditor,
    isLoading: previewIsLoading,
  } = useDocumentPreview()

  const togglePanel = useCallback(() => {
    togglePanelRaw()
    if (!isPanelOpen) {
      previewWidthRef.current = PREVIEW_DEFAULT
      setPreviewWidth(PREVIEW_DEFAULT)
    }
  }, [isPanelOpen, togglePanelRaw])

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')
  const selectedEmailDocument =
    documents.find((d) => d.id === selectedDocIds[selectedDocIds.length - 1]) ||
    documents.find((d) => d.id === selectedTemplateId) ||
    null

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
      setPendingAction(null)
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
      }
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(event.target as Node)) {
        setShowTemplateDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const getSpeechErrorMessage = useCallback((error?: string) => {
    switch (error) {
      case 'not-allowed':
      case 'service-not-allowed':
        return tr('麦克风权限被拒绝，请在浏览器中允许访问麦克风。', 'Microphone permission denied. Please allow microphone access in your browser.', 'マイク権限が拒否されました。ブラウザでマイクへのアクセスを許可してください。')
      case 'audio-capture':
        return tr('未检测到可用麦克风，请检查录音设备。', 'No microphone detected. Please check your recording device.', '利用可能なマイクが見つかりません。録音デバイスを確認してください。')
      case 'network':
        return tr('语音识别网络异常，请稍后重试。', 'Speech recognition network error. Please try again later.', '音声認識のネットワークエラーです。しばらくしてから再試行してください。')
      case 'no-speech':
        return tr('没有识别到语音，请重新尝试。', 'No speech detected. Please try again.', '音声が認識されませんでした。もう一度お試しください。')
      default:
        return tr('语音输入失败，请稍后重试。', 'Voice input failed. Please try again later.', '音声入力に失敗しました。しばらくしてから再試行してください。')
    }
  }, [language])

  const stopSpeechInput = useCallback(() => {
    if (!recognitionRef.current) return
    speechStopRequestedRef.current = true
    recognitionRef.current.stop()
  }, [])

  const handleSpeechToggle = useCallback(() => {
    if (isListening) {
      stopSpeechInput()
      return
    }

    if (!recognitionRef.current) {
      setSpeechSupported(false)
      toast.error(tr('当前浏览器不支持语音输入，推荐使用 Chrome 或 Edge。', 'Voice input is not supported in this browser. Please use Chrome or Edge.', 'このブラウザは音声入力に対応していません。Chrome または Edge を使用してください。'))
      return
    }

    speechBaseInputRef.current = inputValue
    finalTranscriptRef.current = ''
    speechStopRequestedRef.current = false

    try {
      recognitionRef.current.start()
    } catch {
      toast.error(tr('语音输入启动失败，请检查麦克风权限后重试。', 'Failed to start voice input. Please check microphone permission and try again.', '音声入力を開始できませんでした。マイク権限を確認してから再試行してください。'))
    }
  }, [inputValue, isListening, stopSpeechInput, language])

  useEffect(() => {
    const SpeechRecognitionConstructor = getSpeechRecognitionConstructor()
    setSpeechSupported(Boolean(SpeechRecognitionConstructor))

    if (!SpeechRecognitionConstructor) {
      recognitionRef.current = null
      return
    }

    const recognition = new SpeechRecognitionConstructor()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = speechLang

    recognition.onstart = () => {
      setIsListening(true)
    }

    recognition.onresult = (event: any) => {
      let latestFinalTranscript = finalTranscriptRef.current
      let interimTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        const transcript = result?.[0]?.transcript ?? ''

        if (result?.isFinal) {
          latestFinalTranscript += transcript
        } else {
          interimTranscript += transcript
        }
      }

      finalTranscriptRef.current = latestFinalTranscript
      const mergedTranscript = `${latestFinalTranscript} ${interimTranscript}`.trim()
      setInputValue(mergeInputWithTranscript(speechBaseInputRef.current, mergedTranscript))
    }

    recognition.onerror = (event: any) => {
      if (speechStopRequestedRef.current || event?.error === 'aborted') return
      toast.error(getSpeechErrorMessage(event?.error))
    }

    recognition.onend = () => {
      setIsListening(false)
      speechStopRequestedRef.current = false
    }

    recognitionRef.current = recognition

    return () => {
      speechStopRequestedRef.current = true
      recognition.onstart = null
      recognition.onresult = null
      recognition.onerror = null
      recognition.onend = null
      recognition.stop()
      recognitionRef.current = null
      setIsListening(false)
    }
  }, [getSpeechErrorMessage, speechLang])

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
          'replace_text', 'rewrite_paragraph', 'insert_after',
          'heading_promote', 'list_format', 'paragraph_split',
          'set_text_style', 'convert'
        ]
        const isEditOrFill = editTools.includes(toolName) || toolName === 'fill_table'
        if (isEditOrFill && result && result.download_url) {
          const filename = result.output_filename || result.output_file || 'output'
          const file: PreviewFile = {
            id: result.output_file_id || filename,
            name: filename,
            fileType: getFileType(filename),
            source: 'operated',
          }
          addOperatedFile(file)
        }
      }

      if (event.event_type === 'stats_update' && event.data.stats) {
        setStreamingStats(event.data.stats)
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

      if (result._replayDone) {
        // 回放结束但任务已在断连期间完成：保留统计显示，消息已从 DB 加载
        setCurrentSteps([])
        return
      }

      setStreamingStats(null)
      if (result.message || result.download_url || latestStepsRef.current.length > 0) {
        const aiMsg: Message = {
          role: 'assistant',
          content: result.message || '',
          timestamp: Date.now(),
          steps: latestStepsRef.current.length > 0 ? [...latestStepsRef.current] : undefined,
          task_stats: result.task_stats,
        }
        if (result.download_url) {
          aiMsg.action = { action_type: 'completed', filled_file_url: result.download_url, filled_file_id: result.output_file_id }
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
        web_search_enabled: webSearchEnabled,
      },
      onEvent, onComplete, onError,
      taskId
    )
    currentConnectionRef.current = connId
  }, [createStreamCallbacks, webSearchEnabled])

  // ===== fro 原有函数 =====

  const handleNewChat = async () => {
    disconnectCurrentConnection()
    setSelectedDocIds([])
    setSelectedTemplateId(null)
    clearPreview()

    const sessionId = await createSession(null, tr('通用对话', 'General Chat', '一般チャット'), [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingAction(null)
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
    if (isListening) {
      stopSpeechInput()
      return
    }

    const userMessage = inputValue.trim()
    if (!userMessage && !actionConfirmed) return

    if (!actionConfirmed && pendingAction) {
      toast.error(tr('请先处理待确认的操作', 'Please handle the pending action first', '保留中の操作を先に処理してください'))
      return
    }

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
        web_search_enabled: webSearchEnabled,
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
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

  const handleConfirmAction = async () => {
    if (!pendingAction) return

    const currentPendingAction = { ...pendingAction }
    const confirmSessionId = activeSessionId!

    setLocalMessages((prev) => {
      const newMessages = [...prev]
      const lastAiIndex = newMessages.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop()
      if (lastAiIndex !== undefined) {
        newMessages[lastAiIndex] = {
          ...newMessages[lastAiIndex],
          action: { ...pendingAction, action_type: 'executing', progress: 0 }
        }
      }
      return newMessages
    })

    setPendingAction(null)

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
        message: tr('确认执行之前的操作', 'Confirm previous operation', '前の操作を実行確認'),
        file_ids: selectedDocIds,
        template_id: selectedTemplateId || undefined,
        conversation_id: confirmSessionId,
        web_search_enabled: webSearchEnabled
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
  }

  const handleCancelAction = () => {
    setPendingAction(null)
    setLocalMessages((prev) => {
      const newMessages = [...prev]
      const lastAiIndex = newMessages
        .map((m, i) => (m.role === 'assistant' ? i : -1))
        .filter((i) => i >= 0)
        .pop()
      if (lastAiIndex !== undefined) {
        newMessages[lastAiIndex] = {
          ...newMessages[lastAiIndex],
          content: '已取消当前操作。你可以继续输入新指令。',
          action: undefined,
        }
      }
      return newMessages
    })
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
      setPendingAction(null)
    }
  }

  const handleRestoreSession = async (sessionId: string) => {
    disconnectCurrentConnection()
    setShowHistory(false)
    setPendingAction(null)
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

  const openEmailModal = () => {
    if (!selectedEmailDocument) {
      toast.error(tr('请先选择要发送的文档', 'Please select a document to send first', '先に送信する文書を選択してください'))
      return
    }

    setEmailForm({
      to_email: '',
      subject: `${tr('文档分享', 'Document Share', '文書共有')}: ${selectedEmailDocument.original_filename}`,
      body: tr(
        '您好，附件中是我从系统中发送给您的文档，请查收。',
        'Hello, the requested document is attached. Please check it.',
        'こんにちは。ご依頼の文書を添付いたします。ご確認ください。'
      ),
    })
    setShowEmailModal(true)
  }

  const handleSendEmail = async () => {
    if (!selectedEmailDocument) {
      toast.error(tr('未找到可发送的文档', 'No document available to send', '送信可能な文書が見つかりません'))
      return
    }

    if (!emailForm.to_email.trim()) {
      toast.error(tr('请输入收件人邮箱', 'Please enter recipient email', '宛先メールアドレスを入力してください'))
      return
    }

    if (!emailForm.subject.trim()) {
      toast.error(tr('请输入邮件主题', 'Please enter email subject', 'メール件名を入力してください'))
      return
    }

    try {
      setIsSendingEmail(true)
      await api.post(`/documents/${selectedEmailDocument.id}/send-email`, {
        to_email: emailForm.to_email.trim(),
        subject: emailForm.subject.trim(),
        body: emailForm.body,
      })
      toast.success(tr('邮件发送成功', 'Email sent successfully', 'メール送信に成功しました'))
      setShowEmailModal(false)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      toast.error(detail || tr('邮件发送失败', 'Failed to send email', 'メール送信に失敗しました'))
    } finally {
      setIsSendingEmail(false)
    }
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
    <div data-doc-op-container className="flex h-full">
      {/* 左侧历史会话面板 */}
      {isMobile ? (
        /* 移动端：全屏 overlay */
        showHistory && (
          <>
            <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={() => setShowHistory(false)} />
            <div className="fixed inset-y-0 left-0 z-50 w-72 flex flex-col glass shadow-2xl animate-fade-in">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
                <p className="text-sm font-semibold text-slate-900">{tr('历史记录', 'History', '履歴')}</p>
                <button onClick={() => setShowHistory(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100">
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
                className={`p-2 rounded-lg transition-colors shrink-0 ${showHistory ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
              >
                <History className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-2">
                <button onClick={handleNewChat} className="btn-secondary px-3 py-1.5 text-xs">
                  <Plus className="w-3 h-3" />
                  {tr('新建', 'New', '新規')}
                </button>
                <button
                  onClick={openEmailModal}
                  className="btn-secondary px-3 py-1.5 text-xs"
                  title={tr('发送所选文档到邮箱', 'Send selected document by email', '選択文書をメール送信')}
                >
                  <Mail className="w-3 h-3" />
                  {tr('邮件发送', 'Send Email', 'メール送信')}
                </button>
                <button
                  onClick={() => { requestPreview(); setShowMobilePreview(true) }}
                  className="p-2 rounded-lg hover:bg-slate-100 text-slate-500 border border-transparent"
                  title={tr('文档预览', 'Preview', 'プレビュー')}
                >
                  <Eye className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="relative" ref={docDropdownRef}>
              <button
                onClick={() => { setShowDocDropdown(!showDocDropdown); setShowTemplateDropdown(false) }}
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
                  {sourceDocs.length > 0 ? (
                    sourceDocs.map((doc) => (
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
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">{tr('暂无源文档', 'No source docs', 'ソース文書なし')}</div>
                  )}
                </div>
              )}
            </div>

            <div className="relative" ref={templateDropdownRef}>
              <button
                onClick={() => { setShowTemplateDropdown(!showTemplateDropdown); setShowDocDropdown(false) }}
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
                  {templateDocs.length > 0 ? (
                    templateDocs.map((doc) => (
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
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">{tr('暂无模板', 'No templates', 'テンプレートなし')}</div>
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
                  onClick={() => { setShowDocDropdown(!showDocDropdown); setShowTemplateDropdown(false) }}
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
                    {sourceDocs.length > 0 ? (
                      sourceDocs.map((doc) => (
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
                      <div className="px-4 py-3 text-sm text-slate-500 text-center">{tr('暂无源文档', 'No source documents', 'ソース文書がありません')}</div>
                    )}
                  </div>
                )}
              </div>

              <div className="relative min-w-0 flex-1" ref={templateDropdownRef}>
                <button
                  onClick={() => { setShowTemplateDropdown(!showTemplateDropdown); setShowDocDropdown(false) }}
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
                    {templateDocs.length > 0 ? (
                      templateDocs.map((doc) => (
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
                      <div className="px-4 py-3 text-sm text-slate-500 text-center">{tr('暂无模板', 'No templates', 'テンプレートがありません')}</div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button onClick={handleNewChat} className="btn-secondary px-3 py-1.5 text-xs">
                <Plus className="w-3 h-3" />
                {tr('新建对话', 'New Chat', '新しい会話')}
              </button>
              <button
                onClick={openEmailModal}
                className="btn-secondary px-3 py-1.5 text-xs"
                title={tr('发送所选文档到邮箱', 'Send selected document by email', '選択文書をメール送信')}
              >
                <Mail className="w-3 h-3" />
                {tr('邮件发送', 'Send Email', 'メール送信')}
              </button>
              <button
                onClick={togglePanel}
                className={`p-2 rounded-lg transition-colors ${isPanelOpen ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
                title={tr('文档预览', 'Document Preview', '文書プレビュー')}
              >
                <Eye className="w-4 h-4" />
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
              <p className="text-slate-600">{tr(`我是${assistantName}，你的智能文档助手`, `I am ${assistantName}, your smart document assistant`, `私は${assistantName}、あなたのスマート文書アシスタントです`)}</p>
              <p className="text-sm text-slate-500 mt-2">{tr('你可以打字提问，也可以点击麦克风按钮，把语音转成文字后与我交互。', 'You can type your questions or tap the microphone button to convert speech to text and chat with me.', '文字入力でも、マイクボタンで音声をテキスト化して会話することもできます。')}</p>
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
                        {message.content}
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
                <ActionCard action={message.action} onConfirm={handleConfirmAction} onCancel={handleCancelAction} />
                {message.action.action_type === 'completed' && message.action.result?.preview && (
                  <div className="mt-2 flex">
                    <button
                      onClick={() => openPreview(message.action!)}
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

      {showEmailModal && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-6 backdrop-blur-sm">
          <div className={`w-full max-w-xl rounded-xl border shadow-2xl ${
            isDarkMode ? 'border-slate-600 bg-slate-800' : 'border-slate-200 bg-white'
          }`}>
            <div className={`flex items-center justify-between border-b px-6 py-4 ${
              isDarkMode ? 'border-slate-600' : 'border-slate-200'
            }`}>
              <div>
                <h3 className={`text-lg font-semibold ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>
                  {tr('发送邮件', 'Send Email', 'メール送信')}
                </h3>
                <p className={`mt-1 text-sm ${isDarkMode ? 'text-slate-300' : 'text-slate-600'}`}>
                  {selectedEmailDocument?.original_filename || tr('未选择文档', 'No document selected', '文書未選択')}
                </p>
              </div>
              <button
                onClick={() => setShowEmailModal(false)}
                className={`rounded-lg p-2 transition-colors ${
                  isDarkMode
                    ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                    : 'text-slate-400 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4 p-6">
              <div>
                <label className={`mb-1 block text-sm font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
                  {tr('收件人邮箱', 'Recipient Email', '宛先メール')}
                </label>
                <input
                  type="email"
                  value={emailForm.to_email}
                  onChange={(e) => setEmailForm((prev) => ({ ...prev, to_email: e.target.value }))}
                  className="input w-full"
                  placeholder="example@qq.com"
                />
              </div>

              <div>
                <label className={`mb-1 block text-sm font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
                  {tr('邮件主题', 'Email Subject', 'メール件名')}
                </label>
                <input
                  type="text"
                  value={emailForm.subject}
                  onChange={(e) => setEmailForm((prev) => ({ ...prev, subject: e.target.value }))}
                  className="input w-full"
                />
              </div>

              <div>
                <label className={`mb-1 block text-sm font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
                  {tr('邮件正文', 'Email Body', 'メール本文')}
                </label>
                <textarea
                  value={emailForm.body}
                  onChange={(e) => setEmailForm((prev) => ({ ...prev, body: e.target.value }))}
                  className="input min-h-32 w-full resize-y"
                />
              </div>

              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowEmailModal(false)}
                  className="btn-secondary px-4 py-2"
                  disabled={isSendingEmail}
                >
                  {tr('取消', 'Cancel', 'キャンセル')}
                </button>
                <button
                  onClick={handleSendEmail}
                  className="btn-primary px-4 py-2 disabled:opacity-50"
                  disabled={isSendingEmail}
                >
                  {isSendingEmail ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                  {tr('发送', 'Send', '送信')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {previewState && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-6 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="doc-op-preview-title" className={`max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-xl border shadow-2xl ${
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
              <button onClick={() => setPreviewState(null)} aria-label={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} className={`rounded-lg p-2 transition-colors ${
                isDarkMode
                  ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                  : 'text-slate-400 hover:bg-slate-100 hover:text-slate-900'
              }`}>
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(85vh-88px)] space-y-4 overflow-y-auto p-6 scrollbar-thin">
              {previewState.items.map((item, index) => (
                <div key={`${item.op}-${item.paragraph_index}-${index}`} className={`rounded-xl border p-4 ${
                  isDarkMode ? 'border-slate-600 bg-slate-700/80' : 'border-slate-200 bg-slate-50'
                }`}>
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full bg-primary-500/20 px-2.5 py-1 text-primary-700">{item.op}</span>
                    <span className={`rounded-full px-2.5 py-1 ${isDarkMode ? 'bg-slate-600 text-slate-300' : 'bg-white text-slate-600'}`}>段落 {item.paragraph_index >= 0 ? item.paragraph_index : '-'}</span>
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

      <div className={`p-3 sm:p-4 border-t ${isDarkMode ? 'border-slate-700' : 'border-slate-200'}`}>
        <div className="flex gap-2 sm:gap-3">
          <button
            type="button"
            onClick={handleSpeechToggle}
            disabled={isLoading || (!speechSupported && !isListening)}
            aria-label={
              isListening
                ? tr(`停止与${assistantName}的语音输入`, `Stop voice input for ${assistantName}`, `${assistantName} への音声入力を停止`)
                : tr(`开始与${assistantName}语音交互`, `Start voice input for ${assistantName}`, `${assistantName} への音声入力を開始`)
            }
            title={
              isListening
                ? tr('点击结束录音', 'Click to stop recording', 'クリックして録音を停止')
                : tr('点击开始语音输入', 'Click to start voice input', 'クリックして音声入力を開始')
            }
            className={`shrink-0 rounded-xl border px-3 py-2 transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
              isListening
                ? 'border-red-300 bg-red-50 text-red-600 shadow-sm'
                : isDarkMode
                  ? 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700'
                  : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span className="flex items-center gap-2">
              <Mic className={`w-4 h-4 ${isListening ? 'animate-pulse' : ''}`} />
              <span className="hidden sm:inline">{isListening ? tr('录音中', 'Listening', '録音中') : tr('语音输入', 'Voice', '音声入力')}</span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => setWebSearchEnabled((prev) => !prev)}
            disabled={isLoading}
            aria-pressed={webSearchEnabled}
            aria-label={webSearchEnabled ? tr('关闭联网搜索', 'Disable web search', 'Web検索をオフ') : tr('开启联网搜索', 'Enable web search', 'Web検索をオン')}
            title={webSearchEnabled ? tr('联网搜索已开启，点击关闭', 'Web search is on. Click to turn off.', 'Web検索はオンです。クリックでオフ') : tr('联网搜索已关闭，点击开启', 'Web search is off. Click to turn on.', 'Web検索はオフです。クリックでオン')}
            className={`shrink-0 rounded-xl border px-3 py-2 transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
              webSearchEnabled
                ? isDarkMode
                  ? 'border-blue-500/60 bg-blue-500/20 text-blue-300 shadow-sm shadow-blue-500/10'
                  : 'border-blue-300 bg-blue-50 text-blue-600 shadow-sm'
                : isDarkMode
                  ? 'border-slate-700 bg-slate-900 text-slate-500 hover:bg-slate-800'
                  : 'border-slate-200 bg-slate-100 text-slate-400 hover:bg-slate-200'
            }`}
          >
            <span className="flex items-center gap-2">
              <Globe className="w-4 h-4" />
              <span className="hidden sm:inline">{tr('联网搜索', 'Web Search', 'Web検索')}</span>
            </span>
          </button>

          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={pendingAction
              ? tr('操作待确认，请先点击上方卡片完成确认。', 'Action pending confirmation, please confirm above first.', '操作は確認待ちです。先に上のカードで確認してください。')
              : tr(`对${assistantName}说点什么，或输入你的问题和指令...`, `Say something to ${assistantName}, or type your question and instruction...`, `${assistantName} に話しかけるか、質問や指示を入力してください...`)}
            className="input flex-1 min-w-0"
            disabled={isLoading}
          />
          {isStreaming ? (
            <button onClick={handleStop} className={`btn-secondary px-4 py-2 ${
              isDarkMode
                ? 'text-red-400 border-red-500/50 hover:bg-red-900/30'
                : 'text-red-500 border-red-300 hover:bg-red-50'
            }`}>
              <Square className="w-5 h-5" />
              {tr('停止', 'Stop', '停止')}
            </button>
          ) : (
            <button onClick={() => handleSend()} disabled={isLoading || isListening || (!inputValue.trim() && !pendingAction)} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed">
              {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
            </button>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className={isListening ? 'text-red-500' : 'text-slate-500'}>
            {isListening
              ? tr(`${assistantName} 正在听，请开始说话...`, `${assistantName} is listening, please start speaking...`, `${assistantName} が聞いています。話し始めてください...`)
              : speechSupported
                ? tr(`点击麦克风按钮即可与${assistantName}进行语音转文字交互。`, `Click the microphone button to talk with ${assistantName} using speech-to-text.`, `マイクボタンをクリックすると、${assistantName} と音声テキスト変換で会話できます。`)
                : tr('当前浏览器不支持语音输入，推荐使用 Chrome 或 Edge。', 'This browser does not support voice input. Please use Chrome or Edge.', 'このブラウザは音声入力に対応していません。Chrome または Edge を使用してください。')}
          </span>
          <span className={webSearchEnabled ? 'text-blue-500' : 'text-slate-400'}>
            {webSearchEnabled
              ? tr('联网搜索已开启：会优先检索官网/公开网页并给出来源。', 'Web search is on: official/public pages will be searched with sources.', 'Web検索オン：公式/公開ページを検索し、出典を示します。')
              : tr('联网搜索已关闭：仅使用本地文档和已有知识回答。', 'Web search is off: answers use only local documents and existing knowledge.', 'Web検索オフ：ローカル文書と既存知識のみで回答します。')}
          </span>
        </div>
        {/* 快捷提示 */}
        <div className="flex gap-2 mt-3 overflow-x-auto pb-1 scrollbar-thin">
          <button onClick={() => setInputValue(tr('帮我分析这些文档', 'Help me analyze these documents', 'これらの文書を分析してください'))} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('分析文档', 'Analyze docs', '文書分析')}
          </button>
          <button onClick={() => setInputValue(tr('填写汇总表', 'Fill summary table', 'まとめ表を記入'))} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('填写表格', 'Fill table', '表記入')}
          </button>
          <button onClick={() => setInputValue(tr('查询关键信息', 'Query key information', '重要情報を検索'))} className={`px-3 py-1.5 text-xs border rounded-full whitespace-nowrap transition-colors ${
            isDarkMode
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
              : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
          }`}>
            {tr('查询信息', 'Query info', '情報検索')}
          </button>
        </div>
      </div>
      </div>

      {/* 拖动手柄 + 右侧文档预览面板（移动端隐藏） */}
      {!isMobile && (
        <>
          {isPanelOpen && (
            <div
              onMouseDown={(e) => handleDragStart(e.clientX)}
              onTouchStart={(e) => handleDragStart(e.touches[0].clientX)}
              className="shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-primary-100/50 transition-colors"
              style={{ width: HANDLE_WIDTH }}
              title="拖动调整宽度"
            >
              <div className="w-1 h-8 rounded-full bg-slate-300 group-hover:bg-primary-400 transition-colors" />
            </div>
          )}
          {/* 拖动时的透明遮罩，防止 iframe 抢夺事件 */}
          {isDragging && (
            <div className="fixed inset-0 z-30 cursor-col-resize" />
          )}
          <div
            className={`shrink-0 overflow-hidden ${isDragging ? '' : 'transition-[width] duration-300 ease-in-out'}`}
            style={{ width: isPanelOpen ? previewWidth : 0 }}
          >
            <DocumentPreviewPanel
              previewFiles={previewFiles}
              currentFile={previewCurrentFile}
              onFileSelect={setPreviewCurrentFile}
              isLoading={previewIsLoading}
            />
          </div>
        </>
      )}

      {/* 手机端全屏文档预览 */}
      {isMobile && showMobilePreview && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={() => setShowMobilePreview(false)} />
          <div className="fixed inset-0 z-50 flex flex-col animate-fade-in">
            <div className={`flex items-center justify-end px-3 py-2 backdrop-blur-sm border-b ${isDarkMode ? 'bg-slate-800/90 border-slate-700' : 'bg-white/90 border-slate-200'}`}>
              <button onClick={() => setShowMobilePreview(false)} className={`p-1.5 rounded-lg ${isDarkMode ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}>
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <DocumentPreviewPanel
                previewFiles={previewFiles}
                currentFile={previewCurrentFile}
                onFileSelect={setPreviewCurrentFile}
                isLoading={previewIsLoading}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

