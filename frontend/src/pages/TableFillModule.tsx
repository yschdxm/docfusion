import { useState, useEffect, useRef } from 'react'
import { FileText, Loader2, Download, Table, Play, CheckCircle, Clock, XCircle, List, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'

interface FillTask {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  source_files: string[]
  source_names: string[]
  template_name: string
  filled_file_id?: string
  filled_file_url?: string
  progress?: string
  current_step?: string
  estimated_time?: string
  created_at: string
  completed_at?: string
  error?: string
}

export default function TableFillModule() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments } = useDocumentStore()
  const [selectedSourceDocs, setSelectedSourceDocs] = useState<string[]>([])
  const [selectedTemplateDoc, setSelectedTemplateDoc] = useState<string | null>(null)
  const [instruction, setInstruction] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [tasks, setTasks] = useState<FillTask[]>([])
  const [activeTab, setActiveTab] = useState<'fill' | 'queue'>('queue')
  const [extractedDocIds, setExtractedDocIds] = useState<Set<string>>(new Set())

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isMountedRef = useRef(true)

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')

  const notifyBell = (title: string, message: string) => {
    window.dispatchEvent(
      new CustomEvent('app-notify', {
        detail: { title, message },
      })
    )
  }

  const loadExtractedDocs = async () => {
    try {
      const response = await api.get('/extraction/tasks')
      const extractionTasks = response.data || []
      const extractedIds = new Set<string>()

      for (const task of extractionTasks) {
        if (task.status === 'completed' && task.file_ids) {
          task.file_ids.forEach((id: string) => extractedIds.add(id))
        }
      }

      if (isMountedRef.current) {
        setExtractedDocIds(extractedIds)
      }
    } catch (error) {
      console.error('Failed to load extracted docs:', error)
    }
  }

  const loadTasks = async (silent = false) => {
    if (!isMountedRef.current) return
    try {
      const response = await api.get('/table-fill/tasks')
      if (isMountedRef.current) {
        setTasks(response.data || [])
      }
    } catch (error) {
      if (!silent) console.error('Failed to load tasks:', error)
    }
  }

  const startPolling = () => {
    if (pollingRef.current) return
    pollingRef.current = setInterval(() => {
      if (isMountedRef.current) {
        loadTasks(true)
      }
    }, 2000)
  }

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  useEffect(() => {
    isMountedRef.current = true
    fetchDocuments()
    loadTasks()
    loadExtractedDocs()
    startPolling()

    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, [])

  useEffect(() => {
    const hasActiveTasks = tasks.some((t) => t.status === 'processing' || t.status === 'pending')
    if (hasActiveTasks && !pollingRef.current) {
      startPolling()
    }
  }, [tasks])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadExtractedDocs()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  const toggleSourceDoc = (docId: string) => {
    if (!extractedDocIds.has(docId)) {
      toast.error(tr('该文档尚未完成信息提取，请先在“信息提取”流程中处理。', 'This document has not finished extraction yet.', 'この文書は抽出処理が未完了です。'))
      return
    }

    setSelectedSourceDocs((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }

  const handleFill = async () => {
    if (!selectedTemplateDoc || selectedSourceDocs.length === 0) {
      toast.error(tr('请选择源文档和模板', 'Please select source documents and a template', 'ソース文書とテンプレートを選択してください'))
      return
    }

    const unextractedDocs = selectedSourceDocs.filter((id) => !extractedDocIds.has(id))
    if (unextractedDocs.length > 0) {
      const unextractedNames = unextractedDocs.map((id) => sourceDocs.find((d) => d.id === id)?.original_filename || '未知').join(', ')
      toast.error(tr(`以下文档尚未完成提取：${unextractedNames}`, `Extraction not finished: ${unextractedNames}`, `抽出未完了: ${unextractedNames}`))
      return
    }

    const templateDoc = templateDocs.find((d) => d.id === selectedTemplateDoc)
    const sourceNames = selectedSourceDocs.map((id) => sourceDocs.find((d) => d.id === id)?.original_filename || '')

    const newTaskId = `temp-${Date.now()}`
    const newTask: FillTask = {
      id: newTaskId,
      status: 'processing',
      source_files: selectedSourceDocs,
      source_names: sourceNames,
      template_name: templateDoc?.original_filename || '',
      progress: '0%',
      current_step: '准备中...',
      created_at: new Date().toISOString(),
    }

    setTasks((prev) => [newTask, ...prev])
    setActiveTab('queue')
    startPolling()

    setIsProcessing(true)
    try {
      const response = await api.post('/table-fill/fill', {
        source_file_ids: selectedSourceDocs,
        template_file_id: selectedTemplateDoc,
        user_instruction: instruction || tr('请根据源文档智能填写模板', 'Please fill the template based on source documents', 'ソース文書に基づいてテンプレートを入力してください'),
      })

      setTasks((prev) =>
        prev.map((t) =>
          t.id === newTaskId
            ? {
                ...t,
                id: response.data.task_id,
                status: 'completed',
                filled_file_id: response.data.filled_file_id,
                filled_file_url: response.data.filled_file_url,
                progress: '100%',
                current_step: '完成',
                completed_at: new Date().toISOString(),
              }
            : t
        )
      )

      toast.success(tr('表格填写完成', 'Table fill completed', '表入力が完了しました'))
      notifyBell(
        tr('表格填写完成', 'Table fill completed', '表入力が完了しました'),
        `${tr('模板', 'Template', 'テンプレート')}: ${templateDoc?.original_filename || '-'}`
      )
      setSelectedSourceDocs([])
      setSelectedTemplateDoc(null)
      setInstruction('')
      await loadTasks()
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || error.message || tr('填写失败', 'Fill failed', '入力に失敗しました')
      setTasks((prev) =>
        prev.map((t) =>
          t.id === newTaskId
            ? {
                ...t,
                status: 'failed',
                error: errorMsg,
                progress: '100%',
                current_step: `失败: ${errorMsg}`,
                completed_at: new Date().toISOString(),
              }
            : t
        )
      )
      toast.error(errorMsg)
      notifyBell(
        tr('表格填写失败', 'Table fill failed', '表入力に失敗しました'),
        errorMsg
      )
    } finally {
      setIsProcessing(false)
    }
  }

  const handleDownload = (url: string) => {
    window.open(url, '_blank')
  }

  const statusConfig = {
    pending: { icon: Clock, color: 'text-amber-600', bg: 'bg-amber-100', badge: 'status-pending', label: tr('等待中', 'Pending', '待機中') },
    processing: { icon: Loader2, color: 'text-blue-600', bg: 'bg-blue-100', badge: 'status-processing', label: tr('处理中', 'Processing', '処理中') },
    completed: { icon: CheckCircle, color: 'text-emerald-600', bg: 'bg-emerald-100', badge: 'status-completed', label: tr('已完成', 'Completed', '完了') },
    failed: { icon: XCircle, color: 'text-rose-600', bg: 'bg-rose-100', badge: 'status-failed', label: tr('失败', 'Failed', '失敗') },
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div className="glass p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-slate-900 flex items-center gap-2">
                <FileText className="w-5 h-5 text-blue-500" />
                {tr('源文档（数据来源）', 'Source Documents (Data Source)', 'ソース文書（データソース）')}
              </h3>
              <div className="flex items-center gap-2">
                <button onClick={loadExtractedDocs} className="text-xs text-primary-500 hover:text-primary-600 flex items-center gap-1">
                  <RefreshCw className="w-3 h-3" />
                  {tr('刷新状态', 'Refresh status', '状態を更新')}
                </button>
                <span className="text-sm text-slate-500">{tr('共', 'Total', '合計')} {sourceDocs.length} {tr('个', '', '件')}</span>
              </div>
            </div>

            <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-thin">
              {sourceDocs.length > 0 ? (
                sourceDocs.map((doc) => {
                  const isExtracted = extractedDocIds.has(doc.id)
                  return (
                    <div
                      key={doc.id}
                      onClick={() => toggleSourceDoc(doc.id)}
                      className={`flex items-center gap-3 p-2.5 rounded-lg transition-all ${
                        !isExtracted
                          ? 'opacity-50 cursor-not-allowed bg-slate-50'
                          : selectedSourceDocs.includes(doc.id)
                            ? 'bg-blue-50 border border-blue-200 cursor-pointer'
                            : 'bg-slate-50 hover:bg-white border border-transparent cursor-pointer'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedSourceDocs.includes(doc.id)}
                        disabled={!isExtracted}
                        onChange={() => toggleSourceDoc(doc.id)}
                        className="w-4 h-4 rounded border-slate-300 bg-white text-blue-500 disabled:opacity-50"
                      />
                      <FileText className={`w-4 h-4 ${isExtracted ? 'text-blue-500' : 'text-slate-400'}`} />
                      <div className="flex-1 min-w-0">
                        <span className={`text-sm truncate block ${isExtracted ? 'text-slate-900' : 'text-slate-500'}`}>{doc.original_filename}</span>
                        <span className="text-xs text-slate-500">
                          {doc.file_type.toUpperCase()}
                          {!isExtracted && tr(' - 未提取', ' - Not extracted', ' - 未抽出')}
                        </span>
                      </div>
                      {!isExtracted && <span className="status-badge status-pending">{tr('需提取', 'Need extraction', '抽出が必要')}</span>}
                    </div>
                  )
                })
              ) : (
                <p className="text-sm text-slate-500 text-center py-4">{tr('暂无源文档，请先在文档管理中上传', 'No source docs. Upload in Document Manager first.', 'ソース文書がありません。先に文書管理でアップロードしてください。')}</p>
              )}
            </div>

            <div className="mt-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
              <p className="text-xs text-yellow-700">{tr('提示：请先确保源文档完成信息提取，再执行模板填写。', 'Tip: ensure extraction is completed before filling templates.', 'ヒント: テンプレート入力前に抽出完了を確認してください。')}</p>
            </div>
          </div>

          <div className="glass p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-slate-900 flex items-center gap-2">
                <Table className="w-5 h-5 text-green-500" />
                {tr('模板文件', 'Template Files', 'テンプレートファイル')}
              </h3>
              <span className="text-sm text-slate-500">{tr('共', 'Total', '合計')} {templateDocs.length} {tr('个', '', '件')}</span>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
              {templateDocs.length > 0 ? (
                templateDocs.map((doc) => (
                  <button
                    key={doc.id}
                    onClick={() => setSelectedTemplateDoc(doc.id)}
                    className={`w-full text-left p-2.5 rounded-lg transition-all ${
                      selectedTemplateDoc === doc.id
                        ? 'bg-emerald-50 border border-emerald-200'
                        : 'bg-slate-50 hover:bg-white border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Table className="w-4 h-4 text-green-500" />
                      <div className="flex-1 min-w-0">
                        <span className="text-sm text-slate-900 truncate block">{doc.original_filename}</span>
                        <span className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</span>
                      </div>
                      {selectedTemplateDoc === doc.id && <CheckCircle className="w-4 h-4 text-green-500" />}
                    </div>
                  </button>
                ))
              ) : (
                <p className="text-sm text-slate-500 text-center py-4">{tr('暂无模板，请先在文档管理中上传', 'No templates. Upload in Document Manager first.', 'テンプレートがありません。先に文書管理でアップロードしてください。')}</p>
              )}
            </div>
          </div>

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-500 mb-3">{tr('填写指令（可选）', 'Fill Instruction (Optional)', '入力指示（任意）')}</h3>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder={tr('描述你的填写要求，例如：按字段优先级填充，空值保留。', 'Describe your fill requirements, e.g. field priority and keeping empty values.', '入力要件を記述してください。例: フィールド優先、空値は保持。')}
              className="input min-h-[80px] resize-none"
            />
          </div>

          <button
            onClick={handleFill}
            disabled={isProcessing || !selectedTemplateDoc || selectedSourceDocs.length === 0}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isProcessing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {tr('处理中...', 'Processing...', '処理中...')}
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                {tr('开始填写', 'Start Filling', '入力開始')}（{selectedSourceDocs.length} {tr('个源文档', 'source docs', '件のソース文書')} + 1 {tr('个模板', 'template', '件のテンプレート')}）
              </>
            )}
          </button>
        </div>

        <div>
          <div className="flex gap-2 mb-4">
            <button
              onClick={() => {
                setActiveTab('queue')
                loadTasks()
              }}
              className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                activeTab === 'queue'
                  ? 'bg-white text-slate-900 border border-slate-300 shadow-sm'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-50'
              }`}
            >
              <List className="w-4 h-4" />
              {tr('任务队列', 'Task Queue', 'タスクキュー')} ({tasks.length})
            </button>
            <button
              onClick={() => setActiveTab('fill')}
              className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                activeTab === 'fill'
                  ? 'bg-white text-slate-900 border border-slate-300 shadow-sm'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-50'
              }`}
            >
              <Table className="w-4 h-4" />
              {tr('填写结果', 'Fill Results', '入力結果')}
            </button>
          </div>

          {activeTab === 'queue' ? (
            <div className="glass">
              <div className="p-4 border-b border-slate-200">
                <h3 className="font-medium text-slate-900">{tr('任务队列', 'Task Queue', 'タスクキュー')}</h3>
              </div>

              <div className="max-h-[500px] overflow-y-auto scrollbar-thin">
                {tasks.length > 0 ? (
                  <div className="divide-y divide-slate-100">
                    {tasks.map((task) => {
                      const config = statusConfig[task.status]
                      const StatusIcon = config.icon
                      const progressNum = task.progress ? parseInt(task.progress) || 0 : 0
                      return (
                        <div key={task.id} className="p-3 hover:bg-slate-50 transition-colors">
                          <div className="flex items-start gap-4">
                            <div className={`w-8 h-8 rounded-md ${config.bg} flex items-center justify-center shrink-0`}>
                              <StatusIcon className={`w-4 h-4 ${config.color} ${task.status === 'processing' ? 'animate-spin' : ''}`} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`status-badge ${config.badge}`}>{config.label}</span>
                              </div>
                              <p className="text-sm text-slate-900">{tr('模板', 'Template', 'テンプレート')}: {task.template_name}</p>
                              <p className="text-xs text-slate-500 mt-1">{tr('源文档', 'Source docs', 'ソース文書')}: {task.source_names.join(', ')}</p>

                              {(task.status === 'processing' || task.status === 'pending') && (
                                <div className="mt-2">
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-xs text-slate-500">{task.current_step || tr('处理中...', 'Processing...', '処理中...')}</span>
                                    <span className="text-xs text-blue-700">{task.progress || '0%'}</span>
                                  </div>
                                  <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
                                    <div className="h-full bg-gradient-to-r from-primary-500 to-blue-400 transition-all duration-300" style={{ width: `${progressNum}%` }} />
                                  </div>
                                  {task.estimated_time && <p className="text-xs text-slate-500 mt-1">{tr('预计剩余', 'ETA', '残り見込み')}: {task.estimated_time}</p>}
                                </div>
                              )}

                              {task.error && (
                                <div className="mt-2 p-2 rounded-lg bg-red-50 border border-red-200">
                                  <p className="text-xs text-red-700">{tr('错误详情', 'Error', 'エラー詳細')}:</p>
                                  <p className="text-xs text-red-600 mt-1 break-words">{task.error}</p>
                                </div>
                              )}

                              <p className="text-xs text-slate-500 mt-2">{new Date(task.created_at).toLocaleString()}</p>
                            </div>
                            {task.status === 'completed' && task.filled_file_url && (
                              <button
                                onClick={() => handleDownload(task.filled_file_url!)}
                                className="btn-secondary px-2.5 py-1.5 text-xs text-emerald-700 border-emerald-300 hover:bg-emerald-50"
                              >
                                <Download className="w-3 h-3" />
                                {tr('下载', 'Download', 'ダウンロード')}
                              </button>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="p-12 text-center">
                    <List className="w-16 h-16 mx-auto mb-4 text-slate-400" />
                    <p className="text-slate-600">{tr('暂无任务', 'No tasks yet', 'タスクがありません')}</p>
                    <p className="text-sm text-slate-500 mt-2">{tr('选择源文档和模板后点击“开始填写”即可创建任务。', 'Select source docs and a template, then click Start Filling.', 'ソース文書とテンプレートを選択して「入力開始」をクリックしてください。')}</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="glass">
              <div className="p-4 border-b border-slate-200">
                <h3 className="font-medium text-slate-900">{tr('填写结果', 'Fill Results', '入力結果')}</h3>
              </div>

              <div className="p-4 min-h-[500px] flex flex-col items-center justify-center">
                {isProcessing ? (
                  <div className="text-center">
                    <Loader2 className="w-12 h-12 animate-spin text-primary-500 mx-auto mb-4" />
                    <p className="text-slate-500">{tr('正在分析文档并填写模板...', 'Analyzing docs and filling template...', '文書を解析してテンプレート入力中...')}</p>
                  </div>
                ) : tasks.filter((t) => t.status === 'completed').length > 0 ? (
                  <div className="w-full space-y-4">
                    {tasks
                      .filter((t) => t.status === 'completed')
                      .slice(0, 1)
                      .map((task) => (
                        <div key={task.id} className="space-y-4">
                          <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30">
                            <div className="flex items-center gap-3">
                              <CheckCircle className="w-6 h-6 text-green-500" />
                              <div>
                                <p className="font-medium text-slate-900">{tr('填写完成', 'Fill completed', '入力完了')}</p>
                                <p className="text-sm text-slate-500">{task.template_name}</p>
                              </div>
                            </div>
                          </div>

                          {task.filled_file_url && (
                            <button onClick={() => handleDownload(task.filled_file_url!)} className="btn-secondary w-full flex items-center justify-center gap-2">
                              <Download className="w-5 h-5" />
                              {tr('下载填写后的文件', 'Download Filled File', '入力済みファイルをダウンロード')}
                            </button>
                          )}
                        </div>
                      ))}
                  </div>
                ) : (
                  <div className="text-center">
                    <Table className="w-16 h-16 mx-auto mb-4 text-slate-400" />
                    <p className="text-slate-600">{tr('选择源文档和模板后开始填写', 'Select source docs and template to start filling', 'ソース文書とテンプレートを選択して入力を開始')}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

