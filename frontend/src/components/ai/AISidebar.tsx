/**
 * AI 侧边栏组件
 *
 * 基于 DocumentOperation.tsx 改造，作为右边栏集成到 DocumentWorkspace
 * 功能：对话、流式输出、操作卡片、思考过程展示
 */

import { useState, useEffect, useRef } from 'react'
import { Send, Loader2, X, Square } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../../services/api'
import { getAuthUser } from '../../services/auth'
import { useChatStore } from '../../stores/chatStore'
import ActionCard, { ActionData } from '../ActionCard'
import AgentThinkingPanel from '../AgentThinkingPanel'
import TaskStatsBadge from '../TaskStatsBadge'
import agentStreamService, { AgentStep, TaskStats } from '../../services/agentStreamService'
import { useI18n } from '../../hooks/useI18n'
import { useAgentStream } from '../../hooks/useAgentStream'
import { getTheme } from '../../services/theme'
import { getStoredLanguage } from '../../services/i18n'

// 自定义 Markdown 链接组件：对 API 下载链接使用带 token 的请求
function DownloadLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const isDownloadLink = href && (
    href.includes('/documents/') && href.includes('/download')
  )

  const normalizeDownloadHref = (url: string): string => {
    if (!url) return url
    try {
      const urlObj = new URL(url)
      return urlObj.pathname
    } catch {}
    const wrongDomainMatch = url.match(/^https?:\/\/api(\/.*)$/i)
    if (wrongDomainMatch) {
      return wrongDomainMatch[1]
    }
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
        const rfc5987Match = contentDisposition.match(/filename\*=(?:UTF-8'')(.+)/i)
        if (rfc5987Match) {
          filename = decodeURIComponent(rfc5987Match[1])
        } else {
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

interface Message {
  role: 'user' | 'assistant'
  content: string
  action?: ActionData
  timestamp: number
  steps?: AgentStep[]
  isStreaming?: boolean
  task_stats?: TaskStats
}

interface AISidebarProps {
  /** 当前打开的文档ID */
  documentId?: string
  /** 当前打开的文档名称 */
  documentName?: string
  /** 获取选中文本的回调 */
  onGetSelectedText?: () => Promise<string | null>
}

export default function AISidebar({ documentId, documentName, onGetSelectedText }: AISidebarProps) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

  const {
    sessions,
    activeSessionId,
    createSession,
    setActiveSession,
    deleteSession,
    updateSessionFiles,
    updateMessage,
    loadSessions,
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

  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [pendingAction, setPendingAction] = useState<ActionData | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)

  const {
    isStreaming,
    streamingContent,
    currentSteps,
    streamingStats,
    streamingDuration,
    startStream,
    stopStream,
    reconnectToTask,
  } = useAgentStream({
    sessionId: activeSessionId,
    onMessageComplete: (content, steps, stats) => {
      if (content) {
        setLocalMessages(prev => [...prev, {
          role: 'assistant',
          content,
          timestamp: Date.now(),
          steps,
          task_stats: stats || undefined,
        }])
      }
    },
  })

  // isLoading: true while waiting for first content, false once streaming starts
  useEffect(() => {
    if (isStreaming) setIsLoading(false)
  }, [isStreaming])

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages, streamingContent, currentSteps])

  // 加载会话消息
  useEffect(() => {
    if (activeSessionId) {
      const sessionId = activeSessionId
      let cancelled = false

      const hasActiveConn = agentStreamService.hasActiveConnection(sessionId)

      if (!hasActiveConn) {
        setIsLoading(false)
      }

      const { loadSessionMessages } = useChatStore.getState()
      const runningTaskId = agentStreamService.getRunningTaskId(sessionId)

      loadSessionMessages(sessionId, true).then(() => {
        if (cancelled) return
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
          // 自动重连正在运行的任务
          if (runningTaskId && !agentStreamService.hasActiveConnection(sessionId)) {
            reconnectToTask(runningTaskId)
          }
        }
      })

      return () => { cancelled = true }
    } else {
      setLocalMessages([])
      setPendingAction(null)
    }
  }, [activeSessionId])

  // 发送消息
  const handleSend = async (actionConfirmed = false) => {
    const userMessage = inputValue.trim()
    if (!userMessage && !actionConfirmed) return

    if (!actionConfirmed && pendingAction) {
      toast.error(tr('请先处理待确认的操作', 'Please handle the pending action first', '保留中の操作を先に処理してください'))
      return
    }

    // 检查用户是否已选择模型
    const user = getAuthUser()
    if (!user?.selected_model) {
      toast.error(tr('请先在左下角选择一个模型', 'Please select a model first', 'まず左下でモデルを選択してください'))
      return
    }

    let currentSessionId = activeSessionId
    const isNewSession = !currentSessionId
    if (!currentSessionId) {
      const sessionName = documentName || tr('新对话', 'New Chat', '新しい会話')
      currentSessionId = await createSession(
        documentId || null,
        sessionName,
        documentId ? [documentId] : [],
        null
      )
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

    if (isFirstMessage) {
      api.post('/agent/generate-title', { message: userMessage })
        .then(async (res) => {
          const newTitle = res.data.title || tr('新对话', 'New Chat', '新しい会話')
          await api.put(`/conversations/${currentSessionId}`, { title: newTitle })
          useChatStore.getState().loadSessions()
        })
        .catch((e) => console.error('Failed to generate title:', e))
    }

    startStream({
      message: userMessage,
      file_ids: documentId ? [documentId] : [],
      conversation_id: currentSessionId,
    })
  }

  // 停止生成
  const handleStop = async () => {
    const contentToSave = streamingContent
    const stepsToSave = currentSteps.length > 0 ? [...currentSteps] : []
    if (contentToSave) {
      setLocalMessages(prev => [...prev, { role: 'assistant', content: contentToSave, timestamp: Date.now() }])
    }
    if (stepsToSave.length > 0) {
      setLocalMessages(prev => [...prev, { role: 'assistant', content: '', timestamp: Date.now(), steps: stepsToSave }])
    }
    await stopStream()
    setIsLoading(false)
    toast(tr('已停止生成', 'Generation stopped', '生成を停止しました'), { icon: '⏹️' })
  }

  // 确认操作
  const handleConfirmAction = async () => {
    if (!pendingAction) return
    // TODO: 实现确认操作逻辑
    setPendingAction(null)
  }

  // 键盘事件
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 插入快捷提示
  const insertQuickPrompt = (text: string) => {
    setInputValue(text)
  }

  // 滚动条样式
  const scrollbarStyle = `
    .ai-sidebar-scroll::-webkit-scrollbar {
      width: 6px;
    }
    .ai-sidebar-scroll::-webkit-scrollbar-track {
      background: transparent;
    }
    .ai-sidebar-scroll::-webkit-scrollbar-thumb {
      background-color: ${isDarkMode ? 'rgba(148, 163, 184, 0.3)' : 'rgba(148, 163, 184, 0.5)'};
      border-radius: 3px;
    }
    .ai-sidebar-scroll::-webkit-scrollbar-thumb:hover {
      background-color: ${isDarkMode ? 'rgba(148, 163, 184, 0.5)' : 'rgba(148, 163, 184, 0.7)'};
    }
  `

  return (
    <>
      <style>{scrollbarStyle}</style>
      <div className={`flex flex-col h-full ${isDarkMode ? 'bg-slate-900' : 'bg-white'}`}>
      {/* 头部 */}
      <div className={`flex items-center justify-between px-4 py-3 border-b ${
        isDarkMode ? 'border-slate-700' : 'border-slate-200'
      }`}>
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 bg-primary-500 rounded-md flex items-center justify-center">
            <span className="text-white text-xs font-bold">AI</span>
          </div>
          <span className={`text-sm font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
            {tr('智能助手', 'AI Assistant', 'AIアシスタント')}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`p-1.5 rounded-lg transition-colors ${
              isDarkMode ? 'text-slate-400 hover:bg-slate-800' : 'text-slate-500 hover:bg-slate-100'
            }`}
            title={tr('历史会话', 'History', '履歴')}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
          <button
            onClick={() => {
              setActiveSession(null)
              setLocalMessages([])
              setPendingAction(null)
            }}
            className={`p-1.5 rounded-lg transition-colors ${
              isDarkMode ? 'text-slate-400 hover:bg-slate-800' : 'text-slate-500 hover:bg-slate-100'
            }`}
            title={tr('新对话', 'New Chat', '新しい会話')}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
        </div>
      </div>

      {/* 历史会话列表 */}
      {showHistory && (
        <div className={`border-b max-h-48 overflow-y-auto ai-sidebar-scroll ${
          isDarkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'
        }`}>
          {sessions.length === 0 ? (
            <div className={`p-4 text-center text-sm ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
              {tr('暂无历史会话', 'No history', '履歴なし')}
            </div>
          ) : (
            sessions.map(session => (
              <div
                key={session.id}
                onClick={() => {
                  setActiveSession(session.id)
                  setShowHistory(false)
                }}
                className={`flex items-center justify-between px-4 py-2.5 cursor-pointer transition-colors ${
                  activeSessionId === session.id
                    ? isDarkMode ? 'bg-slate-700' : 'bg-primary-50'
                    : isDarkMode ? 'hover:bg-slate-700/50' : 'hover:bg-slate-100'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className={`text-sm truncate ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
                    {session.documentName || tr('新对话', 'New Chat', '新しい会話')}
                  </div>
                  <div className={`text-xs ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                    {session.messages.length} {tr('条消息', 'messages', '件のメッセージ')}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteSession(session.id)
                  }}
                  className={`p-1 rounded transition-colors ${
                    isDarkMode ? 'text-slate-500 hover:text-red-400' : 'text-slate-400 hover:text-red-500'
                  }`}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* 消息列表 */}
      <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4 ai-sidebar-scroll">
        {localMessages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-3 ${
              isDarkMode ? 'bg-slate-800' : 'bg-primary-50'
            }`}>
              <span className="text-lg">🤖</span>
            </div>
            <p className={`text-sm ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
              {tr('有什么可以帮你的？', 'How can I help?', '何かお手伝いできますか？')}
            </p>
          </div>
        )}

        {localMessages.map((msg, index) => (
          <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
              {/* 消息内容 */}
              {msg.content && (
                <div className={`p-3 rounded-2xl ${
                  msg.role === 'user'
                    ? 'bg-primary-500 text-white'
                    : isDarkMode
                      ? 'bg-slate-800 text-slate-200'
                      : 'bg-slate-100 text-slate-700'
                }`}>
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              {/* 操作卡片 */}
              {msg.action && (
                <ActionCard
                  action={msg.action}
                  onConfirm={handleConfirmAction}
                  onCancel={() => setPendingAction(null)}
                />
              )}

              {/* 思考过程 */}
              {msg.steps && msg.steps.length > 0 && (
                <AgentThinkingPanel steps={msg.steps} isActive={false} />
              )}

              {/* 任务统计 */}
              {msg.task_stats && (
                <div className="mt-2">
                  <TaskStatsBadge stats={msg.task_stats} />
                </div>
              )}

              {/* 时间戳 */}
              <div className={`text-xs mt-1 ${msg.role === 'user' ? 'text-right' : 'text-left'} ${
                isDarkMode ? 'text-slate-600' : 'text-slate-400'
              }`}>
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}

        {/* 流式输出 */}
        {isStreaming && streamingContent && (
          <div className="flex justify-start">
            <div className={`max-w-[85%] p-3 rounded-2xl ${
              isDarkMode ? 'bg-slate-800 text-slate-200' : 'bg-slate-100 text-slate-700'
            }`}>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {streamingContent}
                </ReactMarkdown>
              </div>
              <span className={`text-xs mt-2 block ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                {new Date().toLocaleTimeString()}
              </span>
            </div>
          </div>
        )}

        {/* 实时统计 */}
        {isStreaming && (
          <div className="flex justify-start">
            <TaskStatsBadge
              stats={streamingStats || { duration_ms: 0, total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, cached_tokens: 0, reasoning_tokens: 0, llm_calls: 0, iterations: 0 }}
              isLive={true}
              liveDuration={streamingDuration}
            />
          </div>
        )}

        {/* 加载指示器 */}
        {isLoading && !isStreaming && (
          <div className="flex justify-start">
            <div className={`p-4 rounded-2xl ${isDarkMode ? 'bg-slate-800/80' : 'bg-slate-50'}`}>
              <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className={`p-3 border-t ${isDarkMode ? 'border-slate-700' : 'border-slate-200'}`}>
        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={pendingAction
              ? tr('操作待确认，请先点击上方卡片完成确认。', 'Action pending confirmation.', '操作は確認待ちです。')
              : tr('输入你的问题或指令...', 'Enter your question...', '質問を入力...')
            }
            className={`flex-1 px-3 py-2 text-sm rounded-lg border outline-none transition-colors ${
              isDarkMode
                ? 'bg-slate-800 border-slate-600 text-slate-200 placeholder-slate-500 focus:border-primary-500'
                : 'bg-white border-slate-300 text-slate-700 placeholder-slate-400 focus:border-primary-500'
            }`}
            disabled={isLoading}
          />
          {isStreaming ? (
            <button
              onClick={handleStop}
              title={tr('停止生成', 'Stop generation', '生成を停止')}
              className={`px-3 py-2 border rounded-lg transition-colors ${
                isDarkMode
                  ? 'text-red-400 border-red-500/50 hover:bg-red-900/30'
                  : 'text-red-500 border-red-300 hover:bg-red-50'
              }`}
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={() => handleSend()}
              title={tr('发送', 'Send', '送信')}
              disabled={isLoading || (!inputValue.trim() && !pendingAction)}
              className="px-3 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          )}
        </div>

        {/* 快捷提示 */}
        <div className="flex gap-1.5 mt-2 overflow-x-auto ai-sidebar-scroll">
          <button
            onClick={() => insertQuickPrompt(tr('帮我分析这些文档', 'Analyze these documents', 'これらの文書を分析'))}
            className={`px-2.5 py-1 text-xs border rounded-full whitespace-nowrap transition-colors ${
              isDarkMode
                ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
                : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
            }`}
          >
            {tr('分析文档', 'Analyze', '分析')}
          </button>
          <button
            onClick={() => insertQuickPrompt(tr('填写汇总表', 'Fill table', '表記入'))}
            className={`px-2.5 py-1 text-xs border rounded-full whitespace-nowrap transition-colors ${
              isDarkMode
                ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
                : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
            }`}
          >
            {tr('填写表格', 'Fill table', '表記入')}
          </button>
          <button
            onClick={() => insertQuickPrompt(tr('查询关键信息', 'Query info', '情報検索'))}
            className={`px-2.5 py-1 text-xs border rounded-full whitespace-nowrap transition-colors ${
              isDarkMode
                ? 'bg-slate-800 hover:bg-slate-700 border-slate-600 text-slate-300'
                : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600'
            }`}
          >
            {tr('查询信息', 'Query', '検索')}
          </button>
        </div>
      </div>
    </div>
    </>
  )
}
