import { useState, useEffect } from 'react'
import { Loader2, CheckCircle, XCircle, Download, Eye, X, FileText } from 'lucide-react'
import toast from 'react-hot-toast'
import { getTheme } from '../services/theme'
import { useI18n } from '../hooks/useI18n'
import { downloadWithAuth } from '../utils/download'

export interface DryRunReportItem {
  subject: string
  status: 'ok' | 'type_mismatch' | 'ambiguous' | 'not_found' | 'empty_value'
  detail: string
}

export interface DryRunReport {
  items: DryRunReportItem[]
  total: number
  ok_count: number
}

/** dry_run 物化预览数据（服务端生成，实际将写入的内容） */
export interface FillPreview {
  table?: {
    headers: string[]
    rows: string[][]
    total_rows: number
    fill_mode: string
    target: string
  }
  cells?: { target: string; before: string; after: string; status: string }[]
}

export interface ActionData {
  action_id?: string
  action_type: string  // confirm_extract, confirm_fill, executing, completed, failed
  title?: string
  description?: string
  progress?: number
  result?: {
    entities_count?: number
    filled_file_url?: string
    output_filename?: string
    [key: string]: any
  }
  // dry_run 校验报告与预览（人工确认模式）
  dry_run_report?: DryRunReport
  preview?: FillPreview
  /** 确认卡片状态：pending=待确认 / confirmed=已确认 / cancelled=已取消 */
  status?: 'pending' | 'confirmed' | 'cancelled'
  summary?: string
  // 新Agent系统字段
  filled_file_url?: string
  filled_file_id?: string
  filled_filename?: string
  _messageId?: string
}

interface ActionCardProps {
  action: ActionData
  onConfirm?: () => void
  onCancel?: () => void
  /** 预览输出文件（fileId, filename）→ 在预览边栏打开 */
  onPreview?: (fileId: string, filename: string) => void
}

export default function ActionCard({ action, onConfirm, onCancel, onPreview }: ActionCardProps) {
  const { action_type, title, description, progress, result } = action
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')
  // 防连点：点击确认/取消后立即禁用按钮（确认/取消成功后卡片状态翻转，按钮组随之卸载，无需复位）
  const [processing, setProcessing] = useState<'confirm' | 'cancel' | null>(null)
  const [downloading, setDownloading] = useState(false)

  // 带鉴权下载（普通 a[href] 不带 Bearer token，会得到 401 JSON）
  const handleDownload = async (url: string) => {
    if (downloading) return
    setDownloading(true)
    try {
      await downloadWithAuth(url)
    } catch {
      toast.error(tr('下载失败', 'Download failed', 'ダウンロードに失敗しました'))
    } finally {
      setDownloading(false)
    }
  }

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  // 确认卡片（状态：pending=待确认 / confirmed=已确认 / cancelled=已取消）
  if (action_type === 'confirm_extract' || action_type === 'confirm_fill') {
    const status = action.status || 'pending'
    return (
      <div className={`mt-3 p-4 rounded-xl border ${
        status === 'confirmed'
          ? isDarkMode ? 'bg-green-900/20 border-green-500/40' : 'bg-green-50 border-green-200'
          : status === 'cancelled'
            ? isDarkMode ? 'bg-slate-800/50 border-slate-600' : 'bg-slate-50 border-slate-200'
            : isDarkMode ? 'bg-blue-900/30 border-blue-500/40' : 'bg-primary-50 border-primary-200'
      }`}>
        <div className="flex items-start gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
            isDarkMode ? 'bg-blue-800/50' : 'bg-primary-100'
          }`}>
            {status === 'confirmed' ? (
              <CheckCircle className="w-5 h-5 text-green-500" />
            ) : status === 'cancelled' ? (
              <XCircle className={`w-5 h-5 ${isDarkMode ? 'text-slate-500' : 'text-slate-400'}`} />
            ) : (
              <svg className={`w-5 h-5 ${isDarkMode ? 'text-blue-300' : 'text-primary-600'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            )}
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <h4 className={`font-medium ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>{title}</h4>
              {status === 'confirmed' && (
                <span className="text-xs rounded-full px-2 py-0.5 bg-green-500/15 text-green-500">
                  {tr('已确认', 'Confirmed', '確認済み')}
                </span>
              )}
              {status === 'cancelled' && (
                <span className={`text-xs rounded-full px-2 py-0.5 ${isDarkMode ? 'bg-slate-700 text-slate-400' : 'bg-slate-200 text-slate-500'}`}>
                  {tr('已取消', 'Cancelled', 'キャンセル済み')}
                </span>
              )}
            </div>
            <p className={`text-sm mb-3 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>{description}</p>
            {action.dry_run_report && (
              <DryRunReportView report={action.dry_run_report} isDarkMode={isDarkMode} tr={tr} />
            )}
            <div className="flex gap-2">
              {action.preview && (action.preview.table || (action.preview.cells && action.preview.cells.length > 0)) && (
                <PreviewButton preview={action.preview} isDarkMode={isDarkMode} tr={tr} />
              )}
              {status === 'pending' && (
                <>
                  <button
                    onClick={() => { if (!processing) { setProcessing('confirm'); onConfirm?.() } }}
                    disabled={processing !== null}
                    className="btn-primary px-4 py-2 text-sm disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
                    title={tr('确认执行', 'Confirm', '確認')}
                  >
                    {processing === 'confirm' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    {tr('确认执行', 'Confirm', '確認')}
                  </button>
                  <button
                    onClick={() => { if (!processing) { setProcessing('cancel'); onCancel?.() } }}
                    disabled={processing !== null}
                    className="btn-secondary px-4 py-2 text-sm disabled:opacity-60 disabled:cursor-not-allowed"
                    title={tr('取消', 'Cancel', 'キャンセル')}
                  >
                    {tr('取消', 'Cancel', 'キャンセル')}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // 执行中卡片
  if (action_type === 'executing') {
    return (
      <div className={`mt-3 p-4 rounded-xl border ${
        isDarkMode
          ? 'bg-blue-900/30 border-blue-500/40'
          : 'bg-blue-50 border-blue-200'
      }`}>
        <div className="flex items-center gap-3">
          <Loader2 className="w-6 h-6 text-blue-500 animate-spin shrink-0" />
          <div className="flex-1">
            <h4 className={`font-medium mb-1 ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>{title}</h4>
            <p className={`text-sm ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>{description}</p>
            {progress !== undefined && (
              <div className="mt-2">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span>{tr('进度', 'Progress', '進捗')}</span>
                  <span>{progress}%</span>
                </div>
                <div className={`w-full h-1.5 rounded-full overflow-hidden ${isDarkMode ? 'bg-slate-700' : 'bg-slate-200'}`}>
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
    const downloadUrl = result?.filled_file_url || action.filled_file_url
    const fileId = result?.filled_file_id || action.filled_file_id
    const filename = result?.output_filename || action.filled_filename || ''
    return (
      <div className={`mt-3 p-4 rounded-xl border ${
        isDarkMode
          ? 'bg-green-900/30 border-green-500/40'
          : 'bg-green-50 border-green-200'
      }`}>
        <div className="flex items-start gap-3">
          <CheckCircle className="w-6 h-6 text-green-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <h4 className={`font-medium mb-1 ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>
              {title || tr('文档已生成', 'Document generated', '文書が生成されました')}
            </h4>
            {description && (
              <p className={`text-sm ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>{description}</p>
            )}
            {filename && (
              <p className={`mt-1 text-sm truncate flex items-center gap-1.5 ${isDarkMode ? 'text-slate-300' : 'text-slate-700'}`} title={filename}>
                <FileText className={`w-4 h-4 shrink-0 ${isDarkMode ? 'text-green-400' : 'text-green-600'}`} />
                <span className="truncate">{filename}</span>
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              {fileId && onPreview && (
                <button
                  onClick={() => onPreview(fileId, filename || tr('输出文档', 'Output document', '出力文書'))}
                  title={tr('在边栏预览', 'Preview in sidebar', 'サイドバーでプレビュー')}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                    isDarkMode
                      ? 'bg-slate-700/70 text-slate-300 hover:bg-slate-700'
                      : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                  }`}
                >
                  <Eye className="w-4 h-4" />
                  {tr('预览', 'Preview', 'プレビュー')}
                </button>
              )}
              {downloadUrl && (
                <button
                  onClick={() => handleDownload(downloadUrl)}
                  disabled={downloading}
                  title={tr('下载文件', 'Download File', 'ファイルをダウンロード')}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors disabled:opacity-60 ${
                    isDarkMode
                      ? 'bg-green-800/50 text-green-300 hover:bg-green-700/50'
                      : 'bg-green-100 text-green-700 hover:bg-green-200'
                  }`}
                >
                  {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                  {tr('下载文件', 'Download File', 'ファイルをダウンロード')}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // 失败卡片
  if (action_type === 'failed') {
    return (
      <div className={`mt-3 p-4 rounded-xl border ${
        isDarkMode
          ? 'bg-red-900/30 border-red-500/40'
          : 'bg-red-50 border-red-200'
      }`}>
        <div className="flex items-start gap-3">
          <XCircle className="w-6 h-6 text-red-500 shrink-0" />
          <div className="flex-1">
            <h4 className={`font-medium mb-1 ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>{title}</h4>
            <p className={`text-sm ${isDarkMode ? 'text-red-300' : 'text-red-600'}`}>{description}</p>
          </div>
        </div>
      </div>
    )
  }

  return null
}

/** 预览按钮 + 模态框：展示 dry_run 物化的实际写入内容（分页） */
const PREVIEW_PAGE_SIZE = 10

function Pager({ page, pageCount, onChange, isDarkMode, tr }: {
  page: number
  pageCount: number
  onChange: (p: number) => void
  isDarkMode: boolean
  tr: (zh: string, en: string, ja?: string) => string
}) {
  if (pageCount <= 1) return null
  return (
    <div className="mt-2 flex items-center justify-end gap-2 text-xs">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page <= 0}
        className={`px-2 py-1 rounded border disabled:opacity-40 ${isDarkMode ? 'border-slate-600 text-slate-300' : 'border-slate-300 text-slate-600'}`}
      >
        {tr('上一页', 'Prev', '前へ')}
      </button>
      <span className={isDarkMode ? 'text-slate-400' : 'text-slate-500'}>
        {page + 1} / {pageCount}
      </span>
      <button
        onClick={() => onChange(page + 1)}
        disabled={page >= pageCount - 1}
        className={`px-2 py-1 rounded border disabled:opacity-40 ${isDarkMode ? 'border-slate-600 text-slate-300' : 'border-slate-300 text-slate-600'}`}
      >
        {tr('下一页', 'Next', '次へ')}
      </button>
    </div>
  )
}

function PreviewButton({ preview, isDarkMode, tr }: {
  preview: FillPreview
  isDarkMode: boolean
  tr: (zh: string, en: string, ja?: string) => string
}) {
  const [open, setOpen] = useState(false)
  const [tablePage, setTablePage] = useState(0)
  const [cellsPage, setCellsPage] = useState(0)

  const tableRows = preview.table?.rows ?? []
  const tablePageCount = Math.max(1, Math.ceil(tableRows.length / PREVIEW_PAGE_SIZE))
  const pagedTableRows = tableRows.slice(tablePage * PREVIEW_PAGE_SIZE, (tablePage + 1) * PREVIEW_PAGE_SIZE)
  const cells = preview.cells ?? []
  const cellsPageCount = Math.max(1, Math.ceil(cells.length / PREVIEW_PAGE_SIZE))
  const pagedCells = cells.slice(cellsPage * PREVIEW_PAGE_SIZE, (cellsPage + 1) * PREVIEW_PAGE_SIZE)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="btn-secondary px-4 py-2 text-sm inline-flex items-center gap-1.5"
        title={tr('预览将写入的数据', 'Preview data to write', '書き込むデータをプレビュー')}
      >
        <Eye className="w-4 h-4" />
        {tr('预览数据', 'Preview', 'プレビュー')}
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className={`max-h-[80vh] w-full max-w-3xl overflow-auto rounded-xl border p-5 shadow-xl ${
              isDarkMode ? 'bg-slate-900 border-slate-700' : 'bg-white border-slate-200'
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className={`font-medium ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>
                {tr('将写入的数据预览', 'Data to be written', '書き込むデータのプレビュー')}
              </h3>
              <button
                onClick={() => setOpen(false)}
                className={`p-1 rounded-lg ${isDarkMode ? 'hover:bg-slate-800 text-slate-400' : 'hover:bg-slate-100 text-slate-500'}`}
                title={tr('关闭', 'Close', '閉じる')}
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {preview.table && (
              <div className="mb-4">
                <p className={`text-sm mb-2 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
                  {preview.table.target} · {preview.table.fill_mode === 'append' ? tr('追加', 'append', '追加') : tr('覆盖', 'overwrite', '上書き')}
                  {' · '}{tr('共', 'total', '計')} {preview.table.total_rows} {tr('行', 'rows', '行')}
                  {preview.table.total_rows > preview.table.rows.length &&
                    tr(`（仅含前 ${preview.table.rows.length} 行）`, ` (first ${preview.table.rows.length} rows included)`, `（先頭 ${preview.table.rows.length} 行のみ）`)}
                </p>
                <div className="overflow-x-auto">
                  <table className={`w-full text-sm border-collapse ${isDarkMode ? 'text-slate-300' : 'text-slate-700'}`}>
                    <thead>
                      <tr>
                        {preview.table.headers.map((h, i) => (
                          <th key={i} className={`border px-3 py-1.5 text-left font-medium ${
                            isDarkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'
                          }`}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {pagedTableRows.map((row, ri) => (
                        <tr key={tablePage * PREVIEW_PAGE_SIZE + ri}>
                          {row.map((cell, ci) => (
                            <td key={ci} className={`border px-3 py-1.5 ${
                              isDarkMode ? 'border-slate-700' : 'border-slate-200'
                            }`}>{cell || <span className="text-slate-400">—</span>}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager page={tablePage} pageCount={tablePageCount} onChange={setTablePage} isDarkMode={isDarkMode} tr={tr} />
              </div>
            )}

            {preview.cells && preview.cells.length > 0 && (
              <div className="overflow-x-auto">
                <table className={`w-full text-sm border-collapse ${isDarkMode ? 'text-slate-300' : 'text-slate-700'}`}>
                  <thead>
                    <tr>
                      <th className={`border px-3 py-1.5 text-left font-medium ${isDarkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'}`}>{tr('位置', 'Target', '位置')}</th>
                      <th className={`border px-3 py-1.5 text-left font-medium ${isDarkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'}`}>{tr('当前内容', 'Current', '現在の内容')}</th>
                      <th className={`border px-3 py-1.5 text-left font-medium ${isDarkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'}`}>{tr('写入后', 'After', '書き込み後')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedCells.map((cell, i) => (
                      <tr key={cellsPage * PREVIEW_PAGE_SIZE + i}>
                        <td className={`border px-3 py-1.5 ${isDarkMode ? 'border-slate-700' : 'border-slate-200'}`}>{cell.target}</td>
                        <td className={`border px-3 py-1.5 ${isDarkMode ? 'border-slate-700' : 'border-slate-200'}`}>{cell.before || <span className="text-slate-400">—</span>}</td>
                        <td className={`border px-3 py-1.5 ${isDarkMode ? 'border-slate-700 text-green-400' : 'border-slate-200 text-green-700'}`}>{cell.after || <span className="text-slate-400">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Pager page={cellsPage} pageCount={cellsPageCount} onChange={setCellsPage} isDarkMode={isDarkMode} tr={tr} />
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

/** dry_run 校验报告摘要：通过数 + 异常项列表 */
function DryRunReportView({ report, isDarkMode, tr }: {
  report: DryRunReport
  isDarkMode: boolean
  tr: (zh: string, en: string, ja?: string) => string
}) {
  const problems = report.items.filter(i => i.status !== 'ok')
  const statusLabel: Record<string, string> = {
    not_found: tr('未找到', 'not found', '未検出'),
    ambiguous: tr('有歧义', 'ambiguous', '曖昧'),
    type_mismatch: tr('类型不符', 'type mismatch', '型不一致'),
    empty_value: tr('空值', 'empty', '空値'),
  }

  return (
    <div className={`mb-3 rounded-lg border p-3 text-sm ${
      isDarkMode ? 'border-slate-600 bg-slate-800/60' : 'border-slate-200 bg-white'
    }`}>
      <div className={`font-medium mb-1 ${isDarkMode ? 'text-slate-200' : 'text-slate-700'}`}>
        {tr('校验结果', 'Validation', '検証結果')}：{tr('共', 'total', '計')} {report.total} {tr('项', 'items', '件')}，
        <span className="text-green-500"> {report.ok_count} {tr('项通过', 'passed', '件通過')}</span>
        {problems.length > 0 && (
          <span className="text-amber-500">，{problems.length} {tr('项需注意', 'need attention', '件要注意')}</span>
        )}
      </div>
      {problems.length > 0 && (
        <ul className={`mt-1 space-y-1 ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>
          {problems.slice(0, 8).map((item, idx) => (
            <li key={idx} className="flex gap-2">
              <span className="shrink-0 rounded px-1.5 text-xs leading-5 bg-amber-500/15 text-amber-500">
                {statusLabel[item.status] || item.status}
              </span>
              <span className="min-w-0">
                <span className={`${isDarkMode ? 'text-slate-300' : 'text-slate-600'}`}>{item.subject}</span>
                {item.detail && <span> — {item.detail}</span>}
              </span>
            </li>
          ))}
          {problems.length > 8 && (
            <li className="text-xs">{tr(`…其余 ${problems.length - 8} 项略`, `…${problems.length - 8} more`, `他 ${problems.length - 8} 件`)}</li>
          )}
        </ul>
      )}
    </div>
  )
}
