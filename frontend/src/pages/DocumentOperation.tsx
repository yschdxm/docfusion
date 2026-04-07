import { useState, useEffect, useRef } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, Plus, Check, X, Square } from 'lucide-react'
import toast from 'react-hot-toast'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'
import AgentThinkingPanel from '../components/AgentThinkingPanel'
import agentStreamService, { AgentStep } from '../services/agentStreamService'

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
    addMessage,
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

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')

  useEffect(() => {
    fetchDocuments()
    loadSessions()
    setMinimized(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 恢复会话时加载消息和选择状态
  useEffect(() => {
    if (activeSessionId) {
      const { loadSessionMessages } = useChatStore.getState()
      loadSessionMessages(activeSessionId, true).then(() => {
        const updatedSession = useChatStore.getState().sessions.find(s => s.id === activeSessionId)
        if (updatedSession) {
          const loadedMessages = updatedSession.messages.map(m => ({
            role: m.role,
            content: m.content,
            action: m.action_data,
            timestamp: m.timestamp,
            steps: m.steps
          }))
          setLocalMessages(loadedMessages)

          if (updatedSession.fileIds && updatedSession.fileIds.length > 0) {
            setSelectedDocIds([...updatedSession.fileIds])
          }
          if (updatedSession.templateId) {
            setSelectedTemplateId(updatedSession.templateId)
          }
        }
      })
    } else {
      setLocalMessages([])
      setPendingAction(null)
    }
  }, [activeSessionId])

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
    console.log('[DocumentOperation] localMessages changed, length:', localMessages.length)
    if (localMessages.length > 0) {
      console.log('[DocumentOperation] Last message:', localMessages[localMessages.length - 1])
    }
  }, [localMessages])

  // 新建对话
  const handleNewChat = async () => {
    setSelectedDocIds([])
    setSelectedTemplateId(null)

    const sessionId = await createSession(null, '新对话', [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingAction(null)
    setCurrentSteps([])
    setStreamingContent('')
  }

  // 切换会话
  const handleSwitchSession = (sessionId: string) => {
    setActiveSession(sessionId)
    setShowHistory(false)
    setPendingAction(null)
    setCurrentSteps([])
    setStreamingContent('')
  }

  // 删除会话
  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await deleteSession(sessionId)
    if (activeSessionId === sessionId) {
      setLocalMessages([])
      setSelectedDocIds([])
      setSelectedTemplateId(null)
      setPendingAction(null)
      setCurrentSteps([])
        setStreamingContent('')
    }
  }

  // 处理文档选择
  const handleDocSelect = (docId: string) => {
    setSelectedDocIds(prev =>
      prev.includes(docId)
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
    )
  }

  // 处理模板选择
  const handleTemplateSelect = (docId: string) => {
    setSelectedTemplateId(prev => prev === docId ? null : docId)
    setShowTemplateDropdown(false)
  }

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

  // 发送消息 - 使用流式API
  const handleSend = async (actionConfirmed: boolean = false) => {
    const userMessage = inputValue.trim()
    if (!userMessage) return

    if (!actionConfirmed && pendingAction) {
      toast.error('请先处理待确认的操作')
      return
    }

    // 检查是否是填表任务但没有选择模板
    // 注：现在支持智能文档选择，不需要强制选择模板
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

    // 添加用户消息
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

    // 保存用户消息到数据库
    await addMessage(currentSessionId, { role: 'user', content: userMessage })

    // 使用流式API
    // 保存steps的引用，避免闭包问题
    let latestSteps: AgentStep[] = []

    // 创建 AbortController 用于取消请求
    abortControllerRef.current = new AbortController()

    // 流式开始前重置中间回复状态
    setStreamingContent('')

    try {
      await agentStreamService.streamChat(
        {
          message: userMessage,
          file_ids: selectedDocIds,
          template_id: selectedTemplateId || undefined,
          conversation_id: currentSessionId,
          task_type: taskType
        },
        // 事件回调
        (event, steps) => {
          console.log('[DocumentOperation] onEvent:', event.event_type, 'steps count:', steps.length)
          latestSteps = steps
          setCurrentSteps([...steps])

          // 处理 content_chunk 事件 - 实时更新回复内容
          if (event.event_type === 'content_chunk' && event.data.content) {
            setStreamingContent(prev => prev + event.data.content)
          }

          // 处理 assistant_message 事件 - 已作为 assistant_reply 步骤添加到 currentSteps 中
          // 同时将内容追加到 streamingContent 以支持中断保存
          if (event.event_type === 'assistant_message') {
            const message = event.data.message || ''
            if (message) {
              setStreamingContent(prev => prev + '\n\n' + message)
            }
          }

          // 当开始接收内容时，自动折叠思考过程
          // 注意：思考面板展开状态已移除，由组件内部管理
        },
        // 完成回调
        (result) => {
          console.log('[DocumentOperation] onComplete called', result)
          setIsStreaming(false)
          setIsLoading(false)

          // 重置流式内容
          const finalContent = streamingContent || result.message
          setStreamingContent('')

          // 添加AI回复 - 使用latestSteps避免闭包问题
          const aiMsg: Message = {
            role: 'assistant',
            content: finalContent,
            timestamp: Date.now(),
            steps: latestSteps.length > 0 ? latestSteps : currentSteps
          }

          console.log('[DocumentOperation] Adding AI message:', aiMsg)

          // 如果有输出文件，添加action
          if (result.download_url) {
            aiMsg.action = {
              action_type: 'completed',
              filled_file_url: result.download_url,
              filled_file_id: result.output_file_id
            }
          }

          setLocalMessages(prev => {
            console.log('[DocumentOperation] setLocalMessages called, prev length:', prev.length)
            return [...prev, aiMsg]
          })
          addMessage(currentSessionId!, {
            role: 'assistant',
            content: result.message,
            action_data: aiMsg.action,
            steps: latestSteps.length > 0 ? latestSteps : currentSteps
          })

          if (result.success) {
            toast.success('任务完成！')
          }

          // 流式完成后清空 currentSteps，避免和 msg.steps 重复显示
          setCurrentSteps([])
        },
        // 错误回调
        (error) => {
          setIsStreaming(false)
          setIsLoading(false)

          // 检查是否是用户取消
          const isAborted = error?.toString().includes('abort') ||
                            error?.toString().includes('AbortError') ||
                            error?.toString().includes('BodyStreamBuffer was aborted')

          if (isAborted) {
            // 用户取消，保留已生成的内容
            if (streamingContent) {
              const content = streamingContent
              const partialMsg: Message = {
                role: 'assistant',
                content: content,
                timestamp: Date.now()
              }
              setLocalMessages(prev => [...prev, partialMsg])
              addMessage(currentSessionId!, { role: 'assistant', content: content, steps: currentSteps })
            }
          } else {
            // 真正的错误
            const errorMsg: Message = {
              role: 'assistant',
              content: `抱歉，任务执行失败：${error}`,
              timestamp: Date.now()
            }
            setLocalMessages(prev => [...prev, errorMsg])
            addMessage(currentSessionId!, { role: 'assistant', content: errorMsg.content, steps: currentSteps })
            toast.error('请求失败')
          }
        },
        abortControllerRef.current?.signal
      )
    } catch (error) {
      setIsStreaming(false)
      setIsLoading(false)

      // 检查是否是用户取消导致的异常
      const isAborted = (error as Error)?.toString().includes('abort') ||
                        (error as Error)?.toString().includes('AbortError')

      if (!isAborted) {
        toast.error('网络请求失败')

        const errorMsg: Message = {
          role: 'assistant',
          content: '抱歉，发生了错误，请重试。',
          timestamp: Date.now()
        }
        setLocalMessages(prev => [...prev, errorMsg])
        addMessage(currentSessionId, { role: 'assistant', content: errorMsg.content })
      }
    }
  }

  // 停止流式请求
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
      setIsStreaming(false)
      setIsLoading(false)
      // setIntermediateReply(null) // Removed to persist messages on stop
      toast('已停止生成', { icon: '⏹️' })
    }
  }

  // 确认执行操作
  const handleConfirmAction = async () => {
    if (!pendingAction) return

    const currentPendingAction = { ...pendingAction }

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

    const confirmMsg: Message = {
      role: 'user',
      content: '[确认执行操作]',
      timestamp: Date.now()
    }
    setLocalMessages(prev => [...prev, confirmMsg])
    await addMessage(activeSessionId!, { role: 'user', content: confirmMsg.content })

    setIsLoading(true)
    setIsStreaming(true)
    setCurrentSteps([])
    setStreamingContent('')

    // 保存steps的引用，避免闭包问题
    let latestSteps: AgentStep[] = []

    // 创建 AbortController 用于取消请求
    abortControllerRef.current = new AbortController()

    try {
      await agentStreamService.streamChat(
        {
          message: '确认执行之前的操作',
          file_ids: selectedDocIds,
          template_id: selectedTemplateId || undefined,
          conversation_id: activeSessionId!
        },
        (_event, steps) => {
          latestSteps = steps
          setCurrentSteps([...steps])

          // 处理 assistant_message 事件 - 已作为 assistant_reply 步骤添加到 currentSteps 中
        },
        (result) => {
          setIsStreaming(false)
          setIsLoading(false)
      
          const aiMsg: Message = {
            role: 'assistant',
            content: result.message,
            timestamp: Date.now(),
            steps: latestSteps.length > 0 ? latestSteps : currentSteps
          }

          if (result.download_url) {
            aiMsg.action = {
              action_type: 'completed',
              filled_file_url: result.download_url,
              filled_file_id: result.output_file_id
            }
          }

          setLocalMessages(prev => [...prev, aiMsg])
          addMessage(activeSessionId!, {
            role: 'assistant',
            content: result.message,
            action_data: aiMsg.action,
            steps: latestSteps.length > 0 ? latestSteps : currentSteps
          })

          // 更新消息状态
          const msgId = (currentPendingAction as any)._messageId
          if (msgId) {
            updateMessage(activeSessionId!, msgId, {
              role: 'assistant',
              content: result.message,
              action_data: aiMsg.action,
              steps: latestSteps.length > 0 ? latestSteps : currentSteps
            })
          }

          if (result.success) {
            toast.success('操作完成！')
          }
        },
        (error) => {
          setIsStreaming(false)
          setIsLoading(false)
      
          // 检查是否是用户取消
          const isAborted = error?.toString().includes('abort') ||
                            error?.toString().includes('AbortError') ||
                            error?.toString().includes('BodyStreamBuffer was aborted')

          if (isAborted) {
            // 用户取消，不显示错误
            toast('已停止生成', { icon: '⏹️' })
          } else {
            toast.error('操作失败')
            const errorMsg: Message = {
              role: 'assistant',
              content: `操作失败：${error}`,
              timestamp: Date.now()
            }
            setLocalMessages(prev => [...prev, errorMsg])
            addMessage(activeSessionId!, { role: 'assistant', content: errorMsg.content, steps: currentSteps })
          }
        },
        abortControllerRef.current?.signal
      )
    } catch (error) {
      setIsStreaming(false)
      setIsLoading(false)
        // 检查是否是用户取消导致的异常
      const isAborted = (error as Error)?.toString().includes('abort') ||
                        (error as Error)?.toString().includes('AbortError')
      if (!isAborted) {
        toast.error('请求失败')
      }
    }
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

          <button
            onClick={handleNewChat}
            className="flex items-center gap-2 px-3 py-1.5 text-slate-400 hover:bg-white/10 rounded-xl transition-colors text-sm"
          >
            <Plus className="w-4 h-4" />
            <span>新建对话</span>
          </button>
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
    </div>
  )
}
