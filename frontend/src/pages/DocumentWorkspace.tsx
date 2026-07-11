import { useCallback, useEffect, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  CheckCircle,
  Download,
  Eye,
  FileText,
  Filter,
  FolderOpen,
  RefreshCw,
  Search,
  Table,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Dropdown from '../components/ui/Dropdown'
import api from '../services/api'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'
import DocumentPreviewModal from '../components/DocumentPreviewModal'
import OnlyOfficeEditor from '../components/OnlyOfficeEditor'
import AISidebar from '../components/ai/AISidebar'
import ResizeHandle from '../components/ai/ResizeHandle'

type CategoryFilter = 'all' | 'source' | 'template' | 'output'

interface ExtractionStatus {
  task_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed'
  progress: string
  current_step: string
  error?: string
  entities_count: number
}

const categoryConfig = {
  source: { icon: FileText, color: 'text-blue-600', bg: 'bg-blue-100' },
  template: { icon: Table, color: 'text-emerald-600', bg: 'bg-emerald-100' },
  output: { icon: FolderOpen, color: 'text-amber-600', bg: 'bg-amber-100' },
}

function formatFileSize(size?: number) {
  if (!size) return null
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function parseDownloadFilename(contentDisposition?: string, fallbackName?: string) {
  if (!contentDisposition) return fallbackName ?? 'download'

  const utf8Match = contentDisposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const filenameMatch = contentDisposition.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i)
  const parsed = filenameMatch?.[1] ?? filenameMatch?.[2]
  return parsed?.trim() || fallbackName || 'download'
}

function triggerFileDownload(blob: Blob, filename: string) {
  const objectUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(objectUrl)
}

interface Tab {
  id: string
  title: string
  type: 'home' | 'document'
  documentId?: string
}

export default function DocumentWorkspace() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments, addDocuments, deleteDocument, uploadProgress } = useDocumentStore()
  const [filter, setFilter] = useState<CategoryFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [previewDoc, setPreviewDoc] = useState<DocumentInfo | null>(null)
  const sseSourcesRef = useRef<Record<string, EventSource>>({})
  const pendingDeleteTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const isMountedRef = useRef(true)
  const [sortBy, setSortBy] = useState<'recent' | 'name' | 'size'>('recent')

  // 标签页状态
  const [tabs, setTabs] = useState<Tab[]>([
    { id: 'home', title: tr('主页', 'Home', 'ホーム'), type: 'home' },
  ])
  const [activeTabId, setActiveTabId] = useState('home')

  // AI 边栏状态
  const SIDEBAR_DEFAULT = Math.max(320, Math.floor(window.innerWidth / 6))
  const SIDEBAR_MIN = 280
  const SIDEBAR_MAX = Math.floor(window.innerWidth * 0.4)
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT)

  // 处理边栏拖动
  // delta > 0 表示向左拖动（增大边栏宽度），delta < 0 表示向右拖动（减小边栏宽度）
  const handleSidebarResize = useCallback((delta: number) => {
    setSidebarWidth(prev => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, prev + delta)))
  }, [SIDEBAR_MAX])

  const notifyBell = (title: string, message: string) => {
    window.dispatchEvent(
      new CustomEvent('app-notify', {
        detail: { title, message },
      })
    )
  }

  const clearPendingDeleteTimer = (key: string) => {
    const timer = pendingDeleteTimersRef.current[key]
    if (!timer) return
    clearTimeout(timer)
    delete pendingDeleteTimersRef.current[key]
  }

  const closeAllSSEConnections = useCallback(() => {
    Object.values(sseSourcesRef.current).forEach((source) => {
      source.close()
    })
    sseSourcesRef.current = {}
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    fetchDocuments()

    return () => {
      isMountedRef.current = false
      closeAllSSEConnections()
    }
  }, [fetchDocuments, closeAllSSEConnections])

  const startSSEForDoc = useCallback((docId: string) => {
    if (sseSourcesRef.current[docId]) return

    const baseUrl = api.defaults.baseURL || '/api/v1'
    const url = `${baseUrl}/documents/${docId}/progress-stream`

    const eventSource = new EventSource(url)
    sseSourcesRef.current[docId] = eventSource

    eventSource.onmessage = (event) => {
      if (!isMountedRef.current) return

      try {
        const data = JSON.parse(event.data)

        useDocumentStore.setState((state) => ({
          documents: state.documents.map((doc) => {
            if (doc.id === docId) {
              return {
                ...doc,
                extraction_status: {
                  task_id: data.task_id || doc.extraction_status?.task_id,
                  status: data.status,
                  progress: data.progress,
                  current_step: data.current_step,
                  error: data.error,
                  entities_count: doc.extraction_status?.entities_count || 0,
                },
              }
            }
            return doc
          }),
        }))

        if (data.status === 'completed' || data.status === 'failed') {
          eventSource.close()
          delete sseSourcesRef.current[docId]
          fetchDocuments()
        }
      } catch {
        // 忽略解析错误
      }
    }

    eventSource.addEventListener('done', () => {
      eventSource.close()
      delete sseSourcesRef.current[docId]
      if (isMountedRef.current) {
        fetchDocuments()
      }
    })

    eventSource.onerror = () => {
      eventSource.close()
      delete sseSourcesRef.current[docId]
      if (isMountedRef.current) {
        fetchDocuments()
      }
    }
  }, [fetchDocuments])

  useEffect(() => {
    const processingDocs = documents.filter(
      (doc) => doc.doc_category === 'source' && (doc.extraction_status?.status === 'processing' || doc.extraction_status?.status === 'queued')
    )

    processingDocs.forEach((doc) => {
      if (!sseSourcesRef.current[doc.id]) {
        startSSEForDoc(doc.id)
      }
    })

    const docIds = new Set(documents.map((d) => d.id))
    Object.keys(sseSourcesRef.current).forEach((id) => {
      if (!docIds.has(id)) {
        sseSourcesRef.current[id].close()
        delete sseSourcesRef.current[id]
      }
    })
  }, [documents, startSSEForDoc])

  const openPreview = (doc: DocumentInfo) => {
    setPreviewDoc(doc)
  }

  // 打开文档标签页
  const openDocumentTab = (doc: DocumentInfo) => {
    const existingTab = tabs.find((tab) => tab.documentId === doc.id)
    if (existingTab) {
      setActiveTabId(existingTab.id)
      return
    }

    const newTab: Tab = {
      id: `doc-${doc.id}`,
      title: doc.original_filename,
      type: 'document',
      documentId: doc.id,
    }
    setTabs([...tabs, newTab])
    setActiveTabId(newTab.id)
  }

  // 关闭标签页
  const closeTab = (tabId: string) => {
    const tabIndex = tabs.findIndex((tab) => tab.id === tabId)
    if (tabIndex === -1) return

    const newTabs = tabs.filter((tab) => tab.id !== tabId)
    setTabs(newTabs)

    if (activeTabId === tabId) {
      const newActiveIndex = Math.min(tabIndex, newTabs.length - 1)
      setActiveTabId(newTabs[newActiveIndex].id)
    }
  }

  const onSourceDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      const message = tr(`已上传 ${acceptedFiles.length} 个源文档，正在自动提取信息`, `Uploaded ${acceptedFiles.length} source docs, extraction started`, `${acceptedFiles.length} 件のソース文書をアップロードし、抽出を開始しました`)
      toast.success(message)
      notifyBell(tr('上传成功', 'Upload succeeded', 'アップロード成功'), message)
      setTimeout(() => fetchDocuments(), 500)
    } catch {
      toast.error(tr('上传失败', 'Upload failed', 'アップロードに失敗しました'))
    }
  }

  const onTemplateDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'template')
      const message = tr(`已上传 ${acceptedFiles.length} 个模板`, `Uploaded ${acceptedFiles.length} templates`, `${acceptedFiles.length} 件のテンプレートをアップロードしました`)
      toast.success(message)
      notifyBell(tr('上传成功', 'Upload succeeded', 'アップロード成功'), message)
    } catch {
      toast.error(tr('上传失败', 'Upload failed', 'アップロードに失敗しました'))
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

  // 排序
  const sortedDocs = [...filteredDocs].sort((a, b) => {
    if (sortBy === 'recent') {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    }
    if (sortBy === 'name') {
      return a.original_filename.localeCompare(b.original_filename)
    }
    return (b.file_size || 0) - (a.file_size || 0)
  })

  // 按时间分组
  const groupDocsByTime = (docs: DocumentInfo[]) => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000)
    const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)

    const groups: { label: string; docs: DocumentInfo[] }[] = [
      { label: tr('今天', 'Today', '今日'), docs: [] },
      { label: tr('昨天', 'Yesterday', '昨日'), docs: [] },
      { label: tr('7天内', 'Last 7 days', '7日以内'), docs: [] },
      { label: tr('更早', 'Older', 'それ以前'), docs: [] },
    ]

    docs.forEach((doc) => {
      const uploadDate = new Date(doc.created_at)
      if (uploadDate >= today) {
        groups[0].docs.push(doc)
      } else if (uploadDate >= yesterday) {
        groups[1].docs.push(doc)
      } else if (uploadDate >= weekAgo) {
        groups[2].docs.push(doc)
      } else {
        groups[3].docs.push(doc)
      }
    })

    return groups.filter((group) => group.docs.length > 0)
  }

  const groupedDocs = groupDocsByTime(sortedDocs)

  const handleDelete = async (docId: string, docName: string) => {
    if (!confirm(tr(`确认删除 "${docName}" 吗？`, `Delete "${docName}"?`, `「${docName}」を削除しますか？`))) return

    const timerKey = `single-${docId}`
    clearPendingDeleteTimer(timerKey)

    const timer = setTimeout(async () => {
      try {
        await deleteDocument(docId)
        setSelectedDocs((prev) => prev.filter((id) => id !== docId))
        if (previewDoc?.id === docId) {
          setPreviewDoc(null)
        }
        const message = tr('删除成功', 'Deleted', '削除しました')
        toast.success(message)
        notifyBell(tr('删除成功', 'Delete succeeded', '削除成功'), `${docName} · ${message}`)
      } catch {
        toast.error(tr('删除失败', 'Delete failed', '削除に失敗しました'))
      } finally {
        clearPendingDeleteTimer(timerKey)
      }
    }, 4000)
    pendingDeleteTimersRef.current[timerKey] = timer

    // 显示撤销提示
    toast(
      (t) => (
        <div className="flex items-center gap-2">
          <span>{tr('点击撤销可恢复', 'Click undo to restore', '元に戻すにはクリック')}</span>
          <button
            onClick={() => {
              clearPendingDeleteTimer(timerKey)
              toast.dismiss(t.id)
            }}
            className="text-primary-500 hover:text-primary-600 font-medium"
          >
            {tr('撤销', 'Undo', '元に戻す')}
          </button>
        </div>
      ),
      { duration: 4000 }
    )
  }

  const handleDownload = async (doc: DocumentInfo) => {
    try {
      const response = await api.get(`/documents/${doc.id}/download`, {
        responseType: 'blob',
      })
      const filename = parseDownloadFilename(response.headers['content-disposition'], doc.original_filename)
      triggerFileDownload(response.data, filename)
    } catch {
      toast.error(tr('下载失败', 'Download failed', 'ダウンロード失敗'))
    }
  }

  const toggleDocSelection = (docId: string) => {
    setSelectedDocs((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }

  const deleteSelected = async () => {
    if (selectedDocs.length === 0) return
    if (!confirm(tr(`确认删除 ${selectedDocs.length} 个文档吗？`, `Delete ${selectedDocs.length} documents?`, `${selectedDocs.length} 件のドキュメントを削除しますか？`))) return

    try {
      await Promise.all(selectedDocs.map((id) => deleteDocument(id)))
      setSelectedDocs([])
      toast.success(tr('批量删除成功', 'Batch delete succeeded', '一括削除成功'))
    } catch {
      toast.error(tr('批量删除失败', 'Batch delete failed', '一括削除失敗'))
    }
  }

  const getCategoryIcon = (category: string) => {
    const config = categoryConfig[category as keyof typeof categoryConfig]
    if (!config) return <FileText className="h-4 w-4 text-slate-400" />
    const Icon = config.icon
    return <Icon className={`h-4 w-4 ${config.color}`} />
  }

  const getCategoryLabel = (category: string) => {
    switch (category) {
      case 'source': return tr('源文档', 'Source', 'ソース')
      case 'template': return tr('模板', 'Template', 'テンプレート')
      case 'output': return tr('输出', 'Output', '出力')
      default: return category
    }
  }

  const getExtractionStatusIcon = (status?: ExtractionStatus | null) => {
    if (!status) return null
    switch (status.status) {
      case 'processing':
        return <RefreshCw className="h-3 w-3 text-blue-500 animate-spin" />
      case 'completed':
        return <CheckCircle className="h-3 w-3 text-green-500" />
      case 'failed':
        return <X className="h-3 w-3 text-red-500" />
      default:
        return null
    }
  }

  // 渲染主界面内容
  const renderHomeContent = () => (
    <div className="h-full flex">
      {/* 左侧导航栏 */}
      <div className="w-60 border-r border-slate-200 bg-white p-4 flex flex-col">
        {/* 文档上传按钮 */}
        <div
          {...getSourceRootProps()}
          className={`mb-3 cursor-pointer transition-all rounded-lg ${isSourceDragActive ? 'ring-2 ring-blue-400' : ''}`}
        >
          <input {...getSourceInputProps()} />
          <div className={`flex items-center gap-3 p-3 rounded-lg border-2 border-dashed transition-colors ${isSourceDragActive ? 'border-blue-400 bg-blue-50' : 'border-slate-200 hover:border-blue-400 hover:bg-blue-50'}`}>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
              <FileText className="h-4 w-4 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-900">{tr('文档上传', 'Upload Docs', '文書アップロード')}</p>
              <p className="text-xs text-slate-500">docx xlsx md txt</p>
            </div>
          </div>
        </div>

        {/* 模板上传按钮 */}
        <div
          {...getTemplateRootProps()}
          className={`mb-6 cursor-pointer transition-all rounded-lg ${isTemplateDragActive ? 'ring-2 ring-emerald-400' : ''}`}
        >
          <input {...getTemplateInputProps()} />
          <div className={`flex items-center gap-3 p-3 rounded-lg border-2 border-dashed transition-colors ${isTemplateDragActive ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 hover:border-emerald-400 hover:bg-emerald-50'}`}>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100">
              <Table className="h-4 w-4 text-emerald-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-900">{tr('模板上传', 'Upload Templates', 'テンプレートアップロード')}</p>
              <p className="text-xs text-slate-500">docx xlsx</p>
            </div>
          </div>
        </div>

        {/* 目录结构 */}
        <div className="flex-1">
          <h3 className="text-sm font-medium text-slate-500 mb-3">{tr('目录结构', 'Directory', 'ディレクトリ')}</h3>
          <div className="flex flex-col items-center justify-center py-8 text-slate-400">
            <FolderOpen className="h-10 w-10 mb-3" />
            <p className="text-xs">{tr('待实现', 'Coming soon', '近日公開')}</p>
          </div>
        </div>

        {/* 上传进度 */}
        {uploadProgress !== null && (
          <div className="mt-4 p-3 bg-blue-50 rounded-lg">
            <p className="text-xs text-blue-600 mb-2">{tr('上传中...', 'Uploading...', 'アップロード中...')}</p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-blue-200">
              <div className="h-full rounded-full bg-blue-500 transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
            </div>
            <p className="text-xs text-blue-500 mt-1">{uploadProgress}%</p>
          </div>
        )}
      </div>

      {/* 中间主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 搜索和筛选栏 */}
        <div className="flex items-center gap-4 p-4 border-b border-slate-200 bg-white">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder={tr('搜索文档...', 'Search documents...', 'ドキュメントを検索...')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setFilter('all')}
              className={`px-3 py-2 text-sm rounded-lg transition-colors ${filter === 'all' ? 'bg-primary-500 text-white' : 'bg-white text-slate-600 hover:bg-slate-50 border border-slate-200'}`}
            >
              {tr('全部', 'All', 'すべて')}
            </button>
            <button
              onClick={() => setFilter('source')}
              className={`px-3 py-2 text-sm rounded-lg transition-colors ${filter === 'source' ? 'bg-blue-500 text-white' : 'bg-white text-slate-600 hover:bg-slate-50 border border-slate-200'}`}
            >
              {tr('源文档', 'Source', 'ソース')}
            </button>
            <button
              onClick={() => setFilter('template')}
              className={`px-3 py-2 text-sm rounded-lg transition-colors ${filter === 'template' ? 'bg-emerald-500 text-white' : 'bg-white text-slate-600 hover:bg-slate-50 border border-slate-200'}`}
            >
              {tr('模板', 'Template', 'テンプレート')}
            </button>
            <button
              onClick={() => setFilter('output')}
              className={`px-3 py-2 text-sm rounded-lg transition-colors ${filter === 'output' ? 'bg-amber-500 text-white' : 'bg-white text-slate-600 hover:bg-slate-50 border border-slate-200'}`}
            >
              {tr('输出', 'Output', '出力')}
            </button>
          </div>
          <Dropdown
            value={sortBy}
            onChange={(value) => setSortBy(value as 'recent' | 'name' | 'size')}
            options={[
              { value: 'recent', label: tr('最近修改', 'Recent', '最近の変更') },
              { value: 'name', label: tr('名称', 'Name', '名前') },
              { value: 'size', label: tr('大小', 'Size', 'サイズ') },
            ]}
            icon={<Filter className="h-4 w-4" />}
            placeholder={tr('排序', 'Sort', '並べ替え')}
          />
        </div>

        {/* 批量操作 */}
        {selectedDocs.length > 0 && (
          <div className="flex items-center gap-2 px-4 py-3 bg-primary-50 border-b border-slate-200">
            <span className="text-sm text-primary-700">
              {tr(`已选择 ${selectedDocs.length} 个文档`, `Selected ${selectedDocs.length} documents`, `${selectedDocs.length} 件選択中`)}
            </span>
            <button
              onClick={deleteSelected}
              className="ml-auto flex items-center gap-1 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg"
            >
              <Trash2 className="h-4 w-4" />
              {tr('批量删除', 'Delete Selected', '一括削除')}
            </button>
          </div>
        )}

        {/* 文档列表 */}
        <div className="flex-1 overflow-y-auto p-4">
          {groupedDocs.map((group) => (
            <div key={group.label} className="mb-6">
              <h3 className="text-sm font-medium text-slate-500 mb-3">{group.label}</h3>
              <div className="space-y-2">
                {group.docs.map((doc) => (
                  <div
                    key={doc.id}
                    className="glass p-3 hover:shadow-md transition-shadow cursor-pointer"
                    onClick={() => openDocumentTab(doc)}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedDocs.includes(doc.id)}
                          onChange={(e) => {
                            e.stopPropagation()
                            toggleDocSelection(doc.id)
                          }}
                          className="h-4 w-4 text-primary-500 rounded border-slate-300 focus:ring-primary-500"
                        />
                        {getCategoryIcon(doc.doc_category)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-900 truncate">{doc.original_filename}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-slate-500">{getCategoryLabel(doc.doc_category)}</span>
                          {doc.file_size && (
                            <span className="text-xs text-slate-400">{formatFileSize(doc.file_size)}</span>
                          )}
                          {getExtractionStatusIcon(doc.extraction_status)}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            openPreview(doc)
                          }}
                          className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg"
                          title={tr('预览', 'Preview', 'プレビュー')}
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDownload(doc)
                          }}
                          className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg"
                          title={tr('下载', 'Download', 'ダウンロード')}
                        >
                          <Download className="h-4 w-4" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(doc.id, doc.original_filename)
                          }}
                          className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg"
                          title={tr('删除', 'Delete', '削除')}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {groupedDocs.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400">
              <FolderOpen className="h-12 w-12 mb-4" />
              <p className="text-sm">{tr('暂无文档', 'No documents', 'ドキュメントがありません')}</p>
              <p className="text-xs mt-1">{tr('上传文档后将显示在这里', 'Upload documents to see them here', 'アップロード後にここに表示されます')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  // 获取所有打开的文档标签页
  const documentTabs = tabs.filter((tab) => tab.type === 'document' && tab.documentId)

  return (
    <div className="h-full flex flex-col bg-white rounded-xl shadow-sm overflow-hidden">
      {/* 顶部标签栏 */}
      <div className="flex items-center border-b border-slate-200 bg-white">
        <div className="flex items-center overflow-x-auto">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={`flex items-center gap-2 px-4 py-2.5 border-r border-slate-200 cursor-pointer transition-colors ${activeTabId === tab.id ? 'bg-white text-primary-600 border-b-2 border-b-primary-500' : 'bg-slate-50 text-slate-600 hover:bg-slate-100'}`}
              onClick={() => setActiveTabId(tab.id)}
            >
              {tab.type === 'home' ? (
                <FolderOpen className="h-4 w-4" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              <span className="text-sm truncate max-w-[120px]">{tab.title}</span>
              {tab.type === 'document' && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    closeTab(tab.id)
                  }}
                  className="p-0.5 hover:bg-slate-200 rounded"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 主内容区域 */}
      <div className="flex-1 overflow-hidden flex">
        {/* 左侧：首页/编辑器 */}
        <div className="flex-1 overflow-hidden relative">
          {/* 首页内容 */}
          <div className={`h-full ${activeTabId === 'home' ? '' : 'hidden'}`}>
            {renderHomeContent()}
          </div>
          {/* 文档编辑器 - 为每个打开的文档创建实例，使用 display控制显示 */}
          {documentTabs.map((tab) => {
            const doc = documents.find((d) => d.id === tab.documentId)
            if (!doc) return null
            return (
              <div
                key={tab.id}
                className={`h-full absolute inset-0 ${activeTabId === tab.id ? '' : 'hidden'}`}
              >
                <OnlyOfficeEditor
                  documentId={tab.documentId!}
                  mode="edit"
                />
              </div>
            )
          })}
        </div>

        {/* 右侧：AI 边栏（仅在打开文档时显示） */}
        {activeTabId !== 'home' && documentTabs.some(t => t.id === activeTabId) && (
          <>
            <ResizeHandle onResize={handleSidebarResize} direction="left" />
            <div
              className="shrink-0 overflow-hidden"
              style={{ width: sidebarWidth }}
            >
              <AISidebar
                documentId={tabs.find(t => t.id === activeTabId)?.documentId}
                documentName={tabs.find(t => t.id === activeTabId)?.title}
              />
            </div>
          </>
        )}
      </div>

      {/* 预览模态框 */}
      {previewDoc && (
        <DocumentPreviewModal
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
        />
      )}
    </div>
  )
}
