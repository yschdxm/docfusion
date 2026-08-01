/**
 * Agent流式API服务
 *
 * 架构（与后端 TaskEventLog 对应）：
 * - 每个任务一份有序事件日志，SSE 事件带单调递增 seq（SSE 标准 id: 字段）
 * - 页面级重连（切会话/刷新）：从 seq=0 全量回放重建步骤树，消息幂等由页面守卫
 * - 连接级重试（网络抖动）：task_id + lastSeq 增量续传（请求体 last_event_id）
 * - 显式连接状态机：idle → connecting → streaming → done | error
 * - 连接断开不影响后端任务；任务状态可通过 GET /agent/tasks/{id}/status 权威查询
 *
 * 步骤树重建逻辑与后端 agent_persistence.StepAccumulator 同构（修改时需同步）。
 */

import { fetchEventSource, EventSourceMessage } from '@microsoft/fetch-event-source'
import { getAuthToken } from './auth'
import { tr } from './i18n'

export interface AgentStreamRequest {
  message: string
  file_ids: string[]
  template_id?: string | null
  conversation_id?: string | null
  task_type?: 'auto' | 'fill_table' | 'fill_form' | 'query' | 'operation'
  task_id?: string  // 重连时携带
  last_event_id?: number  // 断点续传
}

export interface AgentEvent {
  event_type: string
  step_id?: string
  timestamp: string
  seq?: number
  data: Record<string, any>
}

export interface AgentStep {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'data_retrieval' | 'fill_table' | 'fill_form' | 'assistant_reply' | 'agent_delegation'
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

export interface StreamCompleteResult {
  success: boolean
  message: string
  output_file_id?: string
  download_url?: string
  task_stats?: TaskStats
  /** 任务在断连期间已完成，结果来自状态查询而非事件流（消息已在 DB 中，页面不应重复添加） */
  fromStatusQuery?: boolean
}

export interface TaskStatusResponse {
  task_id: string
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'not_found'
  last_seq: number
  conversation_id?: string | null
  result?: Record<string, any> | null
}

/** 连接状态机 */
type ConnectionStatus = 'connecting' | 'streaming' | 'done' | 'error'

/** 单个SSE连接的状态 */
interface ConnectionState {
  connectionId: string
  sessionId: string
  taskId: string | null
  lastSeq: number           // 已应用的最大事件序号（幂等依据）
  steps: Map<string, AgentStep>
  status: ConnectionStatus
  cancelled: boolean        // 显式取消标记（cancelSession/stopTask 设置）
  abortController: AbortController
  reconnectAttempts: number
  // 回调
  onEvent: (event: AgentEvent, steps: AgentStep[]) => void
  onComplete: (result: StreamCompleteResult) => void
  onError: (error: string) => void
  // 请求参数（重连时重建 body）
  request: AgentStreamRequest
  currentAgentName: string | null
  agentParentStepId: string | null
  replyCounter: number
}

const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_BASE_DELAY_MS = 2000
/** localStorage 中任务数据的过期时间，与后端 TASK_TTL(10分钟) 对齐 */
const TASK_DATA_TTL_MS = 10 * 60 * 1000

class AgentStreamService {
  private static TASK_ID_PREFIX = 'agent_task_'
  private connections: Map<string, ConnectionState> = new Map()
  private connectionCounter = 0
  private lastPersistTime = 0

  // ==================== localStorage 持久化 ====================

  /**
   * 持久化 session → { taskId, startedAt } 映射到 localStorage
   */
  private persistTaskData(sessionId: string, patch: { taskId?: string; startedAt?: number }): void {
    try {
      const existing = this._loadTaskData(sessionId)
      const data = {
        taskId: patch.taskId ?? existing?.taskId ?? '',
        startedAt: patch.startedAt ?? existing?.startedAt ?? Date.now(),
        timestamp: Date.now(),
      }
      localStorage.setItem(AgentStreamService.TASK_ID_PREFIX + sessionId, JSON.stringify(data))
    } catch { /* localStorage 不可用时静默 */ }
  }

  /**
   * 存储任务开始时间到 localStorage（跨组件生命周期存活）
   */
  persistTaskStartTime(sessionId: string, time: number): void {
    this.persistTaskData(sessionId, { startedAt: time })
  }

  /**
   * 从 localStorage 恢复 session 对应的 task_id
   */
  getRunningTaskId(sessionId: string): string | null {
    const data = this._loadTaskData(sessionId)
    return data?.taskId || null
  }

  /**
   * 获取任务开始时间
   */
  getTaskStartTime(sessionId: string): number | null {
    const data = this._loadTaskData(sessionId)
    return data?.startedAt || null
  }

  /** 从 localStorage 加载任务数据 */
  private _loadTaskData(sessionId: string): { taskId: string; startedAt?: number; timestamp: number } | null {
    try {
      const raw = localStorage.getItem(AgentStreamService.TASK_ID_PREFIX + sessionId)
      if (!raw) return null
      const data = JSON.parse(raw)
      // 超过 TASK_TTL 的任务认为已过期（与后端一致）
      if (Date.now() - data.timestamp > TASK_DATA_TTL_MS) {
        this.clearPersistedTask(sessionId)
        return null
      }
      return data
    } catch {
      return null
    }
  }

  /** 清除 localStorage 中的任务数据 */
  clearPersistedTask(sessionId: string): void {
    try {
      localStorage.removeItem(AgentStreamService.TASK_ID_PREFIX + sessionId)
    } catch { /* */ }
  }

  // ==================== 任务控制 ====================

  /**
   * 彻底取消任务（用户主动停止）
   * 调用后端取消接口 + 清除 localStorage + 断开 SSE
   */
  async stopTask(sessionId: string): Promise<void> {
    const taskId = this.getRunningTaskId(sessionId) || this._findTaskIdBySession(sessionId)

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
   * 查询任务状态（权威来源，用于页面恢复时判断任务死活）
   */
  async getTaskStatus(taskId: string): Promise<TaskStatusResponse | null> {
    try {
      const token = getAuthToken()
      const resp = await fetch(`/api/v1/agent/tasks/${taskId}/status`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      })
      if (!resp.ok) return null
      return await resp.json()
    } catch (e) {
      console.warn('[SSE] 查询任务状态失败:', e)
      return null
    }
  }

  /**
   * 启动一个SSE连接（新任务或重连）
   * 返回 connectionId
   */
  startStream(
    sessionId: string,
    request: AgentStreamRequest,
    onEvent: (event: AgentEvent, steps: AgentStep[]) => void,
    onComplete: (result: StreamCompleteResult) => void,
    onError: (error: string) => void,
    existingTaskId?: string
  ): string {
    const connectionId = `conn_${++this.connectionCounter}_${sessionId}`

    // 如果是新任务（非重连），先清除旧的任务数据
    if (!existingTaskId) {
      this.clearPersistedTask(sessionId)
    }

    // 如果该 session 已有连接，先取消旧的
    this.cancelSession(sessionId)

    // lastSeq 从 0 开始（全量回放），不是从持久化的断点续传：
    // 新连接的步骤树是空 Map，必须回放全部事件才能重建断点前的步骤/内容。
    // 消息类事件（assistant_message/completed）的重复由页面幂等守卫挡住。
    // 网络抖动重试走 _connectLoop，同一 ConnectionState 复用 lastSeq 增量续传。
    const state: ConnectionState = {
      connectionId,
      sessionId,
      taskId: existingTaskId || null,
      lastSeq: 0,
      steps: new Map(),
      status: 'connecting',
      cancelled: false,
      abortController: new AbortController(),
      reconnectAttempts: 0,
      onEvent,
      onComplete,
      onError,
      request,
      currentAgentName: null,
      agentParentStepId: null,
      replyCounter: 0,
    }

    this.connections.set(connectionId, state)
    this._connectLoop(state)
    return connectionId
  }

  /**
   * 取消某个 session 的所有连接（断开前端 SSE，后端任务继续运行）
   */
  cancelSession(sessionId: string): void {
    for (const [connId, state] of this.connections) {
      if (state.sessionId === sessionId) {
        state.cancelled = true
        state.abortController.abort()
        this.connections.delete(connId)
      }
    }
    // 注意：不清除 localStorage 中的任务数据
    // cancelSession 只是断开前端 SSE 连接，后端任务仍在运行
    // 用户回到会话时需要靠 task_id + lastSeq 重连续传
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
      if (state.sessionId === sessionId && state.status !== 'done' && state.status !== 'error') {
        return true
      }
    }
    return false
  }

  /** 获取某个 session 的活跃连接 ID */
  getActiveConnectionId(sessionId: string): string | null {
    for (const [connId, state] of this.connections) {
      if (state.sessionId === sessionId && state.status !== 'done' && state.status !== 'error') {
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

  private _findTaskIdBySession(sessionId: string): string | null {
    for (const [, state] of this.connections) {
      if (state.sessionId === sessionId && state.taskId) return state.taskId
    }
    return null
  }

  // ==================== 连接状态机 ====================

  /**
   * 连接循环：连接 → 流式接收 → (异常时)退避重连
   * 每次重连用最新 taskId + lastSeq 重建请求体（断点续传）
   */
  private async _connectLoop(state: ConnectionState): Promise<void> {
    try {
      while (!state.cancelled && state.status !== 'done' && state.status !== 'error') {
        try {
          await this._openStream(state)
          return // 流正常结束（终态事件已处理）
        } catch (err) {
          // state.status 可能被回调并发修改（onmessage 终态/onclose 状态查询），用 string 比较绕过 TS 窄化
          const statusAfterError: string = state.status
          if (state.cancelled || statusAfterError === 'done' || statusAfterError === 'error') return

          state.reconnectAttempts++
          const errMsg = err instanceof Error ? err.message : String(err)
          if (state.reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
            state.status = 'error'
            state.onError(tr(
              `连接中断，重连失败(${MAX_RECONNECT_ATTEMPTS}次)`,
              `Connection lost, reconnect failed (${MAX_RECONNECT_ATTEMPTS} times)`,
              `接続切断、再接続失敗（${MAX_RECONNECT_ATTEMPTS}回）`
            ))
            return
          }
          // 指数退避：2s, 4s, 8s, 16s, 32s
          const delay = RECONNECT_BASE_DELAY_MS * Math.pow(2, state.reconnectAttempts - 1)
          console.warn(`[SSE][${state.connectionId}] 连接中断(${errMsg})，${delay / 1000}s 后第${state.reconnectAttempts}次重连 | task=${state.taskId?.slice(0, 8)} | seq=${state.lastSeq}`)
          await new Promise(r => setTimeout(r, delay))
        }
      }
    } finally {
      if (state.status === 'done' || state.status === 'error') {
        this.connections.delete(state.connectionId)
      }
    }
  }

  /**
   * 建立单次 SSE 连接（fetch-event-source 的自动重试已禁用，重连由 _connectLoop 统一控制）
   */
  private async _openStream(state: ConnectionState): Promise<void> {
    // 每次连接都用最新的 taskId + lastSeq 重建请求体
    const requestBody: Record<string, any> = { ...state.request }
    if (state.taskId) {
      requestBody.task_id = state.taskId
      requestBody.last_event_id = state.lastSeq
    }

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
        // task_id 统一走响应头（新任务与重连一致）
        const headerTaskId = response.headers.get('X-Task-Id')
        if (headerTaskId && headerTaskId !== state.taskId) {
          state.taskId = headerTaskId
          this.persistTaskData(state.sessionId, { taskId: headerTaskId })
          console.log(`[SSE][${state.connectionId}] 获取 task_id: ${headerTaskId.slice(0, 8)}`)
        }
        state.status = 'streaming'
        state.reconnectAttempts = 0 // 连接成功，重置重连计数
      },

      onmessage: (ev: EventSourceMessage) => {
        const event = this._parseEvent(ev)
        if (!event) return

        // seq 幂等：已应用过的事件直接跳过（回放与实时流的重叠部分）
        if (event.seq !== undefined) {
          if (event.seq <= state.lastSeq) return
          state.lastSeq = event.seq
          this._persistSeqThrottled(state, event)
        }

        this._processEvent(state, event)
        const stepsArray = Array.from(state.steps.values())
        state.onEvent(event, stepsArray)
        this._logEvent(state.connectionId, event, state.steps)

        // 子 agent 的终态事件不触发完成回调（嵌入委派步骤展示）
        if (this._isChildAgentEvent(state, event)) return

        if (event.event_type === 'completed') {
          state.status = 'done'
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
          state.status = 'done'
          this.clearPersistedTask(state.sessionId)
          state.onError(event.data.error || tr('任务执行失败', 'Task execution failed', 'タスク実行失敗'))
          state.abortController.abort()
        } else if (event.event_type === 'cancelled') {
          state.status = 'done'
          this.clearPersistedTask(state.sessionId)
          state.onError(event.data.message || tr('任务已取消', 'Task cancelled', 'タスクがキャンセルされました'))
          state.abortController.abort()
        }
      },

      onclose: async () => {
        // 流被服务端正常关闭。正常路径下终态事件已在缓冲中回放并处理，
        // 走到这里说明未收到终态事件 → 通过状态端点做权威判定
        // （state.status 可能被 onmessage 回调并发修改，用 string 比较绕过 TS 窄化）
        const currentStatus: string = state.status
        if (currentStatus === 'done' || currentStatus === 'error' || state.cancelled) {
          throw new Error('stream already terminated')
        }
        // await 状态查询：终态 → 设置 status 并回调；仍在运行 → 内部抛错触发重连
        await this._resolveByStatusQuery(state)
        // _resolveByStatusQuery 返回说明已判定为终态，抛错让 _connectLoop 退出循环
        throw new Error('stream closed by server')
      },

      onerror: (err) => {
        // 抛出异常，禁用 fetch-event-source 内部重试，交由 _connectLoop 退避重连
        throw err
      },
    })
  }

  /**
   * 流关闭但未收到终态事件时，通过状态端点权威判定任务结果
   */
  private async _resolveByStatusQuery(state: ConnectionState): Promise<void> {
    if (!state.taskId) {
      state.status = 'error'
      state.onError(tr('连接中断', 'Connection lost', '接続切断'))
      return
    }
    const status = await this.getTaskStatus(state.taskId)
    if (state.cancelled || state.status === 'done' || state.status === 'error') return

    if (!status) {
      // 状态查询本身失败（网络问题）→ 视为可重连错误，由 _connectLoop 重连
      throw new Error('task status query failed')
    }
    if (status.status === 'not_found') {
      state.status = 'error'
      this.clearPersistedTask(state.sessionId)
      state.onError(tr('任务不存在或已过期', 'Task not found or expired', 'タスクが見つからないか期限切れです'))
      return
    }
    if (status.status === 'completed') {
      state.status = 'done'
      this.clearPersistedTask(state.sessionId)
      const result = status.result || {}
      state.onComplete({
        success: true,
        message: result.message || '',
        output_file_id: result.result?.output_file_id,
        download_url: result.result?.download_url,
        task_stats: result.result?.task_stats,
        fromStatusQuery: true, // 消息已在 DB 中，页面不应重复添加
      })
      return
    }
    if (status.status === 'failed' || status.status === 'cancelled') {
      state.status = 'done'
      this.clearPersistedTask(state.sessionId)
      const result = status.result || {}
      state.onError(result.error || result.message || tr('任务已结束', 'Task ended', 'タスク終了'))
      return
    }
    // 仍在运行但连接被关闭 → 视为可重连错误，由 _connectLoop 重连
    throw new Error('stream closed while task still running')
  }

  /**
   * 持久化任务数据续期（节流，1s 内最多写一次）：保持 timestamp 滑动，
   * 使 localStorage 的 10 分钟过期从最近活动时间起算
   */
  private _persistSeqThrottled(state: ConnectionState, _event: AgentEvent): void {
    const now = Date.now()
    if (now - this.lastPersistTime > 1000) {
      this.lastPersistTime = now
      this.persistTaskData(state.sessionId, { taskId: state.taskId || undefined })
    }
  }

  // ==================== 事件解析与步骤树重建 ====================

  private _parseEvent(ev: EventSourceMessage): AgentEvent | null {
    try {
      const parsedData = JSON.parse(ev.data)
      const seq = ev.id ? parseInt(ev.id, 10) : undefined
      return {
        event_type: parsedData.event_type || ev.event,
        step_id: parsedData.step_id,
        timestamp: parsedData.timestamp || new Date().toISOString(),
        seq: seq !== undefined && !isNaN(seq) ? seq : undefined,
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
      case 'fill_form_progress': {
        let s = state.steps.get(stepId)
        if (!s) { s = { id: stepId, type: 'fill_form', name: tr('填写表单', 'Filling form', 'フォーム入力'), description: tr('正在将数据填入表单', 'Filling data into form', 'データをフォームに入力中'), status: 'running', progress: 0 }; state.steps.set(stepId, s) }
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
    if (stepName.includes('填写表单') || stepName.includes('表单')) return 'fill_form'
    if (stepName.includes('填写') || stepName.includes('填表')) return 'fill_table'
    if (stepName.includes('调用')) return 'tool_call'
    if (stepName.includes('思考')) return 'thinking'
    return 'thinking'
  }
}

export const agentStreamService = new AgentStreamService()
export default agentStreamService
