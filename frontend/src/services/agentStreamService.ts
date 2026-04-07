/**
 * Agent流式API服务
 *
 * 处理SSE(Server-Sent Events)格式的流式响应
 */

export interface AgentStreamRequest {
  message: string
  file_ids: string[]
  template_id?: string | null
  conversation_id?: string | null
  task_type?: 'auto' | 'fill_table' | 'query' | 'operation'
}

export interface AgentEvent {
  event_type: string
  step_id?: string
  timestamp: string
  data: Record<string, any>
}

export interface AgentStep {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'data_retrieval' | 'fill_table' | 'assistant_reply'
  name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'error'
  progress: number
  toolName?: string
  toolParams?: Record<string, any>
  toolResult?: Record<string, any>
  thinkingContent?: string
  errorMessage?: string
}

class AgentStreamService {
  /**
   * 流式调用Agent
   *
   * @param request 请求参数
   * @param onEvent 事件回调
   * @param onComplete 完成回调
   * @param onError 错误回调
   * @param abortSignal 用于取消请求的AbortSignal
   */
  async streamChat(
    request: AgentStreamRequest,
    onEvent: (event: AgentEvent, steps: AgentStep[]) => void,
    onComplete: (result: { success: boolean; message: string; output_file_id?: string; download_url?: string }) => void,
    onError: (error: string) => void,
    abortSignal?: AbortSignal
  ): Promise<void> {
    const steps: Map<string, AgentStep> = new Map()

    try {
      const response = await fetch('/api/v1/agent/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(request),
        signal: abortSignal,
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      if (!reader) {
        throw new Error('No response body')
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        console.log('[agentStreamService] Received chunk, buffer length:', buffer.length)
        const events = this.parseSSE(buffer)

        // 更新buffer，移除已解析的部分
        const lastEventEnd = buffer.lastIndexOf('\n\n')
        if (lastEventEnd !== -1) {
          buffer = buffer.slice(lastEventEnd + 2)
        }

        for (const event of events) {
          console.log('[agentStreamService] Processing event:', event.event_type, 'step_id:', event.step_id, 'data:', event.data)
          this.processEvent(event, steps)
          const stepsArray = Array.from(steps.values())
          console.log('[agentStreamService] Steps after processEvent:', stepsArray.length, stepsArray.map(s => s.id))
          onEvent(event, stepsArray)

          // 检查是否完成、失败或取消
          if (event.event_type === 'completed') {
            console.log('[agentStreamService] Completed event received:', event.data)
            console.log('[agentStreamService] Steps count before onComplete:', steps.size)
            onComplete({
              success: true,
              message: event.data.message || '任务完成',
              output_file_id: event.data.result?.output_file_id,
              download_url: event.data.result?.download_url,
            })
            return
          } else if (event.event_type === 'failed') {
            console.log('[agentStreamService] Failed event received:', event.data)
            console.log('[agentStreamService] Steps count before onError:', steps.size)
            onError(event.data.error || '任务执行失败')
            return
          } else if (event.event_type === 'cancelled') {
            console.log('[agentStreamService] Cancelled event received:', event.data)
            onError(event.data.message || '任务已取消')
            return
          }
        }
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : '网络请求失败')
    }
  }

  /**
   * 解析SSE格式数据
   */
  private parseSSE(data: string): AgentEvent[] {
    console.log('[agentStreamService] parseSSE called with data length:', data.length)
    const events: AgentEvent[] = []
    const lines = data.split('\n')
    let currentEventType: string = ''

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]

      if (line.startsWith('event: ')) {
        currentEventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        try {
          const parsedData = JSON.parse(line.slice(6))
          // 新的SSE格式: data包含event_type, step_id, timestamp和其他字段
          events.push({
            event_type: parsedData.event_type || currentEventType,
            step_id: parsedData.step_id,
            timestamp: parsedData.timestamp || new Date().toISOString(),
            data: parsedData,
          })
        } catch {
          events.push({
            event_type: currentEventType,
            timestamp: new Date().toISOString(),
            data: { raw: line.slice(6) },
          })
        }
        currentEventType = ''
      }
    }

    console.log('[agentStreamService] parseSSE returning', events.length, 'events')
    return events
  }

  /**
   * 处理事件，更新步骤状态
   */
  private processEvent(event: AgentEvent, steps: Map<string, AgentStep>): void {
    console.log('[agentStreamService] processEvent debug - event.step_id:', event.step_id, 'event_type:', event.event_type)
    const stepId = event.step_id || `step_${Date.now()}`

    console.log('[agentStreamService] processEvent:', event.event_type, 'final stepId:', stepId, 'steps size before:', steps.size)

    switch (event.event_type) {
      case 'step_start':
        steps.set(stepId, {
          id: stepId,
          type: this.inferStepType(event.data.step_name),
          name: event.data.step_name,
          description: event.data.description,
          status: 'running',
          progress: 0,
        })
        break

      case 'step_progress':
        const progressStep = steps.get(stepId)
        if (progressStep) {
          progressStep.progress = event.data.progress || 0
        }
        break

      case 'step_end':
        const endStep = steps.get(stepId)
        if (endStep) {
          endStep.status = 'completed'
          endStep.progress = 100
        }
        break

      case 'tool_call':
        steps.set(stepId, {
          id: stepId,
          type: 'tool_call',
          name: `调用 ${event.data.tool_name}`,
          description: `执行工具: ${event.data.tool_name}`,
          status: 'running',
          progress: 50,
          toolName: event.data.tool_name,
          toolParams: event.data.parameters,
        })
        break

      case 'tool_result':
        const toolStep = steps.get(stepId)
        if (toolStep) {
          toolStep.status = 'completed'
          toolStep.progress = 100
          toolStep.toolResult = event.data.result
        }
        break

      case 'tool_error':
        const errorStep = steps.get(stepId)
        if (errorStep) {
          errorStep.status = 'error'
          errorStep.errorMessage = event.data.error
        }
        break

      case 'thinking_start':
        steps.set(stepId, {
          id: stepId,
          type: 'thinking',
          name: event.data.message || '思考中',
          description: 'Agent正在分析任务',
          status: 'running',
          progress: 0,
          thinkingContent: '',
        })
        break

      case 'thinking_chunk':
        let thinkingStep = steps.get(stepId)
        if (!thinkingStep) {
          thinkingStep = {
            id: stepId,
            type: 'thinking',
            name: '思考中',
            description: 'Agent正在分析任务',
            status: 'running',
            progress: 0,
            thinkingContent: '',
          }
          steps.set(stepId, thinkingStep)
        }
        thinkingStep.thinkingContent += event.data.content || ''
        break

      case 'thinking_end':
        const endThinkingStep = steps.get(stepId)
        if (endThinkingStep) {
          endThinkingStep.status = 'completed'
          endThinkingStep.progress = 100
          endThinkingStep.name = '思考完成'
        }
        break

      case 'content_chunk':
        // 处理回复内容片段 - 用于流式显示
        // 注意：这里不存储到 step 中，而是直接通过事件传递给前端显示
        // 避免覆盖 thinkingContent
        break

      case 'content_end':
        // 回复内容结束
        const endContentStep = steps.get(stepId)
        if (endContentStep) {
          endContentStep.status = 'completed'
          endContentStep.progress = 100
        }
        break

      case 'assistant_message':
        // AI助手的完整消息（中间步骤的回复）
        // 创建一个新的步骤来存储这个消息，确保不覆盖现有步骤
        const msgStepId = `step_msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        steps.set(msgStepId, {
          id: msgStepId,
          type: 'assistant_reply',  // 使用新的类型区分思考步骤
          name: 'AI回复',
          description: event.data.message || '',
          status: 'completed',
          progress: 100,
          thinkingContent: event.data.message || '',
        })
        break

      case 'data_retrieval_start':
        steps.set(stepId, {
          id: stepId,
          type: 'data_retrieval',
          name: `查询 ${event.data.source}`,
          description: `从 ${event.data.source} 检索数据`,
          status: 'running',
          progress: 0,
        })
        break

      case 'data_retrieval_progress':
        const retrievalStep = steps.get(stepId)
        if (retrievalStep) {
          retrievalStep.progress = event.data.records_found > 0 ? 50 : 0
        }
        break

      case 'fill_table_progress':
        let fillStep = steps.get(stepId)
        if (!fillStep) {
          fillStep = {
            id: stepId,
            type: 'fill_table',
            name: '填写表格',
            description: '正在将数据填入模板',
            status: 'running',
            progress: 0,
          }
          steps.set(stepId, fillStep)
        }
        fillStep.progress = event.data.progress || 0
        break

      case 'completed':
        // 标记现有思考步骤为完成，不创建新步骤
        const existingThinkingStep = steps.get(stepId)
        if (existingThinkingStep && existingThinkingStep.type === 'thinking') {
          existingThinkingStep.status = 'completed'
          existingThinkingStep.progress = 100
        }
        break

      case 'failed':
        // 为失败事件创建一个特殊步骤
        const failStepId = event.step_id || `step_fail_${Date.now()}`
        steps.set(failStepId, {
          id: failStepId,
          type: 'thinking',
          name: '任务失败',
          description: event.data.error || '任务执行失败',
          status: 'error',
          progress: 0,
          errorMessage: event.data.error,
        })
        break

      case 'error':
        // 处理错误事件
        const errorStepId = event.step_id || `step_error_${Date.now()}`
        const existingErrorStep = steps.get(errorStepId)
        if (existingErrorStep) {
          existingErrorStep.status = 'error'
          existingErrorStep.errorMessage = event.data.error || event.data.message || '发生错误'
        } else {
          steps.set(errorStepId, {
            id: errorStepId,
            type: 'thinking',
            name: '错误',
            description: event.data.error || event.data.message || '发生错误',
            status: 'error',
            progress: 0,
            errorMessage: event.data.error || event.data.message,
          })
        }
        break

      default:
        console.log('[agentStreamService] Unhandled event type:', event.event_type)
    }

    console.log('[agentStreamService] processEvent end, steps size after:', steps.size)
  }

  private inferStepType(stepName: string): AgentStep['type'] {
    if (stepName.includes('查询') || stepName.includes('检索')) return 'data_retrieval'
    if (stepName.includes('填写') || stepName.includes('填表')) return 'fill_table'
    if (stepName.includes('思考')) return 'thinking'
    return 'thinking'
  }
}

export const agentStreamService = new AgentStreamService()
export default agentStreamService
