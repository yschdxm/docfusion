import { useState, useEffect, useRef } from 'react'
import { TaskStats } from '../services/agentStreamService'

interface TaskStatsBadgeProps {
  stats: TaskStats
  isLive?: boolean
  liveDuration?: number
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTokens(tokens: number): string {
  if (tokens < 1000) return tokens.toString()
  if (tokens < 1000000) return `${(tokens / 1000).toFixed(1)}K`
  return `${(tokens / 1000000).toFixed(1)}M`
}

function AnimatedNumber({ value, formatter }: { value: number; formatter: (n: number) => string }) {
  const [displayValue, setDisplayValue] = useState(value)
  const [isAnimating, setIsAnimating] = useState(false)
  const prevValueRef = useRef(value)

  useEffect(() => {
    if (value !== prevValueRef.current) {
      setIsAnimating(true)
      const startValue = prevValueRef.current
      const endValue = value
      const duration = 300
      const startTime = Date.now()

      const animate = () => {
        const elapsed = Date.now() - startTime
        const progress = Math.min(elapsed / duration, 1)
        const eased = 1 - Math.pow(1 - progress, 3)
        const current = Math.round(startValue + (endValue - startValue) * eased)
        setDisplayValue(current)

        if (progress < 1) {
          requestAnimationFrame(animate)
        } else {
          setIsAnimating(false)
          prevValueRef.current = value
        }
      }

      requestAnimationFrame(animate)
    }
  }, [value])

  return (
    <span className={`transition-all ${isAnimating ? 'text-blue-600 font-medium' : ''}`}>
      {formatter(displayValue)}
    </span>
  )
}

export default function TaskStatsBadge({ stats, isLive = false, liveDuration }: TaskStatsBadgeProps) {
  const [expanded, setExpanded] = useState(false)

  const displayDuration = isLive && liveDuration !== undefined ? liveDuration : stats.duration_ms

  return (
    <div className="inline-block mt-1">
      {/* 主统计行 */}
      <div
        className={`flex items-center gap-3 px-2.5 py-1 text-xs rounded-md cursor-pointer transition-colors ${
          isLive
            ? 'text-blue-600 bg-blue-50 border border-blue-200 hover:bg-blue-100'
            : 'text-slate-500 bg-slate-50 border border-slate-200 hover:bg-slate-100'
        }`}
        onClick={() => setExpanded(!expanded)}
      >
        {/* 耗时 */}
        <div className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className={isLive ? 'tabular-nums' : ''}>{formatDuration(displayDuration)}</span>
        </div>

        <span className={isLive ? 'text-blue-300' : 'text-slate-300'}>|</span>

        {/* Token数 */}
        <div className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
          </svg>
          <AnimatedNumber value={stats.total_tokens} formatter={formatTokens} /> tokens
        </div>

        <span className={isLive ? 'text-blue-300' : 'text-slate-300'}>|</span>

        {/* LLM调用次数 */}
        <div className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <AnimatedNumber value={stats.llm_calls} formatter={(n) => n.toString()} /> 次调用
        </div>

        {/* 展开/收起图标 */}
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* 展开的详细信息 */}
      {expanded && (
        <div className={`mt-1 px-2.5 py-2 text-xs rounded-md ${
          isLive
            ? 'text-blue-600 bg-blue-50 border border-blue-200'
            : 'text-slate-500 bg-slate-50 border border-slate-200'
        }`}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <div className="flex justify-between">
              <span className={isLive ? 'text-blue-400' : 'text-slate-400'}>输入tokens:</span>
              <AnimatedNumber value={stats.prompt_tokens} formatter={formatTokens} />
            </div>
            <div className="flex justify-between">
              <span className={isLive ? 'text-blue-400' : 'text-slate-400'}>输出tokens:</span>
              <AnimatedNumber value={stats.completion_tokens} formatter={formatTokens} />
            </div>
            <div className="flex justify-between">
              <span className={isLive ? 'text-blue-400' : 'text-slate-400'}>缓存tokens:</span>
              <AnimatedNumber value={stats.cached_tokens} formatter={formatTokens} />
            </div>
            <div className="flex justify-between">
              <span className={isLive ? 'text-blue-400' : 'text-slate-400'}>思考tokens:</span>
              <AnimatedNumber value={stats.reasoning_tokens} formatter={formatTokens} />
            </div>
            <div className="flex justify-between">
              <span className={isLive ? 'text-blue-400' : 'text-slate-400'}>迭代次数:</span>
              <AnimatedNumber value={stats.iterations} formatter={(n) => n.toString()} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
