/**
 * Agent SSE 流式系统统一类型定义
 *
 * 前后端共用的事件类型和数据结构。
 * 后端 Python 枚举值与这里的字符串字面量保持一致。
 */

// ============================================================
// 事件类型
// ============================================================

export type AgentEventType =
  // 思考事件
  | 'thinking_start'
  | 'thinking_chunk'
  | 'thinking_end'
  // 工具事件
  | 'tool_call'
  | 'tool_result'
  | 'tool_error'
  // 步骤事件
  | 'step_start'
  | 'step_progress'
  | 'step_end'
  // 数据检索事件
  | 'data_retrieval_start'
  | 'data_retrieval_progress'
  | 'data_retrieval_end'
  // 填表事件
  | 'fill_table_start'
  | 'fill_table_progress'
  | 'fill_table_end'
  // 内容事件
  | 'content_chunk'
  | 'content_end'
  | 'assistant_message'
  // 动作事件
  | 'action_required'
  | 'action_confirmed'
  | 'action_cancelled'
  // 系统事件
  | 'system_message'
  | 'warning'
  | 'error'
  // 终态事件
  | 'completed'
  | 'failed'
  | 'cancelled'
  // 统计事件
  | 'stats_update'

// ============================================================
// SSE 事件
// ============================================================

/** 从后端收到的 SSE 事件（解析后） */
export interface AgentEvent {
  event_type: AgentEventType
  step_id?: string
  timestamp: string
  data: Record<string, unknown>
}

// ============================================================
// Agent 步骤
// ============================================================

export type AgentStepType =
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'data_retrieval'
  | 'fill_table'
  | 'assistant_reply'
  | 'agent_delegation'

export type AgentStepStatus = 'pending' | 'running' | 'completed' | 'error'

export interface AgentStep {
  id: string
  type: AgentStepType
  name: string
  description: string
  status: AgentStepStatus
  progress: number
  toolName?: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  toolParams?: Record<string, any>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  toolResult?: Record<string, any>
  thinkingContent?: string
  errorMessage?: string
  agentName?: string
  children?: AgentStep[]
  streamingReply?: string
}

// ============================================================
// 任务统计
// ============================================================

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

// ============================================================
// 流式请求
// ============================================================

export interface AgentStreamRequest {
  message: string
  file_ids: string[]
  template_id?: string | null
  conversation_id?: string | null
  task_type?: 'auto' | 'fill_table' | 'query' | 'operation'
  task_id?: string
}

// ============================================================
// 流式回调
// ============================================================

export interface AgentStreamCallbacks {
  onEvent: (event: AgentEvent, steps: AgentStep[]) => void
  onComplete: (result: AgentStreamResult) => void
  onError: (error: string) => void
}

export interface AgentStreamResult {
  success: boolean
  message: string
  output_file_id?: string
  download_url?: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  task_stats?: any
  _replayDone?: boolean
}
