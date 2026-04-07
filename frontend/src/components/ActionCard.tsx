import { Loader2, CheckCircle, XCircle, Download, AlertCircle } from 'lucide-react'

export interface ActionData {
  action_id: string
  action_type: string  // confirm_extract, confirm_fill, executing, completed, failed
  title: string
  description: string
  progress?: number
  result?: {
    entities_count?: number
    filled_file_url?: string
    output_filename?: string
    [key: string]: any
  }
}

interface ActionCardProps {
  action: ActionData
  onConfirm?: () => void
  onCancel?: () => void
}

export default function ActionCard({ action, onConfirm, onCancel }: ActionCardProps) {
  const { action_type, title, description, progress, result } = action

  // 确认卡片
  if (action_type === 'confirm_extract' || action_type === 'confirm_fill') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-primary-500/10 border border-primary-500/30">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary-500/20 flex items-center justify-center shrink-0">
            {action_type === 'confirm_extract' ? (
              <svg className="w-5 h-5 text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            )}
          </div>
          <div className="flex-1">
            <h4 className="font-medium text-white mb-1">{title}</h4>
            <p className="text-sm text-slate-400 mb-3">{description}</p>
            <div className="flex gap-2">
              <button
                onClick={onConfirm}
                className="px-4 py-2 bg-primary-500 text-white text-sm rounded-lg hover:bg-primary-600 transition-colors"
              >
                确认执行
              </button>
              <button
                onClick={onCancel}
                className="px-4 py-2 bg-white/10 text-slate-300 text-sm rounded-lg hover:bg-white/20 transition-colors"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // 执行中卡片
  if (action_type === 'executing') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-blue-500/10 border border-blue-500/30">
        <div className="flex items-center gap-3">
          <Loader2 className="w-6 h-6 text-blue-400 animate-spin shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-white mb-1">{title}</h4>
            <p className="text-sm text-slate-400">{description}</p>
            {progress !== undefined && (
              <div className="mt-2">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>进度</span>
                  <span>{progress}%</span>
                </div>
                <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-gradient-to-r from-blue-500 to-primary-500 transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // 完成卡片
  if (action_type === 'completed') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-green-500/10 border border-green-500/30">
        <div className="flex items-start gap-3">
          <CheckCircle className="w-6 h-6 text-green-400 shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-white mb-1">{title}</h4>
            <p className="text-sm text-slate-400">{description}</p>
            {result?.filled_file_url && (
              <a
                href={result.filled_file_url}
                download
                className="mt-2 inline-flex items-center gap-2 px-3 py-1.5 bg-green-500/20 text-green-400 text-sm rounded-lg hover:bg-green-500/30 transition-colors"
              >
                <Download className="w-4 h-4" />
                下载文件
              </a>
            )}
          </div>
        </div>
      </div>
    )
  }

  // 失败卡片
  if (action_type === 'failed') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30">
        <div className="flex items-start gap-3">
          <XCircle className="w-6 h-6 text-red-400 shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-white mb-1">{title}</h4>
            <p className="text-sm text-red-300">{description}</p>
          </div>
        </div>
      </div>
    )
  }

  return null
}
