import { useState, useEffect, useRef } from 'react'
import { MessageSquare, Minus, Send, Loader2, Trash2, Clock3 } from 'lucide-react'
import { useChatStore } from '../stores/chatStore'
import { useLocation } from 'react-router-dom'
import api from '../services/api'

export default function ChatFloatWindow() {
  const location = useLocation()
  const { sessions, activeSessionId, isMinimized, setMinimized, setActiveSession, addMessage, deleteSession, loadSessions, createSession } =
    useChatStore()

  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const shouldHide = location.pathname === '/document-operation'

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sessions, activeSessionId])

  const activeSession = sessions.find((s) => s.id === activeSessionId)

  const handleSend = async () => {
    if (!inputValue.trim()) return

    let sessionId = activeSessionId
    if (!sessionId) {
      sessionId = await createSession(null, '通用对话')
    }

    const userText = inputValue
    const userMessage = { role: 'user' as const, content: userText }
    addMessage(sessionId, userMessage)
    setInputValue('')
    setIsLoading(true)

    try {
      const response = await api.post('/agent/chat', {
        message: userText,
        file_ids: [],
        template_id: null,
        conversation_history:
          activeSession?.messages.map((m) => ({
            role: m.role,
            content: m.content,
          })) || [],
        action_confirmed: false,
        action_id: null,
      })

      addMessage(sessionId, {
        role: 'assistant',
        content: response.data.message,
        action_data: response.data.action,
      })
    } catch {
      addMessage(sessionId, {
        role: 'assistant',
        content: '抱歉，处理请求时出现错误，请稍后重试。',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (shouldHide) return null

  if (isMinimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-gradient-to-r from-primary-500 to-blue-400 shadow-lg hover:shadow-xl hover:scale-110 transition-all duration-300 flex items-center justify-center z-50"
      >
        <MessageSquare className="w-6 h-6 text-white" />
      </button>
    )
  }

  return (
    <div className="fixed bottom-6 right-6 w-96 h-[500px] glass rounded-2xl shadow-2xl flex flex-col z-50 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-slate-50">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-primary-500" />
          <span className="font-medium text-slate-900">智能问答</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="p-1.5 rounded-lg hover:bg-white text-slate-400 hover:text-slate-900 transition-colors"
            title="历史记录"
          >
            <Clock3 className="w-4 h-4" />
          </button>
          <button onClick={() => setMinimized(true)} className="p-1.5 rounded-lg hover:bg-white text-slate-400 hover:text-slate-900 transition-colors">
            <Minus className="w-4 h-4" />
          </button>
        </div>
      </div>

      {showHistory && (
        <div className="border-b border-slate-200 bg-slate-50 max-h-40 overflow-y-auto scrollbar-thin">
          {sessions.length > 0 ? (
            sessions.map((session) => (
              <div
                key={session.id}
                className={`flex items-center justify-between px-4 py-2 cursor-pointer hover:bg-white ${session.id === activeSessionId ? 'bg-primary-500/20' : ''}`}
              >
                <div
                  className="flex-1 min-w-0"
                  onClick={() => {
                    setActiveSession(session.id)
                    setShowHistory(false)
                  }}
                >
                  <p className="text-sm text-slate-900 truncate">{session.documentName || '通用对话'}</p>
                  <p className="text-xs text-slate-500 truncate">{session.lastMessage?.slice(0, 40) || '空对话'}</p>
                  <p className="text-xs text-slate-500">{new Date(session.updatedAt).toLocaleString()}</p>
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
            ))
          ) : (
            <div className="px-4 py-3 text-center text-sm text-slate-500">暂无历史记录</div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {activeSession && activeSession.messages.length > 0 ? (
          activeSession.messages.map((message, index) => (
            <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] p-3 rounded-xl text-sm ${message.role === 'user' ? 'bg-primary-500/15 text-slate-900' : 'bg-white text-slate-700'}`}>
                {message.content}
              </div>
            </div>
          ))
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-slate-500">
              <MessageSquare className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">开始对话吧</p>
            </div>
          </div>
        )}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white p-3 rounded-xl">
              <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-slate-200">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="输入问题..."
            className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary-300"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !inputValue.trim()}
            className="px-3 py-2 bg-primary-500 rounded-xl text-white hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
