import { useState, useEffect } from 'react'
import { FileText, Loader2, X } from 'lucide-react'
import type { PreviewFile } from '../hooks/useDocumentPreview'
import { useI18n } from '../hooks/useI18n'
import { getTheme } from '../services/theme'

interface DocumentPreviewPanelProps {
  previewFiles: PreviewFile[]
  currentFile: PreviewFile | null
  onFileSelect: (file: PreviewFile) => void
  onFileRemove: (fileId: string) => void
  isLoading: boolean
}

export default function DocumentPreviewPanel({
  previewFiles,
  currentFile,
  onFileSelect,
  onFileRemove,
  isLoading,
}: DocumentPreviewPanelProps) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return (
    <div className={`h-full overflow-hidden flex flex-col rounded-xl border ${
      isDarkMode ? 'bg-slate-800/80 border-slate-600' : 'glass'
    }`}>
      {/* 标题栏 */}
      <div className={`flex items-center justify-between px-4 py-3 border-b ${
        isDarkMode ? 'border-slate-600 bg-slate-700/50' : 'border-white/10 bg-white/5'
      }`}>
        <div className="flex items-center gap-2 min-w-0">
          <FileText className={`w-4 h-4 flex-shrink-0 ${isDarkMode ? 'text-blue-400' : 'text-primary-400'}`} />
          <span className={`text-sm truncate ${isDarkMode ? 'text-slate-200' : 'text-slate-300'}`}>
            {currentFile?.name || tr('文档预览', 'Document Preview', '文書プレビュー')}
          </span>
        </div>
      </div>

      {/* 文件标签页 */}
      {previewFiles.length > 1 && (
        <div className={`flex gap-1 px-3 py-2 border-b overflow-x-auto scrollbar-thin ${
          isDarkMode ? 'border-slate-600' : 'border-white/10'
        }`}>
          {previewFiles.map(f => (
            <span
              key={f.id}
              className={`group flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg whitespace-nowrap transition-colors cursor-pointer ${
                f.id === currentFile?.id
                  ? isDarkMode
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    : 'bg-primary-500/20 text-primary-400 border border-primary-500/30'
                  : isDarkMode
                    ? 'text-slate-400 hover:bg-slate-700 border border-transparent'
                    : 'text-slate-400 hover:bg-white/5 border border-transparent'
              }`}
              title={f.name}
              onClick={() => onFileSelect(f)}
            >
              <FileText className="w-3 h-3 flex-shrink-0" />
              <span className="truncate max-w-[100px]">{f.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onFileRemove(f.id) }}
                className={`ml-0.5 rounded p-0.5 transition-colors ${
                  isDarkMode ? 'hover:bg-slate-600 hover:text-slate-200' : 'hover:bg-slate-200 hover:text-slate-600'
                }`}
                title={tr('关闭预览', 'Close preview', 'プレビューを閉じる')}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 内容区 */}
      <div className="flex-1 relative">
        {isLoading ? (
          <div className={`h-full flex flex-col items-center justify-center gap-3 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
            <Loader2 className={`w-8 h-8 animate-spin ${isDarkMode ? 'text-blue-400' : 'text-primary-400'}`} />
            <span className="text-sm">{tr('加载 ONLYOFFICE 组件中...', 'Loading ONLYOFFICE component...', 'ONLYOFFICE コンポーネントを読み込み中...')}</span>
          </div>
        ) : currentFile ? (
          <div id="onlyoffice-preview" className="absolute inset-0" />
        ) : (
          <div className={`h-full flex flex-col items-center justify-center gap-3 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
            <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${
              isDarkMode ? 'bg-slate-700' : 'bg-gradient-to-br from-primary-500/10 to-purple-500/10'
            }`}>
              <FileText className={`w-8 h-8 ${isDarkMode ? 'text-slate-500' : 'text-primary-400/40'}`} />
            </div>
            <div className="text-center">
              <p className={`text-sm ${isDarkMode ? 'text-slate-300' : 'text-slate-400'}`}>{tr('操作文档后将自动预览', 'Preview will appear after document operation', '文書操作後にプレビューが表示されます')}</p>
              <p className={`text-xs mt-1 ${isDarkMode ? 'text-slate-500' : 'text-slate-500'}`}>{tr('选择模板或文档也可预览', 'Select a template or document to preview', 'テンプレートまたは文書を選択してプレビュー')}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
