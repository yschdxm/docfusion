import { useCallback, useEffect, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  CheckCircle,
  Download,
  Edit3,
  Eye,
  File,
  FileText,
  Filter,
  FolderOpen,
  Plus,
  RefreshCw,
  Search,
  Table,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Dropdown from '../components/ui/Dropdown'
import api from '../services/api'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (elementId: string, config: Record<string, unknown>) => {
        destroyEditor?: () => void
      }
    }
  }
}

type CategoryFilter = 'all' | 'source' | 'template' | 'output'

interface ExtractionStatus {
  task_id: string
  status: 'processing' | 'completed' | 'failed'
  progress: string
  current_step: string
  error?: string
  entities_count: number
}

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

const categoryConfig = {
  source: { icon: FileText, color: 'text-blue-400', bg: 'bg-blue-500/20', label: '源文档' },
  template: { icon: Table, color: 'text-green-400', bg: 'bg-green-500/20', label: '模板' },
  output: { icon: FolderOpen, color: 'text-orange-400', bg: 'bg-orange-500/20', label: '输出' },
}

function formatFileSize(size?: number) {
  if (!size) return null
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export default function DocumentManager() {
  const { documents, fetchDocuments, addDocuments, deleteDocument } = useDocumentStore()
  const [filter, setFilter] = useState<CategoryFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [previewDoc, setPreviewDoc] = useState<DocumentInfo | null>(null)
  const [previewData, setPreviewData] = useState<PreviewPayload | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [officeMode, setOfficeMode] = useState<'view' | 'edit'>('view')
  const [officeLoading, setOfficeLoading] = useState(false)
  const [officeError, setOfficeError] = useState('')
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isMountedRef = useRef(true)
  const officeEditorRef = useRef<{ destroyEditor?: () => void } | null>(null)
  const loadedScriptRef = useRef<string | null>(null)

  useEffect(() => {
    isMountedRef.current = true
    fetchDocuments()
    startPolling()

    return () => {
      isMountedRef.current = false
      stopPolling()
      destroyOnlyOfficeEditor()
    }
  }, [fetchDocuments])

  useEffect(() => {
    if (previewDoc && previewData?.preview_type === 'onlyoffice') {
      void mountOnlyOffice(officeMode)
    }

    return () => {
      if (previewData?.preview_type === 'onlyoffice') {
        destroyOnlyOfficeEditor()
      }
    }
  }, [previewDoc, previewData, officeMode])

  const startPolling = useCallback(() => {
    if (pollingRef.current) return
    pollingRef.current = setInterval(() => {
      if (isMountedRef.current) {
        fetchDocuments()
      }
    }, 1000)
  }, [fetchDocuments])

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const destroyOnlyOfficeEditor = () => {
    if (officeEditorRef.current?.destroyEditor) {
      officeEditorRef.current.destroyEditor()
    }
    officeEditorRef.current = null
  }

  const ensureOnlyOfficeScript = async (serverUrl: string) => {
    if (window.DocsAPI?.DocEditor) return

    const normalized = serverUrl.endsWith('/') ? serverUrl.slice(0, -1) : serverUrl
    const scriptUrl = `${normalized}/web-apps/apps/api/documents/api.js`

    if (loadedScriptRef.current && loadedScriptRef.current !== scriptUrl) {
      const oldScript = document.querySelector(`script[src="${loadedScriptRef.current}"]`)
      oldScript?.remove()
      loadedScriptRef.current = null
    }

    await new Promise<void>((resolve, reject) => {
      let script = document.querySelector(`script[src="${scriptUrl}"]`) as HTMLScriptElement | null
      if (!script) {
        script = document.createElement('script')
        script.src = scriptUrl
        document.body.appendChild(script)
        loadedScriptRef.current = scriptUrl
      }

      const startedAt = Date.now()
      const timer = window.setInterval(() => {
        if (window.DocsAPI?.DocEditor) {
          window.clearInterval(timer)
          resolve()
          return
        }

        if (Date.now() - startedAt > 60000) {
          window.clearInterval(timer)
          reject(new Error('OnlyOffice 脚本加载超时，请检查文档服务是否启动'))
        }
      }, 200)

      script.onerror = () => {
        window.clearInterval(timer)
        reject(new Error('OnlyOffice 脚本加载失败，请检查文档服务地址是否可访问'))
      }
    })
  }

  const mountOnlyOffice = async (mode: 'view' | 'edit') => {
    if (!previewDoc) return

    setOfficeLoading(true)
    setOfficeError('')
    destroyOnlyOfficeEditor()

    try {
      const response = await api.get<OfficeConfigResponse>(`/documents/${previewDoc.id}/office-config`, {
        params: { mode },
      })

      await ensureOnlyOfficeScript(response.data.serverUrl)

      if (!window.DocsAPI?.DocEditor) {
        throw new Error('OnlyOffice 组件未正确加载')
      }

      officeEditorRef.current = new window.DocsAPI.DocEditor('onlyoffice-editor', response.data.config)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'OnlyOffice 加载失败'
      setOfficeError(message)
    } finally {
      setOfficeLoading(false)
    }
  }

  const closePreview = () => {
    destroyOnlyOfficeEditor()
    setPreviewDoc(null)
    setPreviewData(null)
    setPreviewLoading(false)
    setEditorOpen(false)
    setEditContent('')
    setSaving(false)
    setOfficeMode('view')
    setOfficeLoading(false)
    setOfficeError('')
  }

  const openPreview = async (doc: DocumentInfo, editMode = false) => {
    setPreviewDoc(doc)
    setPreviewLoading(true)
    setPreviewData(null)
    setEditorOpen(false)
    setOfficeMode('view')
    setOfficeError('')

    try {
      const response = await api.get<PreviewPayload>(`/documents/${doc.id}/preview`)
      setPreviewData(response.data)
      setEditContent(response.data.content ?? '')
      setEditorOpen(editMode && response.data.can_edit)
      if (response.data.preview_type === 'onlyoffice') {
        setOfficeMode(editMode ? 'edit' : 'view')
      }
    } catch (error) {
      toast.error('文档预览加载失败')
      setPreviewDoc(null)
    } finally {
      setPreviewLoading(false)
    }
  }

  const onSourceDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      toast.success(`已上传 ${acceptedFiles.length} 个源文档，正在自动提取信息`)
    } catch (error) {
      toast.error('上传失败')
    }
  }

  const onTemplateDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'template')
      toast.success(`已上传 ${acceptedFiles.length} 个模板`)
    } catch (error) {
      toast.error('上传失败')
    }
  }

  const { getRootProps: getSourceRootProps, getInputProps: getSourceInputProps, isDragActive: isSourceDragActive } =
    useDropzone({
      onDrop: onSourceDrop,
      accept: {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
        'text/markdown': ['.md'],
        'text/plain': ['.txt'],
      },
    })

  const { getRootProps: getTemplateRootProps, getInputProps: getTemplateInputProps, isDragActive: isTemplateDragActive } =
    useDropzone({
      onDrop: onTemplateDrop,
      accept: {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      },
    })

  const filteredDocs = documents.filter((doc) => {
    const matchFilter = filter === 'all' || doc.doc_category === filter
    const matchSearch = doc.original_filename.toLowerCase().includes(searchTerm.toLowerCase())
    return matchFilter && matchSearch
  })

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')
  const outputDocs = documents.filter((d) => d.doc_category === 'output')

  const handleDelete = async (docId: string, docName: string) => {
    if (!confirm(`确认删除 "${docName}" 吗？`)) return

    try {
      await deleteDocument(docId)
      setSelectedDocs((prev) => prev.filter((id) => id !== docId))
      if (previewDoc?.id === docId) {
        closePreview()
      }
      toast.success('删除成功')
    } catch (error) {
      toast.error('删除失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selectedDocs.length === 0) {
      toast.error('请先选择要删除的文档')
      return
    }
    if (!confirm(`确认删除选中的 ${selectedDocs.length} 个文档吗？`)) return

    try {
      for (const docId of selectedDocs) {
        await deleteDocument(docId)
      }
      if (previewDoc && selectedDocs.includes(previewDoc.id)) {
        closePreview()
      }
      setSelectedDocs([])
      toast.success('批量删除成功')
    } catch (error) {
      toast.error('批量删除失败')
    }
  }

  const handleRetryExtraction = async (docId: string, docName: string) => {
    try {
      await api.post(`/documents/${docId}/retry-extraction`)
      toast.success(`已重新开始提取 "${docName}"`)
      setTimeout(() => {
        fetchDocuments()
      }, 300)
    } catch (error) {
      toast.error('重试失败')
    }
  }

  const handleSave = async () => {
    if (!previewDoc || !previewData?.can_edit) return

    setSaving(true)
    try {
      await api.post(`/documents/${previewDoc.id}/save`, { content: editContent })
      setPreviewData({
        ...previewData,
        content: editContent,
        html_content: null,
        truncated: false,
      })
      setEditorOpen(false)
      await fetchDocuments()
      toast.success('保存成功')
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleSelect = (docId: string) => {
    setSelectedDocs((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }

  const toggleSelectAll = () => {
    if (selectedDocs.length === filteredDocs.length) {
      setSelectedDocs([])
    } else {
      setSelectedDocs(filteredDocs.map((d) => d.id))
    }
  }

  const renderExtractionStatus = (doc: DocumentInfo) => {
    if (doc.doc_category !== 'source') return null

    const status = doc.extraction_status as ExtractionStatus | null
    if (!status) {
      return <span className="text-xs text-slate-500">待提取</span>
    }

    if (status.status === 'processing') {
      const progressNum = parseInt(status.progress, 10) || 0
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-700">
            <div className="h-full rounded-full bg-blue-500 transition-all duration-300" style={{ width: `${progressNum}%` }} />
          </div>
          <span className="text-xs text-blue-400">{progressNum}%</span>
        </div>
      )
    }

    if (status.status === 'completed') {
      return (
        <div className="flex items-center gap-1">
          <CheckCircle className="h-3.5 w-3.5 text-green-400" />
          <span className="text-xs text-green-400">已完成</span>
        </div>
      )
    }

    if (status.status === 'failed') {
      const errorMsg = status.error || '提取失败'
      const shortError = errorMsg.length > 36 ? `${errorMsg.slice(0, 36)}...` : errorMsg
      return (
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1" title={errorMsg}>
            <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
            <span className="text-xs text-red-400">{shortError}</span>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleRetryExtraction(doc.id, doc.original_filename)
            }}
            className="text-xs text-blue-400 underline hover:text-blue-300"
          >
            重试
          </button>
        </div>
      )
    }

    return null
  }

  const renderPreviewContent = () => {
    if (previewLoading) {
      return <div className="flex h-full items-center justify-center text-slate-400">正在加载预览...</div>
    }

    if (!previewData) {
      return <div className="flex h-full items-center justify-center text-slate-500">暂无预览内容</div>
    }

    if (previewData.preview_type === 'onlyoffice') {
      return (
        <div className="h-[68vh] overflow-hidden rounded-2xl border border-white/10 bg-white">
          {officeLoading && <div className="p-4 text-sm text-slate-500">正在加载 OnlyOffice...</div>}
          {officeError && <div className="border-b border-red-100 bg-red-50 p-4 text-sm text-red-600">{officeError}</div>}
          <div id="onlyoffice-editor" className="h-full w-full" />
        </div>
      )
    }

    if (editorOpen && previewData.can_edit) {
      return (
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          spellCheck={false}
          className="h-full min-h-[420px] w-full rounded-2xl border border-white/10 bg-slate-950/80 p-4 font-mono text-sm leading-7 text-slate-100 outline-none"
        />
      )
    }

    if (previewData.preview_type === 'pdf') {
      return (
        <iframe
          title="document-preview"
          src={`/api/v1/documents/${previewDoc?.id}/inline`}
          className="h-[68vh] w-full rounded-2xl border border-white/10 bg-white"
        />
      )
    }

    if (previewData.preview_type === 'spreadsheet') {
      return (
        <div className="space-y-5">
          {previewData.sheets?.map((sheet) => (
            <div key={sheet.name} className="overflow-hidden rounded-2xl border border-white/10 bg-slate-950/60">
              <div className="border-b border-white/10 px-4 py-3">
                <div className="text-sm font-medium text-white">{sheet.name}</div>
                <div className="text-xs text-slate-400">
                  {sheet.rows} 行 · {sheet.cols} 列
                </div>
              </div>
              <div className="max-h-72 overflow-auto scrollbar-thin">
                <table className="min-w-full text-left text-sm">
                  <tbody>
                    {sheet.data.slice(0, 20).map((row, rowIndex) => (
                      <tr key={`${sheet.name}-${rowIndex}`} className="border-b border-white/5">
                        {row.map((cell, colIndex) => (
                          <td key={`${sheet.name}-${rowIndex}-${colIndex}`} className="px-4 py-2 text-slate-200">
                            {cell || '-'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          <pre className="whitespace-pre-wrap rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-xs leading-6 text-slate-300">
            {previewData.content}
          </pre>
        </div>
      )
    }

    if (previewData.preview_type === 'markdown' && previewData.html_content) {
      return (
        <div className="space-y-4">
          <div
            className="prose prose-invert max-w-none rounded-2xl border border-white/10 bg-slate-950/70 p-5 prose-headings:text-white prose-p:text-slate-200 prose-strong:text-white prose-code:text-blue-300"
            dangerouslySetInnerHTML={{ __html: previewData.html_content }}
          />
          <details className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
            <summary className="cursor-pointer text-sm text-slate-300">查看原始 Markdown</summary>
            <pre className="mt-4 whitespace-pre-wrap text-xs leading-6 text-slate-300">{previewData.content}</pre>
          </details>
        </div>
      )
    }

    return (
      <pre className="min-h-[420px] whitespace-pre-wrap rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm leading-7 text-slate-200">
        {previewData.content}
      </pre>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="glass p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/20">
              <FileText className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h3 className="font-medium text-white">上传源文档</h3>
              <p className="text-xs text-slate-400">支持 docx、xlsx、md、txt</p>
            </div>
          </div>
          <div {...getSourceRootProps()} className={`upload-zone ${isSourceDragActive ? 'upload-zone-active' : ''}`}>
            <input {...getSourceInputProps()} />
            <div className="flex items-center justify-center gap-2">
              <Plus className="h-5 w-5 text-slate-400" />
              <span className="text-slate-400">点击或拖拽上传源文档</span>
            </div>
          </div>
        </div>

        <div className="glass p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-green-500/20">
              <Table className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h3 className="font-medium text-white">上传模板</h3>
              <p className="text-xs text-slate-400">支持 docx、xlsx</p>
            </div>
          </div>
          <div {...getTemplateRootProps()} className={`upload-zone ${isTemplateDragActive ? 'upload-zone-active' : ''}`}>
            <input {...getTemplateInputProps()} />
            <div className="flex items-center justify-center gap-2">
              <Plus className="h-5 w-5 text-slate-400" />
              <span className="text-slate-400">点击或拖拽上传模板</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className={`glass cursor-pointer p-4 transition-all ${filter === 'all' ? 'ring-2 ring-primary-500' : ''}`} onClick={() => setFilter('all')}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-500/20">
              <File className="h-5 w-5 text-primary-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{documents.length}</p>
              <p className="text-xs text-slate-400">全部文档</p>
            </div>
          </div>
        </div>

        <div className={`glass cursor-pointer p-4 transition-all ${filter === 'source' ? 'ring-2 ring-blue-500' : ''}`} onClick={() => setFilter('source')}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/20">
              <FileText className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{sourceDocs.length}</p>
              <p className="text-xs text-slate-400">源文档</p>
            </div>
          </div>
        </div>

        <div className={`glass cursor-pointer p-4 transition-all ${filter === 'template' ? 'ring-2 ring-green-500' : ''}`} onClick={() => setFilter('template')}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-500/20">
              <Table className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{templateDocs.length}</p>
              <p className="text-xs text-slate-400">模板</p>
            </div>
          </div>
        </div>

        <div className={`glass cursor-pointer p-4 transition-all ${filter === 'output' ? 'ring-2 ring-orange-500' : ''}`} onClick={() => setFilter('output')}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500/20">
              <FolderOpen className="h-5 w-5 text-orange-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{outputDocs.length}</p>
              <p className="text-xs text-slate-400">输出文件</p>
            </div>
          </div>
        </div>
      </div>

      <div className="glass p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索文档..."
                className="input w-64 pl-10"
              />
            </div>

            <Dropdown
              value={filter}
              onChange={(v) => setFilter(v as CategoryFilter)}
              options={[
                { value: 'all', label: '全部' },
                { value: 'source', label: '源文档' },
                { value: 'template', label: '模板' },
                { value: 'output', label: '输出' },
              ]}
              icon={<Filter className="h-4 w-4 text-slate-400" />}
              className="w-40"
            />
          </div>

          <div className="flex items-center gap-3">
            <button onClick={() => fetchDocuments()} className="btn-secondary flex items-center gap-2" title="刷新">
              <RefreshCw className="h-4 w-4" />
            </button>
            {selectedDocs.length > 0 && (
              <button onClick={handleBatchDelete} className="btn-secondary flex items-center gap-2 text-red-400 hover:text-red-300">
                <Trash2 className="h-4 w-4" />
                删除选中 ({selectedDocs.length})
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="glass overflow-hidden">
        <div className="border-b border-white/10 p-4">
          <label className="flex cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              checked={selectedDocs.length === filteredDocs.length && filteredDocs.length > 0}
              onChange={toggleSelectAll}
              className="h-4 w-4 rounded border-white/20 bg-white/10 text-primary-500"
            />
            <span className="text-sm text-slate-400">全选 ({filteredDocs.length} 个文档)</span>
          </label>
        </div>

        <div className="max-h-[560px] overflow-y-auto scrollbar-thin">
          {filteredDocs.length > 0 ? (
            filteredDocs.map((doc) => {
              const config = categoryConfig[doc.doc_category as keyof typeof categoryConfig] || categoryConfig.source
              const Icon = config.icon
              const downloadUrl =
                doc.doc_category === 'output' ? `/api/v1/table-fill/download/${doc.id}` : `/api/v1/documents/${doc.id}/download`

              return (
                <div
                  key={doc.id}
                  className={`flex items-center gap-4 border-b border-white/5 p-4 transition-colors hover:bg-white/5 ${
                    selectedDocs.includes(doc.id) ? 'bg-primary-500/10' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleSelect(doc.id)}
                    className="h-4 w-4 rounded border-white/20 bg-white/10 text-primary-500"
                  />

                  <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${config.bg}`}>
                    <Icon className={`h-5 w-5 ${config.color}`} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-white">{doc.original_filename}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-3">
                      <span className={`rounded px-2 py-0.5 text-xs ${config.bg} ${config.color}`}>{config.label}</span>
                      <span className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</span>
                      {formatFileSize(doc.file_size) && <span className="text-xs text-slate-500">{formatFileSize(doc.file_size)}</span>}
                      <span className="text-xs text-slate-500">{new Date(doc.created_at).toLocaleDateString('zh-CN')}</span>
                    </div>
                  </div>

                  {doc.doc_category === 'source' && <div className="w-64 shrink-0">{renderExtractionStatus(doc)}</div>}

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openPreview(doc)}
                      className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                      title="预览"
                    >
                      <Eye className="h-4 w-4" />
                    </button>
                    {(doc.file_type === 'txt' || doc.file_type === 'md') && (
                      <button
                        onClick={() => openPreview(doc, true)}
                        className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-emerald-500/20 hover:text-emerald-300"
                        title="编辑"
                      >
                        <Edit3 className="h-4 w-4" />
                      </button>
                    )}
                    <a href={downloadUrl} className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-blue-500/20 hover:text-blue-400" download>
                      <Download className="h-4 w-4" />
                    </a>
                    <button
                      onClick={() => handleDelete(doc.id, doc.original_filename)}
                      className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-500/20 hover:text-red-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )
            })
          ) : (
            <div className="p-12 text-center">
              <FileText className="mx-auto mb-4 h-16 w-16 text-slate-600" />
              <p className="text-slate-400">{searchTerm ? '没有匹配的文档' : '暂无文档'}</p>
            </div>
          )}
        </div>
      </div>

      {previewDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 px-4 py-6 backdrop-blur-sm">
          <div className="glass-dark flex h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-[28px]">
            <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
              <div className="min-w-0">
                <h3 className="truncate text-lg font-semibold text-white">{previewDoc.original_filename}</h3>
                <p className="mt-1 text-sm text-slate-400">
                  {previewDoc.file_type.toUpperCase()} · {categoryConfig[previewDoc.doc_category as keyof typeof categoryConfig]?.label || '文档'}
                  {previewData?.truncated ? ' · 当前为截断预览' : ''}
                  {previewData?.preview_type === 'onlyoffice' ? ' · OnlyOffice' : ''}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {previewData?.preview_type === 'onlyoffice' && (
                  <button
                    onClick={() => setOfficeMode((current) => (current === 'edit' ? 'view' : 'edit'))}
                    className="btn-secondary flex items-center gap-2 px-4 py-2"
                  >
                    <Edit3 className="h-4 w-4" />
                    {officeMode === 'edit' ? '切到只读' : '进入编辑'}
                  </button>
                )}
                {previewData?.can_edit && (
                  <button
                    onClick={() => {
                      setEditorOpen((current) => !current)
                      setEditContent(previewData.content)
                    }}
                    className="btn-secondary flex items-center gap-2 px-4 py-2"
                  >
                    <Edit3 className="h-4 w-4" />
                    {editorOpen ? '返回预览' : '编辑'}
                  </button>
                )}
                {editorOpen && previewData?.can_edit && (
                  <button onClick={handleSave} className="btn-primary flex items-center gap-2 px-4 py-2" disabled={saving}>
                    <CheckCircle className="h-4 w-4" />
                    {saving ? '保存中...' : '保存'}
                  </button>
                )}
                <button onClick={closePreview} className="rounded-full p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white">
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-6 scrollbar-thin">{renderPreviewContent()}</div>
          </div>
        </div>
      )}
    </div>
  )
}
