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
import { getTheme } from '../services/theme'

interface AgentThinkingPanelProps {
  steps: AgentStep[]
  isActive: boolean
}

/**
 * 单个步骤的详情渲染（主步骤和子步骤共用）
 */
function StepDetails({ step }: { step: AgentStep }) {
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return (
    <div className="px-3 pb-3 border-t border-slate-200">
      {/* 进度条 */}
      {step.status === 'running' && step.progress > 0 && (
        <div className="mt-2">
          <div className="w-full bg-slate-200 rounded-full h-1.5">
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
        <div className={`mt-2 p-2 rounded-lg text-sm border max-h-64 overflow-y-auto scrollbar-thin ${
          isDarkMode
            ? 'bg-blue-900/30 text-slate-200 border-blue-500/40'
            : 'bg-blue-50 text-slate-700 border-blue-200'
        }`}>
          <p className={`text-xs font-medium mb-1 ${isDarkMode ? 'text-blue-300' : 'text-blue-600'}`}>
            {step.type === 'assistant_reply' ? 'AI回复:' : '思考过程:'}
          </p>
          {step.thinkingContent}
        </div>
      )}

      {/* 工具参数 */}
      {step.toolParams && Object.keys(step.toolParams).length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-slate-500 font-medium">参数:</p>
          <pre className={`mt-1 p-2 rounded-lg text-xs max-h-32 overflow-auto scrollbar-thin ${
            isDarkMode
              ? 'bg-slate-800/80 text-slate-200'
              : 'bg-slate-100 text-slate-700'
          }`}>
            {JSON.stringify(step.toolParams, null, 2)}
          </pre>
        </div>
      )}

      {/* 工具结果 */}
      {step.toolResult && (
        <div className="mt-2">
          <p className="text-xs text-slate-500 font-medium">结果:</p>
          <div className={`mt-1 p-2 rounded-lg text-xs max-h-32 overflow-auto scrollbar-thin ${
            isDarkMode
              ? 'bg-green-900/30 text-slate-200 border border-green-500/40'
              : 'bg-green-50 border border-green-200 text-slate-700'
          }`}>
            {typeof step.toolResult === 'object' ? (
              <>
                {step.toolResult.records_count !== undefined && (
                  <p className={`font-medium mb-1 ${isDarkMode ? 'text-green-300' : 'text-green-600'}`}>
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
                  <p className="text-slate-600">
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
        <div className={`mt-2 p-2 rounded-lg text-sm ${
          isDarkMode
            ? 'bg-red-900/30 border border-red-500/40 text-red-300'
            : 'bg-red-50 border border-red-200 text-red-600'
        }`}>
          <p className={`text-xs font-medium mb-1 ${isDarkMode ? 'text-red-300' : 'text-red-600'}`}>错误:</p>
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
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const getStepIcon = (s: AgentStep) => {
    switch (s.type) {
      case 'thinking':
        return <Brain className="w-4 h-4 text-blue-500" />
      case 'tool_call':
        return <Wrench className="w-4 h-4 text-purple-500" />
      case 'data_retrieval':
        return <Database className="w-4 h-4 text-green-500" />
      case 'fill_table':
        return <Table className="w-4 h-4 text-orange-500" />
      case 'assistant_reply':
        return <MessageSquare className="w-4 h-4 text-blue-500" />
      case 'agent_delegation':
        return <Users className="w-4 h-4 text-cyan-500" />
      default:
        return <Search className="w-4 h-4 text-slate-400" />
    }
  }

  const getStepStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'error':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'running':
        return <Loader2 className="w-4 h-4 text-primary-500 animate-spin" />
      default:
        return null
    }
  }

  return (
    <div className={`rounded-lg border overflow-hidden ${
      isDarkMode
        ? 'bg-slate-800/80 border-slate-600'
        : 'bg-white border-slate-200'
    }`}>
      <button
        onClick={() => onToggle(step.id)}
        className={`w-full flex items-center justify-between p-3 transition-colors ${
          isDarkMode ? 'hover:bg-slate-700/80' : 'hover:bg-slate-50'
        }`}
      >
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-sm">#{index + 1}</span>
          {getStepIcon(step)}
          <span className={`font-medium text-sm ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>{step.name}</span>
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
  const autoCollapsedRef = useRef<Set<string>>(new Set())
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const allStepIds = steps.flatMap(s => {
    const ids = [s.id]
    if (s.children) ids.push(...s.children.map(c => c.id))
    return ids
  })
  const allStepIdsKey = allStepIds.join(',')

  useEffect(() => {
    if (steps.length > 0) {
      const latestStep = steps[steps.length - 1]
      setInternalExpanded((prev) => {
        const newSet = new Set(prev)
        if (!autoCollapsedRef.current.has(latestStep.id)) {
          newSet.add(latestStep.id)
        }
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
    <div className={`rounded-xl border p-4 my-2 ${
      isDarkMode
        ? 'bg-slate-800/80 border-slate-600'
        : 'bg-white border-slate-200'
    }`}>
      <div className="flex items-center gap-2 mb-3">
        {isActive ? (
          <Loader2 className="w-5 h-5 text-primary-500 animate-spin" />
        ) : (
          <CheckCircle className="w-5 h-5 text-green-500" />
        )}
        <span className={`font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
          {isActive ? 'Agent正在处理...' : 'Agent执行完成'}
        </span>
      </div>

      <div className="space-y-2">
        {steps.map((step, index) => (
          <div key={step.id}>
            <StepCard
              step={step}
              index={index}
              expanded={internalExpanded.has(step.id)}
              onToggle={toggleStep}
            />

            {step.children && step.children.length > 0 && internalExpanded.has(step.id) && (
              <div className={`ml-6 mt-1.5 pl-4 border-l-2 border-dashed space-y-1.5 ${
                isDarkMode ? 'border-cyan-500/60' : 'border-cyan-300'
              }`}>
                <p className={`text-xs font-medium ${isDarkMode ? 'text-cyan-300' : 'text-cyan-600'}`}>
                  {step.agentName === 'delegate_fill_table' ? '填表Agent' :
                   step.agentName === 'delegate_document_edit' ? '文档编辑Agent' :
                   step.agentName || '子Agent'} 执行过程:
                </p>
                {step.children.map((child, ci) => (
                  <div key={child.id}>
                    {child.type === 'assistant_reply' ? (
                      <div className={`rounded-xl p-3 border text-sm ${
                        isDarkMode
                          ? 'bg-slate-700/80 border-slate-600 text-slate-200'
                          : 'bg-slate-50 border-slate-200 text-slate-700'
                      }`}>
                        <div className="prose prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{child.thinkingContent || child.description}</ReactMarkdown>
                        </div>
                      </div>
                    ) : (
                      <StepCard
                        step={child}
                        index={ci}
                        expanded={internalExpanded.has(child.id)}
                        onToggle={toggleStep}
                      />
                    )}
                  </div>
                ))}

                {step.streamingReply && (
                  <div className={`rounded-xl p-3 border text-sm mt-2 ${
                    isDarkMode
                      ? 'bg-slate-700/80 border-slate-600 text-slate-200'
                      : 'bg-slate-50 border-slate-200 text-slate-700'
                  }`}>
                    <div className="prose prose-sm max-w-none">
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
