import { create } from 'zustand'
import api from '../services/api'
import { tr } from '../services/i18n'

export interface Message {
  id?: number
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  action_data?: any
  steps?: any[]
  task_stats?: any
}

export interface ChatSession {
  id: string
  documentId: string | null
  documentName: string
  fileIds: string[]
  templateId: string | null
  messages: Message[]
  lastMessage?: string
  createdAt: number
  updatedAt: number
}

interface ChatStore {
  sessions: ChatSession[]
  activeSessionId: string | null
  isMinimized: boolean
  isLoading: boolean
  isStreaming: boolean  // 是否正在流式输出
  abortController: AbortController | null  // 用于取消流式请求

  // 从数据库加载所有会话
  loadSessions: () => Promise<void>
  
  // 加载单个会话的消息
  loadSessionMessages: (sessionId: string, force?: boolean) => Promise<void>
  
  // 创建新会话
  createSession: (documentId: string | null, documentName: string, fileIds?: string[], templateId?: string | null) => Promise<string>
  
  // 获取会话
  getSession: (sessionId: string) => ChatSession | undefined
  
  // 添加消息
  addMessage: (sessionId: string, message: Omit<Message, 'timestamp'>) => Promise<number | null>
  
  // 更新消息
  updateMessage: (sessionId: string, messageId: number, message: Omit<Message, 'timestamp'>) => Promise<void>
  
  // 设置活跃会话
  setActiveSession: (sessionId: string | null) => void
  
  // 删除会话
  deleteSession: (sessionId: string) => Promise<void>
  
  // 更新会话的文件选择
  updateSessionFiles: (sessionId: string, fileIds: string[], templateId: string | null) => Promise<void>
  
  // 最小化状态
  setMinimized: (minimized: boolean) => void

  // 流式控制
  setStreaming: (isStreaming: boolean, abortController?: AbortController | null) => void
  stopStreaming: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  isMinimized: true,
  isLoading: false,
  isStreaming: false,
  abortController: null,

  loadSessions: async () => {
    set({ isLoading: true })
    try {
      const response = await api.get('/conversations/')
      const sessions: ChatSession[] = response.data.map((conv: any) => ({
        id: conv.id,
        documentId: conv.file_ids?.[0] || null,
        documentName: conv.title || tr('新对话', 'New Chat', '新しい会話'),
        fileIds: conv.file_ids || [],
        templateId: conv.template_id,
        messages: [],
        lastMessage: conv.last_message || '',
        createdAt: new Date(conv.created_at).getTime(),
        updatedAt: new Date(conv.updated_at).getTime()
      }))
      set({ sessions })

      // 自动设置最新会话为活跃会话
      const currentActive = get().activeSessionId
      if (!currentActive && sessions.length > 0) {
        set({ activeSessionId: sessions[0].id })
        await get().loadSessionMessages(sessions[0].id)
      }
    } catch (error) {
      console.error('Failed to load sessions:', error)
    } finally {
      set({ isLoading: false })
    }
  },

  loadSessionMessages: async (sessionId: string, force: boolean = false) => {
    // 检查是否已经加载过消息
    const currentSession = get().sessions.find(s => s.id === sessionId)
    if (!force && currentSession && currentSession.messages.length > 0) {
      // 消息已存在，跳过加载
      return
    }

    try {
      const response = await api.get(`/conversations/${sessionId}`)
      const conv = response.data

      const messages: Message[] = conv.messages.map((msg: any) => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp || Date.now(),
        action_data: msg.action_data,
        steps: msg.steps,
        task_stats: msg.task_stats
      }))

      set(state => {
        // 查找并更新会话
        const updatedSessions = state.sessions.map(s =>
          s.id === sessionId
            ? {
                ...s,
                messages,
                fileIds: conv.file_ids || [],
                templateId: conv.template_id,
                documentName: conv.title || s.documentName,
                lastMessage: conv.last_message || s.lastMessage
              }
            : s
        )

        // 如果会话不在列表中，添加它
        const sessionExists = state.sessions.some(s => s.id === sessionId)
        if (!sessionExists) {
          updatedSessions.unshift({
            id: conv.id,
            documentId: conv.file_ids?.[0] || null,
            documentName: conv.title || tr('新对话', 'New Chat', '新しい会話'),
            fileIds: conv.file_ids || [],
            templateId: conv.template_id,
            messages,
            lastMessage: conv.last_message || '',
            createdAt: new Date(conv.created_at).getTime(),
            updatedAt: new Date(conv.updated_at).getTime()
          })
        }

        return { sessions: updatedSessions }
      })
    } catch (error) {
      console.error('Failed to load session messages:', error)
    }
  },

  createSession: async (documentId, documentName, fileIds = [], templateId = null) => {
    const sessionId = `chat-${Date.now()}`
    
    try {
      await api.post('/conversations/', {
        id: sessionId,
        title: documentName,
        file_ids: fileIds,
        template_id: templateId
      })
      
      const newSession: ChatSession = {
        id: sessionId,
        documentId,
        documentName,
        fileIds,
        templateId,
        messages: [],
        createdAt: Date.now(),
        updatedAt: Date.now()
      }
      
      set(state => ({
        sessions: [newSession, ...state.sessions.filter(s => s.id !== sessionId)],
        activeSessionId: sessionId
      }))
    } catch (error) {
      console.error('Failed to create session:', error)
    }
    
    return sessionId
  },

  getSession: (sessionId) => {
    return get().sessions.find(s => s.id === sessionId)
  },

  addMessage: async (sessionId, message) => {
    const newMessage: Message = {
      ...message,
      timestamp: Date.now()
    }
    
    // 先更新本地状态
    set(state => ({
      sessions: state.sessions.map(s => 
        s.id === sessionId 
          ? { ...s, messages: [...s.messages, newMessage], updatedAt: Date.now() }
          : s
      )
    }))
    
    // 保存到数据库并返回消息ID
    try {
      const response = await api.post(`/conversations/${sessionId}/messages`, {
        role: message.role,
        content: message.content,
        action_data: message.action_data,
        steps: (message as any).steps
      })
      return response.data.id
    } catch (error) {
      console.error('Failed to save message:', error)
      return null
    }
  },

  updateMessage: async (sessionId, messageId, message) => {
    // 更新本地状态
    set(state => ({
      sessions: state.sessions.map(s =>
        s.id === sessionId
          ? {
              ...s,
              messages: s.messages.map(m =>
                m.id === messageId
                  ? { ...m, content: message.content, action_data: message.action_data, steps: (message as any).steps || m.steps }
                  : m
              ),
              updatedAt: Date.now()
            }
          : s
      )
    }))

    // 更新数据库
    try {
      await api.put(`/conversations/${sessionId}/messages/${messageId}`, {
        role: message.role || 'assistant',
        content: message.content,
        action_data: message.action_data,
        steps: (message as any).steps
      })
    } catch (error) {
      console.error('Failed to update message:', error)
    }
  },

  setActiveSession: (sessionId) => {
    set({ activeSessionId: sessionId })
  },

  deleteSession: async (sessionId) => {
    try {
      await api.delete(`/conversations/${sessionId}`)
      set(state => ({
        sessions: state.sessions.filter(s => s.id !== sessionId),
        activeSessionId: state.activeSessionId === sessionId 
          ? (state.sessions.length > 1 ? state.sessions.find(s => s.id !== sessionId)?.id || null : null)
          : state.activeSessionId
      }))
    } catch (error) {
      console.error('Failed to delete session:', error)
    }
  },

  updateSessionFiles: async (sessionId, fileIds, templateId) => {
    // 更新本地状态
    set(state => ({
      sessions: state.sessions.map(s => 
        s.id === sessionId 
          ? { ...s, fileIds, templateId, updatedAt: Date.now() }
          : s
      )
    }))
    
    // 保存到数据库
    try {
      await api.put(`/conversations/${sessionId}`, {
        file_ids: fileIds,
        template_id: templateId
      })
    } catch (error) {
      console.error('Failed to update session:', error)
    }
  },

  setMinimized: (minimized) => {
    set({ isMinimized: minimized })
  },

  setStreaming: (isStreaming, abortController = null) => {
    set({ isStreaming, abortController })
  },

  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
      set({ isStreaming: false, abortController: null })
    }
  }
}))
