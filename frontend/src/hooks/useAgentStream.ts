/**
 * useAgentStream — SSE 流式 hook
 *
 * 桥接 agentStreamService 和 React 组件。
 * 管理流式状态（content、steps、stats、duration），
 * 提供 startStream / stopStream / reconnectToTask 方法。
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import agentStreamService from '../services/agentStreamService'
import type { AgentEvent, AgentStep, AgentStreamRequest, TaskStats } from '../types/agent'

interface UseAgentStreamOptions {
  sessionId: string | null
  onMessageComplete?: (sessionId: string, content: string, steps: AgentStep[], stats?: TaskStats) => void
}

export interface FillTablePluginData {
  action: string
  current_doc_id: string
  file_type: string
  headers: string[]
  data: Record<string, unknown>[]
  fill_mode: 'overwrite' | 'append'
  target_table_index: number
}

interface UseAgentStreamReturn {
  isStreaming: boolean
  streamingContent: string
  currentSteps: AgentStep[]
  streamingStats: TaskStats | null
  streamingDuration: number
  editorDocumentId: string | null
  fillTablePluginData: FillTablePluginData | null
  startStream: (request: AgentStreamRequest, sessionId?: string) => void
  stopStream: () => Promise<void>
  reconnectToTask: (taskId: string) => void
  clearEditorDocumentId: () => void
  clearFillTablePluginData: () => void
}

export function useAgentStream({ sessionId, onMessageComplete }: UseAgentStreamOptions): UseAgentStreamReturn {
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [currentSteps, setCurrentSteps] = useState<AgentStep[]>([])
  const [streamingStats, setStreamingStats] = useState<TaskStats | null>(null)
  const [streamingDuration, setStreamingDuration] = useState(0)
  const [editorDocumentId, setEditorDocumentId] = useState<string | null>(null)
  const [fillTablePluginData, setFillTablePluginData] = useState<FillTablePluginData | null>(null)

  const contentRef = useRef('')
  const stepsRef = useRef<AgentStep[]>([])
  const statsRef = useRef<TaskStats | null>(null)
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef(0)

  const sessionIdRef = useRef(sessionId)
  const onMessageCompleteRef = useRef(onMessageComplete)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    onMessageCompleteRef.current = onMessageComplete
  }, [onMessageComplete])

  // 清理 duration timer
  useEffect(() => {
    return () => {
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current)
      }
    }
  }, [])

  // 切换会话时重置流式状态
  useEffect(() => {
    setStreamingContent('')
    setCurrentSteps([])
    setStreamingStats(null)
    setStreamingDuration(0)
    contentRef.current = ''
    stepsRef.current = []
    statsRef.current = null
  }, [sessionId])

  const startDurationTimer = useCallback(() => {
    startTimeRef.current = Date.now()
    if (durationTimerRef.current) clearInterval(durationTimerRef.current)
    durationTimerRef.current = setInterval(() => {
      setStreamingDuration(Date.now() - startTimeRef.current)
    }, 100)
  }, [])

  const stopDurationTimer = useCallback(() => {
    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current)
      durationTimerRef.current = null
    }
  }, [])

  /**
   * 构建流式回调（提取为公共方法，startStream 和 reconnectToTask 共用）
   * @param targetSessionId 本次流式任务的 sessionId，在调用时捕获，不依赖 ref
   */
  const buildCallbacks = useCallback((targetSessionId: string) => ({
    onEvent: (event: AgentEvent, steps: AgentStep[]) => {
      // 区分主 agent 和子 agent 事件：
      // 子 agent 的 content_chunk/assistant_message 由 processor 处理（写入步骤的 streamingReply），
      // 不应影响主 agent 的 contentRef。
      const isChildAgent = !!event.data.agent_name && !event.data.is_delegation_end

      if (!isChildAgent) {
        // 主 agent 的 content_chunk → 累积到 contentRef（流式显示）
        if (event.event_type === 'content_chunk' && event.data.content) {
          contentRef.current += event.data.content as string
          setStreamingContent(contentRef.current)
        }
        // assistant_message 是内容分界点：保存当前内容为消息，清空 contentRef
        // 后续 content_chunk 从头累积，形成独立的新消息。
        if (event.event_type === 'assistant_message') {
          if (contentRef.current && targetSessionId) {
            onMessageCompleteRef.current?.(
              targetSessionId,
              contentRef.current,
              stepsRef.current,
              statsRef.current || undefined,
            )
          }
          contentRef.current = ''
          setStreamingContent('')
        }
      }

      // stats_update 始终处理（不分子 agent）
      if (event.event_type === 'stats_update' && event.data.stats) {
        const stats = event.data.stats as TaskStats
        statsRef.current = stats
        setStreamingStats(stats)
      }
      // open_editor 事件：设置要打开的文档ID
      if (event.event_type === 'open_editor' && event.data.document_id) {
        setEditorDocumentId(event.data.document_id as string)
      }
      // tool_result 事件：检测 fill_table_via_plugin 数据
      if (event.event_type === 'tool_result' && event.data.result) {
        const result = event.data.result as Record<string, unknown>
        if (result.action === 'fill_table_via_plugin' && result.current_doc_id) {
          setFillTablePluginData(result as unknown as FillTablePluginData)
        }
      }
      // steps 始终更新（processor 已正确路由子 agent 事件到步骤的 children）
      stepsRef.current = steps
      setCurrentSteps([...steps])
    },
    onComplete: (result: { success: boolean; message: string }) => {
      const finalContent = contentRef.current
      const finalSteps = stepsRef.current
      const finalStats = statsRef.current
      // 优先使用 result.message（后端最终回复），contentRef 作为兜底
      const contentToSave = result.message || finalContent

      setIsStreaming(false)
      stopDurationTimer()
      setStreamingContent('')
      setCurrentSteps([])

      if (contentToSave && targetSessionId) {
        onMessageCompleteRef.current?.(
          targetSessionId,
          contentToSave,
          finalSteps,
          finalStats || undefined,
        )
      }
    },
    onError: (_error: string) => {
      setIsStreaming(false)
      stopDurationTimer()
      setStreamingContent('')
      setCurrentSteps([])
    },
  }), [stopDurationTimer])

  const startStream = useCallback((request: AgentStreamRequest, overrideSessionId?: string) => {
    const targetSessionId = overrideSessionId || sessionIdRef.current
    if (!targetSessionId) return

    contentRef.current = ''
    stepsRef.current = []
    statsRef.current = null
    setStreamingContent('')
    setCurrentSteps([])
    setStreamingStats(null)
    setIsStreaming(true)
    startDurationTimer()

    agentStreamService.startStream(targetSessionId, request, buildCallbacks(targetSessionId))
  }, [startDurationTimer, buildCallbacks])

  const stopStream = useCallback(async () => {
    const targetSessionId = sessionIdRef.current
    if (!targetSessionId) return

    const contentToSave = contentRef.current
    const stepsToSave = stepsRef.current
    const statsToSave = statsRef.current

    await agentStreamService.stopStream(targetSessionId)

    setIsStreaming(false)
    stopDurationTimer()

    // 保存已流式输出的内容
    if (contentToSave && targetSessionId) {
      onMessageCompleteRef.current?.(targetSessionId, contentToSave, stepsToSave, statsToSave || undefined)
    }

    setStreamingContent('')
    setCurrentSteps([])
  }, [stopDurationTimer])

  const reconnectToTask = useCallback((taskId: string) => {
    const targetSessionId = sessionIdRef.current
    if (!targetSessionId) return

    setIsStreaming(true)
    startDurationTimer()

    agentStreamService.reconnectToTask(targetSessionId, taskId, buildCallbacks(targetSessionId))
  }, [startDurationTimer, buildCallbacks])

  const clearEditorDocumentId = useCallback(() => {
    setEditorDocumentId(null)
  }, [])

  const clearFillTablePluginData = useCallback(() => {
    setFillTablePluginData(null)
  }, [])

  return {
    isStreaming,
    streamingContent,
    currentSteps,
    streamingStats,
    streamingDuration,
    editorDocumentId,
    fillTablePluginData,
    startStream,
    stopStream,
    reconnectToTask,
    clearEditorDocumentId,
    clearFillTablePluginData,
  }
}
