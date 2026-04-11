/**
 * Agent思考过程展示面板
 *
 * 实时展示Agent的执行步骤、工具调用和结果
 */
import { useState, useEffect } from 'react'
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
} from 'lucide-react'
import { AgentStep } from '../services/agentStreamService'

interface AgentThinkingPanelProps {
  steps: AgentStep[]
  isActive: boolean
}

export default function AgentThinkingPanel({ steps, isActive }: AgentThinkingPanelProps) {
  const [internalExpanded, setInternalExpanded] = useState<Set<string>>(new Set())

  // 自动展开最新步骤
  useEffect(() => {
    if (steps.length > 0) {
      const latestStep = steps[steps.length - 1]
      setInternalExpanded((prev) => new Set([...prev, latestStep.id]))
    }
  }, [steps.length])

  // 当 thinking 步骤完成时自动折叠
  useEffect(() => {
    steps.forEach(step => {
      if (step.type === 'thinking' && step.status === 'completed' && step.name === '思考完成') {
        // 延迟一点时间再折叠，让用户看到完成状态
        setTimeout(() => {
          setInternalExpanded((prev) => {
            const newSet = new Set(prev)
            newSet.delete(step.id)
            return newSet
          })
        }, 500)
      }
    })
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

  const getStepIcon = (step: AgentStep) => {
    switch (step.type) {
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
          <div
            key={step.id}
            className="bg-white/5 rounded-lg border border-white/5 overflow-hidden"
          >
            <button
              onClick={() => toggleStep(step.id)}
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
                {internalExpanded.has(step.id) ? (
                  <ChevronUp className="w-4 h-4 text-slate-400" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-slate-400" />
                )}
              </div>
            </button>

            {internalExpanded.has(step.id) && (
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
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
