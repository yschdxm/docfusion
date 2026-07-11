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

interface UseAgentStreamReturn {
  isStreaming: boolean
  streamingContent: string
  currentSteps: AgentStep[]
  streamingStats: TaskStats | null
  streamingDuration: number
  startStream: (request: AgentStreamRequest, sessionId?: string) => void
  stopStream: () => Promise<void>
  reconnectToTask: (taskId: string) => void
}

export function useAgentStream({ sessionId, onMessageComplete }: UseAgentStreamOptions): UseAgentStreamReturn {
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [currentSteps, setCurrentSteps] = useState<AgentStep[]>([])
  const [streamingStats, setStreamingStats] = useState<TaskStats | null>(null)
  const [streamingDuration, setStreamingDuration] = useState(0)

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
      // 捕获 content_chunk（累积）
      if (event.event_type === 'content_chunk' && event.data.content) {
        contentRef.current += event.data.content as string
        setStreamingContent(contentRef.current)
      }
      // assistant_message 是内容边界：后端在此清空 full_content，
      // 前端也应清空 contentRef，让后续 content_chunk 从头累积。
      // 中间回复内容不需要保留（最终回复通过 content_chunk 或 completed.result.message 到达）。
      if (event.event_type === 'assistant_message') {
        contentRef.current = ''
        setStreamingContent('')
      }
      // 捕获 stats_update
      if (event.event_type === 'stats_update' && event.data.stats) {
        const stats = event.data.stats as TaskStats
        statsRef.current = stats
        setStreamingStats(stats)
      }
      // 更新 steps
      stepsRef.current = steps
      setCurrentSteps([...steps])
    },
    onComplete: (result: { success: boolean; message: string }) => {
      const finalContent = contentRef.current
      const finalSteps = stepsRef.current
      const finalStats = statsRef.current
      const contentToSave = finalContent || result.message

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

  return {
    isStreaming,
    streamingContent,
    currentSteps,
    streamingStats,
    streamingDuration,
    startStream,
    stopStream,
    reconnectToTask,
  }
}
