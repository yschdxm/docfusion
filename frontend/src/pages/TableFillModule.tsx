import { useState, useCallback, useEffect, useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Loader2, Download, Table, Play, CheckCircle, Plus, Clock, XCircle, List, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

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
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedSourceDocs, setSelectedSourceDocs] = useState<string[]>([])
  const [selectedTemplateDoc, setSelectedTemplateDoc] = useState<string | null>(null)
  const [instruction, setInstruction] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [tasks, setTasks] = useState<FillTask[]>([])
  const [activeTab, setActiveTab] = useState<'fill' | 'queue'>('queue')
  const [isLoadingTasks, setIsLoadingTasks] = useState(false)
  
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const isMountedRef = useRef(true)

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')

  // 加载任务
  const loadTasks = useCallback(async (silent = false) => {
    if (!isMountedRef.current) return
    if (!silent) setIsLoadingTasks(true)
    try {
      const response = await api.get('/table-fill/tasks')
      if (isMountedRef.current) {
        setTasks(response.data || [])
      }
    } catch (error) {
      if (!silent) console.error('Failed to load tasks:', error)
    } finally {
      if (!silent && isMountedRef.current) {
        setIsLoadingTasks(false)
      }
    }
  }, [])

  // 启动轮询
  const startPolling = useCallback(() => {
    if (pollingRef.current) return
    
    pollingRef.current = setInterval(() => {
      if (isMountedRef.current) {
        loadTasks(true)
      }
    }, 2000)
  }, [loadTasks])

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    fetchDocuments()
    loadTasks()
    startPolling()
    
    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 检查是否有处理中的任务
  useEffect(() => {
    const hasActiveTasks = tasks.some(t => t.status === 'processing' || t.status === 'pending')
    if (hasActiveTasks && !pollingRef.current) {
      startPolling()
    }
  }, [tasks, startPolling])

  const onSourceDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      toast.success(`上传了 ${acceptedFiles.length} 个源文档`)
    } catch {
      toast.error('上传失败')
    }
  }, [addDocuments])

  const onTemplateDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'template')
      toast.success(`上传了 ${acceptedFiles.length} 个模板文件`)
    } catch {
      toast.error('上传失败')
    }
  }, [addDocuments])

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

  const toggleSourceDoc = (docId: string) => {
    setSelectedSourceDocs((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    )
  }

  const handleFill = async () => {
    if (!selectedTemplateDoc || selectedSourceDocs.length === 0) {
      toast.error('请选择源文档和模板')
      return
    }

    const templateDoc = templateDocs.find(d => d.id === selectedTemplateDoc)
    const sourceNames = selectedSourceDocs.map(id => sourceDocs.find(d => d.id === id)?.original_filename || '')

    const newTaskId = `temp-${Date.now()}`
    
    // 立即添加任务到队列
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
    
    setTasks(prev => [newTask, ...prev])
    setActiveTab('queue')
    startPolling()

    setIsProcessing(true)
    try {
      const response = await api.post('/table-fill/fill', {
        source_file_ids: selectedSourceDocs,
        template_file_id: selectedTemplateDoc,
        user_instruction: instruction || '帮我智能填表',
      })

      setTasks(prev => prev.map(t => 
        t.id === newTaskId 
          ? { 
              ...t, 
              id: response.data.task_id,
              status: 'completed', 
              filled_file_id: response.data.filled_file_id,
              filled_file_url: response.data.filled_file_url,
              progress: '100%',
              current_step: '完成',
              completed_at: new Date().toISOString() 
            }
          : t
      ))

      toast.success('表格填写完成！')
      setSelectedSourceDocs([])
      setSelectedTemplateDoc(null)
      setInstruction('')
      
      await loadTasks()
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || error.message || '填写失败'
      
      setTasks(prev => prev.map(t => 
        t.id === newTaskId 
          ? { 
              ...t, 
              status: 'failed', 
              error: errorMsg,
              progress: '100%',
              current_step: `失败: ${errorMsg}`,
              completed_at: new Date().toISOString() 
            }
          : t
      ))
      toast.error(errorMsg)
    } finally {
      setIsProcessing(false)
    }
  }

  const handleDownload = (url: string) => {
    window.open(url, '_blank')
  }

  const statusConfig = {
    pending: { icon: Clock, color: 'text-yellow-400', bg: 'bg-yellow-500/20', label: '等待中' },
    processing: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-500/20', label: '处理中' },
    completed: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/20', label: '已完成' },
    failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/20', label: '失败' },
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          {/* 源文档区域 */}
          <div className="glass p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-white flex items-center gap-2">
                <FileText className="w-5 h-5 text-blue-400" />
                源文档（数据来源）
              </h3>
              <span className="text-sm text-slate-400">共 {sourceDocs.length} 个</span>
            </div>
            
            <div
              {...getSourceRootProps()}
              className={`upload-zone mb-4 ${isSourceDragActive ? 'upload-zone-active' : ''}`}
            >
              <input {...getSourceInputProps()} />
              <div className="flex items-center justify-center gap-2">
                <Plus className="w-5 h-5 text-slate-400" />
                <span className="text-slate-400 text-sm">添加源文档</span>
              </div>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
              {sourceDocs.length > 0 ? sourceDocs.map((doc) => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all
                    ${selectedSourceDocs.includes(doc.id)
                      ? 'bg-blue-500/20 border border-blue-500/30'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedSourceDocs.includes(doc.id)}
                    onChange={() => toggleSourceDoc(doc.id)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-blue-500"
                  />
                  <FileText className="w-4 h-4 text-blue-400" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-white truncate block">{doc.original_filename}</span>
                    <span className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</span>
                  </div>
                </label>
              )) : (
                <p className="text-sm text-slate-500 text-center py-4">暂无源文档，请上传</p>
              )}
            </div>
          </div>

          {/* 模板区域 */}
          <div className="glass p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-white flex items-center gap-2">
                <Table className="w-5 h-5 text-green-400" />
                模板文件
              </h3>
              <span className="text-sm text-slate-400">共 {templateDocs.length} 个</span>
            </div>

            <div
              {...getTemplateRootProps()}
              className={`upload-zone mb-4 ${isTemplateDragActive ? 'upload-zone-active' : ''}`}
            >
              <input {...getTemplateInputProps()} />
              <div className="flex items-center justify-center gap-2">
                <Plus className="w-5 h-5 text-slate-400" />
                <span className="text-slate-400 text-sm">添加模板文件</span>
              </div>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
              {templateDocs.length > 0 ? templateDocs.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => setSelectedTemplateDoc(doc.id)}
                  className={`w-full text-left p-3 rounded-lg transition-all
                    ${selectedTemplateDoc === doc.id
                      ? 'bg-green-500/20 border border-green-500/30'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                    }`}
                >
                  <div className="flex items-center gap-2">
                    <Table className="w-4 h-4 text-green-400" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-white truncate block">{doc.original_filename}</span>
                      <span className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</span>
                    </div>
                    {selectedTemplateDoc === doc.id && (
                      <CheckCircle className="w-4 h-4 text-green-400" />
                    )}
                  </div>
                </button>
              )) : (
                <p className="text-sm text-slate-500 text-center py-4">暂无模板，请上传</p>
              )}
            </div>
          </div>

          {/* 填写指令 */}
          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">填写指令（可选）</h3>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="描述填写要求，例如：将所有数值数据填入对应的单元格中..."
              className="input min-h-[80px] resize-none"
            />
          </div>

          {/* 开始填写按钮 */}
          <button
            onClick={handleFill}
            disabled={isProcessing || !selectedTemplateDoc || selectedSourceDocs.length === 0}
            className="btn-primary w-full flex items-center justify-center gap-2 
                      disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isProcessing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                处理中...
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                开始填写 ({selectedSourceDocs.length} 个源文档 + 1 个模板)
              </>
            )}
          </button>

          {/* 任务队列摘要 */}
          <div className="glass p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-400">任务队列</h3>
              <button 
                onClick={() => loadTasks()} 
                disabled={isLoadingTasks}
                className="text-xs text-primary-400 hover:text-primary-300 flex items-center gap-1"
              >
                <RefreshCw className={`w-3 h-3 ${isLoadingTasks ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>
            <div className="space-y-2">
              {isLoadingTasks ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
                </div>
              ) : tasks.length > 0 ? (
                tasks.slice(0, 3).map((task) => {
                  const config = statusConfig[task.status]
                  const StatusIcon = config.icon
                  return (
                    <div key={task.id} className="flex items-center gap-2 p-2 rounded-lg bg-white/5">
                      <StatusIcon className={`w-4 h-4 ${config.color} ${task.status === 'processing' ? 'animate-spin' : ''}`} />
                      <span className="text-xs text-white truncate flex-1">{task.template_name}</span>
                      <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.color}`}>
                        {config.label}
                      </span>
                    </div>
                  )
                })
              ) : (
                <p className="text-xs text-slate-500 text-center py-2">暂无任务</p>
              )}
            </div>
          </div>
        </div>

        {/* 右侧结果/队列区域 */}
        <div>
          {/* 标签切换 */}
          <div className="flex gap-2 mb-4">
            <button
              onClick={() => { setActiveTab('queue'); loadTasks(); }}
              className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                ${activeTab === 'queue' ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
            >
              <List className="w-4 h-4" />
              任务队列 ({tasks.length})
            </button>
            <button
              onClick={() => setActiveTab('fill')}
              className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                ${activeTab === 'fill' ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
            >
              <Table className="w-4 h-4" />
              填写结果
            </button>
          </div>

          {activeTab === 'queue' ? (
            <div className="glass">
              <div className="p-4 border-b border-white/10">
                <h3 className="font-medium text-white">任务队列</h3>
              </div>

              <div className="max-h-[500px] overflow-y-auto scrollbar-thin">
                {tasks.length > 0 ? (
                  <div className="divide-y divide-white/5">
                    {tasks.map((task) => {
                      const config = statusConfig[task.status]
                      const StatusIcon = config.icon
                      const progressNum = task.progress ? parseInt(task.progress) || 0 : 0
                      return (
                        <div key={task.id} className="p-4 hover:bg-white/5 transition-colors">
                          <div className="flex items-start gap-4">
                            <div className={`w-10 h-10 rounded-lg ${config.bg} flex items-center justify-center shrink-0`}>
                              <StatusIcon className={`w-5 h-5 ${config.color} ${task.status === 'processing' ? 'animate-spin' : ''}`} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.color}`}>
                                  {config.label}
                                </span>
                              </div>
                              <p className="text-sm text-white">模板: {task.template_name}</p>
                              <p className="text-xs text-slate-400 mt-1">
                                源文档: {task.source_names.join(', ')}
                              </p>
                              
                              {/* 进度条 */}
                              {(task.status === 'processing' || task.status === 'pending') && (
                                <div className="mt-2">
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-xs text-slate-400">{task.current_step || '处理中...'}</span>
                                    <span className="text-xs text-primary-400">{task.progress || '0%'}</span>
                                  </div>
                                  <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                                    <div 
                                      className="h-full bg-gradient-to-r from-primary-500 to-purple-500 transition-all duration-300"
                                      style={{ width: `${progressNum}%` }}
                                    />
                                  </div>
                                  {task.estimated_time && (
                                    <p className="text-xs text-slate-500 mt-1">预计剩余: {task.estimated_time}</p>
                                  )}
                                </div>
                              )}
                              
                              {task.error && (
                                <div className="mt-2 p-2 rounded-lg bg-red-500/10 border border-red-500/30">
                                  <p className="text-xs text-red-400">错误详情:</p>
                                  <p className="text-xs text-red-300 mt-1 break-words">{task.error}</p>
                                </div>
                              )}
                              <p className="text-xs text-slate-500 mt-2">
                                {new Date(task.created_at).toLocaleString()}
                              </p>
                            </div>
                            {task.status === 'completed' && task.filled_file_url && (
                              <button
                                onClick={() => handleDownload(task.filled_file_url!)}
                                className="px-3 py-1 text-xs rounded-lg bg-green-500/20 text-green-400 
                                          hover:bg-green-500/30 transition-colors flex items-center gap-1"
                              >
                                <Download className="w-3 h-3" />
                                下载
                              </button>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="p-12 text-center">
                    <List className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                    <p className="text-slate-400">暂无任务</p>
                    <p className="text-sm text-slate-500 mt-2">
                      选择源文档和模板并点击"开始填写"创建新任务
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="glass">
              <div className="p-4 border-b border-white/10">
                <h3 className="font-medium text-white">填写结果</h3>
              </div>

              <div className="p-4 min-h-[500px] flex flex-col items-center justify-center">
                {isProcessing ? (
                  <div className="text-center">
                    <Loader2 className="w-12 h-12 animate-spin text-primary-400 mx-auto mb-4" />
                    <p className="text-slate-400">正在分析文档并填写表格...</p>
                    <p className="text-sm text-slate-500 mt-2">这可能需要一些时间</p>
                  </div>
                ) : tasks.filter(t => t.status === 'completed').length > 0 ? (
                  <div className="w-full space-y-4">
                    {tasks.filter(t => t.status === 'completed').slice(0, 1).map((task) => (
                      <div key={task.id} className="space-y-4">
                        <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30">
                          <div className="flex items-center gap-3">
                            <CheckCircle className="w-6 h-6 text-green-400" />
                            <div>
                              <p className="font-medium text-white">填写完成</p>
                              <p className="text-sm text-slate-400">{task.template_name}</p>
                            </div>
                          </div>
                        </div>

                        {task.filled_file_url && (
                          <button
                            onClick={() => handleDownload(task.filled_file_url!)}
                            className="btn-secondary w-full flex items-center justify-center gap-2"
                          >
                            <Download className="w-5 h-5" />
                            下载填写后的文件
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center">
                    <Table className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                    <p className="text-slate-400">选择源文档和模板后开始填写</p>
                    <p className="text-sm text-slate-500 mt-2">
                      左侧分别上传源文档和模板，然后选择要使用的文件
                    </p>
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
