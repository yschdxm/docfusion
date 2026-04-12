/**
 * Agent思考过程展示面板
 *
 * 实时展示Agent的执行步骤、工具调用和结果
 * 支持子Agent嵌套显示
 */
import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Brain,
  Database,
  Search,
  Table,
  Wrench,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Users,
} from 'lucide-react'
import { AgentStep } from '../services/agentStreamService'

interface AgentThinkingPanelProps {
  steps: AgentStep[]
  isActive: boolean
}

/**
 * 单个步骤的详情渲染（主步骤和子步骤共用）
 */
function StepDetails({ step }: { step: AgentStep }) {
  return (
    <div className="px-3 pb-3 border-t border-white/5">
      {/* 进度条 */}
      {step.status === 'running' && step.progress > 0 && (
        <div className="mt-2">
          <div className="w-full bg-slate-700 rounded-full h-1.5">
            <div
              className="bg-gradient-to-r from-primary-500 to-purple-500 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${step.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* 描述 */}
      {step.description && (
        <p className="text-xs text-slate-500 mt-2">{step.description}</p>
      )}

      {/* 思考内容或AI回复内容 */}
      {step.thinkingContent && (
        <div className="mt-2 p-2 bg-blue-500/10 rounded-lg text-sm text-slate-300 border border-blue-500/20 max-h-64 overflow-y-auto scrollbar-thin">
          <p className="text-xs text-blue-400 font-medium mb-1">
            {step.type === 'assistant_reply' ? 'AI回复:' : '思考过程:'}
          </p>
          {step.thinkingContent}
        </div>
      )}

      {/* 工具参数 */}
      {step.toolParams && Object.keys(step.toolParams).length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-slate-500 font-medium">参数:</p>
          <pre className="mt-1 p-2 bg-slate-800/50 rounded-lg text-xs text-slate-300 overflow-x-auto scrollbar-thin">
            {JSON.stringify(step.toolParams, null, 2)}
          </pre>
        </div>
      )}

      {/* 工具结果 */}
      {step.toolResult && (
        <div className="mt-2">
          <p className="text-xs text-slate-500 font-medium">结果:</p>
          <div className="mt-1 p-2 bg-green-500/10 border border-green-500/20 rounded-lg text-xs text-slate-300 max-h-32 overflow-y-auto scrollbar-thin">
            {typeof step.toolResult === 'object' ? (
              <>
                {step.toolResult.records_count !== undefined && (
                  <p className="font-medium text-green-400 mb-1">
                    找到 {step.toolResult.records_count} 条记录
                  </p>
                )}
                {step.toolResult.records && (
                  <pre className="whitespace-pre-wrap">
                    {JSON.stringify(step.toolResult.records.slice(0, 3), null, 2)}
                    {step.toolResult.records.length > 3 && (
                      <p className="text-slate-500 mt-1">
                        ... 还有 {step.toolResult.records.length - 3} 条记录
                      </p>
                    )}
                  </pre>
                )}
                {step.toolResult.headers && (
                  <p className="text-slate-400">
                    表头: {step.toolResult.headers.join(', ')}
                  </p>
                )}
                {!step.toolResult.records && !step.toolResult.headers && (
                  <pre className="whitespace-pre-wrap">
                    {JSON.stringify(step.toolResult, null, 2)}
                  </pre>
                )}
              </>
            ) : (
              String(step.toolResult)
            )}
          </div>
        </div>
      )}

      {/* 错误信息 */}
      {step.errorMessage && (
        <div className="mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400">
          <p className="text-xs text-red-400 font-medium mb-1">错误:</p>
          {step.errorMessage}
        </div>
      )}
    </div>
  )
}

/**
 * 单个步骤卡片（主步骤和子步骤共用）
 */
function StepCard({
  step,
  index,
  expanded,
  onToggle,
}: {
  step: AgentStep
  index: number
  expanded: boolean
  onToggle: (id: string) => void
}) {
  const getStepIcon = (s: AgentStep) => {
    switch (s.type) {
      case 'thinking':
        return <Brain className="w-4 h-4 text-blue-400" />
      case 'tool_call':
        return <Wrench className="w-4 h-4 text-purple-400" />
      case 'data_retrieval':
        return <Database className="w-4 h-4 text-green-400" />
      case 'fill_table':
        return <Table className="w-4 h-4 text-orange-400" />
      case 'assistant_reply':
        return <MessageSquare className="w-4 h-4 text-blue-400" />
      case 'agent_delegation':
        return <Users className="w-4 h-4 text-cyan-400" />
      default:
        return <Search className="w-4 h-4 text-slate-400" />
    }
  }

  const getStepStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />
      case 'running':
        return <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
      default:
        return null
    }
  }

  return (
    <div className="bg-white/5 rounded-lg border border-white/5 overflow-hidden">
      <button
        onClick={() => onToggle(step.id)}
        className="w-full flex items-center justify-between p-3 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-slate-500 text-sm">#{index + 1}</span>
          {getStepIcon(step)}
          <span className="font-medium text-sm text-slate-300">{step.name}</span>
          {getStepStatusIcon(step.status)}
        </div>
        <div className="flex items-center gap-2">
          {step.status === 'running' && step.progress > 0 && (
            <span className="text-xs text-slate-500">{Math.round(step.progress)}%</span>
          )}
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
        </div>
      </button>

      {expanded && <StepDetails step={step} />}
    </div>
  )
}

export default function AgentThinkingPanel({ steps, isActive }: AgentThinkingPanelProps) {
  const [internalExpanded, setInternalExpanded] = useState<Set<string>>(new Set())
  // 追踪被自动折叠的步骤ID，防止 auto-expand 重新展开它们
  const autoCollapsedRef = useRef<Set<string>>(new Set())

  // 收集所有步骤ID（主步骤 + 子步骤），用于自动展开/折叠
  const allStepIds = steps.flatMap(s => {
    const ids = [s.id]
    if (s.children) ids.push(...s.children.map(c => c.id))
    return ids
  })
  const allStepIdsKey = allStepIds.join(',')

  // 自动展开最新步骤（主步骤和子步骤都适用）
  // 跳过已被自动折叠的步骤，避免 expand/collapse 竞争
  useEffect(() => {
    if (steps.length > 0) {
      const latestStep = steps[steps.length - 1]
      setInternalExpanded((prev) => {
        const newSet = new Set(prev)
        // 只展开未被自动折叠的步骤
        if (!autoCollapsedRef.current.has(latestStep.id)) {
          newSet.add(latestStep.id)
        }
        // 如果最新主步骤有子步骤，也展开最新的子步骤
        if (latestStep.children && latestStep.children.length > 0) {
          const latestChild = latestStep.children[latestStep.children.length - 1]
          if (!autoCollapsedRef.current.has(latestChild.id)) {
            newSet.add(latestChild.id)
          }
        }
        return newSet
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps.length, allStepIdsKey])

  // 当步骤完成时自动折叠（thinking、agent_delegation 及子步骤都适用）
  useEffect(() => {
    const checkAndCollapse = (s: AgentStep) => {
      if (s.type === 'thinking' && s.status === 'completed' && s.name === '思考完成') {
        setTimeout(() => {
          autoCollapsedRef.current.add(s.id)
          setInternalExpanded((prev) => {
            const newSet = new Set(prev)
            newSet.delete(s.id)
            return newSet
          })
        }, 500)
      }
      // 委派步骤完成时折叠自身
      if (s.type === 'agent_delegation' && s.status === 'completed') {
        setTimeout(() => {
          autoCollapsedRef.current.add(s.id)
          setInternalExpanded((prev) => {
            const newSet = new Set(prev)
            newSet.delete(s.id)
            return newSet
          })
        }, 500)
      }
    }
    steps.forEach(checkAndCollapse)
    steps.forEach(s => s.children?.forEach(checkAndCollapse))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps])

  const toggleStep = (stepId: string) => {
    setInternalExpanded((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(stepId)) {
        newSet.delete(stepId)
      } else {
        newSet.add(stepId)
      }
      return newSet
    })
  }

  if (!isActive && steps.length === 0) {
    return null
  }

  return (
    <div className="bg-white/5 rounded-xl border border-white/10 p-4 my-2">
      <div className="flex items-center gap-2 mb-3">
        {isActive ? (
          <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
        ) : (
          <CheckCircle className="w-5 h-5 text-green-400" />
        )}
        <span className="font-medium text-slate-300">
          {isActive ? 'Agent正在处理...' : 'Agent执行完成'}
        </span>
      </div>

      <div className="space-y-2">
        {steps.map((step, index) => (
          <div key={step.id}>
            {/* 主步骤 */}
            <StepCard
              step={step}
              index={index}
              expanded={internalExpanded.has(step.id)}
              onToggle={toggleStep}
            />

            {/* 子步骤嵌套区域 — 跟随父步骤折叠状态 */}
            {step.children && step.children.length > 0 && internalExpanded.has(step.id) && (
              <div className="ml-6 mt-1.5 pl-4 border-l-2 border-dashed border-cyan-500/30 space-y-1.5">
                <p className="text-xs text-cyan-400/70 font-medium">
                  {step.agentName === 'delegate_fill_table' ? '填表Agent' :
                   step.agentName === 'delegate_document_edit' ? '文档编辑Agent' :
                   step.agentName || '子Agent'} 执行过程:
                </p>
                {step.children.map((child, ci) => (
                  <div key={child.id}>
                    {child.type === 'assistant_reply' ? (
                      // 子Agent的消息渲染为消息气泡
                      <div className="rounded-xl p-3 bg-white/5 border border-white/10 text-slate-200 text-sm">
                        <div className="prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{child.thinkingContent || child.description}</ReactMarkdown>
                        </div>
                      </div>
                    ) : (
                      // 其他步骤渲染为步骤卡片
                      <StepCard
                        step={child}
                        index={ci}
                        expanded={internalExpanded.has(child.id)}
                        onToggle={toggleStep}
                      />
                    )}
                  </div>
                ))}

                {/* 子Agent流式回复的实时显示 */}
                {step.streamingReply && (
                  <div className="rounded-xl p-3 bg-white/5 border border-white/10 text-slate-200 text-sm mt-2">
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.streamingReply}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
