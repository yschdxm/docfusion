import { create } from 'zustand'
import api from '../services/api'

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
        documentName: conv.title || '新对话',
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

      // 检查是否有confirm_fill类型的消息，如果有，从任务API获取最新状态
      for (let i = 0; i < messages.length; i++) {
        const msg = messages[i]
        if (msg.role === 'assistant' && msg.action_data?.action_type === 'confirm_fill') {
          // 使用task_id查询任务状态
          let taskId = msg.action_data?.task_id
          
          // 如果没有task_id，尝试从所有任务中查找最近的相关任务
          if (!taskId) {
            try {
              const tasksResponse = await api.get('/table-fill/tasks?limit=10')
              const tasks = tasksResponse.data
              // 查找最近的processing或completed任务
              const recentTask = tasks.find((t: any) => 
                t.status === 'processing' || 
                (t.status === 'completed' && t.result?.source === 'agent')
              )
              if (recentTask) {
                taskId = recentTask.id
              }
            } catch (e) {
              console.log('Failed to get tasks:', e)
            }
          }
          
          if (taskId) {
            try {
              const taskResponse = await api.get(`/table-fill/tasks/${taskId}`)
              const task = taskResponse.data
              
              if (task.status === 'completed') {
                const filledDocId = task.filled_doc_id || task.result?.filled_doc_id
                messages[i] = {
                  ...msg,
                  content: '表格填写完成！您可以下载填写后的文件。',
                  action_data: {
                    action_type: 'completed',
                    title: '表格填写完成',
                    description: '已完成',
                    progress: 100,
                    result: {
                      filled_file_id: filledDocId,
                      filled_file_url: filledDocId ? `/api/v1/documents/${filledDocId}/download` : null
                    }
                  }
                }
              } else if (task.status === 'failed') {
                messages[i] = {
                  ...msg,
                  content: `表格填写失败：${task.error || task.result?.error || '未知错误'}`,
                  action_data: {
                    action_type: 'failed',
                    title: '表格填写失败',
                    description: task.error || task.result?.error || '未知错误'
                  }
                }
              } else if (task.status === 'processing') {
                const progress = parseInt(task.result?.progress) || 0
                const currentStep = task.result?.current_step || '处理中...'
                messages[i] = {
                  ...msg,
                  action_data: {
                    ...msg.action_data,
                    action_type: 'executing',
                    progress: progress,
                    description: currentStep
                  }
                }
              }
            } catch (e) {
              console.log('Task not found or error:', e)
            }
          }
        }
      }

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
            documentName: conv.title || '新对话',
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
