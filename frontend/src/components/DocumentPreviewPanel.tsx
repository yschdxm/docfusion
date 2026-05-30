import { FileText, Loader2 } from 'lucide-react'
import type { PreviewFile } from '../hooks/useDocumentPreview'

interface DocumentPreviewPanelProps {
  previewFiles: PreviewFile[]
  currentFile: PreviewFile | null
  onFileSelect: (file: PreviewFile) => void
  isLoading: boolean
}

export default function DocumentPreviewPanel({
  previewFiles,
  currentFile,
  onFileSelect,
  isLoading,
}: DocumentPreviewPanelProps) {
  return (
    <div className="h-full overflow-hidden flex flex-col glass">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-4 h-4 text-primary-400 flex-shrink-0" />
          <span className="text-sm text-slate-300 truncate">
            {currentFile?.name || '文档预览'}
          </span>
        </div>
      </div>

      {/* 文件标签页 */}
      {previewFiles.length > 1 && (
        <div className="flex gap-1 px-3 py-2 border-b border-white/10 overflow-x-auto scrollbar-thin">
          {previewFiles.map(f => (
            <button
              key={f.id}
              onClick={() => onFileSelect(f)}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg whitespace-nowrap transition-colors ${
                f.id === currentFile?.id
                  ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30'
                  : 'text-slate-400 hover:bg-white/5 border border-transparent'
              }`}
              title={f.name}
            >
              <FileText className="w-3 h-3 flex-shrink-0" />
              <span className="truncate max-w-[100px]">{f.name}</span>
            </button>
          ))}
        </div>
      )}

      {/* 内容区 */}
      <div className="flex-1 relative">
        {isLoading ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-3">
            <Loader2 className="w-8 h-8 animate-spin text-primary-400" />
            <span className="text-sm">加载 ONLYOFFICE 组件中...</span>
          </div>
        ) : currentFile ? (
          <div id="onlyoffice-preview" className="absolute inset-0" />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-3">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-500/10 to-purple-500/10 flex items-center justify-center">
              <FileText className="w-8 h-8 text-primary-400/40" />
            </div>
            <div className="text-center">
              <p className="text-sm text-slate-400">操作文档后将自动预览</p>
              <p className="text-xs text-slate-500 mt-1">选择模板或文档也可预览</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
