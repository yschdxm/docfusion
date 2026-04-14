import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, Plus, Check, X, Square, Eye } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'
import AgentThinkingPanel from '../components/AgentThinkingPanel'
import agentStreamService, { AgentStep } from '../services/agentStreamService'
import { useDocumentPreview, getFileType } from '../hooks/useDocumentPreview'
import type { PreviewFile } from '../hooks/useDocumentPreview'
import DocumentPreviewPanel from '../components/DocumentPreviewPanel'

interface Message {
  role: 'user' | 'assistant'
  content: string
  action?: ActionData
  timestamp: number
  steps?: AgentStep[]
  isStreaming?: boolean
}

export default function DocumentOperation() {
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
    setMinimized
  } = useChatStore()

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showDocDropdown, setShowDocDropdown] = useState(false)
  const [showTemplateDropdown, setShowTemplateDropdown] = useState(false)
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [pendingAction, setPendingAction] = useState<ActionData | null>(null)
  const [currentSteps, setCurrentSteps] = useState<AgentStep[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const streamingContentRef = useRef('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const currentConnectionRef = useRef<string | null>(null)  // 当前活跃的 SSE connectionId
  const currentConnectionSessionRef = useRef<string | null>(null)  // 当前连接对应的 sessionId
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)

  // 文档预览面板
  const {
    isPanelOpen,
    togglePanel,
    previewFiles,
    currentFile: previewCurrentFile,
    setCurrentFile: setPreviewCurrentFile,
    addOperatedFile,
    clearPreview,
    isLoading: previewIsLoading,
  } = useDocumentPreview()

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')

  useEffect(() => {
    fetchDocuments()
    loadSessions()
    setMinimized(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 组件卸载时断开 SSE 连接（但不取消后端任务）
  useEffect(() => {
    return () => {
      if (currentConnectionSessionRef.current) {
        agentStreamService.cancelSession(currentConnectionSessionRef.current)
      }
    }
  }, [])

  // 恢复会话时加载消息和选择状态
  useEffect(() => {
    if (activeSessionId) {
      const sessionId = activeSessionId  // 捕获当前值

      // 清空上一个会话的流式状态
      setStreamingContent('')
      streamingContentRef.current = ''
      setCurrentSteps([])
      setIsStreaming(false)
      setIsLoading(false)

      const { loadSessionMessages } = useChatStore.getState()
      const runningTaskId = agentStreamService.getRunningTaskId(sessionId)

      loadSessionMessages(sessionId, true).then(() => {
        // 异步竞态保护：如果 activeSessionId 已变化，丢弃结果
        if (useChatStore.getState().activeSessionId !== sessionId) return
        const updatedSession = useChatStore.getState().sessions.find(s => s.id === sessionId)
        if (updatedSession) {
          // 如果有运行中的任务，不要用 DB 数据覆盖 localMessages（流式回调会持续更新）
          // 仅在 localMessages 为空时才从 DB 加载
          if (!runningTaskId || localMessages.length === 0) {
            const loadedMessages = updatedSession.messages.map(m => ({
              role: m.role,
              content: m.content,
              action: m.action_data,
              timestamp: m.timestamp,
              steps: m.steps
            }))
            setLocalMessages(loadedMessages)
          }

          if (updatedSession.fileIds && updatedSession.fileIds.length > 0) {
            setSelectedDocIds([...updatedSession.fileIds])
          }
          if (updatedSession.templateId) {
            setSelectedTemplateId(updatedSession.templateId)
          }

          // 检查该 session 是否有正在运行的任务，自动重连
          if (runningTaskId && !agentStreamService.hasActiveConnection(sessionId)) {
            console.log(`[DocumentOperation] 检测到运行中的任务: ${runningTaskId}，自动重连`)
            reconnectToTask(runningTaskId, updatedSession)
          }
        }
      })
    } else {
      setLocalMessages([])
      setPendingAction(null)
    }
  }, [activeSessionId])

  // SSE 回调工厂 — 所有流式连接共用同一套 UI 回调，无持久化逻辑（后端统一保存）
  const createStreamCallbacks = useCallback((
    sessionId: string,
    latestStepsRef: { current: AgentStep[] },
  ) => {
    const onEvent = (event: any, steps: AgentStep[]) => {
      if (currentConnectionSessionRef.current !== sessionId) return

      if (event.event_type === 'assistant_message') {
        const message = event.data.message || ''
        if (message) {
          if (event.data.agent_name) return // 子Agent消息：后端统一保存
          const messagesToAdd: Message[] = []
          if (streamingContentRef.current) {
            messagesToAdd.push({ role: 'assistant', content: streamingContentRef.current, timestamp: Date.now() })
          }
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
          'ReplaceTextTool', 'RewriteParagraphTool', 'InsertAfterTool',
          'HeadingPromoteTool', 'ListFormatTool', 'ParagraphSplitTool',
          'SetTextStyleTool', 'ConvertTool'
        ]
        const isEditOrFill = editTools.includes(toolName) || toolName === 'fill_table'
        if (isEditOrFill && result && result.download_url) {
          const filename = result.output_filename || result.output_file || 'output'
          const file: PreviewFile = {
            id: result.output_file_id || filename,
            name: filename,
            fileUrl: `${window.location.origin}${result.download_url}`,
            fileType: getFileType(filename),
            source: 'operated',
          }
          addOperatedFile(file)
        }
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

      // UI 即时显示 completed 的结果（后端已持久化到 DB，这里不做任何 API 调用）
      if (result.message || result.download_url || latestStepsRef.current.length > 0) {
        const aiMsg: Message = {
          role: 'assistant',
          content: result.message || '',
          timestamp: Date.now(),
          steps: latestStepsRef.current.length > 0 ? [...latestStepsRef.current] : undefined,
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
      currentConnectionRef.current = null; currentConnectionSessionRef.current = null
      if (error?.toString().includes('abort') || error?.toString().includes('AbortError')) return
      toast.error(error)
    }

    return { onEvent, onComplete, onError }
  }, [addOperatedFile])

  // 重连到正在运行的任务（页面刷新/切换后恢复）
  const reconnectToTask = useCallback((taskId: string, session: any) => {
    setIsStreaming(true)
    setIsLoading(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''
    currentConnectionSessionRef.current = session.id

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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages, currentSteps])

  // 监听 localMessages 变化
  useEffect(() => {
    // localMessages updated
  }, [localMessages])

  // 断开当前连接（切换会话/新建/删除时，断开SSE，但后端任务继续运行）
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

  // 新建对话
  const handleNewChat = async () => {
    disconnectCurrentConnection()
    setSelectedDocIds([])
    setSelectedTemplateId(null)
    clearPreview()

    const sessionId = await createSession(null, '新对话', [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingAction(null)
  }

  // 切换会话
  const handleSwitchSession = (sessionId: string) => {
    disconnectCurrentConnection()
    setActiveSession(sessionId)
    setShowHistory(false)
    setPendingAction(null)
    clearPreview()
  }

  // 删除会话
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

  // 处理文档选择
  const handleDocSelect = (docId: string) => {
    setSelectedDocIds(prev => {
      const next = prev.includes(docId)
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
      // 预览最后一个选中的文档
      if (next.length > 0) {
        const lastDocId = next[next.length - 1]
        const doc = documents.find(d => d.id === lastDocId)
        if (doc) previewDocument(doc)
      }
      return next
    })
  }

  // 处理模板选择
  const handleTemplateSelect = (docId: string) => {
    setSelectedTemplateId(prev => prev === docId ? null : docId)
    setShowTemplateDropdown(false)
    // 预览选中的模板
    if (docId) {
      const doc = templateDocs.find(d => d.id === docId)
      if (doc) previewDocument(doc)
    }
  }

  // 预览指定文档
  const previewDocument = useCallback((doc: { id: string; original_filename: string; file_type: string }) => {
    const file: PreviewFile = {
      id: doc.id,
      name: doc.original_filename,
      fileUrl: `${window.location.origin}/api/v1/documents/${doc.id}/download`,
      fileType: doc.file_type || getFileType(doc.original_filename),
      source: 'selected',
    }
    addOperatedFile(file)
  }, [addOperatedFile])

  // 判断任务类型
  const detectTaskType = (message: string): 'fill_table' | 'query' | 'auto' => {
    const lowerMsg = message.toLowerCase()
    if (lowerMsg.includes('填表') || lowerMsg.includes('填写') || lowerMsg.includes('fill')) {
      return 'fill_table'
    }
    if (lowerMsg.includes('查询') || lowerMsg.includes('查找') || lowerMsg.includes('search') || lowerMsg.includes('query')) {
      return 'query'
    }
    return 'auto'
  }

  // 发送消息 - 使用流式API（后端统一持久化）
  const handleSend = async (actionConfirmed: boolean = false) => {
    const userMessage = inputValue.trim()
    if (!userMessage) return

    if (!actionConfirmed && pendingAction) {
      toast.error('请先处理待确认的操作')
      return
    }

    const taskType = detectTaskType(userMessage)

    let currentSessionId = activeSessionId
    const isNewSession = !currentSessionId
    if (!currentSessionId) {
      const firstDoc = documents.find(d => d.id === selectedDocIds[0] || d.id === selectedTemplateId)
      const docCount = selectedDocIds.length + (selectedTemplateId ? 1 : 0)
      const sessionName = docCount === 0
        ? '通用对话'
        : docCount === 1
          ? firstDoc?.original_filename || '新对话'
          : `${firstDoc?.original_filename || '文档'}等${docCount}个文件`
      currentSessionId = await createSession(selectedDocIds[0] || selectedTemplateId || null, sessionName, selectedDocIds, selectedTemplateId)
    } else {
      await updateSessionFiles(currentSessionId, selectedDocIds, selectedTemplateId)
    }

    const isFirstMessage = isNewSession || (localMessages.length === 0)

    // UI 显示用户消息（后端统一持久化，前端不调用 addMessage）
    const userMsg: Message = {
      role: 'user',
      content: userMessage,
      timestamp: Date.now()
    }
    setLocalMessages(prev => [...prev, userMsg])
    setInputValue('')
    setIsLoading(true)
    setIsStreaming(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''

    // 生成标题
    if (isFirstMessage) {
      api.post('/agent/generate-title', { message: userMessage })
        .then(async (res) => {
          const newTitle = res.data.title || '通用对话'
          await api.put(`/conversations/${currentSessionId}`, { title: newTitle })
          useChatStore.getState().loadSessions()
        })
        .catch(e => console.error('Failed to generate title:', e))
    }

    // 使用工厂创建回调
    const latestStepsRef: { current: AgentStep[] } = { current: [] }
    const { onEvent, onComplete, onError } = createStreamCallbacks(currentSessionId, latestStepsRef)

    // 启动 SSE 连接
    currentConnectionSessionRef.current = currentSessionId

    const connId = agentStreamService.startStream(
      currentSessionId,
      {
        message: userMessage,
        file_ids: selectedDocIds,
        template_id: selectedTemplateId || undefined,
        conversation_id: currentSessionId,
        task_type: taskType
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
  }

  // 停止流式请求（用户主动停止，后端 cancel 端点统一保存累积状态）
  const handleStop = async () => {
    const sessionId = currentConnectionSessionRef.current
    if (!sessionId) return

    // UI 清理 — 后端 cancel 端点已保存累积的 steps 和 content
    setIsStreaming(false)
    setIsLoading(false)
    setStreamingContent('')
    streamingContentRef.current = ''
    setCurrentSteps([])

    // 彻底取消任务（后端 + 前端 SSE）
    await agentStreamService.stopTask(sessionId)
    currentConnectionRef.current = null
    currentConnectionSessionRef.current = null

    toast('已停止生成', { icon: '⏹️' })
  }

  // 确认执行操作（后端统一持久化）
  const handleConfirmAction = async () => {
    if (!pendingAction) return

    const currentPendingAction = { ...pendingAction }
    const confirmSessionId = activeSessionId!

    setLocalMessages(prev => {
      const newMessages = [...prev]
      const lastAiIndex = newMessages.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop()
      if (lastAiIndex !== undefined) {
        newMessages[lastAiIndex] = {
          ...newMessages[lastAiIndex],
          action: {
            ...pendingAction,
            action_type: 'executing',
            progress: 0
          }
        }
      }
      return newMessages
    })

    setPendingAction(null)

    // UI 显示确认消息（后端统一持久化）
    const confirmMsg: Message = {
      role: 'user',
      content: '[确认执行操作]',
      timestamp: Date.now()
    }
    setLocalMessages(prev => [...prev, confirmMsg])

    setIsLoading(true)
    setIsStreaming(true)
    setCurrentSteps([])
    setStreamingContent('')
    streamingContentRef.current = ''

    // 使用工厂创建回调
    const latestStepsRef: { current: AgentStep[] } = { current: [] }
    const { onEvent, onComplete: rawOnComplete, onError } = createStreamCallbacks(confirmSessionId, latestStepsRef)

    // 包装 onComplete，额外处理 updateMessage（confirm_fill 的 action_data 更新）
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
        toast.success('操作完成！')
      }
    }

    currentConnectionSessionRef.current = confirmSessionId

    const connId = agentStreamService.startStream(
      confirmSessionId,
      {
        message: '确认执行之前的操作',
        file_ids: selectedDocIds,
        template_id: selectedTemplateId || undefined,
        conversation_id: confirmSessionId
      },
      onEvent, onComplete, onError
    )
    currentConnectionRef.current = connId
  }

  return (
    <div className="h-[calc(100vh-2rem)] flex gap-4">
      {/* 左侧历史会话面板 */}
      <div className={`${showHistory ? 'w-64' : 'w-0'} transition-all duration-300 overflow-hidden flex flex-col glass rounded-2xl`}>
        <div className="p-4 border-b border-white/10">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary-500/20 text-primary-400 border border-primary-500/30 rounded-xl hover:bg-primary-500/30 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建对话
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {sessions.map(session => (
            <div
              key={session.id}
              onClick={() => handleSwitchSession(session.id)}
              className={`p-3 cursor-pointer hover:bg-white/5 border-b border-white/5 flex items-center justify-between group transition-all ${
                activeSessionId === session.id ? 'bg-primary-500/10 border-l-4 border-l-primary-500' : ''
              }`}
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <Clock className="w-4 h-4 text-slate-500 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-300 truncate">{(session as any).title || session.documentName || '新对话'}</p>
                  <p className="text-xs text-slate-500">
                    {new Date(session.updatedAt).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <button
                onClick={(e) => handleDeleteSession(session.id, e)}
                className="p-1 text-slate-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 主聊天区域 */}
      <div className="flex-1 flex flex-col glass rounded-2xl overflow-hidden">
        {/* 顶部工具栏 */}
        <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between bg-white/5">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`p-2 rounded-xl transition-colors ${showHistory ? 'bg-primary-500/20 text-primary-400' : 'hover:bg-white/10 text-slate-400'}`}
              title="历史会话"
            >
              <History className="w-5 h-5" />
            </button>

            {/* 文档选择器 */}
            <div className="relative" ref={docDropdownRef}>
              <button
                onClick={() => setShowDocDropdown(!showDocDropdown)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-colors text-sm ${
                  selectedDocIds.length > 0
                    ? 'border-blue-500/50 bg-blue-500/10 text-blue-400'
                    : 'border-white/10 hover:bg-white/5 text-slate-300'
                }`}
              >
                <FileText className="w-4 h-4" />
                <span>
                  {selectedDocIds.length === 0
                    ? '选择源文档'
                    : `已选 ${selectedDocIds.length} 个文档`}
                </span>
                <ChevronDown className={`w-4 h-4 transition-transform ${showDocDropdown ? 'rotate-180' : ''}`} />
              </button>

              {showDocDropdown && (
                <div className="absolute top-full left-0 mt-1 w-64 glass border border-white/10 rounded-xl shadow-xl z-50 max-h-64 overflow-y-auto scrollbar-thin">
                  {sourceDocs.length === 0 ? (
                    <div className="p-3 text-sm text-slate-500">暂无源文档</div>
                  ) : (
                    sourceDocs.map(doc => (
                      <label
                        key={doc.id}
                        className="flex items-center gap-2 p-3 hover:bg-white/5 cursor-pointer transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={selectedDocIds.includes(doc.id)}
                          onChange={() => handleDocSelect(doc.id)}
                          className="rounded border-white/20 bg-white/10 text-primary-500 focus:ring-primary-500"
                        />
                        <span className="text-sm text-slate-300 truncate">{doc.original_filename}</span>
                      </label>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* 模板选择器 */}
            <div className="relative" ref={templateDropdownRef}>
              <button
                onClick={() => setShowTemplateDropdown(!showTemplateDropdown)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-colors text-sm ${
                  selectedTemplateId
                    ? 'border-green-500/50 bg-green-500/10 text-green-400'
                    : 'border-white/10 hover:bg-white/5 text-slate-300'
                }`}
              >
                <Table className="w-4 h-4" />
                <span>
                  {selectedTemplateId
                    ? templateDocs.find(d => d.id === selectedTemplateId)?.original_filename || '已选模板'
                    : '选择模板'}
                </span>
                <ChevronDown className={`w-4 h-4 transition-transform ${showTemplateDropdown ? 'rotate-180' : ''}`} />
              </button>

              {showTemplateDropdown && (
                <div className="absolute top-full left-0 mt-1 w-64 glass border border-white/10 rounded-xl shadow-xl z-50 max-h-64 overflow-y-auto scrollbar-thin">
                  {templateDocs.length === 0 ? (
                    <div className="p-3 text-sm text-slate-500">暂无模板</div>
                  ) : (
                    templateDocs.map(doc => (
                      <button
                        key={doc.id}
                        onClick={() => handleTemplateSelect(doc.id)}
                        className={`w-full flex items-center gap-2 p-3 hover:bg-white/5 text-left transition-colors ${
                          selectedTemplateId === doc.id ? 'bg-primary-500/10 text-primary-400' : 'text-slate-300'
                        }`}
                      >
                        {selectedTemplateId === doc.id && <Check className="w-4 h-4" />}
                        <span className="text-sm truncate">{doc.original_filename}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* 已选文档标签 */}
            {selectedDocIds.length > 0 && (
              <div className="flex items-center gap-1">
                {selectedDocIds.slice(0, 2).map(docId => {
                  const doc = sourceDocs.find(d => d.id === docId)
                  if (!doc) return null
                  return (
                    <span key={docId} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-blue-500/20 text-blue-400 text-xs">
                      <FileText className="w-3 h-3" />
                      {doc.original_filename.slice(0, 10)}...
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDocSelect(docId)
                        }}
                        className="hover:text-blue-300"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  )
                })}
                {selectedDocIds.length > 2 && (
                  <span className="text-xs text-slate-500">+{selectedDocIds.length - 2}</span>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleNewChat}
              className="flex items-center gap-2 px-3 py-1.5 text-slate-400 hover:bg-white/10 rounded-xl transition-colors text-sm"
            >
              <Plus className="w-4 h-4" />
              <span>新建对话</span>
            </button>
            <button
              onClick={togglePanel}
              className={`p-2 rounded-xl transition-colors ${isPanelOpen ? 'bg-primary-500/20 text-primary-400' : 'hover:bg-white/10 text-slate-400'}`}
              title="文档预览"
            >
              <Eye className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
          {localMessages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-primary-500/20 to-purple-500/20 flex items-center justify-center mb-4">
                <FileText className="w-10 h-10 text-primary-400/50" />
              </div>
              <p className="text-lg font-medium text-slate-300">开始一个新的对话</p>
              <p className="text-sm mt-2 text-slate-500">选择文档或模板，然后输入您的问题</p>
              <div className="mt-6 text-xs text-slate-500 space-y-1 text-center">
                <p>提示：选择表格模板后，可以要求我帮您填写表格</p>
                <p>新功能：支持实时查看Agent思考过程</p>
              </div>
            </div>
          ) : (
            <>
              {localMessages.map((msg, index) => (
                <div key={index} className="space-y-2">
                  {/* 对于AI消息，显示步骤 - 但当前正在流式的最后一条消息不显示（避免和currentSteps重复） */}
                  {msg.role === 'assistant' && msg.steps && msg.steps.length > 0 &&
                   !(isStreaming && index === localMessages.length - 1) && (
                    <div className="flex justify-start">
                      <div className="max-w-[80%]">
                        <AgentThinkingPanel
                          steps={msg.steps}
                          isActive={false}
                        />
                      </div>
                    </div>
                  )}

                  {/* 空内容的步骤消息不渲染气泡 */}
                  {msg.content ? (
                  <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[80%] rounded-2xl p-4 ${
                      msg.role === 'user'
                        ? 'bg-primary-500/20 text-white border border-primary-500/30'
                        : 'bg-white/5 border border-white/10 text-slate-200'
                    }`}>
                      {msg.role === 'assistant' ? (
                        <div className="prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({ children, node }: any) => {
                                const hasPre = node?.children?.some(
                                  (child: any) => child.tagName === 'pre' || child.tagName === 'code' && !child.properties?.inline
                                )
                                if (hasPre) return <div className="mb-4 last:mb-0">{children}</div>
                                return <p>{children}</p>
                              },
                              code: ({ inline, children, ...props }: any) => (
                                inline ? (
                                  <code className="bg-slate-700 px-1 py-0.5 rounded text-sm" {...props}>
                                    {children}
                                  </code>
                                ) : (
                                  <pre className="bg-slate-800 p-3 rounded-lg overflow-x-auto my-2">
                                    <code className="text-sm" {...props}>{children}</code>
                                  </pre>
                                )
                              ),
                              table: ({ children }: any) => (
                                <table className="border-collapse border border-slate-600 my-2">
                                  {children}
                                </table>
                              ),
                              th: ({ children }: any) => (
                                <th className="border border-slate-600 px-2 py-1 bg-slate-700">
                                  {children}
                                </th>
                              ),
                              td: ({ children }: any) => (
                                <td className="border border-slate-600 px-2 py-1">
                                  {children}
                                </td>
                              ),
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                      )}
                      <span className={`text-xs mt-2 block ${
                        msg.role === 'user' ? 'text-primary-400/70' : 'text-slate-500'
                      }`}>
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                  ) : null}

                  {/* 显示操作卡片 */}
                  {msg.action && (
                    <div className="flex justify-start">
                      <div className="max-w-[80%]">
                        <ActionCard
                          action={msg.action}
                          onConfirm={handleConfirmAction}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {/* 当前正在进行的步骤展示 - 只在流式进行时显示，避免和历史消息的步骤重复 */}
              {isStreaming && currentSteps.length > 0 && (
                <div className="flex justify-start">
                  <div className="max-w-[80%] w-full">
                    {/* 显示步骤 - 包括 assistant_reply 类型的步骤 */}
                    {currentSteps.length > 0 && (
                      <AgentThinkingPanel
                        steps={currentSteps}
                        isActive={isStreaming}
                      />
                    )}

                  </div>
                </div>
              )}

              {/* 流式回复内容 - 实时内容 */}
              {isStreaming && streamingContent && (
                <div className="flex justify-start">
                  <div className="max-w-[80%] rounded-2xl p-4 bg-white/5 border border-white/10 text-slate-200">
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children, node }: any) => {
                            const hasPre = node?.children?.some(
                              (child: any) => child.tagName === 'pre' || child.tagName === 'code' && !child.properties?.inline
                            )
                            if (hasPre) return <div className="mb-4 last:mb-0">{children}</div>
                            return <p>{children}</p>
                          },
                          code: ({ inline, children, ...props }: any) => (
                            inline ? (
                              <code className="bg-slate-700 px-1 py-0.5 rounded text-sm" {...props}>
                                {children}
                              </code>
                            ) : (
                              <pre className="bg-slate-800 p-3 rounded-lg overflow-x-auto my-2">
                                <code className="text-sm" {...props}>{children}</code>
                              </pre>
                            )
                          ),
                          table: ({ children }: any) => (
                            <table className="border-collapse border border-slate-600 my-2">
                              {children}
                            </table>
                          ),
                          th: ({ children }: any) => (
                            <th className="border border-slate-600 px-2 py-1 bg-slate-700">
                              {children}
                            </th>
                          ),
                          td: ({ children }: any) => (
                            <td className="border border-slate-600 px-2 py-1">
                              {children}
                            </td>
                          ),
                        }}
                      >
                        {streamingContent}
                      </ReactMarkdown>
                    </div>
                    <span className="text-xs mt-2 block text-slate-500">
                      {new Date().toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* 输入区域 */}
        <div className="p-4 border-t border-white/10 bg-white/5">
          <div className="max-w-4xl mx-auto">
            <div className="flex gap-3">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                placeholder="输入您的问题，例如：帮我填写汇总表..."
                disabled={isLoading}
                className="flex-1 px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500/30 disabled:opacity-50 transition-all"
              />
              {isStreaming ? (
                <button
                  onClick={handleStop}
                  className="px-6 py-3 bg-gradient-to-r from-red-500 to-orange-500 text-white rounded-xl hover:from-red-600 hover:to-orange-600 transition-all flex items-center gap-2 font-medium"
                >
                  <Square className="w-5 h-5" />
                  停止
                </button>
              ) : (
                <button
                  onClick={() => handleSend()}
                  disabled={isLoading || !inputValue.trim()}
                  className="px-6 py-3 bg-gradient-to-r from-primary-500 to-purple-500 text-white rounded-xl hover:from-primary-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 font-medium"
                >
                  {isLoading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Send className="w-5 h-5" />
                  )}
                  发送
                </button>
              )}
            </div>

            {/* 快捷提示 */}
            <div className="flex gap-2 mt-3 overflow-x-auto pb-1 scrollbar-thin">
              <button
                onClick={() => setInputValue('帮我分析这些文档')}
                className="px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 rounded-full text-slate-400 whitespace-nowrap transition-colors"
              >
                分析文档
              </button>
              <button
                onClick={() => setInputValue('填写汇总表')}
                className="px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 rounded-full text-slate-400 whitespace-nowrap transition-colors"
              >
                填写表格
              </button>
              <button
                onClick={() => setInputValue('查询关键信息')}
                className="px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 rounded-full text-slate-400 whitespace-nowrap transition-colors"
              >
                查询信息
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 右侧文档预览面板 */}
      <DocumentPreviewPanel
        isPanelOpen={isPanelOpen}
        onToggle={togglePanel}
        previewFiles={previewFiles}
        currentFile={previewCurrentFile}
        onFileSelect={setPreviewCurrentFile}
        isLoading={previewIsLoading}
      />
    </div>
  )
}
