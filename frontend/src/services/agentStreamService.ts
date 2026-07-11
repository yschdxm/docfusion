/**
 * Agent 流式服务 — 组合层
 *
 * 组合 agentStreamClient（SSE连接）和 agentEventProcessor（事件处理）。
 * 对外暴露简洁的 startStream / stopStream / getSteps API。
 *
 * 职责：
 * - 管理每个 session 的 StepState
 * - 协调 client 和 processor
 * - 管理 task_id 的 localStorage 持久化（用于跨组件生命周期的断线重连）
 */

import agentStreamClient from './agentStreamClient'
import { createStepState, processEvent, getStepsArray, type StepState } from './agentEventProcessor'
import type { AgentEvent, AgentStep, AgentStreamRequest, AgentStreamResult } from '../types/agent'

// Re-export types for backward compatibility
export type { AgentStep, TaskStats, AgentStreamRequest, AgentEvent } from '../types/agent'

// ============================================================
// 回调接口
// ============================================================

export interface StreamCallbacks {
  onEvent: (event: AgentEvent, steps: AgentStep[]) => void
  onComplete: (result: AgentStreamResult) => void
  onError: (error: string) => void
  onTaskId?: (taskId: string) => void
}

// ============================================================
// localStorage task_id 管理
// ============================================================

const TASK_ID_PREFIX = 'agent_task_'
const TASK_TTL = 10 * 60 * 1000 // 10 分钟

interface PersistedTaskData {
  taskId: string
  timestamp: number
  startedAt: number
}

function persistTaskId(sessionId: string, taskId: string, startedAt?: number): void {
  try {
    const existing = loadTaskData(sessionId)
    localStorage.setItem(TASK_ID_PREFIX + sessionId, JSON.stringify({
      taskId,
      timestamp: Date.now(),
      startedAt: startedAt || existing?.startedAt || Date.now(),
    }))
  } catch { /* */ }
}

function loadTaskData(sessionId: string): PersistedTaskData | null {
  try {
    const raw = localStorage.getItem(TASK_ID_PREFIX + sessionId)
    if (!raw) return null
    const data = JSON.parse(raw) as PersistedTaskData
    if (Date.now() - data.timestamp > TASK_TTL) {
      clearPersistedTask(sessionId)
      return null
    }
    return data
  } catch {
    return null
  }
}

function clearPersistedTask(sessionId: string): void {
  try {
    localStorage.removeItem(TASK_ID_PREFIX + sessionId)
  } catch { /* */ }
}

// ============================================================
// AgentStreamService
// ============================================================

class AgentStreamService {
  private sessionStates = new Map<string, StepState>()
  private sessionCallbacks = new Map<string, StreamCallbacks>()
  private taskTimers = new Map<string, ReturnType<typeof setInterval>>()

  /**
   * 启动流式任务
   */
  startStream(
    sessionId: string,
    request: AgentStreamRequest,
    callbacks: StreamCallbacks,
  ): void {
    // 清理旧状态
    this.clearSessionState(sessionId)

    // 创建新的 step state
    const stepState = createStepState()
    this.sessionStates.set(sessionId, stepState)
    this.sessionCallbacks.set(sessionId, callbacks)

    // 如果是非重连，清除旧 task_id
    if (!request.task_id) {
      clearPersistedTask(sessionId)
    }

    // 记录任务开始时间
    const startedAt = Date.now()
    persistTaskId(sessionId, '', startedAt)

    agentStreamClient.start(
      sessionId,
      request,
      {
        onEvent: (event: AgentEvent) => {
          const steps = processEvent(stepState, event)
          callbacks.onEvent(event, steps)
        },
        onTaskId: (taskId: string) => {
          persistTaskId(sessionId, taskId, startedAt)
          callbacks.onTaskId?.(taskId)
        },
        onComplete: (result) => {
          clearPersistedTask(sessionId)
          this.clearSessionState(sessionId)
          callbacks.onComplete({
            success: result.success,
            message: result.message,
            output_file_id: result.output_file_id,
            download_url: result.download_url,
            task_stats: result.task_stats,
          })
        },
        onError: (error: string) => {
          clearPersistedTask(sessionId)
          this.clearSessionState(sessionId)
          callbacks.onError(error)
        },
        onReconnecting: () => {
          // 重连中，可选通知
        },
      },
      request.task_id || undefined,
    )
  }

  /**
   * 停止流式任务（前端主动停止 + 后端取消）
   */
  async stopStream(sessionId: string): Promise<void> {
    await agentStreamClient.stopTask(sessionId)
    clearPersistedTask(sessionId)
    this.clearSessionState(sessionId)
  }

  /**
   * 获取某个 session 的当前步骤
   */
  getSteps(sessionId: string): AgentStep[] {
    const state = this.sessionStates.get(sessionId)
    return state ? getStepsArray(state) : []
  }

  /**
   * 获取某个 session 是否有活跃连接
   */
  hasActiveConnection(sessionId: string): boolean {
    return agentStreamClient.isConnected(sessionId)
  }

  /**
   * 获取某个 session 的运行中 task_id（从 localStorage 恢复）
   */
  getRunningTaskId(sessionId: string): string | null {
    const data = loadTaskData(sessionId)
    return data?.taskId || null
  }

  /**
   * 获取任务开始时间
   */
  getTaskStartTime(sessionId: string): number | null {
    const data = loadTaskData(sessionId)
    return data?.startedAt || null
  }

  /**
   * 持久化任务开始时间
   */
  persistTaskStartTime(sessionId: string, time: number): void {
    try {
      const existing = loadTaskData(sessionId)
      const data: PersistedTaskData = existing || { taskId: '', timestamp: Date.now(), startedAt: Date.now() }
      data.startedAt = time
      localStorage.setItem(TASK_ID_PREFIX + sessionId, JSON.stringify(data))
    } catch { /* */ }
  }

  /**
   * 清除持久化的 task_id
   */
  clearPersistedTask(sessionId: string): void {
    clearPersistedTask(sessionId)
  }

  /**
   * 重连到已有任务
   */
  reconnectToTask(
    sessionId: string,
    taskId: string,
    callbacks: StreamCallbacks,
  ): void {
    this.startStream(sessionId, {
      message: '',
      file_ids: [],
      task_id: taskId,
    }, callbacks)
  }

  /**
   * 取消所有连接
   */
  cancelAll(): void {
    for (const sessionId of this.sessionStates.keys()) {
      agentStreamClient.cancel(sessionId)
      clearPersistedTask(sessionId)
    }
    this.sessionStates.clear()
    this.sessionCallbacks.clear()
  }

  // ============================================================
  // 内部
  // ============================================================

  private clearSessionState(sessionId: string): void {
    this.sessionStates.delete(sessionId)
    this.sessionCallbacks.delete(sessionId)
    const timer = this.taskTimers.get(sessionId)
    if (timer) {
      clearInterval(timer)
      this.taskTimers.delete(sessionId)
    }
  }
}

export const agentStreamService = new AgentStreamService()
export default agentStreamService
