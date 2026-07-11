/**
 * Agent 事件处理器
 *
 * 纯函数：接收 SSE 事件 + 当前步骤状态 → 返回更新后的步骤列表。
 * 不持有副作用，不管理连接，不访问 DOM。
 *
 * 从原 agentStreamService._processEvent / _handleChildEvent 提取。
 */

import type { AgentEvent, AgentStep } from '../types/agent'
import { tr } from './i18n'

// ============================================================
// StepState — 事件处理器的内部状态
// ============================================================

export interface StepState {
  steps: Map<string, AgentStep>
  orderedIds: string[]
  currentAgentName: string | null
  agentParentStepId: string | null
  replyCounter: number
}

export function createStepState(): StepState {
  return {
    steps: new Map(),
    orderedIds: [],
    currentAgentName: null,
    agentParentStepId: null,
    replyCounter: 0,
  }
}

export function getStepsArray(state: StepState): AgentStep[] {
  return state.orderedIds
    .map(id => state.steps.get(id))
    .filter((s): s is AgentStep => s !== undefined)
}

// ============================================================
// 事件处理入口
// ============================================================

/**
 * 处理一个 SSE 事件，更新 StepState。
 * 返回更新后的 steps 数组快照。
 */
export function processEvent(state: StepState, event: AgentEvent): AgentStep[] {
  const etype = event.event_type

  // 委派结束
  if (event.data.is_delegation_end) {
    const delegationStep = state.steps.get(event.step_id || '')
    if (delegationStep) {
      delegationStep.status = 'completed'
      delegationStep.progress = 100
    }
    state.currentAgentName = null
    state.agentParentStepId = null
    return getStepsArray(state)
  }

  // 子 agent 事件 → 路由到 children
  if (isChildAgentEvent(state, event)) {
    handleChildEvent(state, event)
    return getStepsArray(state)
  }

  // 主 agent 事件
  const stepId = event.step_id || `step_${Date.now()}`

  switch (etype) {
    case 'step_start':
      if (event.data.is_delegation_start) {
        state.currentAgentName = event.data.agent_name as string
        state.agentParentStepId = stepId
        ensureStep(state, stepId, {
          id: stepId,
          type: 'agent_delegation',
          name: event.data.step_name as string,
          description: (event.data.description as string) || '',
          status: 'running',
          progress: 0,
          children: [],
          agentName: event.data.agent_name as string,
        })
      } else {
        ensureStep(state, stepId, {
          id: stepId,
          type: inferStepType(event.data.step_name as string),
          name: event.data.step_name as string,
          description: event.data.description as string,
          status: 'running',
          progress: 0,
        })
      }
      break

    case 'step_progress': {
      const s = state.steps.get(stepId)
      if (s) s.progress = (event.data.progress as number) || 0
      break
    }

    case 'step_end': {
      const s = state.steps.get(stepId)
      if (s) { s.status = 'completed'; s.progress = 100 }
      break
    }

    case 'tool_call':
      ensureStep(state, stepId, {
        id: stepId,
        type: 'tool_call',
        name: tr(`调用 ${event.data.tool_name}`, `Calling ${event.data.tool_name}`, `${event.data.tool_name} を呼び出し`),
        description: tr(`执行工具: ${event.data.tool_name}`, `Executing tool: ${event.data.tool_name}`, `ツール実行: ${event.data.tool_name}`),
        status: 'running',
        progress: 50,
        toolName: event.data.tool_name as string,
        toolParams: event.data.parameters as Record<string, unknown>,
      })
      break

    case 'tool_result': {
      const s = state.steps.get(stepId)
      if (s) {
        s.status = 'completed'
        s.progress = 100
        s.toolResult = event.data.result as Record<string, unknown>
      }
      break
    }

    case 'tool_error': {
      const s = state.steps.get(stepId)
      if (s) {
        s.status = 'error'
        s.errorMessage = event.data.error as string
      }
      break
    }

    case 'thinking_start': {
      const existing = state.steps.get(stepId)
      if (existing) {
        existing.status = 'running'
        existing.name = (event.data.message as string) || existing.name
      } else {
        ensureStep(state, stepId, {
          id: stepId,
          type: 'thinking',
          name: (event.data.message as string) || tr('思考中', 'Thinking', '思考中'),
          description: tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'),
          status: 'running',
          progress: 0,
          thinkingContent: '',
        })
      }
      break
    }

    case 'thinking_chunk': {
      let s = state.steps.get(stepId)
      if (!s) {
        s = {
          id: stepId,
          type: 'thinking',
          name: tr('思考中', 'Thinking', '思考中'),
          description: tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'),
          status: 'running',
          progress: 0,
          thinkingContent: '',
        }
        ensureStep(state, stepId, s)
      }
      s.thinkingContent = (s.thinkingContent || '') + (event.data.content as string || '')
      break
    }

    case 'thinking_end': {
      const s = state.steps.get(stepId)
      if (s) {
        s.status = 'completed'
        s.progress = 100
        s.name = tr('思考完成', 'Thinking complete', '思考完了')
      }
      break
    }

    case 'content_chunk':
      // 主 agent 的 content_chunk 不在 steps 中体现
      break

    case 'content_end': {
      const s = state.steps.get(stepId)
      if (s) { s.status = 'completed'; s.progress = 100 }
      break
    }

    case 'assistant_message':
      // 新一轮对话，清空步骤
      state.steps.clear()
      state.orderedIds = []
      break

    case 'data_retrieval_start':
      ensureStep(state, stepId, {
        id: stepId,
        type: 'data_retrieval',
        name: tr(`查询 ${event.data.source}`, `Query ${event.data.source}`, `${event.data.source} を検索`),
        description: tr(`从 ${event.data.source} 检索数据`, `Retrieving data from ${event.data.source}`, `${event.data.source} からデータを取得`),
        status: 'running',
        progress: 0,
      })
      break

    case 'data_retrieval_progress': {
      const s = state.steps.get(stepId)
      if (s) s.progress = (event.data.records_found as number) > 0 ? 50 : 0
      break
    }

    case 'fill_table_progress': {
      let s = state.steps.get(stepId)
      if (!s) {
        s = {
          id: stepId,
          type: 'fill_table',
          name: tr('填写表格', 'Filling table', '表を入力'),
          description: tr('正在将数据填入模板', 'Filling data into template', 'データをテンプレートに入力中'),
          status: 'running',
          progress: 0,
        }
        ensureStep(state, stepId, s)
      }
      s.progress = (event.data.progress as number) || 0
      break
    }

    case 'stats_update':
      // 统计更新事件，由上层处理
      break

    case 'completed': {
      const s = state.steps.get(stepId)
      if (s && s.type === 'thinking') {
        s.status = 'completed'
        s.progress = 100
      }
      break
    }

    case 'failed': {
      const fid = event.step_id || `step_fail_${Date.now()}`
      ensureStep(state, fid, {
        id: fid,
        type: 'thinking',
        name: tr('任务失败', 'Task failed', 'タスク失敗'),
        description: (event.data.error as string) || tr('任务执行失败', 'Task execution failed', 'タスク実行失敗'),
        status: 'error',
        progress: 0,
        errorMessage: event.data.error as string,
      })
      break
    }

    case 'error': {
      const eid = event.step_id || `step_error_${Date.now()}`
      const e = state.steps.get(eid)
      const msg = (event.data.error as string) || (event.data.message as string) || tr('发生错误', 'An error occurred', 'エラーが発生しました')
      if (e) {
        e.status = 'error'
        e.errorMessage = msg
      } else {
        ensureStep(state, eid, {
          id: eid,
          type: 'thinking',
          name: tr('错误', 'Error', 'エラー'),
          description: msg,
          status: 'error',
          progress: 0,
          errorMessage: msg,
        })
      }
      break
    }
  }

  return getStepsArray(state)
}

// ============================================================
// 子 agent 事件处理
// ============================================================

function isChildAgentEvent(state: StepState, event: AgentEvent): boolean {
  if (event.data.is_delegation_end) return false
  return !!(
    event.data.agent_name &&
    state.currentAgentName &&
    event.data.agent_name === state.currentAgentName
  )
}

function handleChildEvent(state: StepState, event: AgentEvent): void {
  if (!state.agentParentStepId) return
  const parentStep = state.steps.get(state.agentParentStepId)
  if (!parentStep) return
  if (!parentStep.children) parentStep.children = []

  const stepId = event.step_id || `child_step_${Date.now()}`

  switch (event.event_type) {
    case 'step_start': {
      const stepType = inferStepType(event.data.step_name as string || '')
      findOrCreateChildStep(parentStep, stepId, stepType, (event.data.step_name as string) || tr('步骤', 'Step', 'ステップ'), (event.data.description as string) || '')
      break
    }
    case 'step_progress': {
      const child = parentStep.children.find(c => c.id === stepId)
      if (child) child.progress = (event.data.progress as number) || 0
      break
    }
    case 'step_end': {
      const child = parentStep.children.find(c => c.id === stepId)
      if (child) { child.status = 'completed'; child.progress = 100 }
      break
    }
    case 'thinking_start': {
      const child = findOrCreateChildStep(parentStep, stepId, 'thinking', event.data.message as string || tr('思考中', 'Thinking', '思考中'), tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'))
      child.status = 'running'
      if (!child.thinkingContent) child.thinkingContent = ''
      break
    }
    case 'thinking_chunk': {
      const child = findOrCreateChildStep(parentStep, stepId, 'thinking', tr('思考中', 'Thinking', '思考中'), tr('Agent正在分析任务', 'Agent is analyzing the task', 'Agentがタスクを分析中'))
      child.thinkingContent = (child.thinkingContent || '') + (event.data.content as string || '')
      break
    }
    case 'thinking_end': {
      const child = parentStep.children.find(c => c.id === stepId)
      if (child) {
        child.status = 'completed'
        child.progress = 100
        child.name = tr('思考完成', 'Thinking complete', '思考完了')
      }
      break
    }
    case 'tool_call': {
      const child = findOrCreateChildStep(
        parentStep, stepId, 'tool_call',
        tr(`调用 ${event.data.tool_name}`, `Calling ${event.data.tool_name}`, `${event.data.tool_name} を呼び出し`),
        tr(`执行工具: ${event.data.tool_name}`, `Executing tool: ${event.data.tool_name}`, `ツール実行: ${event.data.tool_name}`)
      )
      child.toolName = event.data.tool_name as string
      child.toolParams = event.data.parameters as Record<string, unknown>
      child.status = 'running'
      child.progress = 50
      break
    }
    case 'tool_result': {
      const child = parentStep.children.find(c => c.id === stepId)
      if (child) {
        child.status = 'completed'
        child.progress = 100
        child.toolResult = event.data.result as Record<string, unknown>
      }
      break
    }
    case 'tool_error': {
      const child = parentStep.children.find(c => c.id === stepId)
      if (child) {
        child.status = 'error'
        child.errorMessage = event.data.error as string
      }
      break
    }
    case 'content_chunk':
      if (event.data.content) {
        if (!parentStep.streamingReply) parentStep.streamingReply = ''
        parentStep.streamingReply += event.data.content as string
      }
      break
    case 'content_end':
      parentStep.streamingReply = ''
      break
    case 'assistant_message': {
      const msg = event.data.message as string || ''
      if (msg) {
        parentStep.children.push({
          id: `reply_${++state.replyCounter}`,
          type: 'assistant_reply',
          name: tr('AI回复', 'AI Reply', 'AI応答'),
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
      parentStep.children.forEach(c => {
        if (c.status === 'running') {
          c.status = event.event_type === 'completed' ? 'completed' : 'error'
          c.progress = 100
        }
      })
      break
    }
  }
}

// ============================================================
// 工具函数
// ============================================================

function ensureStep(state: StepState, id: string, step: AgentStep): void {
  if (!state.steps.has(id)) {
    state.orderedIds.push(id)
  }
  state.steps.set(id, step)
}

function findOrCreateChildStep(
  parent: AgentStep, stepId: string, type: AgentStep['type'], name: string, description: string
): AgentStep {
  if (!parent.children) parent.children = []
  const existing = parent.children.find(c => c.id === stepId)
  if (existing) return existing
  const child: AgentStep = { id: stepId, type, name, description, status: 'running', progress: 0 }
  parent.children.push(child)
  return child
}

function inferStepType(stepName: string): AgentStep['type'] {
  if (stepName.includes('查询') || stepName.includes('检索')) return 'data_retrieval'
  if (stepName.includes('填写') || stepName.includes('填表')) return 'fill_table'
  if (stepName.includes('调用')) return 'tool_call'
  if (stepName.includes('思考')) return 'thinking'
  return 'thinking'
}
