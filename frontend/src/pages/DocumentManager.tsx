import { useCallback, useEffect, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  FileText,
  Filter,
  FolderOpen,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Table,
  Trash2,
  Undo2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Dropdown from '../components/ui/Dropdown'
import api from '../services/api'
import { getAuthUser, isAdmin } from '../services/auth'
import { useDocumentStore, type DocumentInfo, type DocumentVersion } from '../stores/documentStore'

// 判断当前用户是否可以编辑/删除文档
const canEditDoc = (doc: DocumentInfo): boolean => {
  const user = getAuthUser()
  if (!user) return false
  if (isAdmin()) return true
  return doc.user_id === user.id
}
import { useI18n } from '../hooks/useI18n'
import DocumentPreviewModal from '../components/DocumentPreviewModal'

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

export default function DocumentManager() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments, addDocuments, deleteDocument, uploadProgress, fetchVersions, rollbackDocument, deleteVersion } = useDocumentStore()
  const [filter, setFilter] = useState<CategoryFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [previewDoc, setPreviewDoc] = useState<DocumentInfo | null>(null)
  const [previewViewOnly, setPreviewViewOnly] = useState(false)
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null)
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const sseSourcesRef = useRef<Record<string, EventSource>>({})
  const pendingDeleteTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const isMountedRef = useRef(true)
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

  useEffect(() => {
    isMountedRef.current = true
    fetchDocuments()

    return () => {
      isMountedRef.current = false
      closeAllSSEConnections()
    }
  }, [fetchDocuments])

  const closeAllSSEConnections = useCallback(() => {
    Object.values(sseSourcesRef.current).forEach((source) => {
      source.close()
    })
    sseSourcesRef.current = {}
  }, [])

  const startSSEForDoc = useCallback((docId: string) => {
    // 如果已有连接，不重复创建
    if (sseSourcesRef.current[docId]) return

    const baseUrl = api.defaults.baseURL || '/api/v1'
    const url = `${baseUrl}/documents/${docId}/progress-stream`

    const eventSource = new EventSource(url)
    sseSourcesRef.current[docId] = eventSource

    eventSource.onmessage = (event) => {
      if (!isMountedRef.current) return

      try {
        const data = JSON.parse(event.data)

        // 更新文档列表中的提取状态
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

        // 任务完成或失败时关闭连接
        if (data.status === 'completed' || data.status === 'failed') {
          eventSource.close()
          delete sseSourcesRef.current[docId]
          // 最终刷新一次确保数据一致
          fetchDocuments()
        }
      } catch (e) {
        // 忽略解析错误
      }
    }

    // 监听 done 事件（服务器通知任务结束）
    eventSource.addEventListener('done', () => {
      eventSource.close()
      delete sseSourcesRef.current[docId]
      if (isMountedRef.current) {
        fetchDocuments()
      }
    })

    eventSource.onerror = () => {
      // SSE 连接错误时，静默关闭连接并刷新文档状态
      eventSource.close()
      delete sseSourcesRef.current[docId]
      // 刷新文档列表获取最新状态
      if (isMountedRef.current) {
        fetchDocuments()
      }
    }
  }, [fetchDocuments])

  // 监听文档列表变化，为处理中的文档启动 SSE
  useEffect(() => {
    const processingDocs = documents.filter(
      (doc) => doc.doc_category === 'source' && (doc.extraction_status?.status === 'processing' || doc.extraction_status?.status === 'queued')
    )

    // 为处理中的文档启动 SSE
    processingDocs.forEach((doc) => {
      if (!sseSourcesRef.current[doc.id]) {
        startSSEForDoc(doc.id)
      }
    })

    // 清理已不存在的文档的 SSE 连接
    const docIds = new Set(documents.map((d) => d.id))
    Object.keys(sseSourcesRef.current).forEach((id) => {
      if (!docIds.has(id)) {
        sseSourcesRef.current[id].close()
        delete sseSourcesRef.current[id]
      }
    })
  }, [documents, startSSEForDoc])

  const openPreview = (doc: DocumentInfo, viewOnly = false) => {
    setPreviewViewOnly(viewOnly)
    setPreviewDoc(doc)
  }

  const toggleVersions = async (doc: DocumentInfo) => {
    if (expandedDocId === doc.id) {
      setExpandedDocId(null)
      setVersions([])
      return
    }
    setExpandedDocId(doc.id)
    setVersions([])
    setVersionsLoading(true)
    try {
      const list = await fetchVersions(doc.id)
      setVersions(list)
    } catch {
      toast.error(tr('版本列表加载失败', 'Failed to load versions', 'バージョン一覧の取得に失敗しました'))
    } finally {
      setVersionsLoading(false)
    }
  }

  const handleRollback = async (doc: DocumentInfo, v: DocumentVersion) => {
    try {
      await rollbackDocument(doc.id, v.id)
      toast.success(tr(`已回滚到 v${v.version}`, `Rolled back to v${v.version}`, `v${v.version} にロールバックしました`))
      const list = await fetchVersions(doc.id)
      setVersions(list)
      fetchDocuments()
    } catch {
      toast.error(tr('回滚失败', 'Rollback failed', 'ロールバックに失敗しました'))
    }
  }

  const handleDeleteVersion = async (doc: DocumentInfo, v: DocumentVersion) => {
    if (!window.confirm(tr(`确定删除版本 v${v.version} 吗？`, `Delete version v${v.version}?`, `バージョン v${v.version} を削除しますか？`))) return
    try {
      await deleteVersion(doc.id, v.id)
      toast.success(tr('版本已删除', 'Version deleted', 'バージョンを削除しました'))
      const list = await fetchVersions(doc.id)
      setVersions(list)
      fetchDocuments()
    } catch {
      toast.error(tr('删除版本失败', 'Failed to delete version', 'バージョンの削除に失敗しました'))
    }
  }

  const handleDownloadVersion = async (doc: DocumentInfo, v: DocumentVersion) => {
    await handleDownload({ ...doc, id: v.id, file_size: v.file_size, created_at: v.created_at })
  }

  const openVersionPreview = (doc: DocumentInfo, v: DocumentVersion) => {
    openPreview({ ...doc, id: v.id, file_size: v.file_size, created_at: v.created_at }, true)
  }

  const onSourceDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      const message = tr(`已上传 ${acceptedFiles.length} 个源文档，正在自动提取信息`, `Uploaded ${acceptedFiles.length} source docs, extraction started`, `${acceptedFiles.length} 件のソース文書をアップロードし、抽出を開始しました`)
      toast.success(message)
      notifyBell(tr('上传成功', 'Upload succeeded', 'アップロード成功'), message)
      // 延迟刷新，等待后台任务创建
      setTimeout(() => fetchDocuments(), 500)
    } catch (error) {
      toast.error(tr('上传失败', 'Upload failed', 'アップロードに失敗しました'))
    }
  }

  const onTemplateDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'template')
      const message = tr(`已上传 ${acceptedFiles.length} 个模板`, `Uploaded ${acceptedFiles.length} templates`, `${acceptedFiles.length} 件のテンプレートをアップロードしました`)
      toast.success(message)
      notifyBell(tr('上传成功', 'Upload succeeded', 'アップロード成功'), message)
    } catch (error) {
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

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')
  const outputDocs = documents.filter((d) => d.doc_category === 'output')

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
      } catch (error) {
        toast.error(tr('删除失败', 'Delete failed', '削除に失敗しました'))
      } finally {
        clearPendingDeleteTimer(timerKey)
      }
    }, 4000)
    pendingDeleteTimersRef.current[timerKey] = timer

    toast.custom(
      (t) => (
        <div className="glass flex items-center gap-3 px-3 py-2 text-sm text-slate-700">
          <span>{tr(`“${docName}” 将在 4 秒后删除`, `"${docName}" will be deleted in 4s`, `「${docName}」は4秒後に削除されます`)}</span>
          <button
            className="btn-secondary px-2 py-1 text-xs"
            title={tr('撤销', 'Undo', '元に戻す')}
            onClick={() => {
              clearPendingDeleteTimer(timerKey)
              toast.dismiss(t.id)
            }}
          >
            <Undo2 className="h-3.5 w-3.5" />
            {tr('撤销', 'Undo', '元に戻す')}
          </button>
        </div>
      ),
      { duration: 4000 }
    )
  }

  const handleBatchDelete = async () => {
    if (selectedDocs.length === 0) {
      toast.error(tr('请先选择要删除的文档', 'Select documents to delete first', '先に削除対象の文書を選択してください'))
      return
    }
    // 只删除有权限的文档（自己的 + 管理员可删所有）
    const deletableIds = selectedDocs.filter(id => {
      const doc = documents.find(d => d.id === id)
      return doc && canEditDoc(doc)
    })
    if (deletableIds.length === 0) {
      toast.error(tr('选中的文档无删除权限', 'No permission to delete selected documents', '選択した文書の削除権限がありません'))
      return
    }
    if (!confirm(tr(`确认删除选中的 ${deletableIds.length} 个文档吗？`, `Delete ${deletableIds.length} selected documents?`, `選択した ${deletableIds.length} 件の文書を削除しますか？`))) return

    try {
      const deleting = [...deletableIds]
      for (const docId of deleting) {
        await deleteDocument(docId)
      }
      if (previewDoc && deleting.includes(previewDoc.id)) {
        setPreviewDoc(null)
      }
      setSelectedDocs([])
      const message = tr('批量删除成功', 'Batch delete completed', '一括削除が完了しました')
      toast.success(message)
      notifyBell(tr('删除成功', 'Delete succeeded', '削除成功'), `${deleting.length} ${tr('个文档已删除', 'documents deleted', '件の文書を削除しました')}`)
    } catch (error) {
      toast.error(tr('批量删除失败', 'Batch delete failed', '一括削除に失敗しました'))
    }
  }

  const handleDownload = async (doc: DocumentInfo) => {
    const downloadUrl = `/documents/${doc.id}/download`

    try {
      const response = await api.get(downloadUrl, { responseType: 'blob' })
      const contentDisposition = response.headers['content-disposition'] as string | undefined
      const filename = parseDownloadFilename(contentDisposition, doc.original_filename)
      const blob =
        response.data instanceof Blob
          ? response.data
          : new Blob([response.data], { type: (response.headers['content-type'] as string) || 'application/octet-stream' })

      triggerFileDownload(blob, filename)

      const message = tr('下载已开始', 'Download started', 'ダウンロードを開始しました')
      toast.success(message)
      notifyBell(tr('下载成功', 'Download succeeded', 'ダウンロード成功'), `${filename} · ${message}`)
    } catch (error) {
      toast.error(tr('下载失败', 'Download failed', 'ダウンロードに失敗しました'))
    }
  }

  const handleRetryExtraction = async (docId: string, docName: string) => {
    try {
      await api.post(`/documents/${docId}/retry-extraction`)
      toast.success(tr(`已重新开始提取 "${docName}"`, `Extraction restarted for "${docName}"`, `「${docName}」の抽出を再開しました`))
      setTimeout(() => {
        fetchDocuments()
      }, 300)
    } catch (error) {
      toast.error(tr('重试失败', 'Retry failed', '再試行に失敗しました'))
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
      return <span className="status-badge status-pending">{tr('待提取', 'Pending extraction', '抽出待ち')}</span>
    }

    if (status.status === 'queued') {
      return (
        <div className="flex items-center gap-2">
          <span className="status-badge status-pending">{tr('排队中', 'Queued', '待機中')}</span>
          <span className="text-xs text-slate-500">{status.current_step || tr('等待处理...', 'Waiting...', '処理待ち...')}</span>
        </div>
      )
    }

    if (status.status === 'processing') {
      const progressNum = parseInt(status.progress, 10) || 0
      return (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="status-badge status-processing">{tr('处理中', 'Processing', '処理中')}</span>
            <span className="text-xs text-blue-700">{progressNum}%</span>
          </div>
          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-blue-500 transition-all duration-300" style={{ width: `${progressNum}%` }} />
          </div>
        </div>
      )
    }

    if (status.status === 'completed') {
      return (
        <div className="flex items-center gap-1.5">
          <span className="status-badge status-completed">{tr('已完成', 'Completed', '完了')}</span>
          <CheckCircle className="h-3.5 w-3.5 text-emerald-600" />
        </div>
      )
    }

    if (status.status === 'failed') {
      const errorMsg = status.error || tr('提取失败', 'Extraction failed', '抽出に失敗しました')
      const shortError = errorMsg.length > 30 ? `${errorMsg.slice(0, 30)}...` : errorMsg
      return (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2" title={errorMsg}>
            <span className="status-badge status-failed">{tr('失败', 'Failed', '失敗')}</span>
            <span className="text-xs text-rose-700">{shortError}</span>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleRetryExtraction(doc.id, doc.original_filename)
            }}
            className="text-xs text-blue-700 hover:text-blue-800"
            title={tr('重新提取', 'Retry extraction', '再抽出')}
          >
            {tr('重新提取', 'Retry extraction', '再抽出')}
          </button>
        </div>
      )
    }

    return null
  }

  return (
    <div className="h-full flex flex-col gap-2 sm:gap-2.5 min-h-0">
      {/* 上传区域：手机端两按钮一行，桌面端并排卡片 */}
      <div className="shrink-0">
        {/* 手机端：紧凑双按钮 */}
        <div className="grid grid-cols-2 gap-2 md:hidden">
          <div {...getSourceRootProps()} className={`glass px-3 py-2.5 cursor-pointer transition-all ${isSourceDragActive ? 'ring-2 ring-blue-400' : ''}`}>
            <input {...getSourceInputProps()} />
            {uploadProgress !== null ? (
              <div className="flex flex-col items-center gap-1">
                <span className="text-[11px] text-blue-400">{tr('上传中...', 'Uploading...', '...')}</span>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
                  <div className="h-full rounded-full bg-blue-500 transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
                </div>
                <span className="text-[10px] text-slate-400">{uploadProgress}%</span>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-500/20 shrink-0">
                  <FileText className="h-3.5 w-3.5 text-blue-400" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-medium text-slate-900 truncate">{tr('上传源文档', 'Source Docs', 'ソース文書')}</p>
                  <p className="text-[10px] text-slate-400">docx xlsx md txt</p>
                </div>
                <Plus className="h-4 w-4 text-slate-400 shrink-0 ml-auto" />
              </div>
            )}
          </div>
          <div {...getTemplateRootProps()} className={`glass px-3 py-2.5 cursor-pointer transition-all ${isTemplateDragActive ? 'ring-2 ring-green-400' : ''}`}>
            <input {...getTemplateInputProps()} />
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-green-500/20 shrink-0">
                <Table className="h-3.5 w-3.5 text-green-400" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-900 truncate">{tr('上传模板', 'Templates', 'テンプレート')}</p>
                <p className="text-[10px] text-slate-400">docx xlsx</p>
              </div>
              <Plus className="h-4 w-4 text-slate-400 shrink-0 ml-auto" />
            </div>
          </div>
        </div>
        {/* 桌面端：完整卡片 */}
        <div className="hidden md:grid md:grid-cols-2 md:gap-3">
          <div className="glass p-4">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/20">
                <FileText className="h-4 w-4 text-blue-400" />
              </div>
              <div>
                <h3 className="text-sm font-medium text-slate-900">{tr('上传源文档', 'Upload Source Docs', 'ソース文書をアップロード')}</h3>
                <p className="text-xs text-slate-400">{tr('支持 docx、xlsx、md、txt', 'Supports docx, xlsx, md, txt', 'docx/xlsx/md/txt 対応')}</p>
              </div>
            </div>
            <div {...getSourceRootProps()} className={`upload-zone ${isSourceDragActive ? 'upload-zone-active' : ''}`}>
              <input {...getSourceInputProps()} />
              {uploadProgress !== null ? (
                <div className="flex flex-col items-center gap-2">
                  <span className="text-sm text-blue-400">{tr('上传中...', 'Uploading...', 'アップロード中...')}</span>
                  <div className="h-2 w-48 overflow-hidden rounded-full bg-slate-700">
                    <div className="h-full rounded-full bg-blue-500 transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
                  </div>
                  <span className="text-xs text-slate-400">{uploadProgress}%</span>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2">
                  <Plus className="h-4 w-4 text-slate-400" />
                  <span className="text-sm text-slate-400">{tr('点击或拖拽上传源文档', 'Click or drag to upload source docs', 'クリックまたはドラッグしてソース文書をアップロード')}</span>
                </div>
              )}
            </div>
          </div>
          <div className="glass p-4">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-500/20">
                <Table className="h-4 w-4 text-green-400" />
              </div>
              <div>
                <h3 className="text-sm font-medium text-slate-900">{tr('上传模板', 'Upload Templates', 'テンプレートをアップロード')}</h3>
                <p className="text-xs text-slate-400">{tr('支持 docx、xlsx', 'Supports docx, xlsx', 'docx/xlsx 対応')}</p>
              </div>
            </div>
            <div {...getTemplateRootProps()} className={`upload-zone ${isTemplateDragActive ? 'upload-zone-active' : ''}`}>
              <input {...getTemplateInputProps()} />
              <div className="flex items-center justify-center gap-2">
                <Plus className="h-4 w-4 text-slate-400" />
                <span className="text-sm text-slate-400">{tr('点击或拖拽上传模板', 'Click or drag to upload templates', 'クリックまたはドラッグしてテンプレートをアップロード')}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 统计卡片：手机端 4 列紧凑行 */}
      <div className="grid grid-cols-4 gap-2 shrink-0">
        <div className={`glass card-hover-lift cursor-pointer px-2 py-2 transition-all ${filter === 'all' ? 'ring-2 ring-primary-500' : ''}`} onClick={() => setFilter('all')}>
          <div className="flex items-center gap-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-primary-500/20 shrink-0">
              <FileText className="h-3 w-3 text-primary-400" />
            </div>
            <div className="min-w-0">
              <p className="text-sm lg:text-base font-bold text-slate-900 leading-tight">{documents.length}</p>
              <p className="text-[9px] lg:text-[10px] text-slate-400 leading-tight">{tr('全部', 'All', 'すべて')}</p>
            </div>
          </div>
        </div>
        <div className={`glass card-hover-lift cursor-pointer px-2 py-2 transition-all ${filter === 'source' ? 'ring-2 ring-blue-500' : ''}`} onClick={() => setFilter('source')}>
          <div className="flex items-center gap-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-blue-500/20 shrink-0">
              <FileText className="h-3 w-3 text-blue-400" />
            </div>
            <div className="min-w-0">
              <p className="text-sm lg:text-base font-bold text-slate-900 leading-tight">{sourceDocs.length}</p>
              <p className="text-[9px] lg:text-[10px] text-slate-400 leading-tight">{tr('源文档', 'Source', 'ソース')}</p>
            </div>
          </div>
        </div>
        <div className={`glass card-hover-lift cursor-pointer px-2 py-2 transition-all ${filter === 'template' ? 'ring-2 ring-green-500' : ''}`} onClick={() => setFilter('template')}>
          <div className="flex items-center gap-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-green-500/20 shrink-0">
              <Table className="h-3 w-3 text-green-400" />
            </div>
            <div className="min-w-0">
              <p className="text-sm lg:text-base font-bold text-slate-900 leading-tight">{templateDocs.length}</p>
              <p className="text-[9px] lg:text-[10px] text-slate-400 leading-tight">{tr('模板', 'Template', 'テンプレート')}</p>
            </div>
          </div>
        </div>
        <div className={`glass card-hover-lift cursor-pointer px-2 py-2 transition-all ${filter === 'output' ? 'ring-2 ring-orange-500' : ''}`} onClick={() => setFilter('output')}>
          <div className="flex items-center gap-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-orange-500/20 shrink-0">
              <FolderOpen className="h-3 w-3 text-orange-400" />
            </div>
            <div className="min-w-0">
              <p className="text-sm lg:text-base font-bold text-slate-900 leading-tight">{outputDocs.length}</p>
              <p className="text-[9px] lg:text-[10px] text-slate-400 leading-tight">{tr('输出', 'Output', '出力')}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="glass flex flex-col min-h-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-slate-200 shrink-0">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <label className="flex cursor-pointer items-center gap-1.5 shrink-0">
              <input
                type="checkbox"
                checked={selectedDocs.length === filteredDocs.length && filteredDocs.length > 0}
                onChange={toggleSelectAll}
                className="h-3.5 w-3.5 rounded border-slate-300 bg-white text-primary-500"
              />
              <span className="text-[10px] text-slate-400 hidden sm:inline">{tr('全选', 'Select all', 'すべて選択')}</span>
            </label>
            <div className="relative flex-1 min-w-0 sm:max-w-xs">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder={tr('搜索文档...', 'Search documents...', 'ドキュメントを検索...')}
                className="input h-8 pl-8 text-xs"
              />
            </div>
            <Dropdown
              value={filter}
              onChange={(v) => setFilter(v as CategoryFilter)}
              options={[
                { value: 'all', label: tr('全部', 'All', 'すべて') },
                { value: 'source', label: tr('源文档', 'Source Docs', 'ソース文書') },
                { value: 'template', label: tr('模板', 'Templates', 'テンプレート') },
                { value: 'output', label: tr('输出', 'Output', '出力') },
              ]}
              icon={<Filter className="h-3.5 w-3.5 text-slate-400" />}
              className="hidden sm:block w-32"
            />
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button onClick={() => fetchDocuments()} className="btn-secondary p-1.5" title={tr('刷新', 'Refresh', '更新')}>
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            {selectedDocs.length > 0 && (
              <button onClick={handleBatchDelete} className="btn-secondary flex items-center gap-1 px-2 py-1 text-red-400 hover:text-red-300 text-[11px]" title={tr('批量删除', 'Batch Delete', '一括削除')}>
                <Trash2 className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{tr('删除', 'Delete', '削除')}</span>
                ({selectedDocs.length})
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
          {filteredDocs.length > 0 ? (
            filteredDocs.map((doc) => {
              const config = categoryConfig[doc.doc_category as keyof typeof categoryConfig] || categoryConfig.source
              const Icon = config.icon
              return (
                <div key={doc.id}>
                <div
                  className={`flex items-center gap-2 sm:gap-3 border-b border-slate-100 px-3 sm:px-4 py-2 sm:py-3 transition-colors hover:bg-slate-50 ${
                    selectedDocs.includes(doc.id) ? 'bg-primary-500/10' : ''
                  }`}
                >
                  {canEditDoc(doc) ? (
                    <input
                      type="checkbox"
                      checked={selectedDocs.includes(doc.id)}
                      onChange={() => toggleSelect(doc.id)}
                      className="h-3.5 w-3.5 rounded border-slate-300 bg-white text-primary-500 shrink-0"
                    />
                  ) : (
                    <div className="w-3.5 shrink-0" />
                  )}

                  <div className={`flex h-7 w-7 sm:h-9 sm:w-9 shrink-0 items-center justify-center rounded-md ${config.bg}`}>
                    <Icon className={`h-3.5 w-3.5 sm:h-4 sm:w-4 ${config.color}`} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="truncate text-xs sm:text-sm font-medium text-slate-900">{doc.original_filename}</p>
                      {(doc.version_count ?? 1) > 1 && (
                        <button
                          onClick={() => toggleVersions(doc)}
                          className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] sm:text-xs text-slate-600 hover:bg-slate-200 shrink-0"
                          title={tr('查看版本历史', 'View version history', 'バージョン履歴')}
                        >
                          v{doc.version ?? 1} / {doc.version_count}{tr('个版本', ' versions', '版')}
                          {expandedDocId === doc.id ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                        </button>
                      )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 sm:gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] sm:text-xs ${config.bg} ${config.color} hidden sm:inline`}>
                        {doc.doc_category === 'source'
                          ? tr('源文档', 'Source', 'ソース')
                          : doc.doc_category === 'template'
                            ? tr('模板', 'Template', 'テンプレート')
                            : tr('输出', 'Output', '出力')}
                      </span>
                      <span className="text-[10px] sm:text-xs text-slate-500 hidden sm:inline">{doc.file_type.toUpperCase()}</span>
                      <span className="text-[10px] sm:text-xs text-slate-500">{formatFileSize(doc.file_size)}</span>
                      <span className="text-[10px] sm:text-xs text-slate-500">{new Date(doc.created_at).toLocaleString(language, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                      {doc.doc_category === 'source' && (
                        <span className="md:hidden">{renderExtractionStatus(doc)}</span>
                      )}
                    </div>
                  </div>

                  {doc.doc_category === 'source' && <div className="hidden md:block w-56 shrink-0">{renderExtractionStatus(doc)}</div>}

                  <div className="flex items-center gap-0.5 sm:gap-1 shrink-0">
                    <button
                      onClick={() => openPreview(doc)}
                      aria-label={tr('预览文档', 'Preview document', '文書をプレビュー')}
                      className="rounded p-1.5 sm:p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-900"
                      title={tr('预览', 'Preview', 'プレビュー')}
                    >
                      <Eye className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                    </button>
                    <button onClick={() => handleDownload(doc)} aria-label={tr('下载文档', 'Download document', '文書をダウンロード')} title={tr('下载', 'Download', 'ダウンロード')} className="rounded p-1.5 sm:p-2 text-slate-400 transition-colors hover:bg-blue-500/20 hover:text-blue-400">
                      <Download className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                    </button>
                    {canEditDoc(doc) && (
                      <button
                        onClick={() => handleDelete(doc.id, doc.original_filename)}
                        aria-label={tr('删除文档', 'Delete document', '文書を削除')}
                        title={tr('删除', 'Delete', '削除')}
                        className="rounded p-1.5 sm:p-2 text-slate-400 transition-colors hover:bg-red-500/20 hover:text-red-400"
                      >
                        <Trash2 className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                      </button>
                    )}
                  </div>
                </div>

                {expandedDocId === doc.id && (
                  <div className="border-b border-slate-100 bg-slate-50/70 px-8 sm:px-14 py-1">
                    {versionsLoading ? (
                      <p className="py-2 text-[11px] text-slate-400">{tr('加载版本...', 'Loading versions...', 'バージョンを読み込み中...')}</p>
                    ) : (
                      versions.map((v) => (
                        <div key={v.id} className="flex items-center gap-2 border-b border-slate-100 last:border-0 py-1.5 text-[11px] sm:text-xs">
                          <span className={`rounded px-1.5 py-0.5 font-mono ${v.is_latest ? 'bg-primary-100 text-primary-700' : 'bg-slate-200 text-slate-600'}`}>
                            v{v.version}{v.is_latest ? ` ${tr('最新', 'latest', '最新')}` : ''}
                          </span>
                          <span className="text-slate-500">{v.origin_label || v.origin_type || '-'}</span>
                          <span className="text-slate-400 hidden sm:inline">{formatFileSize(v.file_size)}</span>
                          <span className="text-slate-400 hidden md:inline">{v.created_at ? new Date(v.created_at).toLocaleString(language, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}</span>
                          <div className="ml-auto flex items-center gap-0.5">
                            <button onClick={() => openVersionPreview(doc, v)} title={tr('预览', 'Preview', 'プレビュー')} className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-900">
                              <Eye className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => handleDownloadVersion(doc, v)} title={tr('下载', 'Download', 'ダウンロード')} className="rounded p-1 text-slate-400 hover:bg-blue-500/20 hover:text-blue-400">
                              <Download className="h-3.5 w-3.5" />
                            </button>
                            {!v.is_latest && canEditDoc(doc) && (
                              <>
                                <button onClick={() => handleRollback(doc, v)} title={tr('恢复到此版本', 'Restore this version', 'このバージョンに戻す')} className="rounded p-1 text-slate-400 hover:bg-emerald-500/20 hover:text-emerald-500">
                                  <RotateCcw className="h-3.5 w-3.5" />
                                </button>
                                <button onClick={() => handleDeleteVersion(doc, v)} title={tr('删除此版本', 'Delete this version', 'このバージョンを削除')} className="rounded p-1 text-slate-400 hover:bg-red-500/20 hover:text-red-400">
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
                </div>
              )
            })
          ) : (
            <div className="p-8 sm:p-12 text-center">
              <FileText className="mx-auto mb-3 h-10 w-10 sm:h-16 sm:w-16 text-slate-600" />
              <p className="text-xs sm:text-slate-400 text-slate-400">{searchTerm ? tr('没有匹配的文档', 'No matching documents', '一致する文書がありません') : tr('暂无文档', 'No documents', '文書がありません')}</p>
            </div>
          )}
        </div>
      </div>

      <DocumentPreviewModal doc={previewDoc} onClose={() => setPreviewDoc(null)} forceViewOnly={previewViewOnly} />
    </div>
  )
}







