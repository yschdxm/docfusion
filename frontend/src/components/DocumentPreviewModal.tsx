import { useEffect, useRef, useState } from 'react'
import { CheckCircle, Edit3, X } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import type { DocumentInfo } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'
import { getTheme } from '../services/theme'

interface PreviewSheet {
  name: string
  data: string[][]
  rows: number
  cols: number
}

interface PreviewPayload {
  file_name: string
  file_type: string
  preview_type: 'text' | 'markdown' | 'spreadsheet' | 'pdf' | 'onlyoffice'
  content: string
  html_content?: string | null
  truncated: boolean
  can_edit: boolean
  sheets?: PreviewSheet[] | null
}

interface OfficeConfigResponse {
  serverUrl: string
  config: Record<string, unknown>
}

interface Props {
  doc: DocumentInfo | null
  onClose: () => void
}

export default function DocumentPreviewModal({ doc, onClose }: Props) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

  const [previewData, setPreviewData] = useState<PreviewPayload | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [officeMode, setOfficeMode] = useState<'view' | 'edit'>('view')
  const [officeLoading, setOfficeLoading] = useState(false)
  const [officeError, setOfficeError] = useState('')
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  const officeEditorRef = useRef<{ destroyEditor?: () => void } | null>(null)
  const loadedScriptRef = useRef<string | null>(null)

  // 监听主题变化
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  const officeContainerRef = useRef<HTMLDivElement | null>(null)
  const [officeHost] = useState(() => {
    const el = document.createElement('div')
    el.id = 'onlyoffice-editor'
    el.style.width = '100%'
    el.style.height = '100%'
    return el
  })

  const destroyOnlyOfficeEditor = () => {
    if (officeEditorRef.current?.destroyEditor) {
      officeEditorRef.current.destroyEditor()
    }
    officeEditorRef.current = null
    if (officeHost.parentNode) {
      officeHost.parentNode.removeChild(officeHost)
    }
    officeHost.innerHTML = ''
  }

  const ensureOnlyOfficeScript = async () => {
    if (window.DocsAPI?.DocEditor) return
    const scriptUrl = '/web-apps/apps/api/documents/api.js'

    await new Promise<void>((resolve, reject) => {
      if (window.DocsAPI?.DocEditor) {
        resolve()
        return
      }

      const script = document.createElement('script')
      script.src = scriptUrl
      document.head.appendChild(script)
      loadedScriptRef.current = scriptUrl

      const startedAt = Date.now()
      const timer = window.setInterval(() => {
        if (window.DocsAPI?.DocEditor) {
          window.clearInterval(timer)
          resolve()
          return
        }
        if (Date.now() - startedAt > 60000) {
          window.clearInterval(timer)
          reject(new Error('OnlyOffice script load timeout'))
        }
      }, 200)

      script.onerror = () => {
        window.clearInterval(timer)
        reject(new Error('OnlyOffice script load failed'))
      }
    })
  }

  const mountOnlyOffice = async (mode: 'view' | 'edit') => {
    if (!doc || !officeContainerRef.current) return

    setOfficeLoading(true)
    setOfficeError('')
    destroyOnlyOfficeEditor()

    officeContainerRef.current.innerHTML = ''
    officeContainerRef.current.appendChild(officeHost)

    try {
      const response = await api.get<OfficeConfigResponse>(`/documents/${doc.id}/office-config`, {
        params: { mode },
      })

      await ensureOnlyOfficeScript()

      if (!window.DocsAPI?.DocEditor) {
        throw new Error('OnlyOffice component not loaded')
      }

      officeEditorRef.current = new window.DocsAPI.DocEditor('onlyoffice-editor', response.data.config)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'OnlyOffice load failed'
      setOfficeError(message)
    } finally {
      setOfficeLoading(false)
    }
  }

  const handleSave = async () => {
    if (!doc || !previewData?.can_edit) return
    setSaving(true)
    try {
      await api.put(`/documents/${doc.id}/content`, { content: editContent })
      toast.success(tr('保存成功', 'Saved', '保存しました'))
      setPreviewData({ ...previewData, content: editContent })
      setEditorOpen(false)
    } catch {
      toast.error(tr('保存失败', 'Save failed', '保存に失敗しました'))
    } finally {
      setSaving(false)
    }
  }

  // Fetch preview data when doc changes
  useEffect(() => {
    if (!doc) {
      setPreviewData(null)
      setPreviewLoading(false)
      return
    }

    let cancelled = false
    const fetchPreview = async () => {
      setPreviewLoading(true)
      setPreviewData(null)
      setEditorOpen(false)
      setOfficeMode('view')
      setOfficeError('')

      try {
        const response = await api.get<PreviewPayload>(`/documents/${doc.id}/preview`)
        if (cancelled) return
        setPreviewData(response.data)
        setEditContent(response.data.content ?? '')
      } catch {
        if (cancelled) return
        toast.error(tr('文档预览加载失败', 'Failed to load preview', 'プレビューの読み込みに失敗しました'))
        onClose()
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }

    fetchPreview()
    return () => { cancelled = true }
  }, [doc])

  // Mount OnlyOffice when needed
  useEffect(() => {
    if (doc && previewData?.preview_type === 'onlyoffice') {
      void mountOnlyOffice(officeMode)
    }
    return () => { destroyOnlyOfficeEditor() }
  }, [doc, previewData, officeMode])

  const renderPreviewContent = () => {
    if (previewLoading) {
      return <div className="flex h-full items-center justify-center text-slate-400">{tr('正在加载预览...', 'Loading preview...', 'プレビューを読み込み中...')}</div>
    }

    if (!previewData) {
      return <div className="flex h-full items-center justify-center text-slate-500">{tr('暂无预览内容', 'No preview content', 'プレビューはありません')}</div>
    }

    if (previewData.preview_type === 'onlyoffice') {
      return (
        <div className={`h-[68vh] overflow-hidden rounded-xl border ${
          isDarkMode ? 'border-slate-600 bg-slate-800' : 'border-slate-200 bg-white'
        }`}>
          {officeLoading && <div className={`p-4 text-sm ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}`}>正在加载 OnlyOffice...</div>}
          {officeError && <div className={`border-b p-4 text-sm ${
            isDarkMode ? 'border-red-500/40 bg-red-900/30 text-red-300' : 'border-red-100 bg-red-50 text-red-600'
          }`}>{officeError}</div>}
          <div ref={officeContainerRef} className="h-full w-full" />
        </div>
      )
    }

    if (editorOpen && previewData.can_edit) {
      return (
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          spellCheck={false}
          className={`h-full min-h-[420px] w-full rounded-xl border p-4 font-mono text-sm leading-7 outline-none ${
            isDarkMode
              ? 'border-slate-600 bg-slate-700 text-slate-200'
              : 'border-slate-200 bg-slate-50 text-slate-800'
          }`}
        />
      )
    }

    if (previewData.preview_type === 'pdf') {
      return (
        <iframe
          title="document-preview"
          src={`/api/v1/documents/${doc?.id}/inline`}
          className={`h-[68vh] w-full rounded-xl border ${
            isDarkMode ? 'border-slate-600 bg-slate-800' : 'border-slate-200 bg-white'
          }`}
        />
      )
    }

    if (previewData.preview_type === 'spreadsheet') {
      return (
        <div className="space-y-5">
          {previewData.sheets?.map((sheet) => (
            <div key={sheet.name} className={`overflow-hidden rounded-xl border ${
              isDarkMode ? 'border-slate-600 bg-slate-700' : 'border-slate-200 bg-slate-50'
            }`}>
              <div className={`border-b px-4 py-3 ${isDarkMode ? 'border-slate-600' : 'border-slate-200'}`}>
                <div className={`text-sm font-medium ${isDarkMode ? 'text-slate-200' : 'text-slate-900'}`}>{sheet.name}</div>
                <div className="text-xs text-slate-400">{sheet.rows} rows · {sheet.cols} cols</div>
              </div>
              <div className="max-h-72 overflow-auto scrollbar-thin">
                <table className="min-w-full text-left text-xs">
                  <tbody>
                    {sheet.data.slice(0, 20).map((row, rowIndex) => (
                      <tr key={`${sheet.name}-${rowIndex}`} className={`border-b ${isDarkMode ? 'border-slate-600' : 'border-slate-100'}`}>
                        {row.map((cell, colIndex) => (
                          <td key={`${sheet.name}-${rowIndex}-${colIndex}`} className={`px-3 py-1.5 ${isDarkMode ? 'text-slate-300' : 'text-slate-700'}`}>{cell || '-'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          <pre className={`whitespace-pre-wrap rounded-xl border p-4 text-xs leading-6 ${
            isDarkMode ? 'border-slate-600 bg-slate-700 text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-600'
          }`}>{previewData.content}</pre>
        </div>
      )
    }

    if (previewData.preview_type === 'markdown' && previewData.html_content) {
      return (
        <div className="space-y-4">
          <div
            className={`prose max-w-none rounded-xl border p-5 ${
              isDarkMode
                ? 'border-slate-600 bg-slate-700 prose-headings:text-slate-200 prose-p:text-slate-300 prose-strong:text-slate-200 prose-code:text-blue-300'
                : 'border-slate-200 bg-slate-50 prose-headings:text-slate-900 prose-p:text-slate-700 prose-strong:text-slate-900 prose-code:text-blue-300'
            }`}
            dangerouslySetInnerHTML={{ __html: previewData.html_content }}
          />
          <details className={`rounded-xl border p-4 ${
            isDarkMode ? 'border-slate-600 bg-slate-700' : 'border-slate-200 bg-slate-50'
          }`}>
            <summary className={`cursor-pointer text-sm ${isDarkMode ? 'text-slate-300' : 'text-slate-600'}`}>{tr('查看原始 Markdown', 'View raw Markdown', '生のMarkdownを表示')}</summary>
            <pre className={`mt-4 whitespace-pre-wrap text-xs leading-6 ${isDarkMode ? 'text-slate-400' : 'text-slate-600'}`}>{previewData.content}</pre>
          </details>
        </div>
      )
    }

    return (
      <pre className={`min-h-[420px] whitespace-pre-wrap rounded-xl border p-4 text-sm leading-7 ${
        isDarkMode ? 'border-slate-600 bg-slate-700 text-slate-200' : 'border-slate-200 bg-slate-50 text-slate-700'
      }`}>
        {previewData.content}
      </pre>
    )
  }

  if (!doc) return null

  const categoryLabel = doc.doc_category === 'source'
    ? tr('源文档', 'Source', 'ソース')
    : doc.doc_category === 'template'
      ? tr('模板', 'Template', 'テンプレート')
      : tr('输出', 'Output', '出力')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4 py-6 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="document-preview-title" className="glass-dark flex h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-[28px]">
        <div className={`flex items-center justify-between border-b px-6 py-4 ${
          isDarkMode ? 'border-slate-600' : 'border-slate-200'
        }`}>
          <div className="min-w-0">
            <h3 id="document-preview-title" className={`truncate text-lg font-semibold ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}`}>{doc.original_filename}</h3>
            <p className="mt-1 text-sm text-slate-400">
              {doc.file_type.toUpperCase()} · {categoryLabel}
              {previewData?.truncated ? tr(' · 当前为截断预览', ' · Truncated preview', ' · 省略プレビュー') : ''}
              {previewData?.preview_type === 'onlyoffice' ? ' · OnlyOffice' : ''}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {previewData?.preview_type === 'onlyoffice' && previewData?.can_edit && (
              <button
                onClick={() => setOfficeMode((c) => (c === 'edit' ? 'view' : 'edit'))}
                className="btn-secondary flex items-center gap-2 px-4 py-2"
              >
                <Edit3 className="h-4 w-4" />
                {officeMode === 'edit' ? tr('切到只读', 'Read-only', '閲覧モード') : tr('进入编辑', 'Edit', '編集')}
              </button>
            )}
            {previewData?.can_edit && (
              <button
                onClick={() => {
                  setEditorOpen((c) => !c)
                  setEditContent(previewData.content)
                }}
                className="btn-secondary flex items-center gap-2 px-4 py-2"
              >
                <Edit3 className="h-4 w-4" />
                {editorOpen ? tr('返回预览', 'Preview', 'プレビュー') : tr('编辑', 'Edit', '編集')}
              </button>
            )}
            {editorOpen && previewData?.can_edit && (
              <button onClick={handleSave} className="btn-primary flex items-center gap-2 px-4 py-2" disabled={saving}>
                <CheckCircle className="h-4 w-4" />
                {saving ? tr('保存中...', 'Saving...', '保存中...') : tr('保存', 'Save', '保存')}
              </button>
            )}
            <button onClick={onClose} aria-label={tr('关闭预览', 'Close preview', 'プレビューを閉じる')} className={`rounded-full p-2 transition-colors ${
              isDarkMode
                ? 'text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                : 'text-slate-400 hover:bg-slate-100 hover:text-slate-900'
            }`}>
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-6 scrollbar-thin">{renderPreviewContent()}</div>
      </div>
    </div>
  )
}
