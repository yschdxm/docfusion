/**
 * Agent流式API服务
 *
 * 使用 @microsoft/fetch-event-source 处理SSE流式响应
 * - 字节级buffer处理，彻底解决TCP分片问题
 * - 内置自动重连
 * - 支持POST + JSON body
 */

import { fetchEventSource, EventSourceMessage } from '@microsoft/fetch-event-source'

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
  agentName?: string          // 标识该步骤属于哪个agent
  children?: AgentStep[]      // 子步骤（子agent的步骤）
  streamingReply?: string     // 子Agent正在流式输出的回复内容
}

class AgentStreamService {
  // 子Agent状态跟踪
  private currentAgentName: string | null = null
  private agentParentStepId: string | null = null
  // 全局递增计数器，用于生成唯一的步骤ID
  private _replyCounter = 0

  /**
   * 重置状态（每次新的流式调用前必须重置）
   */
  private reset(): void {
    this.currentAgentName = null
    this.agentParentStepId = null
    this._replyCounter = 0
  }

  /**
   * 将 EventSourceMessage 转换为 AgentEvent
   */
  private parseEvent(ev: EventSourceMessage): AgentEvent | null {
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
    this.reset()

    await fetchEventSource('/api/v1/agent/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
      signal: abortSignal,

      onopen: async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
      },

      onmessage: (ev: EventSourceMessage) => {
        const event = this.parseEvent(ev)
        if (!event) return

        this.processEvent(event, steps)
        const stepsArray = Array.from(steps.values())
        onEvent(event, stepsArray)

        // === 完整消息级别日志 ===
        this.logEvent(event, steps)

        // 子Agent的 assistant_message 不触发父级回调（已在 handleChildEvent 中处理）
        if (this.isChildAgentEvent(event) && event.event_type === 'assistant_message') return

        // 子Agent的 completed/failed/cancelled 不触发父级回调
        if (this.isChildAgentEvent(event)) return

        // 检查是否完成、失败或取消（仅父级Agent）
        if (event.event_type === 'completed') {
          onComplete({
            success: true,
            message: event.data.message || '任务完成',
            output_file_id: event.data.result?.output_file_id,
            download_url: event.data.result?.download_url,
          })
        } else if (event.event_type === 'failed') {
          onError(event.data.error || '任务执行失败')
        } else if (event.event_type === 'cancelled') {
          onError(event.data.message || '任务已取消')
        }
      },

      onclose: () => {
        // 流正常关闭
      },

      onerror: (err) => {
        // 返回重试间隔(ms)，返回null停止重试
        onError(err instanceof Error ? err.message : '连接中断')
        return null  // 不自动重连
      },
    })
  }

  /**
   * 打印完整消息级别日志
   */
  private logEvent(event: AgentEvent, steps: Map<string, AgentStep>): void {
    const d = event.data
    switch (event.event_type) {
      case 'thinking_start':
        console.log(`[SSE] 思考开始${d.agent_name ? ` (${d.agent_name})` : ''}`)
        break
      case 'thinking_end': {
        const thinkingStep = steps.get(event.step_id || '')
        const tc = thinkingStep?.thinkingContent
        const summary = tc ? tc.substring(0, 150) + (tc.length > 150 ? '...' : '') : ''
        console.log(`[SSE] 思考完成${summary ? ': ' + summary : ''}`)
        break
      }
      case 'tool_call':
        console.log(`[SSE] 工具调用: ${d.tool_name}`)
        break
      case 'tool_result': {
        const rStr = JSON.stringify(d.result ?? '')
        const rSum = rStr.substring(0, 100) + (rStr.length > 100 ? '...' : '')
        console.log(`[SSE] 工具结果: ${d.tool_name} → ${rSum}`)
        break
      }
      case 'step_start':
        if (d.is_delegation_start) {
          console.log(`[SSE] 委派开始: ${d.step_name}`)
        }
        break
      case 'step_end':
        if (d.is_delegation_end) {
          console.log(`[SSE] 委派结束`)
        }
        break
      case 'assistant_message': {
        const msg = d.message || ''
        const src = d.agent_name ? '子Agent' : '主Agent'
        console.log(`[SSE] 中途回复(${src}): ${msg.substring(0, 100)}${msg.length > 100 ? '...' : ''}`)
        break
      }
      case 'content_end':
        console.log('[SSE] 回复完成')
        break
      case 'completed':
        console.log(`[SSE] 任务完成`)
        break
      case 'failed':
        console.log(`[SSE] 任务失败: ${(d.error || '').substring(0, 150)}`)
        break
    }
  }

  /**
   * 判断事件是否属于当前子Agent
   */
  private isChildAgentEvent(event: AgentEvent): boolean {
    if (event.data.is_delegation_end) return false
    return !!(event.data.agent_name && this.currentAgentName && event.data.agent_name === this.currentAgentName)
  }

  /**
   * 在委派步骤的children中查找或创建子步骤
   */
  private findOrCreateChildStep(
    parentStep: AgentStep,
    stepId: string,
    type: AgentStep['type'],
    name: string,
    description: string
  ): AgentStep {
    if (!parentStep.children) {
      parentStep.children = []
    }
    const existing = parentStep.children.find(c => c.id === stepId)
    if (existing) return existing

    const child: AgentStep = {
      id: stepId,
      type,
      name,
      description,
      status: 'running',
      progress: 0,
    }
    parentStep.children.push(child)
    return child
  }

  /**
   * 处理子Agent的事件，归入委派步骤的children
   */
  private handleChildEvent(event: AgentEvent, steps: Map<string, AgentStep>): void {
    if (!this.agentParentStepId) return
    const parentStep = steps.get(this.agentParentStepId)
    if (!parentStep) return

    const stepId = event.step_id || `child_step_${Date.now()}`

    switch (event.event_type) {
      case 'step_start': {
        const stepType = this.inferStepType(event.data.step_name || '')
        this.findOrCreateChildStep(parentStep, stepId, stepType, event.data.step_name || '步骤', event.data.description || '')
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
        const child = this.findOrCreateChildStep(parentStep, stepId, 'thinking', event.data.message || '思考中', 'Agent正在分析任务')
        child.status = 'running'
        if (!child.thinkingContent) child.thinkingContent = ''
        break
      }
      case 'thinking_chunk': {
        const child = this.findOrCreateChildStep(parentStep, stepId, 'thinking', '思考中', 'Agent正在分析任务')
        child.thinkingContent = (child.thinkingContent || '') + (event.data.content || '')
        break
      }
      case 'thinking_end': {
        const child = parentStep.children?.find(c => c.id === stepId)
        if (child) { child.status = 'completed'; child.progress = 100; child.name = '思考完成' }
        break
      }
      case 'tool_call': {
        const child = this.findOrCreateChildStep(
          parentStep, stepId, 'tool_call',
          `调用 ${event.data.tool_name}`,
          `执行工具: ${event.data.tool_name}`
        )
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
            id: `reply_${++this._replyCounter}`,
            type: 'assistant_reply',
            name: 'AI回复',
            description: msg,
            status: 'completed',
            progress: 100,
            thinkingContent: msg,
          })
        }
        break
      }
      case 'completed':
      case 'failed': {
        if (parentStep.children) {
          parentStep.children.forEach(c => {
            if (c.status === 'running') {
              c.status = event.event_type === 'completed' ? 'completed' : 'error'
              c.progress = 100
            }
          })
        }
        break
      }
    }
  }

  /**
   * 处理事件，更新步骤状态
   */
  private processEvent(event: AgentEvent, steps: Map<string, AgentStep>): void {
    // 委派结束事件总是需要处理（清除子Agent状态）
    if (event.data.is_delegation_end) {
      const delegationStep = steps.get(event.step_id || '')
      if (delegationStep) {
        delegationStep.status = 'completed'
        delegationStep.progress = 100
      }
      this.currentAgentName = null
      this.agentParentStepId = null
      return
    }

    // 如果是子Agent的事件，归入children
    if (this.isChildAgentEvent(event)) {
      this.handleChildEvent(event, steps)
      return
    }

    const stepId = event.step_id || `step_${Date.now()}`

    switch (event.event_type) {
      case 'step_start':
        if (event.data.is_delegation_start) {
          this.currentAgentName = event.data.agent_name
          this.agentParentStepId = stepId
          steps.set(stepId, {
            id: stepId,
            type: 'agent_delegation',
            name: event.data.step_name,
            description: event.data.description || '',
            status: 'running',
            progress: 0,
            children: [],
            agentName: event.data.agent_name,
          })
        } else {
          steps.set(stepId, {
            id: stepId,
            type: this.inferStepType(event.data.step_name),
            name: event.data.step_name,
            description: event.data.description,
            status: 'running',
            progress: 0,
          })
        }
        break

      case 'step_progress': {
        const progressStep = steps.get(stepId)
        if (progressStep) progressStep.progress = event.data.progress || 0
        break
      }

      case 'step_end': {
        const endStep = steps.get(stepId)
        if (endStep) { endStep.status = 'completed'; endStep.progress = 100 }
        break
      }

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

      case 'tool_result': {
        const toolStep = steps.get(stepId)
        if (toolStep) { toolStep.status = 'completed'; toolStep.progress = 100; toolStep.toolResult = event.data.result }
        break
      }

      case 'tool_error': {
        const errorStep = steps.get(stepId)
        if (errorStep) { errorStep.status = 'error'; errorStep.errorMessage = event.data.error }
        break
      }

      case 'thinking_start': {
        const existing = steps.get(stepId)
        if (existing) {
          existing.status = 'running'
          existing.name = event.data.message || existing.name
        } else {
          steps.set(stepId, {
            id: stepId,
            type: 'thinking',
            name: event.data.message || '思考中',
            description: 'Agent正在分析任务',
            status: 'running',
            progress: 0,
            thinkingContent: '',
          })
        }
        break
      }

      case 'thinking_chunk': {
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
      }

      case 'thinking_end': {
        const endThinkingStep = steps.get(stepId)
        if (endThinkingStep) { endThinkingStep.status = 'completed'; endThinkingStep.progress = 100; endThinkingStep.name = '思考完成' }
        break
      }

      case 'content_chunk':
        break

      case 'content_end': {
        const endContentStep = steps.get(stepId)
        if (endContentStep) { endContentStep.status = 'completed'; endContentStep.progress = 100 }
        break
      }

      case 'assistant_message':
        steps.clear()
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

      case 'data_retrieval_progress': {
        const retrievalStep = steps.get(stepId)
        if (retrievalStep) retrievalStep.progress = event.data.records_found > 0 ? 50 : 0
        break
      }

      case 'fill_table_progress': {
        let fillStep = steps.get(stepId)
        if (!fillStep) {
          fillStep = { id: stepId, type: 'fill_table', name: '填写表格', description: '正在将数据填入模板', status: 'running', progress: 0 }
          steps.set(stepId, fillStep)
        }
        fillStep.progress = event.data.progress || 0
        break
      }

      case 'completed': {
        const completedStep = steps.get(stepId)
        if (completedStep && completedStep.type === 'thinking') {
          completedStep.status = 'completed'
          completedStep.progress = 100
        }
        break
      }

      case 'failed': {
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
      }

      case 'error': {
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
      }
    }
  }

  private inferStepType(stepName: string): AgentStep['type'] {
    if (stepName.includes('查询') || stepName.includes('检索')) return 'data_retrieval'
    if (stepName.includes('填写') || stepName.includes('填表')) return 'fill_table'
    if (stepName.includes('调用')) return 'tool_call'
    if (stepName.includes('思考')) return 'thinking'
    return 'thinking'
  }
}

export const agentStreamService = new AgentStreamService()
export default agentStreamService
