/**
 * Agent流式API服务
 *
 * 使用 @microsoft/fetch-event-source 处理SSE流式响应
 * 支持多并发连接（每个会话独立的SSE连接）
 * 支持断线重连：通过 task_id 接入已有任务，不重启
 */

import { fetchEventSource, EventSourceMessage } from '@microsoft/fetch-event-source'
import { getAuthToken } from './auth'
import { tr } from './i18n'

export interface AgentStreamRequest {
  message: string
  file_ids: string[]
  template_id?: string | null
  conversation_id?: string | null
  task_type?: 'auto' | 'fill_table' | 'query' | 'operation'
  task_id?: string  // 重连时携带
}

export interface AgentEvent {
  event_type: string
  step_id?: string
  timestamp: string
  data: Record<string, any>
}

export interface AgentStep {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'data_retrieval' | 'fill_table' | 'assistant_reply' | 'agent_delegation'
  name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'error'
  progress: number
  toolName?: string
  toolParams?: Record<string, any>
  toolResult?: Record<string, any>
  thinkingContent?: string
  errorMessage?: string
  agentName?: string
  children?: AgentStep[]
  streamingReply?: string
}

export interface TaskStats {
  duration_ms: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  reasoning_tokens: number
  llm_calls: number
  iterations: number
}

/** 单个SSE连接的状态 */
interface ConnectionState {
  connectionId: string
  sessionId: string
  taskId: string | null
  steps: Map<string, AgentStep>
  currentAgentName: string | null
  agentParentStepId: string | null
  replyCounter: number
  completedFired: boolean
  taskEnded: boolean
  cancelled: boolean  // 显式取消标记，cancelSession 设为 true
  abortController: AbortController
  reconnectAttempts: number
  maxReconnectAttempts: number
  // 回调
  onEvent: (event: AgentEvent, steps: AgentStep[]) => void
  onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string; task_stats?: TaskStats; _replayDone?: boolean }) => void
  onError: (error: string) => void
  // 重连用的请求参数
  request: AgentStreamRequest
  existingTaskId?: string
}

class AgentStreamService {
  private static TASK_ID_PREFIX = 'agent_task_'
  private connections: Map<string, ConnectionState> = new Map()
  private connectionCounter = 0

  /**
   * 持久化 session → task_id + startedAt 映射到 localStorage
   */
  private persistTaskId(sessionId: string, taskId: string, startedAt?: number): void {
    try {
      const existing = this._loadTaskData(sessionId)
      localStorage.setItem(AgentStreamService.TASK_ID_PREFIX + sessionId, JSON.stringify({
        taskId,
        timestamp: Date.now(),
        startedAt: startedAt || existing?.startedAt || Date.now(),
      }))
    } catch { /* localStorage 不可用时静默 */ }
  }

  /**
   * 存储任务开始时间到 localStorage
   * 如果已有记录则更新，否则创建新记录（taskId 暂为空，后续 persistTaskId 会补上）
   */
  persistTaskStartTime(sessionId: string, time: number): void {
    try {
      const existing = this._loadTaskData(sessionId)
      const data = existing || { taskId: '', timestamp: Date.now() }
      data.startedAt = time
      localStorage.setItem(AgentStreamService.TASK_ID_PREFIX + sessionId, JSON.stringify(data))
    } catch { /* */ }
  }

  /**
   * 从 localStorage 恢复 session 对应的 task_id
   */
  getRunningTaskId(sessionId: string): string | null {
    const data = this._loadTaskData(sessionId)
    return data?.taskId || null
  }

  /**
   * 获取任务开始时间（从 localStorage 读取，跨组件生命周期存活）
   */
  getTaskStartTime(sessionId: string): number | null {
    const data = this._loadTaskData(sessionId)
    return data?.startedAt || null
  }

  /** 从 localStorage 加载任务数据 */
  private _loadTaskData(sessionId: string): { taskId: string; timestamp: number; startedAt?: number } | null {
    try {
      const raw = localStorage.getItem(AgentStreamService.TASK_ID_PREFIX + sessionId)
      if (!raw) return null
      const data = JSON.parse(raw)
      // 超过10分钟的任务认为已过期
      if (Date.now() - data.timestamp > 10 * 60 * 1000) {
        this.clearPersistedTask(sessionId)
        return null
      }
      return data
    } catch {
      return null
    }
  }

  /** 清除 localStorage 中的 task_id */
  clearPersistedTask(sessionId: string): void {
    try {
      localStorage.removeItem(AgentStreamService.TASK_ID_PREFIX + sessionId)
    } catch { /* */ }
  }

  /**
   * 彻底取消任务（用户主动停止）
   * 调用后端取消接口 + 清除 localStorage + 断开 SSE
   */
  async stopTask(sessionId: string): Promise<void> {
    const taskId = this.getRunningTaskId(sessionId)

    // 调用后端取消接口
    if (taskId) {
      try {
        const token = getAuthToken()
        await fetch(`/api/v1/agent/stream/${taskId}`, {
          method: 'DELETE',
          headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        })
      } catch (e) {
        console.warn('[SSE] 取消后端任务失败:', e)
      }
    }

    // 清除 localStorage
    this.clearPersistedTask(sessionId)

    // 断开前端 SSE 连接
    this.cancelSession(sessionId)
  }

  /**
   * 启动一个SSE连接（新任务或重连）
   * 返回 connectionId，用于暂停/恢复/取消
   */
  startStream(
    sessionId: string,
    request: AgentStreamRequest,
    onEvent: (event: AgentEvent, steps: AgentStep[]) => void,
    onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string }) => void,
    onError: (error: string) => void,
    existingTaskId?: string
  ): string {
    const connectionId = `conn_${++this.connectionCounter}_${sessionId}`

    // 如果是新任务（非重连），先清除旧的 task_id
    if (!existingTaskId) {
      this.clearPersistedTask(sessionId)
    }

    // 如果该 session 已有连接，先取消旧的
    this.cancelSession(sessionId)

    const state: ConnectionState = {
      connectionId,
      sessionId,
      taskId: existingTaskId || null,
      steps: new Map(),
      currentAgentName: null,
      agentParentStepId: null,
      replyCounter: 0,
      completedFired: false,
      taskEnded: false,
      cancelled: false,
      abortController: new AbortController(),
      reconnectAttempts: 0,
      maxReconnectAttempts: 3,
      onEvent,
      onComplete,
      onError,
      request,
      existingTaskId,
    }

    this.connections.set(connectionId, state)
    this._doStream(state)
    return connectionId
  }

  /**
   * 暂停回调（切换会话时调用，SSE连接不断开）
   * 将回调替换为空操作，任务继续在后台运行
   */
  pauseConnection(connectionId: string): void {
    const state = this.connections.get(connectionId)
    if (!state) return
    state.onEvent = () => {}
    state.onComplete = () => {}
    state.onError = () => {}
  }

  /**
   * 恢复回调（回到会话时调用）
   * 替换回调为新的回调，用 task_id 重连SSE以获取最新事件
   */
  resumeConnection(
    connectionId: string,
    onEvent: (event: AgentEvent, steps: AgentStep[]) => void,
    onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string }) => void,
    onError: (error: string) => void
  ): void {
    const state = this.connections.get(connectionId)
    if (!state) return
    state.onEvent = onEvent
    state.onComplete = onComplete
    state.onError = onError
  }

  /**
   * 取消某个 session 的所有连接（彻底断开）
   */
  cancelSession(sessionId: string): void {
    for (const [connId, state] of this.connections) {
      if (state.sessionId === sessionId) {
        state.cancelled = true
        state.abortController.abort()
        this.connections.delete(connId)
      }
    }
    // 注意：不清除 localStorage 中的 task_id
    // 因为 cancelSession 只是断开前端 SSE 连接，后端任务仍在运行
    // 用户回到会话时需要靠 task_id 重连
  }

  /**
   * 取消所有连接
   */
  cancelAll(): void {
    for (const [, state] of this.connections) {
      state.cancelled = true
      state.abortController.abort()
    }
    this.connections.clear()
  }

  /** 获取某个 session 是否有活跃连接 */
  hasActiveConnection(sessionId: string): boolean {
    for (const [, state] of this.connections) {
      if (state.sessionId === sessionId && !state.taskEnded) {
        return true
      }
    }
    return false
  }

  /** 获取某个 session 的活跃连接 ID */
  getActiveConnectionId(sessionId: string): string | null {
    for (const [connId, state] of this.connections) {
      if (state.sessionId === sessionId && !state.taskEnded) {
        return connId
      }
    }
    return null
  }

  /** 获取连接当前的 steps */
  getConnectionSteps(connectionId: string): AgentStep[] {
    const state = this.connections.get(connectionId)
    if (!state) return []
    return Array.from(state.steps.values())
  }

  /** 获取连接的 taskId */
  getConnectionTaskId(connectionId: string): string | null {
    const state = this.connections.get(connectionId)
    return state?.taskId || null
  }

  /**
   * 执行SSE流式连接
   */
  private async _doStream(state: ConnectionState): Promise<void> {
    const requestBody: Record<string, any> = { ...state.request }
    if (state.taskId) {
      requestBody.task_id = state.taskId
      console.log(`[SSE][${state.connectionId}] 重连任务: ${state.taskId} (第${state.reconnectAttempts}次)`)
    }

    try {
      await fetchEventSource('/api/v1/agent/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAuthToken() ? { 'Authorization': `Bearer ${getAuthToken()}` } : {}),
        },
        body: JSON.stringify(requestBody),
        signal: state.abortController.signal,

        onopen: async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`)
          }
        },

        onmessage: (ev: EventSourceMessage) => {
          const event = this._parseEvent(ev)
          if (!event) return

          if (event.data.task_id && !state.taskId) {
            state.taskId = event.data.task_id
            this.persistTaskId(state.sessionId, event.data.task_id)
            console.log(`[SSE][${state.connectionId}] 获取 task_id: ${state.taskId}`)
          }

          this._processEvent(state, event)
          const stepsArray = Array.from(state.steps.values())
          state.onEvent(event, stepsArray)
          this._logEvent(state.connectionId, event, state.steps)

          if (this._isChildAgentEvent(state, event) && event.event_type === 'assistant_message') return
          if (this._isChildAgentEvent(state, event)) return

          if (event.event_type === 'completed') {
            if (state.completedFired) return
            state.completedFired = true
            state.taskEnded = true
            this.clearPersistedTask(state.sessionId)
            state.onComplete({
              success: true,
              message: event.data.message || tr('任务完成', 'Task completed', 'タスク完了'),
              output_file_id: event.data.result?.output_file_id,
              download_url: event.data.result?.download_url,
              task_stats: event.data.result?.task_stats,
            })
            state.abortController.abort()
          } else if (event.event_type === 'failed') {
            if (state.completedFired) return
            state.completedFired = true
            state.taskEnded = true
            this.clearPersistedTask(state.sessionId)
            const errorMsg = event.data.error || tr('任务执行失败', 'Task execution failed', 'タスク実行失敗')
            state.onError(errorMsg)
            state.abortController.abort()
          } else if (event.event_type === 'cancelled') {
            if (state.completedFired) return
            state.completedFired = true
            state.taskEnded = true
            this.clearPersistedTask(state.sessionId)
            state.onError(event.data.message || tr('任务已取消', 'Task cancelled', 'タスクがキャンセルされました'))
            state.abortController.abort()
          }
        },

        onclose: () => {
          // 流正常关闭。如果 completedFired 未触发（回放跳过了终端事件），
          // 回放结束但未收到终端事件（任务已在断连期间完成）
          // 通知前端清理流式状态，但标记 _replayDone 以保留统计显示
          if (!state.completedFired && !state.cancelled) {
            state.completedFired = true
            state.taskEnded = true
            this.clearPersistedTask(state.sessionId)
            state.onComplete({
              success: true,
              message: '',
              _replayDone: true,
            })
          }
        },

        onerror: (_err) => {
          // 显式取消或任务已结束 → 停止重试
          if (state.cancelled || state.taskEnded) {
            return null
          }
          // 重连次数耗尽 → 停止重试并通知
          if (state.reconnectAttempts >= state.maxReconnectAttempts) {
            state.onError(tr(`连接中断，重连失败(${state.reconnectAttempts}次)`, `Connection lost, reconnect failed (${state.reconnectAttempts} times)`, `接続切断、再接続失敗（${state.reconnectAttempts}回）`))
            return null
          }
          // 继续重试
          state.reconnectAttempts++
          console.warn(`[SSE][${state.connectionId}] 连接中断，第${state.reconnectAttempts}次重试`)
          return 5000  // 5秒后由 fetchEventSource 内部重试
        },
      })
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err)

      // 显式取消（cancelSession / stopTask）— 静默
      if (state.cancelled) {
        // 静默
      }
      // 用户 abort
      else if (errMsg.includes('abort') || errMsg.includes('AbortError')) {
        // handled in finally
      }
      // 任务已正常结束
      else if (state.taskEnded) {
        // handled in finally
      }
      // onerror 返回 null 导致的最终退出，不重复通知
      else if (state.reconnectAttempts >= state.maxReconnectAttempts) {
        // 已在 onerror 中通知
      }
      // 其他意外错误
      else {
        state.onError(tr(`连接中断: ${errMsg}`, `Connection lost: ${errMsg}`, `接続切断: ${errMsg}`))
      }
    } finally {
      if (state.taskEnded) {
        this.clearPersistedTask(state.sessionId)
        this.connections.delete(state.connectionId)
      }
    }
  }

  private _parseEvent(ev: EventSourceMessage): AgentEvent | null {
    try {
      const parsedData = JSON.parse(ev.data)
      return {
        event_type: parsedData.event_type || ev.event,
        step_id: parsedData.step_id,
        timestamp: parsedData.timestamp || new Date().toISOString(),
        data: parsedData,
      }
    } catch {
      console.warn('[SSE] JSON解析失败:', ev.data.substring(0, 100))
      return null
    }
  }

  private _logEvent(connectionId: string, event: AgentEvent, steps: Map<string, AgentStep>): void {
    const d = event.data
    switch (event.event_type) {
      case 'thinking_start':
        console.log(`[SSE][${connectionId}] 思考开始${d.agent_name ? ` (${d.agent_name})` : ''}`)
        break
      case 'thinking_end': {
        const thinkingStep = steps.get(event.step_id || '')
        const tc = thinkingStep?.thinkingContent
        const summary = tc ? tc.substring(0, 150) + (tc.length > 150 ? '...' : '') : ''
        console.log(`[SSE][${connectionId}] 思考完成${summary ? ': ' + summary : ''}`)
        break
      }
      case 'tool_call':
        console.log(`[SSE][${connectionId}] 工具调用: ${d.tool_name}`)
        break
      case 'tool_result': {
        const rStr = JSON.stringify(d.result ?? '')
        const rSum = rStr.substring(0, 100) + (rStr.length > 100 ? '...' : '')
        console.log(`[SSE][${connectionId}] 工具结果: ${d.tool_name} → ${rSum}`)
        break
      }
      case 'step_start':
        if (d.is_delegation_start) {
          console.log(`[SSE][${connectionId}] 委派开始: ${d.step_name}`)
        }
        break
      case 'step_end':
        if (d.is_delegation_end) {
          console.log(`[SSE][${connectionId}] 委派结束`)
        }
        break
      case 'assistant_message': {
        const msg = d.message || ''
        const src = d.agent_name ? tr('子Agent', 'Sub-Agent', 'サブAgent') : tr('主Agent', 'Main Agent', 'メインAgent')
        console.log(`[SSE][${connectionId}] 中途回复(${src}): ${msg.substring(0, 100)}${msg.length > 100 ? '...' : ''}`)
        break
      }
      case 'content_end':
        console.log(`[SSE][${connectionId}] 回复完成`)
        break
      case 'completed':
        console.log(`[SSE][${connectionId}] 任务完成`)
        break
      case 'failed':
        console.log(`[SSE][${connectionId}] 任务失败: ${(d.error || '').substring(0, 150)}`)
        break
    }
  }

  private _isChildAgentEvent(state: ConnectionState, event: AgentEvent): boolean {
    if (event.data.is_delegation_end) return false
    return !!(event.data.agent_name && state.currentAgentName && event.data.agent_name === state.currentAgentName)
  }

  private _findOrCreateChildStep(
    parentStep: AgentStep, stepId: string, type: AgentStep['type'], name: string, description: string
  ): AgentStep {
    if (!parentStep.children) parentStep.children = []
    const existing = parentStep.children.find(c => c.id === stepId)
    if (existing) return existing
    const child: AgentStep = { id: stepId, type, name, description, status: 'running', progress: 0 }
    parentStep.children.push(child)
    return child
  }

  private _handleChildEvent(state: ConnectionState, event: AgentEvent): void {
    if (!state.agentParentStepId) return
    const parentStep = state.steps.get(state.agentParentStepId)
    if (!parentStep) return
    const stepId = event.step_id || `child_step_${Date.now()}`

    switch (event.event_type) {
      case 'step_start': {
        const stepType = this._inferStepType(event.data.step_name || '')
        this._findOrCreateChildStep(parentStep, stepId, stepType, event.data.step_name || tr('步骤', 'Step', 'ステップ'), event.data.description || '')
        break
      }
      case 'step_progress': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) child.progress = event.data.progress || 0
        break
      }
      case 'step_end': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) { child.status = 'completed'; child.progress = 100 }
        break
      }
      case 'thinking_start': {
        const child = this._findOrCreateChildStep(parentStep, stepId, 'thinking', event.data.message || tr('思考中', 'Thinking', '思考中'), tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'))
        child.status = 'running'
        if (!child.thinkingContent) child.thinkingContent = ''
        break
      }
      case 'thinking_chunk': {
        const child = this._findOrCreateChildStep(parentStep, stepId, 'thinking', tr('思考中', 'Thinking', '思考中'), tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'))
        child.thinkingContent = (child.thinkingContent || '') + (event.data.content || '')
        break
      }
      case 'thinking_end': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) { child.status = 'completed'; child.progress = 100; child.name = tr('思考完成', 'Thinking complete', '思考完了') }
        break
      }
      case 'tool_call': {
        const child = this._findOrCreateChildStep(parentStep, stepId, 'tool_call', tr(`调用 ${event.data.tool_name}`, `Calling ${event.data.tool_name}`, `${event.data.tool_name} を呼び出し`), tr(`执行工具: ${event.data.tool_name}`, `Executing tool: ${event.data.tool_name}`, `ツール実行: ${event.data.tool_name}`))
        child.toolName = event.data.tool_name
        child.toolParams = event.data.parameters
        child.status = 'running'
        child.progress = 50
        break
      }
      case 'tool_result': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) { child.status = 'completed'; child.progress = 100; child.toolResult = event.data.result }
        break
      }
      case 'tool_error': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) { child.status = 'error'; child.errorMessage = event.data.error }
        break
      }
      case 'content_chunk':
        if (event.data.content) {
          if (!parentStep.streamingReply) parentStep.streamingReply = ''
          parentStep.streamingReply += event.data.content
        }
        break
      case 'content_end':
        parentStep.streamingReply = ''
        break
      case 'assistant_message': {
        const msg = event.data.message || ''
        if (msg) {
          parentStep.children?.push({
            id: `reply_${++state.replyCounter}`, type: 'assistant_reply', name: tr('AI回复', 'AI Reply', 'AI応答'),
            description: msg, status: 'completed', progress: 100, thinkingContent: msg,
          })
        }
        break
      }
      case 'completed':
      case 'failed': {
        parentStep.children?.forEach(c => {
          if (c.status === 'running') {
            c.status = event.event_type === 'completed' ? 'completed' : 'error'
            c.progress = 100
          }
        })
        break
      }
    }
  }

  private _processEvent(state: ConnectionState, event: AgentEvent): void {
    if (event.data.is_delegation_end) {
      const delegationStep = state.steps.get(event.step_id || '')
      if (delegationStep) { delegationStep.status = 'completed'; delegationStep.progress = 100 }
      state.currentAgentName = null
      state.agentParentStepId = null
      return
    }

    if (this._isChildAgentEvent(state, event)) {
      this._handleChildEvent(state, event)
      return
    }

    const stepId = event.step_id || `step_${Date.now()}`

    switch (event.event_type) {
      case 'step_start':
        if (event.data.is_delegation_start) {
          state.currentAgentName = event.data.agent_name
          state.agentParentStepId = stepId
          state.steps.set(stepId, {
            id: stepId, type: 'agent_delegation', name: event.data.step_name,
            description: event.data.description || '', status: 'running', progress: 0,
            children: [], agentName: event.data.agent_name,
          })
        } else {
          state.steps.set(stepId, {
            id: stepId, type: this._inferStepType(event.data.step_name), name: event.data.step_name,
            description: event.data.description, status: 'running', progress: 0,
          })
        }
        break
      case 'step_progress': { const s = state.steps.get(stepId); if (s) s.progress = event.data.progress || 0; break }
      case 'step_end': { const s = state.steps.get(stepId); if (s) { s.status = 'completed'; s.progress = 100 } break }
      case 'tool_call':
        state.steps.set(stepId, {
          id: stepId, type: 'tool_call', name: tr(`调用 ${event.data.tool_name}`, `Calling ${event.data.tool_name}`, `${event.data.tool_name} を呼び出し`),
          description: tr(`执行工具: ${event.data.tool_name}`, `Executing tool: ${event.data.tool_name}`, `ツール実行: ${event.data.tool_name}`), status: 'running', progress: 50,
          toolName: event.data.tool_name, toolParams: event.data.parameters,
        })
        break
      case 'tool_result': { const s = state.steps.get(stepId); if (s) { s.status = 'completed'; s.progress = 100; s.toolResult = event.data.result } break }
      case 'tool_error': { const s = state.steps.get(stepId); if (s) { s.status = 'error'; s.errorMessage = event.data.error } break }
      case 'thinking_start': {
        const existing = state.steps.get(stepId)
        if (existing) { existing.status = 'running'; existing.name = event.data.message || existing.name }
        else { state.steps.set(stepId, { id: stepId, type: 'thinking', name: event.data.message || tr('思考中', 'Thinking', '思考中'), description: tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'), status: 'running', progress: 0, thinkingContent: '' }) }
        break
      }
      case 'thinking_chunk': {
        let s = state.steps.get(stepId)
        if (!s) { s = { id: stepId, type: 'thinking', name: tr('思考中', 'Thinking', '思考中'), description: tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'), status: 'running', progress: 0, thinkingContent: '' }; state.steps.set(stepId, s) }
        s.thinkingContent += event.data.content || ''
        break
      }
      case 'thinking_end': { const s = state.steps.get(stepId); if (s) { s.status = 'completed'; s.progress = 100; s.name = tr('思考完成', 'Thinking complete', '思考完了') } break }
      case 'content_chunk': break
      case 'content_end': { const s = state.steps.get(stepId); if (s) { s.status = 'completed'; s.progress = 100 } break }
      case 'assistant_message': state.steps.clear(); break
      case 'data_retrieval_start':
        state.steps.set(stepId, { id: stepId, type: 'data_retrieval', name: tr(`查询 ${event.data.source}`, `Query ${event.data.source}`, `${event.data.source} を検索`), description: tr(`从 ${event.data.source} 检索数据`, `Retrieving data from ${event.data.source}`, `${event.data.source} からデータを取得`), status: 'running', progress: 0 })
        break
      case 'data_retrieval_progress': { const s = state.steps.get(stepId); if (s) s.progress = event.data.records_found > 0 ? 50 : 0; break }
      case 'fill_table_progress': {
        let s = state.steps.get(stepId)
        if (!s) { s = { id: stepId, type: 'fill_table', name: tr('填写表格', 'Filling table', '表を入力'), description: tr('正在将数据填入模板', 'Filling data into template', 'データをテンプレートに入力中'), status: 'running', progress: 0 }; state.steps.set(stepId, s) }
        s.progress = event.data.progress || 0
        break
      }
      case 'stats_update': break  // 统计更新事件，由onEvent回调处理
      case 'completed': { const s = state.steps.get(stepId); if (s && s.type === 'thinking') { s.status = 'completed'; s.progress = 100 } break }
      case 'failed': {
        const fid = event.step_id || `step_fail_${Date.now()}`
        state.steps.set(fid, { id: fid, type: 'thinking', name: tr('任务失败', 'Task failed', 'タスク失敗'), description: event.data.error || tr('任务执行失败', 'Task execution failed', 'タスク実行失敗'), status: 'error', progress: 0, errorMessage: event.data.error })
        break
      }
      case 'error': {
        const eid = event.step_id || `step_error_${Date.now()}`
        const e = state.steps.get(eid)
        if (e) { e.status = 'error'; e.errorMessage = event.data.error || event.data.message || tr('发生错误', 'An error occurred', 'エラーが発生しました') }
        else { state.steps.set(eid, { id: eid, type: 'thinking', name: tr('错误', 'Error', 'エラー'), description: event.data.error || event.data.message || tr('发生错误', 'An error occurred', 'エラーが発生しました'), status: 'error', progress: 0, errorMessage: event.data.error || event.data.message }) }
        break
      }
    }
  }

  private _inferStepType(stepName: string): AgentStep['type'] {
    if (stepName.includes('查询') || stepName.includes('检索')) return 'data_retrieval'
    if (stepName.includes('填写') || stepName.includes('填表')) return 'fill_table'
    if (stepName.includes('调用')) return 'tool_call'
    if (stepName.includes('思考')) return 'thinking'
    return 'thinking'
  }
}

export const agentStreamService = new AgentStreamService()
export default agentStreamService
