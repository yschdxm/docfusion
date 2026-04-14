import { Loader2, CheckCircle, XCircle, Download } from 'lucide-react'

export interface ActionData {
  action_id: string
  action_type: string
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

  if (action_type === 'confirm_extract' || action_type === 'confirm_fill') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-primary-500/10 border border-primary-500/30">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary-500/20 flex items-center justify-center shrink-0">
            <CheckCircle className="w-5 h-5 text-primary-500" />
          </div>
          <div className="flex-1">
            <h4 className="font-medium text-slate-900 mb-1">{title}</h4>
            <p className="text-sm text-slate-600 mb-3">{description}</p>
            <div className="flex gap-2">
              <button onClick={onConfirm} className="px-4 py-2 bg-primary-500 text-white text-sm rounded-lg hover:bg-primary-600 transition-colors">
                确认执行
              </button>
              <button onClick={onCancel} className="px-4 py-2 bg-white text-slate-700 text-sm rounded-lg border border-slate-200 hover:bg-slate-100 transition-colors">
                取消
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (action_type === 'executing') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-blue-500/10 border border-blue-500/30">
        <div className="flex items-center gap-3">
          <Loader2 className="w-6 h-6 text-blue-500 animate-spin shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-slate-900 mb-1">{title}</h4>
            <p className="text-sm text-slate-600">{description}</p>
            {progress !== undefined && (
              <div className="mt-2">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span>进度</span>
                  <span>{progress}%</span>
                </div>
                <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-blue-500 to-primary-500 transition-all duration-300" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (action_type === 'completed') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-green-500/10 border border-green-500/30">
        <div className="flex items-start gap-3">
          <CheckCircle className="w-6 h-6 text-green-500 shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-slate-900 mb-1">{title}</h4>
            <p className="text-sm text-slate-600">{description}</p>
            {result?.filled_file_url && (
              <a
                href={result.filled_file_url}
                download
                className="mt-2 inline-flex items-center gap-2 px-3 py-1.5 bg-green-500/20 text-green-700 text-sm rounded-lg hover:bg-green-500/30 transition-colors"
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

  if (action_type === 'failed') {
    return (
      <div className="mt-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30">
        <div className="flex items-start gap-3">
          <XCircle className="w-6 h-6 text-red-500 shrink-0" />
          <div className="flex-1">
            <h4 className="font-medium text-slate-900 mb-1">{title}</h4>
            <p className="text-sm text-red-700">{description}</p>
          </div>
        </div>
      </div>
    )
  }

  return null
}
