import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, FileOutput, Network, X } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useI18n } from '../hooks/useI18n'
import { getFileType, type PreviewFile } from '../hooks/useDocumentPreview'
import ProvenanceModal from './ProvenanceModal'

interface ConversationOutput {
  id: string
  original_filename: string
  file_type: string
  file_size?: number
  version: number
  version_count: number
  origin_type?: string | null
  origin_label?: string | null
  created_at?: string | null
  download_url: string
  has_provenance?: boolean
}

interface Props {
  sessionId: string | null
  /** 递增触发刷新（工具产出文件后） */
  refreshKey: number
  isDarkMode: boolean
  onOpenFile: (file: PreviewFile) => void
  onClose: () => void
}

function formatSize(size?: number) {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export default function ConversationOutputsPanel({ sessionId, refreshKey, isDarkMode, onOpenFile, onClose }: Props) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

  const [outputs, setOutputs] = useState<ConversationOutput[]>([])
  const [loading, setLoading] = useState(false)
  const [provenanceFor, setProvenanceFor] = useState<ConversationOutput | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchOutputs = useCallback(async () => {
    if (!sessionId) {
      setOutputs([])
      return
    }
    setLoading(true)
    try {
      const response = await api.get(`/conversations/${sessionId}/outputs`)
      setOutputs(response.data || [])
    } catch {
      // 面板数据加载失败不打断主流程
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  // 会话切换时立即加载
  useEffect(() => {
    fetchOutputs()
  }, [fetchOutputs])

  // refreshKey 变化时防抖刷新（工具可能连续产出多个文件）
  useEffect(() => {
    if (!refreshKey) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchOutputs(), 1000)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [refreshKey, fetchOutputs])

  const handleDownload = async (item: ConversationOutput) => {
    try {
      const response = await api.get(item.download_url.replace('/api/v1', ''), { responseType: 'blob' })
      const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
      const objectUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = item.original_filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(objectUrl)
    } catch {
      toast.error(tr('下载失败', 'Download failed', 'ダウンロードに失敗しました'))
    }
  }

  return (
    <div className={`h-full overflow-hidden flex flex-col rounded-xl border ${
      isDarkMode ? 'bg-slate-800/80 border-slate-600' : 'glass'
    }`}>
      <div className={`flex items-center justify-between px-4 py-3 border-b ${
        isDarkMode ? 'border-slate-600 bg-slate-700/50' : 'border-white/10 bg-white/5'
      }`}>
        <div className="flex items-center gap-2 min-w-0">
          <FileOutput className={`w-4 h-4 flex-shrink-0 ${isDarkMode ? 'text-blue-400' : 'text-primary-400'}`} />
          <span className={`text-sm truncate ${isDarkMode ? 'text-slate-200' : 'text-slate-300'}`}>
            {tr('本次会话产出', 'Session outputs', 'このセッションの成果物')}
          </span>
          <span className={`text-xs ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>({outputs.length})</span>
        </div>
        <button onClick={onClose} title={tr('关闭', 'Close', '閉じる')} className={`rounded p-1 ${isDarkMode ? 'text-slate-400 hover:bg-slate-700' : 'text-slate-500 hover:bg-slate-100'}`}>
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-2">
        {loading && outputs.length === 0 ? (
          <p className={`py-6 text-center text-xs ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>{tr('加载中...', 'Loading...', '読み込み中...')}</p>
        ) : outputs.length === 0 ? (
          <p className={`py-6 text-center text-xs ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
            {tr('暂无产出文件', 'No outputs yet', '成果物はまだありません')}
          </p>
        ) : (
          outputs.map((item) => (
            <div
              key={item.id}
              onClick={() => onOpenFile({ id: item.id, name: item.original_filename, fileType: getFileType(item.original_filename), source: 'operated' })}
              className={`group mb-1.5 cursor-pointer rounded-lg border px-2.5 py-2 transition-colors ${
                isDarkMode ? 'border-slate-700 hover:bg-slate-800' : 'border-slate-200 hover:bg-slate-50'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <p className={`min-w-0 flex-1 truncate text-xs font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-800'}`}>
                  {item.original_filename}
                </p>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDownload(item) }}
                  title={tr('下载', 'Download', 'ダウンロード')}
                  className={`rounded p-1 opacity-0 group-hover:opacity-100 transition-opacity ${isDarkMode ? 'text-slate-400 hover:bg-slate-700 hover:text-blue-400' : 'text-slate-400 hover:bg-blue-50 hover:text-blue-500'}`}
                >
                  <Download className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className={`mt-1 flex items-center gap-1.5 text-[10px] ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                <span className={`rounded px-1 py-0.5 font-mono ${isDarkMode ? 'bg-slate-700 text-slate-300' : 'bg-slate-100 text-slate-600'}`}>
                  v{item.version}{item.version_count > 1 ? `/${item.version_count}` : ''}
                </span>
                <span>{item.file_type.toUpperCase()}</span>
                <span>{formatSize(item.file_size)}</span>
                {item.has_provenance && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setProvenanceFor(item) }}
                    title={tr('查看数据溯源', 'View data provenance', 'データ出所を見る')}
                    className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 ${
                      isDarkMode ? 'bg-blue-900/40 text-blue-300 hover:bg-blue-900/60' : 'bg-blue-50 text-blue-600 hover:bg-blue-100'
                    }`}
                  >
                    <Network className="h-3 w-3" />
                    {tr('溯源', 'Source', '出所')}
                  </button>
                )}
                {item.created_at && (
                  <span className="ml-auto">{new Date(item.created_at).toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })}</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {provenanceFor && (
        <ProvenanceModal
          documentId={provenanceFor.id}
          filename={provenanceFor.original_filename}
          isDarkMode={isDarkMode}
          tr={tr}
          onClose={() => setProvenanceFor(null)}
        />
      )}
    </div>
  )
}
