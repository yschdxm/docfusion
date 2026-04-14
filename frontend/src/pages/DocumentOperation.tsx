import { useState, useEffect, useRef } from 'react'
import { Send, FileText, Loader2, Table, History, Trash2, Clock, ChevronDown, Plus, Check, Eye, X } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useChatStore } from '../stores/chatStore'
import ActionCard, { ActionData } from '../components/ActionCard'
import { useI18n } from '../hooks/useI18n'

interface Message {
  role: 'user' | 'assistant'
  content: string
  action?: ActionData
  timestamp: number
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

export default function DocumentOperation() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments } = useDocumentStore()
  const {
    sessions,
    activeSessionId,
    createSession,
    setActiveSession,
    deleteSession,
    updateSessionFiles,
    addMessage,
    loadSessions,
    setMinimized,
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
  const [previewState, setPreviewState] = useState<PreviewState | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const docDropdownRef = useRef<HTMLDivElement>(null)
  const templateDropdownRef = useRef<HTMLDivElement>(null)

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')

  useEffect(() => {
    fetchDocuments()
    loadSessions()
    setMinimized(true)
  }, [])

  useEffect(() => {
    if (activeSessionId) {
      const session = sessions.find((s) => s.id === activeSessionId)
      if (session && session.messages.length === 0) {
        const { loadSessionMessages } = useChatStore.getState()
        loadSessionMessages(activeSessionId).then(() => {
          const updatedSession = useChatStore.getState().sessions.find((s) => s.id === activeSessionId)
          if (updatedSession) {
            setLocalMessages(
              updatedSession.messages.map((m) => ({
                role: m.role,
                content: m.content,
                action: m.action_data,
                timestamp: m.timestamp,
              }))
            )
            if (updatedSession.fileIds && updatedSession.fileIds.length > 0) {
              setSelectedDocIds([...updatedSession.fileIds])
            }
            if (updatedSession.templateId) {
              setSelectedTemplateId(updatedSession.templateId)
            }
          }
        })
      } else if (session && session.messages.length > 0) {
        setLocalMessages(
          session.messages.map((m) => ({
            role: m.role,
            content: m.content,
            action: m.action_data,
            timestamp: m.timestamp,
          }))
        )
        if (session.fileIds && session.fileIds.length > 0) {
          setSelectedDocIds([...session.fileIds])
        }
        if (session.templateId) {
          setSelectedTemplateId(session.templateId)
        }
      }
    } else {
      setLocalMessages([])
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
  }, [localMessages])

  const handleNewChat = async () => {
    setSelectedDocIds([])
    setSelectedTemplateId(null)

    const sessionId = await createSession(null, tr('通用对话', 'General Chat', '一般チャット'), [], null)
    setActiveSession(sessionId)
    setLocalMessages([])
    setPendingAction(null)
    toast.success(tr('已创建新对话', 'New chat created', '新しい会話を作成しました'))
  }

  const toggleDocSelection = (docId: string) => {
    setSelectedDocIds((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }

  const handleTemplateSelect = (docId: string) => {
    setSelectedTemplateId(selectedTemplateId === docId ? null : docId)
    setShowTemplateDropdown(false)
  }

  const handleSend = async (actionConfirmed = false, actionId?: string) => {
    if (!inputValue.trim() && !actionConfirmed) {
      toast.error(tr('请输入指令', 'Please enter an instruction', '指示を入力してください'))
      return
    }

    const userMessage = inputValue || '确认执行'

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

    if (isFirstMessage) {
      api
        .post('/agent/generate-title', { message: userMessage })
        .then(async (res) => {
          const newTitle = res.data.title || '通用对话'
          await api.put(`/conversations/${currentSessionId}`, { title: newTitle })
          useChatStore.getState().loadSessions()
        })
        .catch((e) => console.error('Failed to generate title:', e))
    }

    try {
      const response = await api.post('/agent/chat', {
        message: userMessage,
        file_ids: selectedDocIds,
        template_id: selectedTemplateId,
        conversation_history: localMessages.map((m) => ({ role: m.role, content: m.content })),
        action_confirmed: actionConfirmed,
        action_id: actionId,
      })

      const { message, action } = response.data

      const aiMsg: Message = {
        role: 'assistant',
        content: message,
        action,
        timestamp: Date.now(),
      }
      setLocalMessages((prev) => [...prev, aiMsg])

      await addMessage(currentSessionId, { role: 'user', content: userMessage })
      await addMessage(currentSessionId, { role: 'assistant', content: message, action_data: action })

      if (action && (action.action_type === 'confirm_extract' || action.action_type === 'confirm_fill')) {
        setPendingAction(action)
      } else {
        setPendingAction(null)
      }
    } catch {
      toast.error(tr('请求失败', 'Request failed', 'リクエストに失敗しました'))
      setLocalMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: tr('抱歉，处理请求时出现错误，请稍后重试。', 'Sorry, an error occurred. Please try again later.', '処理中にエラーが発生しました。しばらくして再試行してください。'),
          timestamp: Date.now(),
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const handleConfirmAction = async () => {
    if (!pendingAction) return

    setLocalMessages((prev) => {
      const newMessages = [...prev]
      const lastAiIndex = newMessages
        .map((m, i) => (m.role === 'assistant' ? i : -1))
        .filter((i) => i >= 0)
        .pop()
      if (lastAiIndex !== undefined) {
        newMessages[lastAiIndex] = {
          ...newMessages[lastAiIndex],
          action: {
            ...pendingAction,
            action_type: 'executing',
            progress: 0,
          },
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
        action_id: pendingAction.action_id,
      })

      const { message, action } = response.data

      setLocalMessages((prev) => {
        const newMessages = [...prev]
        const lastAiIndex = newMessages
          .map((m, i) => (m.role === 'assistant' ? i : -1))
          .filter((i) => i >= 0)
          .pop()
        if (lastAiIndex !== undefined) {
          newMessages[lastAiIndex] = {
            ...newMessages[lastAiIndex],
            content: message,
            action,
          }
        }
        return newMessages
      })

      if (activeSessionId) {
        await addMessage(activeSessionId, { role: 'assistant', content: message, action_data: action })
      }
    } catch {
      toast.error(tr('执行失败', 'Execution failed', '実行に失敗しました'))
      setLocalMessages((prev) => {
        const newMessages = [...prev]
        const lastAiIndex = newMessages
          .map((m, i) => (m.role === 'assistant' ? i : -1))
          .filter((i) => i >= 0)
          .pop()
        if (lastAiIndex !== undefined) {
          newMessages[lastAiIndex] = {
            ...newMessages[lastAiIndex],
            content: tr('执行失败，请重试。', 'Execution failed, please retry.', '実行に失敗しました。再試行してください。'),
            action: {
              ...pendingAction,
              action_type: 'failed',
              title: tr('执行失败', 'Execution failed', '実行失敗'),
              description: tr('请重试或调整指令后再次提交。', 'Please retry or adjust your instruction.', '再試行するか、指示を調整して再送してください。'),
            },
          }
        }
        return newMessages
      })
    } finally {
      setIsLoading(false)
    }
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

  const handleRestoreSession = async (sessionId: string) => {
    setShowHistory(false)
    setPendingAction(null)
    setActiveSession(sessionId)

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
    <div className="glass relative flex flex-col h-[calc(100vh-200px)]">
      <div className="p-4 border-b border-slate-200">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            <div className="relative min-w-[240px]" ref={docDropdownRef}>
              <button
                onClick={() => {
                  setShowDocDropdown(!showDocDropdown)
                  setShowTemplateDropdown(false)
                }}
                className="w-full flex items-center gap-2 px-3 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-sm text-slate-900 truncate flex-1 text-left">
                  {selectedDocIds.length > 0 ? `${tr('已选', 'Selected', '選択済み')} ${selectedDocIds.length} ${tr('个源文档', 'source docs', '件のソース文書')}` : tr('选择源文档（可多选）', 'Select source docs (multi-select)', 'ソース文書を選択（複数可）')}
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
                        <div
                          className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 ${
                            selectedDocIds.includes(doc.id) ? 'bg-primary-500 border-primary-500' : 'border-slate-300'
                          }`}
                        >
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

            <div className="relative min-w-[200px]" ref={templateDropdownRef}>
              <button
                onClick={() => {
                  setShowTemplateDropdown(!showTemplateDropdown)
                  setShowDocDropdown(false)
                }}
                className="w-full flex items-center gap-2 px-3 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <Table className="w-4 h-4 text-green-400" />
                <span className="text-sm text-slate-900 truncate flex-1 text-left">
                  {templateDocs.find((d) => d.id === selectedTemplateId)?.original_filename || tr('选择模板（可选）', 'Select template (optional)', 'テンプレートを選択（任意）')}
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

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowHistory(!showHistory)}
              aria-label={tr('切换历史记录', 'Toggle history', '履歴を切替')}
              className={`p-2 rounded-lg transition-colors ${showHistory ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'hover:bg-slate-100 text-slate-500 border border-transparent'}`}
              title={tr('历史记录', 'History', '履歴')}
            >
              <History className="w-4 h-4" />
            </button>
            <button
              onClick={handleNewChat}
              className="btn-secondary px-3 py-1.5 text-xs"
            >
              <Plus className="w-3 h-3" />
              {tr('新建对话', 'New Chat', '新しい会話')}
            </button>
          </div>
        </div>

        <p className="text-xs text-slate-500">{getSelectionHint()}</p>
      </div>

      {showHistory && (
        <div className="p-4 border-b border-slate-200 bg-slate-50 max-h-48 overflow-y-auto scrollbar-thin">
          <h4 className="text-sm font-medium text-slate-500 mb-3">{tr('对话历史', 'Chat History', '会話履歴')}</h4>
          {sessions.length > 0 ? (
            <div className="space-y-2">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`flex items-center justify-between p-2 rounded-lg cursor-pointer ${
                    session.id === activeSessionId ? 'bg-blue-50 border border-blue-200' : 'bg-slate-50 hover:bg-slate-100'
                  }`}
                  onClick={() => handleRestoreSession(session.id)}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-primary-500 truncate mb-1">{session.documentName || tr('通用对话', 'General Chat', '一般チャット')}</p>
                    <p className="text-sm text-slate-900 truncate">
                      {(session.lastMessage?.slice(0, 30) || session.messages[0]?.content.slice(0, 30) || tr('空对话', 'Empty chat', '空の会話')) + '...'}
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
                    aria-label={tr('删除会话', 'Delete session', '会話を削除')}
                    className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500 text-center">{tr('暂无对话历史', 'No chat history', '会話履歴はありません')}</p>
          )}
        </div>
      )}

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
            <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] p-4 rounded-2xl ${message.role === 'user' ? 'bg-primary-500/15 text-slate-900' : 'bg-slate-50 text-slate-700'}`}>
                {message.content}
              </div>
            </div>

            {message.role === 'assistant' && message.action && (
              <div className="ml-0 max-w-[80%]">
                <ActionCard action={message.action} onConfirm={handleConfirmAction} onCancel={handleCancelAction} />
                {message.action.action_type === 'completed' && message.action.result?.preview && (
                  <div className="mt-2 flex">
                    <button
                      onClick={() => openPreview(message.action!)}
                      className="btn-secondary px-3 py-2 text-sm text-blue-700 border-blue-300 hover:bg-blue-50"
                    >
                      <Eye className="w-4 h-4" />
                      {tr('预览修改结果', 'Preview Changes', '変更プレビュー')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-slate-50 p-4 rounded-2xl">
              <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {previewState && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-6 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="doc-op-preview-title" className="max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
              <div>
                <h3 id="doc-op-preview-title" className="text-lg font-semibold text-slate-900">{previewState.title}</h3>
                <p className="mt-1 text-sm text-slate-600">{previewState.description}</p>
                <p className="mt-2 text-xs text-slate-500">
                  {tr('共', 'Total', '合計')} {previewState.totalChanges} {tr('处修改', 'changes', '件の変更')}{previewState.outputFilename ? ` · ${previewState.outputFilename}` : ''}
                </p>
              </div>
              <button onClick={() => setPreviewState(null)} aria-label={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-900">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(85vh-88px)] space-y-4 overflow-y-auto p-6 scrollbar-thin">
              {previewState.items.map((item, index) => (
                <div key={`${item.op}-${item.paragraph_index}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full bg-primary-500/20 px-2.5 py-1 text-primary-700">{item.op}</span>
                    <span className="rounded-full bg-white px-2.5 py-1 text-slate-600">段落 {item.paragraph_index >= 0 ? item.paragraph_index : '-'}</span>
                    {item.reason && <span className="text-slate-500">{item.reason}</span>}
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-red-700">{tr('修改前', 'Before', '変更前')}</div>
                      <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-700">{item.before || tr('无', 'None', 'なし')}</pre>
                    </div>
                    <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-green-700">{tr('修改后', 'After', '変更後')}</div>
                      <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-800">{item.after || tr('无', 'None', 'なし')}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="p-4 border-t border-slate-200">
        <div className="flex gap-3">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={pendingAction ? tr('操作待确认，请先点击上方卡片完成确认。', 'Action pending confirmation, please confirm above first.', '操作は確認待ちです。先に上のカードで確認してください。') : tr('输入你的问题或指令...', 'Enter your question or instruction...', '質問または指示を入力してください...')}
            className="input flex-1"
            disabled={isLoading}
          />
          <button onClick={() => handleSend()} disabled={isLoading || (!inputValue.trim() && !pendingAction)} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed">
            {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </div>
      </div>
    </div>
  )
}

