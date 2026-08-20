import { useEffect, useState } from 'react'
import { X, FileText, Database, FileSearch, MessageSquare } from 'lucide-react'
import api from '../services/api'

/** 与后端 provenance manifest 对齐的类型 */
interface RowSource {
  doc_id?: string | null
  doc_name?: string
  origin?: string
  detail?: string | null
  meta?: { row_no?: number | null; chunk?: string } | null
}

interface RowSourceRange {
  from: number
  to: number
  /** 文档级来源（doc_id/doc_name/origin），不含逐行 detail */
  source: RowSource | null
  /** 有序源行号列表（sheet 行号，逐行真实行号） */
  row_nos?: number[]
}

interface FillEntry {
  at?: string
  via?: string | null
  query?: string | null
  sql?: string | null
  template?: { id: string; name: string } | null
  source_documents?: { doc_id: string; doc_name: string; via?: string | null }[]
  column_map?: Record<string, string> | null
  row_sources?: {
    target?: string
    fill_mode?: string
    filled_rows?: number
    ranges?: RowSourceRange[]
    truncated?: boolean
  }[]
  cell_sources?: { target?: string; after?: string; source?: string | null; rationale?: string | null }[]
  filled_rows?: number
  tagged_rows?: number
}

interface ProvenanceResponse {
  document_id: string
  original_filename: string
  version: number
  fill_count: number
  fills: FillEntry[]
}

interface Props {
  documentId: string
  filename: string
  isDarkMode: boolean
  tr: (zh: string, en: string, ja?: string) => string
  onClose: () => void
}

export function sourceLabel(src: RowSource | null | undefined): string {
  if (!src) return ''
  const name = src.doc_name || ''
  return src.detail ? `${name} · ${src.detail}` : name
}

/** 把有序行号列表格式化为连续段/离散点的可读形式（[1,2,3,5,7,8,9]→"1–3, 5, 7–9"） */
export function formatRowNos(nos: number[]): string {
  if (!nos.length) return ''
  const parts: string[] = []
  let start = nos[0]
  let prev = nos[0]
  for (let i = 1; i <= nos.length; i++) {
    const cur = nos[i]
    if (cur === prev + 1) {
      prev = cur
      continue
    }
    parts.push(start === prev ? `${start}` : `${start}–${prev}`)
    start = cur
    prev = cur
  }
  return parts.join(', ')
}

/** 区间来源文案：目标行 ↔ 源行一一对应。
 *  row_nos 与目标行 from..to 一一对应；连续源行压缩为区间（COVID：第 2–2487 行），
 *  交错源行逐行对应（德州：→ 第 306 行 / → 第 308 行 …），不用逗号把一堆行号堆一起。
 */
function rangeSourceLabel(r: RowSourceRange, unknownText: string): string {
  if (!r.source) return unknownText
  const doc = r.source.doc_name || unknownText
  if (r.row_nos && r.row_nos.length) {
    const srcRows = formatRowNos(r.row_nos)
    // 单行区间：明确"→ 第 N 行"的映射；多行区间：来源行范围
    return r.from === r.to ? `${doc} → 第 ${srcRows} 行` : `${doc} · 第 ${srcRows} 行`
  }
  return doc
}

const RANGE_PAGE_SIZE = 20

/** 取数方式标签（ zh 文案由调用方 tr 处理，这里只做图标与 key 映射） */
function viaIcon(via?: string | null) {
  if (via === 'sql_query') return <Database className="w-3.5 h-3.5" />
  if (via === 'extract_records') return <FileSearch className="w-3.5 h-3.5" />
  return <MessageSquare className="w-3.5 h-3.5" />
}

export default function ProvenanceModal({ documentId, filename, isDarkMode, tr, onClose }: Props) {
  const [data, setData] = useState<ProvenanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [expandedSql, setExpandedSql] = useState<number | null>(null)
  // 行区间分页：key = `${fillIdx}:${rsIdx}`，全部区间可翻页查看（不截断）
  const [rangePages, setRangePages] = useState<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    api.get(`/documents/${documentId}/provenance`)
      .then((res) => { if (!cancelled) { setData(res.data); setLoading(false) } })
      .catch(() => { if (!cancelled) { setError(true); setLoading(false) } })
    return () => { cancelled = true }
  }, [documentId])

  const viaLabel = (via?: string | null) =>
    via === 'sql_query'
      ? tr('表格自动查询', 'SQL query', 'SQLクエリ')
      : via === 'extract_records'
        ? tr('文档内容提取', 'Document extraction', '文書抽出')
        : tr('对话内容整理', 'Compiled from conversation', '会話から整理')

  const border = isDarkMode ? 'border-slate-700' : 'border-slate-200'
  const subText = isDarkMode ? 'text-slate-400' : 'text-slate-500'
  const mainText = isDarkMode ? 'text-slate-200' : 'text-slate-700'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        className={`max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl border p-5 shadow-xl ${
          isDarkMode ? 'bg-slate-900 border-slate-700' : 'bg-white border-slate-200'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className={`font-medium flex items-center gap-2 ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>
            <FileText className="w-4 h-4" />
            {tr('数据溯源', 'Data provenance', 'データ出所')}
            <span className={`text-xs font-normal ${subText}`}>{filename}</span>
          </h3>
          <button
            onClick={onClose}
            className={`p-1 rounded-lg ${isDarkMode ? 'hover:bg-slate-800 text-slate-400' : 'hover:bg-slate-100 text-slate-500'}`}
            title={tr('关闭', 'Close', '閉じる')}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading && <p className={`text-sm ${subText}`}>{tr('加载中…', 'Loading…', '読み込み中…')}</p>}
        {error && <p className="text-sm text-red-500">{tr('溯源信息加载失败', 'Failed to load provenance', '出所情報の読み込みに失敗しました')}</p>}
        {data && data.fill_count === 0 && (
          <p className={`text-sm ${subText}`}>
            {tr('该文档没有记录的填表溯源信息（可能由旧版本生成）', 'No provenance recorded (possibly generated before this feature)', '出所情報がありません')}
          </p>
        )}

        {data?.fills.map((fill, fi) => (
          <div key={fi} className={`mb-4 rounded-lg border p-3 ${border} ${isDarkMode ? 'bg-slate-800/40' : 'bg-slate-50/60'}`}>
            <div className={`flex flex-wrap items-center gap-2 text-sm mb-2 ${mainText}`}>
              <span className="font-medium">
                {tr(`第 ${fi + 1} 次填写`, `Fill #${fi + 1}`, `記入 ${fi + 1} 回目`)}
              </span>
              <span className={`inline-flex items-center gap-1 text-xs rounded-full px-2 py-0.5 ${
                isDarkMode ? 'bg-slate-700 text-slate-300' : 'bg-white text-slate-600 border border-slate-200'
              }`}>
                {viaIcon(fill.via)}{viaLabel(fill.via)}
              </span>
              {fill.at && (
                <span className={`text-xs ${subText}`}>{fill.at.replace('T', ' ').slice(0, 19)}</span>
              )}
              {typeof fill.filled_rows === 'number' && (
                <span className={`text-xs ${subText}`}>{tr(`${fill.filled_rows} 行`, `${fill.filled_rows} rows`, `${fill.filled_rows} 行`)}</span>
              )}
            </div>

            {fill.source_documents && fill.source_documents.length > 0 && (
              <div className="mb-2">
                <p className={`text-xs mb-1 ${subText}`}>{tr('来源文档', 'Source documents', '出所文書')}：</p>
                <div className="flex flex-wrap gap-1.5">
                  {fill.source_documents.map((s, si) => (
                    <span key={si} className={`text-xs rounded px-2 py-1 ${
                      isDarkMode ? 'bg-blue-900/40 text-blue-300' : 'bg-blue-50 text-blue-700'
                    }`}>{s.doc_name}</span>
                  ))}
                </div>
              </div>
            )}

            {fill.query && (
              <p className={`text-xs mb-1 ${subText}`}>
                {tr('取数需求', 'Query', '取得条件')}：<span className={mainText}>{fill.query}</span>
              </p>
            )}
            {fill.sql && (
              <div className="mb-2">
                <button
                  onClick={() => setExpandedSql(expandedSql === fi ? null : fi)}
                  className={`text-xs underline ${isDarkMode ? 'text-blue-300' : 'text-blue-600'}`}
                >
                  {expandedSql === fi ? tr('收起 SQL', 'Hide SQL', 'SQLを閉じる') : tr('查看取数 SQL', 'View SQL', 'SQLを表示')}
                </button>
                {expandedSql === fi && (
                  <pre className={`mt-1 text-xs p-2 rounded overflow-x-auto ${
                    isDarkMode ? 'bg-slate-950 text-slate-300' : 'bg-slate-100 text-slate-700'
                  }`}>{fill.sql}</pre>
                )}
              </div>
            )}

            {fill.row_sources?.map((rs, ri) => {
              const allRanges = rs.ranges || []
              const pageKey = `${fi}:${ri}`
              const page = rangePages[pageKey] || 0
              const pageCount = Math.max(1, Math.ceil(allRanges.length / RANGE_PAGE_SIZE))
              const pagedRanges = allRanges.slice(page * RANGE_PAGE_SIZE, (page + 1) * RANGE_PAGE_SIZE)
              return (
              <div key={ri} className="mb-2">
                <p className={`text-xs mb-1 ${subText}`}>
                  {rs.target} · {rs.fill_mode === 'append' ? tr('追加', 'append', '追加') : tr('覆盖', 'overwrite', '上書き')}
                  {rs.truncated && <span className="text-amber-500">（{tr('来源区间过多，已截断', 'too many ranges, truncated', '範囲が多すぎるため省略')}）</span>}
                </p>
                <div className="overflow-x-auto">
                  <table className={`w-full text-xs border-collapse ${mainText}`}>
                    <thead>
                      <tr>
                        <th className={`border px-2 py-1 text-left ${border} ${isDarkMode ? 'bg-slate-800' : 'bg-slate-100'}`}>{tr('行范围', 'Rows', '行範囲')}</th>
                        <th className={`border px-2 py-1 text-left ${border} ${isDarkMode ? 'bg-slate-800' : 'bg-slate-100'}`}>{tr('来源', 'Source', '出所')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedRanges.map((r, i) => (
                        <tr key={i}>
                          <td className={`border px-2 py-1 whitespace-nowrap align-top ${border}`}>
                            {r.from === r.to ? r.from : `${r.from}–${r.to}`}
                          </td>
                          <td className={`border px-2 py-1 ${border} break-words`} style={{ maxWidth: '28rem' }}>
                            {rangeSourceLabel(r, tr('对话内容整理', 'From conversation', '会話から'))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {pageCount > 1 && (
                    <div className="mt-1.5 flex items-center justify-end gap-2 text-xs">
                      <button
                        onClick={() => setRangePages((p) => ({ ...p, [pageKey]: page - 1 }))}
                        disabled={page <= 0}
                        className={`px-2 py-0.5 rounded border disabled:opacity-40 ${isDarkMode ? 'border-slate-600 text-slate-300' : 'border-slate-300 text-slate-600'}`}
                      >{tr('上一页', 'Prev', '前へ')}</button>
                      <span className={subText}>{page + 1} / {pageCount}（{tr('共', 'total', '計')} {allRanges.length} {tr('个区间', 'ranges', '範囲')}）</span>
                      <button
                        onClick={() => setRangePages((p) => ({ ...p, [pageKey]: page + 1 }))}
                        disabled={page >= pageCount - 1}
                        className={`px-2 py-0.5 rounded border disabled:opacity-40 ${isDarkMode ? 'border-slate-600 text-slate-300' : 'border-slate-300 text-slate-600'}`}
                      >{tr('下一页', 'Next', '次へ')}</button>
                    </div>
                  )}
                </div>
              </div>
              )
            })}

            {fill.cell_sources && fill.cell_sources.length > 0 && (
              <div className="overflow-x-auto">
                <table className={`w-full text-xs border-collapse ${mainText}`}>
                  <thead>
                    <tr>
                      <th className={`border px-2 py-1 text-left ${border} ${isDarkMode ? 'bg-slate-800' : 'bg-slate-100'}`}>{tr('位置', 'Target', '位置')}</th>
                      <th className={`border px-2 py-1 text-left ${border} ${isDarkMode ? 'bg-slate-800' : 'bg-slate-100'}`}>{tr('写入值', 'Value', '書き込み値')}</th>
                      <th className={`border px-2 py-1 text-left ${border} ${isDarkMode ? 'bg-slate-800' : 'bg-slate-100'}`}>{tr('来源', 'Source', '出所')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fill.cell_sources.slice(0, 50).map((c, i) => (
                      <tr key={i}>
                        <td className={`border px-2 py-1 ${border}`}>{c.target}</td>
                        <td className={`border px-2 py-1 ${border}`}>{c.after || '—'}</td>
                        <td className={`border px-2 py-1 ${border}`} title={c.rationale || undefined}>
                          {c.source || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
