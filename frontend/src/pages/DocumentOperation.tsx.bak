import { useState, useEffect, useRef } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, Plus, Check } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'

interface Message {
  role: 'user' | 'assistant'
  content: string
  action?: ActionData
  timestamp: number
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
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')
  
  const activeSession = sessions.find(s => s.id === activeSessionId)

  useEffect(() => {
    fetchDocuments()
    loadSessions()  // 从数据库加载会话
    setMinimized(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 恢复会话时加载消息和选择状态
  useEffect(() => {
    if (activeSessionId) {
      // 始终强制重新加载消息，以便获取最新的任务状态
      const { loadSessionMessages } = useChatStore.getState()
      loadSessionMessages(activeSessionId, true).then(() => {
        const updatedSession = useChatStore.getState().sessions.find(s => s.id === activeSessionId)
        if (updatedSession) {
          const loadedMessages = updatedSession.messages.map(m => ({
            role: m.role,
            content: m.content,
            action: m.action_data,
            timestamp: m.timestamp
          }))
          setLocalMessages(loadedMessages)
          
          // 恢复文档和模板选择
          if (updatedSession.fileIds && updatedSession.fileIds.length > 0) {
            setSelectedDocIds([...updatedSession.fileIds])
          }
          if (updatedSession.templateId) {
            setSelectedTemplateId(updatedSession.templateId)
          }
          
          // 恢复pendingAction（如果是确认状态）
          const lastAiMessage = loadedMessages.filter(m => m.role === 'assistant').pop()
          if (lastAiMessage?.action && 
              (lastAiMessage.action.action_type === 'confirm_fill' || 
               lastAiMessage.action.action_type === 'confirm_extract')) {
            setPendingAction(lastAiMessage.action)
          } else {
            setPendingAction(null)
          }
        }
      })
    } else {
      setLocalMessages([])
      setPendingAction(null)
    }
  }, [activeSessionId])

  // 轮询检查任务状态
  useEffect(() => {
    const hasProcessingTask = localMessages.some(m => 
      m.action?.action_type === 'executing' || 
      m.action?.action_type === 'confirm_fill'
    )
    
    if (!hasProcessingTask || !activeSessionId) return
    
    const pollInterval = setInterval(async () => {
      const { loadSessionMessages } = useChatStore.getState()
      await loadSessionMessages(activeSessionId, true)
      const updatedSession = useChatStore.getState().sessions.find(s => s.id === activeSessionId)
      if (updatedSession) {
        setLocalMessages(updatedSession.messages.map(m => ({
          role: m.role,
          content: m.content,
          action: m.action_data,
          timestamp: m.timestamp
        })))
      }
    }, 2000) // 每2秒轮询一次
    
    return () => clearInterval(pollInterval)
  }, [localMessages, activeSessionId])

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
  }, [localMessages])

  // 新建对话
  const handleNewChat = async () => {
    // 清空当前选择
    setSelectedDocIds([])
    setSelectedTemplateId(null)
    
    // 创建新会话
    const sessionId = await createSession(null, '通用对话', [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingAction(null)
    toast.success('已创建新对话')
  }

  // 切换文档选择（多选）
  const toggleDocSelection = (docId: string) => {
    setSelectedDocIds(prev => 
      prev.includes(docId) 
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
    )
  }

  // 选择模板
  const handleTemplateSelect = (docId: string) => {
    setSelectedTemplateId(selectedTemplateId === docId ? null : docId)
    setShowTemplateDropdown(false)
  }

  // 发送消息
  const handleSend = async (actionConfirmed = false, actionId?: string) => {
    if (!inputValue.trim() && !actionConfirmed) {
      toast.error('请输入指令')
      return
    }


    const userMessage = inputValue || '确认执行'
    
    // 如果没有活跃会话，创建一个
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
      // 更新会话的文件选择
      await updateSessionFiles(currentSessionId, selectedDocIds, selectedTemplateId)
    }

    // 判断是否是第一条消息（新会话 or 旧会话但没有消息）
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

    // 如果是第一条消息，用轻量接口生成标题
    if (isFirstMessage) {
      api.post('/agent/generate-title', { message: userMessage })
        .then(async (res) => {
          const newTitle = res.data.title || '通用对话'
          await api.put(`/conversations/${currentSessionId}`, { title: newTitle })
          useChatStore.getState().loadSessions()
        })
        .catch(e => console.error('Failed to generate title:', e))
    }

    try {
      const response = await api.post('/agent/chat', {
        message: userMessage,
        file_ids: selectedDocIds,
        template_id: selectedTemplateId,
        conversation_history: localMessages.map(m => ({ role: m.role, content: m.content })),
        action_confirmed: actionConfirmed,
        action_id: actionId
      })

      const { message, action } = response.data

      // 添加AI回复
      const aiMsg: Message = {
        role: 'assistant',
        content: message,
        action: action,
        timestamp: Date.now()
      }
      setLocalMessages(prev => [...prev, aiMsg])

      // 保存消息到数据库，并记录消息ID
      await addMessage(currentSessionId, { role: 'user', content: userMessage })
      const aiMsgId = await addMessage(currentSessionId, { role: 'assistant', content: message, action_data: action })

      // 如果需要确认，保存待执行操作和消息ID
      if (action && (action.action_type === 'confirm_extract' || action.action_type === 'confirm_fill')) {
        setPendingAction({ ...action, _messageId: aiMsgId })
      } else {
        setPendingAction(null)
      }
    } catch (error) {
      toast.error('请求失败')
      setLocalMessages(prev => [...prev, {
        role: 'assistant',
        content: '抱歉，发生了错误，请重试。',
        timestamp: Date.now()
      }])
    } finally {
      setIsLoading(false)
    }
  }

  // 确认执行操作
  const handleConfirmAction = async () => {
    if (!pendingAction) return
    
    // 保存当前的pendingAction，因为后面会被清空
    const currentPendingAction = { ...pendingAction }
    
    // 更新最后一条AI消息的状态为执行中
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
    setIsLoading(true)

    try {
      const response = await api.post('/agent/chat', {
        message: '',
        file_ids: selectedDocIds,
        template_id: selectedTemplateId,
        conversation_history: [],
        action_confirmed: true,
        action_id: currentPendingAction.action_id
      })

      const { message, action } = response.data
      
      // 更新最后一条AI消息
      setLocalMessages(prev => {
        const newMessages = [...prev]
        const lastAiIndex = newMessages.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop()
        if (lastAiIndex !== undefined) {
          newMessages[lastAiIndex] = {
            ...newMessages[lastAiIndex],
            content: message,
            action: action
          }
        }
        return newMessages
      })

      // 更新数据库中的确认消息（不添加新消息）
      if (activeSessionId && currentPendingAction._messageId) {
        await updateMessage(activeSessionId, currentPendingAction._messageId, { 
          role: 'assistant', 
          content: message, 
          action_data: action 
        })
      }
    } catch (error) {
      toast.error('执行失败')
      setLocalMessages(prev => {
        const newMessages = [...prev]
        const lastAiIndex = newMessages.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop()
        if (lastAiIndex !== undefined) {
          newMessages[lastAiIndex] = {
            ...newMessages[lastAiIndex],
            content: '执行失败，请重试。',
            action: {
              ...currentPendingAction,
              action_type: 'failed',
              title: '执行失败',
              description: '请重试'
            }
          }
        }
        return newMessages
      })
    } finally {
      setIsLoading(false)
    }
  }

  // 取消操作
  const handleCancelAction = () => {
    setPendingAction(null)
    setLocalMessages(prev => {
      const newMessages = [...prev]
      const lastAiIndex = newMessages.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop()
      if (lastAiIndex !== undefined) {
        newMessages[lastAiIndex] = {
          ...newMessages[lastAiIndex],
          content: '已取消操作。如果您需要其他帮助，请告诉我。',
          action: undefined
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

  // 恢复历史对话
  const handleRestoreSession = async (sessionId: string) => {
    setShowHistory(false)
    setPendingAction(null)
    
    // 先设置活跃会话
    setActiveSession(sessionId)
    
    // 等待消息加载完成
    const { sessions } = useChatStore.getState()
    const session = sessions.find(s => s.id === sessionId)
    
    if (session) {
      // 恢复该会话的文档和模板选择
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
      
      // 更新本地消息显示
      setLocalMessages(session.messages.map(m => ({
        role: m.role,
        content: m.content,
        action: m.action_data,
        timestamp: m.timestamp
      })))
    }
  }

  // 获取选中数量提示
  const getSelectionHint = () => {
    const docCount = selectedDocIds.length
    const templateCount = selectedTemplateId ? 1 : 0
    const total = docCount + templateCount

    if (total === 0) return '可随时开始对话，选择文档可进行文档操作'

    const parts = []
    if (docCount > 0) parts.push(`${docCount}个文档`)
    if (templateCount > 0) parts.push(`1个模板`)

    return `已选 ${parts.join(' + ')}`
  }

  return (
    <div className="glass flex flex-col h-[calc(100vh-200px)]">
      {/* 顶部操作栏 */}
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            {/* 源文档下拉 */}
            <div className="relative min-w-[240px]" ref={docDropdownRef}>
              <button
                onClick={() => {
                  setShowDocDropdown(!showDocDropdown)
                  setShowTemplateDropdown(false)
                }}
                className="w-full flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-xl
                          hover:bg-white/10 transition-colors"
              >
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-sm text-white truncate flex-1 text-left">
                  {selectedDocIds.length > 0 
                    ? `已选 ${selectedDocIds.length} 个源文档` 
                    : '选择源文档（可多选）'}
                </span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showDocDropdown ? 'rotate-180' : ''}`} />
              </button>
              
              {showDocDropdown && (
                <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                  {sourceDocs.length > 0 ? (
                    sourceDocs.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => toggleDocSelection(doc.id)}
                        className={`dropdown-item ${selectedDocIds.includes(doc.id) ? 'dropdown-item-active' : ''}`}
                      >
                        <div className={`w-5 h-5 rounded border flex items-center justify-center shrink-0
                          ${selectedDocIds.includes(doc.id) 
                            ? 'bg-primary-500 border-primary-500' 
                            : 'border-white/30'}`}
                        >
                          {selectedDocIds.includes(doc.id) && <Check className="w-3 h-3 text-white" />}
                        </div>
                        <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">
                      暂无源文档
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 模板下拉 */}
            <div className="relative min-w-[200px]" ref={templateDropdownRef}>
              <button
                onClick={() => {
                  setShowTemplateDropdown(!showTemplateDropdown)
                  setShowDocDropdown(false)
                }}
                className="w-full flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-xl
                          hover:bg-white/10 transition-colors"
              >
                <Table className="w-4 h-4 text-green-400" />
                <span className="text-sm text-white truncate flex-1 text-left">
                  {templateDocs.find(d => d.id === selectedTemplateId)?.original_filename || '选择模板（可选）'}
                </span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showTemplateDropdown ? 'rotate-180' : ''}`} />
              </button>
              
              {showTemplateDropdown && (
                <div className="absolute top-full left-0 right-0 mt-2 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-50">
                  {templateDocs.length > 0 ? (
                    templateDocs.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => handleTemplateSelect(doc.id)}
                        className={`dropdown-item ${selectedTemplateId === doc.id ? 'dropdown-item-active' : ''}`}
                      >
                        <Table className="w-4 h-4 text-green-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</p>
                        </div>
                        {selectedTemplateId === doc.id && (
                          <Check className="w-4 h-4 text-green-400 shrink-0" />
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-sm text-slate-500 text-center">
                      暂无模板
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`p-2 rounded-lg transition-colors ${showHistory ? 'bg-primary-500/20 text-primary-400' : 'hover:bg-white/10 text-slate-400'}`}
              title="历史记录"
            >
              <History className="w-4 h-4" />
            </button>
            <button
              onClick={handleNewChat}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary-500/20 text-primary-400 rounded-lg hover:bg-primary-500/30"
            >
              <Plus className="w-3 h-3" />
              新建对话
            </button>
          </div>
        </div>
        
        <p className="text-xs text-slate-400">{getSelectionHint()}</p>
      </div>

      {/* 历史记录面板 */}
      {showHistory && (
        <div className="p-4 border-b border-white/10 bg-white/5 max-h-48 overflow-y-auto scrollbar-thin">
          <h4 className="text-sm font-medium text-slate-400 mb-3">对话历史</h4>
          {sessions.length > 0 ? (
            <div className="space-y-2">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`flex items-center justify-between p-2 rounded-lg cursor-pointer
                    ${session.id === activeSessionId 
                      ? 'bg-primary-500/20 border border-primary-500/30' 
                      : 'bg-white/5 hover:bg-white/10'}`}
                  onClick={() => handleRestoreSession(session.id)}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-primary-400 truncate mb-1">
                      {session.documentName || '通用对话'}
                    </p>
                    <p className="text-sm text-white truncate">
                      {session.lastMessage?.slice(0, 30) || session.messages[0]?.content.slice(0, 30) || '空对话'}...
                    </p>
                    <p className="text-xs text-slate-500 flex items-center gap-1 mt-1">
                      <Clock className="w-3 h-3" />
                      {new Date(session.updatedAt).toLocaleString()}
                    </p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteSession(session.id)
                    }}
                    className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500 text-center">暂无对话历史</p>
          )}
        </div>
      )}

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {localMessages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <FileText className="w-16 h-16 mx-auto mb-4 text-slate-600" />
              <p className="text-slate-400">我是您的智能文档助手</p>
              <p className="text-sm text-slate-500 mt-2">
                您可以问我任何关于文档的问题，或者让我帮您提取信息、填写表格
              </p>
              <div className="mt-4 space-y-2 text-left max-w-md mx-auto">
                <p className="text-xs text-slate-500">示例指令：</p>
                <p className="text-xs text-slate-400">• "这些文档的主要内容是什么？"</p>
                <p className="text-xs text-slate-400">• "帮我提取文档中的关键信息"</p>
                <p className="text-xs text-slate-400">• "用文档数据填写模板"</p>
              </div>
            </div>
          </div>
        )}
        
        {localMessages.map((message, index) => (
          <div key={index}>
            <div
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] p-4 rounded-2xl ${
                  message.role === 'user'
                    ? 'bg-primary-500/20 text-white'
                    : 'bg-white/5 text-slate-200'
                }`}
              >
                {message.content}
              </div>
            </div>
            
            {/* 操作卡片 */}
            {message.role === 'assistant' && message.action && (
              <div className="ml-0 max-w-[80%]">
                <ActionCard
                  action={message.action}
                  onConfirm={handleConfirmAction}
                  onCancel={handleCancelAction}
                />
              </div>
            )}
          </div>
        ))}
        
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white/5 p-4 rounded-2xl">
              <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-white/10">
        <div className="flex gap-3">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={pendingAction ? '操作待确认，请点击上方卡片确认' : '输入您的问题或指令...'}
            className="input flex-1"
            disabled={isLoading}
          />
          <button
            onClick={() => handleSend()}
            disabled={isLoading || (!inputValue.trim() && !pendingAction)}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
