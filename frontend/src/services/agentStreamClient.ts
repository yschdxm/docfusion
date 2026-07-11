/**
 * Agent SSE 流式客户端
 *
 * 职责：管理 SSE 连接生命周期（建立、重连、断开）。
 * 不处理事件语义，不管理步骤状态，不访问 localStorage。
 *
 * 从原 agentStreamService 的连接管理逻辑提取。
 */

import { fetchEventSource, EventSourceMessage } from '@microsoft/fetch-event-source'
import { getAuthToken } from './auth'
import type { AgentEvent, AgentStreamRequest, AgentEventType } from '../types/agent'

// ============================================================
// 连接状态
// ============================================================

interface Connection {
  sessionId: string
  taskId: string | null
  abortController: AbortController
  status: 'connecting' | 'streaming' | 'completed' | 'failed' | 'cancelled'
  reconnectAttempts: number
  maxReconnectAttempts: number
}

// ============================================================
// AgentStreamClient
// ============================================================

class AgentStreamClient {
  private connections = new Map<string, Connection>()

  /**
   * 启动 SSE 连接。
   * 回调会持续触发直到连接结束或被 cancel()。
   * 返回 taskId（首次从服务端事件中获取）。
   */
  start(
    sessionId: string,
    request: AgentStreamRequest,
    callbacks: {
      onEvent: (event: AgentEvent) => void
      onTaskId: (taskId: string) => void
      onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string }) => void
      onError: (error: string) => void
      onReconnecting: () => void
    },
    existingTaskId?: string,
  ): void {
    // 如果该 session 已有连接，先取消
    this.cancel(sessionId)

    const conn: Connection = {
      sessionId,
      taskId: existingTaskId || null,
      abortController: new AbortController(),
      status: 'connecting',
      reconnectAttempts: 0,
      maxReconnectAttempts: 3,
    }

    this.connections.set(sessionId, conn)
    this._doStream(conn, request, callbacks)
  }

  /**
   * 停止连接（前端主动断开）
   */
  cancel(sessionId: string): void {
    const conn = this.connections.get(sessionId)
    if (conn) {
      conn.status = 'cancelled'
      conn.abortController.abort()
      this.connections.delete(sessionId)
    }
  }

  /**
   * 是否有活跃连接
   */
  isConnected(sessionId: string): boolean {
    const conn = this.connections.get(sessionId)
    return !!conn && conn.status !== 'completed' && conn.status !== 'failed' && conn.status !== 'cancelled'
  }

  /**
   * 获取连接的 taskId
   */
  getTaskId(sessionId: string): string | null {
    return this.connections.get(sessionId)?.taskId || null
  }

  /**
   * 通过 DELETE /agent/stream/{taskId} 停止后端任务
   */
  async stopTask(sessionId: string): Promise<void> {
    const conn = this.connections.get(sessionId)
    if (!conn) return

    // 调用后端取消接口
    if (conn.taskId) {
      try {
        const token = getAuthToken()
        await fetch(`/api/v1/agent/stream/${conn.taskId}`, {
          method: 'DELETE',
          headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        })
      } catch (e) {
        console.warn('[SSE] 取消后端任务失败:', e)
      }
    }

    this.cancel(sessionId)
  }

  // ============================================================
  // 内部实现
  // ============================================================

  private async _doStream(
    conn: Connection,
    request: AgentStreamRequest,
    callbacks: {
      onEvent: (event: AgentEvent) => void
      onTaskId: (taskId: string) => void
      onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string }) => void
      onError: (error: string) => void
      onReconnecting: () => void
    },
  ): Promise<void> {
    const requestBody: Record<string, unknown> = { ...request }
    if (conn.taskId) {
      requestBody.task_id = conn.taskId
    }

    let completedFired = false

    try {
      await fetchEventSource('/api/v1/agent/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAuthToken() ? { 'Authorization': `Bearer ${getAuthToken()}` } : {}),
        },
        body: JSON.stringify(requestBody),
        signal: conn.abortController.signal,

        onopen: async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`)
          }
          conn.status = 'streaming'
        },

        onmessage: (ev: EventSourceMessage) => {
          const event = this._parseEvent(ev)
          if (!event) return

          // 提取 task_id
          if (event.data.task_id && !conn.taskId) {
            conn.taskId = event.data.task_id as string
            callbacks.onTaskId(conn.taskId)
          }

          // 触发事件回调
          callbacks.onEvent(event)

          // 处理终态事件
          const etype = event.event_type
          if (etype === 'completed') {
            if (completedFired) return
            completedFired = true
            conn.status = 'completed'
            callbacks.onComplete({
              success: true,
              message: (event.data.message as string) || '',
              output_file_id: (event.data.result as Record<string, unknown>)?.output_file_id as string,
              download_url: (event.data.result as Record<string, unknown>)?.download_url as string,
              task_stats: (event.data.result as Record<string, unknown>)?.task_stats,
            })
            conn.abortController.abort()
          } else if (etype === 'failed') {
            if (completedFired) return
            completedFired = true
            conn.status = 'failed'
            callbacks.onError((event.data.error as string) || 'Task execution failed')
            conn.abortController.abort()
          } else if (etype === 'cancelled') {
            if (completedFired) return
            completedFired = true
            conn.status = 'cancelled'
            callbacks.onError((event.data.message as string) || 'Task cancelled')
            conn.abortController.abort()
          }
        },

        onclose: () => {
          if (!completedFired && conn.status !== 'cancelled') {
            completedFired = true
            conn.status = 'completed'
            callbacks.onComplete({ success: true, message: '' })
          }
        },

        onerror: (_err) => {
          if (conn.status === 'cancelled') return null
          if (conn.reconnectAttempts >= conn.maxReconnectAttempts) {
            callbacks.onError(`Connection lost, reconnect failed (${conn.reconnectAttempts} times)`)
            return null
          }
          conn.reconnectAttempts++
          callbacks.onReconnecting()
          return 5000
        },
      })
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err)
      if (conn.status === 'cancelled') {
        // 静默
      } else if (errMsg.includes('abort') || errMsg.includes('AbortError')) {
        // 用户 abort
      } else if (conn.status === 'completed' || conn.status === 'failed') {
        // 已处理
      } else if (conn.reconnectAttempts >= conn.maxReconnectAttempts) {
        // 已在 onerror 中通知
      } else {
        callbacks.onError(`Connection lost: ${errMsg}`)
      }
    } finally {
      if (conn.status === 'completed' || conn.status === 'failed') {
        this.connections.delete(conn.sessionId)
      }
    }
  }

  private _parseEvent(ev: EventSourceMessage): AgentEvent | null {
    try {
      const parsed = JSON.parse(ev.data)
      return {
        event_type: (parsed.event_type || ev.event) as AgentEventType,
        step_id: parsed.step_id,
        timestamp: parsed.timestamp || new Date().toISOString(),
        data: parsed,
      }
    } catch {
      console.warn('[SSE] JSON parse failed:', ev.data.substring(0, 100))
      return null
    }
  }
}

export const agentStreamClient = new AgentStreamClient()
export default agentStreamClient
