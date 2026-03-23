import { useState, useCallback, useEffect, useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Loader2, Search, Filter, Database, Clock, CheckCircle, XCircle, List, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

interface Entity {
  entity_type: string
  entity_name: string
  entity_value: string
  context?: string
}

interface ExtractionTask {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  file_ids: string[]
  file_names: string[]
  entities_count: number
  progress?: string
  current_step?: string
  estimated_time?: string
  created_at: string
  completed_at?: string
  error?: string
}

export default function ExtractionModule() {
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('all')
  const [tasks, setTasks] = useState<ExtractionTask[]>([])
  const [activeTab, setActiveTab] = useState<'extract' | 'queue'>('queue')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [isLoadingTasks, setIsLoadingTasks] = useState(false)
  
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const isMountedRef = useRef(true)

  const sourceDocs = documents.filter(d => d.doc_category === 'source')

  // 加载任务
  const loadTasks = useCallback(async (silent = false) => {
    if (!isMountedRef.current) return
    if (!silent) setIsLoadingTasks(true)
    try {
      const response = await api.get('/extraction/tasks')
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
    if (pollingRef.current) return // 已经在轮询中
    
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

  // 检查是否有处理中的任务，决定是否需要轮询
  useEffect(() => {
    const hasActiveTasks = tasks.some(t => t.status === 'processing' || t.status === 'pending')
    if (hasActiveTasks && !pollingRef.current) {
      startPolling()
    }
  }, [tasks, startPolling])

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      toast.success(`成功上传 ${acceptedFiles.length} 个文件`)
    } catch (error) {
      toast.error('上传失败')
    }
  }, [addDocuments])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/markdown': ['.md'],
      'text/plain': ['.txt'],
    },
  })

  const toggleDocSelection = (docId: string) => {
    setSelectedDocs((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    )
  }

  const handleExtract = async () => {
    if (selectedDocs.length === 0) {
      toast.error('请选择至少一个文档')
      return
    }

    // 获取文件名
    const fileNames = selectedDocs.map(id => {
      const doc = sourceDocs.find(d => d.id === id)
      return doc?.original_filename || '未知文件'
    })

    // 创建临时任务ID
    const tempTaskId = `temp-${Date.now()}`
    
    // 立即添加任务到队列（在请求发送前）
    const newTask: ExtractionTask = {
      id: tempTaskId,
      status: 'processing',
      file_ids: selectedDocs,
      file_names: fileNames,
      entities_count: 0,
      progress: '0%',
      current_step: '准备中...',
      created_at: new Date().toISOString(),
    }
    
    // 确保任务被添加到队列
    setTasks(prev => [newTask, ...prev])
    setActiveTab('queue')
    
    // 确保轮询在运行
    startPolling()

    setIsLoading(true)
    try {
      const response = await api.post('/extraction/extract', {
        file_ids: selectedDocs,
        entity_types: ['PERSON', 'LOCATION', 'ORGANIZATION', 'DATE', 'NUMBER'],
      })
      
      const resultEntities = response.data.entities || []
      const realTaskId = response.data.task_id
      
      // 更新本地任务状态
      setTasks(prev => prev.map(t => 
        t.id === tempTaskId 
          ? { 
              ...t, 
              id: realTaskId,
              status: 'completed', 
              entities_count: resultEntities.length,
              progress: '100%',
              current_step: '完成',
              completed_at: new Date().toISOString()
            }
          : t
      ))
      
      setEntities(resultEntities)
      setSelectedTaskId(realTaskId)
      
      toast.success(`成功提取 ${resultEntities.length} 个实体`)
      setSelectedDocs([])
      
      // 刷新任务列表
      await loadTasks()
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || error.message || '提取失败'
      
      // 更新本地任务状态为失败
      setTasks(prev => prev.map(t => 
        t.id === tempTaskId 
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
      setIsLoading(false)
    }
  }

  const viewTaskResult = async (task: ExtractionTask) => {
    setSelectedTaskId(task.id)
    
    if (task.status === 'completed') {
      if (task.file_ids.length > 0) {
        try {
          const entitiesResponse = await api.get('/extraction/entities', {
            params: { document_id: task.file_ids[0], limit: 500 }
          })
          
          if (entitiesResponse.data && entitiesResponse.data.length > 0) {
            setEntities(entitiesResponse.data)
          } else {
            setEntities([])
            if (task.entities_count > 0) {
              toast('该任务提取的实体可能已过期，请重新提取', { icon: '⚠️' })
            }
          }
          setActiveTab('extract')
        } catch (error) {
          toast.error('加载结果失败')
        }
      }
    } else if (task.status === 'failed') {
      toast.error(`任务失败: ${task.error || '未知错误'}`, { duration: 5000 })
    } else if (task.status === 'processing') {
      toast('任务正在处理中，请稍后查看', { icon: '⏳' })
    }
  }

  const entityTypes = Array.from(new Set(entities.map((e) => e.entity_type)))

  const filteredEntities =
    entityTypeFilter === 'all'
      ? entities
      : entities.filter((e) => e.entity_type === entityTypeFilter)

  const entityTypeColors: Record<string, string> = {
    PERSON: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    LOCATION: 'bg-green-500/20 text-green-400 border-green-500/30',
    ORGANIZATION: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    DATE: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    NUMBER: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    TABLE_DATA: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
    CUSTOM: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  }

  const statusConfig = {
    pending: { icon: Clock, color: 'text-yellow-400', bg: 'bg-yellow-500/20', label: '等待中' },
    processing: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-500/20', label: '处理中' },
    completed: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/20', label: '已完成' },
    failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/20', label: '失败' },
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div
            {...getRootProps()}
            className={`upload-zone ${isDragActive ? 'upload-zone-active' : ''}`}
          >
            <input {...getInputProps()} />
            <div className="text-center">
              <Upload className="w-10 h-10 mx-auto mb-3 text-slate-400" />
              <p className="text-slate-400">批量上传文档</p>
              <p className="text-xs text-slate-500 mt-1">支持 docx, xlsx, md, txt</p>
            </div>
          </div>

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">选择要提取的文档</h3>
            <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-thin">
              {sourceDocs.map((doc) => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all
                    ${selectedDocs.includes(doc.id)
                      ? 'bg-primary-500/20 border border-primary-500/30'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleDocSelection(doc.id)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
                  />
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-white truncate">{doc.original_filename}</span>
                </label>
              ))}
              {sourceDocs.length === 0 && (
                <p className="text-sm text-slate-500 text-center py-4">请先上传文档</p>
              )}
            </div>
          </div>

          <button
            onClick={handleExtract}
            disabled={isLoading || selectedDocs.length === 0}
            className="btn-primary w-full flex items-center justify-center gap-2 
                      disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                提取中...
              </>
            ) : (
              <>
                <Search className="w-5 h-5" />
                开始提取 ({selectedDocs.length} 个文档)
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
                    <div 
                      key={task.id} 
                      className="flex items-center gap-2 p-2 rounded-lg bg-white/5 cursor-pointer hover:bg-white/10"
                      onClick={() => viewTaskResult(task)}
                    >
                      <StatusIcon className={`w-4 h-4 ${config.color} ${task.status === 'processing' ? 'animate-spin' : ''}`} />
                      <span className="text-xs text-white truncate flex-1">
                        {task.file_names.length > 0 ? task.file_names[0] : '加载中...'}
                      </span>
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

        <div className="lg:col-span-2">
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
              onClick={() => setActiveTab('extract')}
              className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                ${activeTab === 'extract' ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
            >
              <Database className="w-4 h-4" />
              提取结果
            </button>
          </div>

          {activeTab === 'queue' ? (
            <div className="glass">
              <div className="p-4 border-b border-white/10 flex items-center justify-between">
                <h3 className="font-medium text-white">任务队列</h3>
                <button 
                  onClick={() => loadTasks()} 
                  disabled={isLoadingTasks}
                  className="text-xs text-primary-400 hover:text-primary-300 flex items-center gap-1"
                >
                  <RefreshCw className={`w-3 h-3 ${isLoadingTasks ? 'animate-spin' : ''}`} />
                  刷新
                </button>
              </div>

              <div className="max-h-[500px] overflow-y-auto scrollbar-thin">
                {isLoadingTasks ? (
                  <div className="p-12 text-center">
                    <Loader2 className="w-8 h-8 animate-spin text-primary-400 mx-auto mb-4" />
                    <p className="text-slate-400">加载中...</p>
                  </div>
                ) : tasks.length > 0 ? (
                  <div className="divide-y divide-white/5">
                    {tasks.map((task) => {
                      const config = statusConfig[task.status]
                      const StatusIcon = config.icon
                      const isSelected = selectedTaskId === task.id
                      const progressNum = task.progress ? parseInt(task.progress) || 0 : 0
                      return (
                        <div 
                          key={task.id} 
                          className={`p-4 hover:bg-white/5 transition-colors cursor-pointer ${isSelected ? 'bg-primary-500/10' : ''}`}
                          onClick={() => viewTaskResult(task)}
                        >
                          <div className="flex items-start gap-4">
                            <div className={`w-10 h-10 rounded-lg ${config.bg} flex items-center justify-center shrink-0`}>
                              <StatusIcon className={`w-5 h-5 ${config.color} ${task.status === 'processing' ? 'animate-spin' : ''}`} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.color}`}>
                                  {config.label}
                                </span>
                                <span className="text-xs text-slate-500">
                                  {task.file_ids.length} 个文档
                                </span>
                              </div>
                              <p className="text-sm text-white truncate">
                                {task.file_names.length > 0 ? task.file_names.join(', ') : '加载中...'}
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
                              
                              {task.status === 'completed' && (
                                <p className="text-xs text-slate-400 mt-1">
                                  提取了 {task.entities_count} 个实体
                                </p>
                              )}
                              {task.error && (
                                <div className="mt-2 p-2 rounded-lg bg-red-500/10 border border-red-500/30">
                                  <p className="text-xs text-red-400">错误详情:</p>
                                  <p className="text-xs text-red-300 mt-1 break-words">{task.error}</p>
                                </div>
                              )}
                              <p className="text-xs text-slate-500 mt-2">
                                {new Date(task.created_at).toLocaleString()}
                                {task.completed_at && ` - ${new Date(task.completed_at).toLocaleString()}`}
                              </p>
                            </div>
                            {task.status === 'completed' && (
                              <span className="px-3 py-1 text-xs rounded-lg bg-green-500/20 text-green-400">
                                点击查看
                              </span>
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
                      选择文档并点击"开始提取"创建新任务
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="glass">
              <div className="p-4 border-b border-white/10 flex items-center justify-between">
                <h3 className="font-medium text-white">提取结果</h3>
                {entityTypes.length > 0 && (
                  <div className="flex items-center gap-2">
                    <Filter className="w-4 h-4 text-slate-400" />
                    <select
                      value={entityTypeFilter}
                      onChange={(e) => setEntityTypeFilter(e.target.value)}
                      className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 
                                text-sm text-white focus:outline-none focus:ring-2 
                                focus:ring-primary-500/50"
                    >
                      <option value="all">全部类型</option>
                      {entityTypes.map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="p-4 max-h-[500px] overflow-y-auto scrollbar-thin">
                {filteredEntities.length > 0 ? (
                  <div className="space-y-3">
                    {filteredEntities.map((entity, index) => (
                      <div
                        key={index}
                        className="p-4 rounded-xl bg-white/5 border border-white/10 
                                  hover:border-primary-500/30 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-2">
                              <span
                                className={`px-2 py-0.5 rounded text-xs font-medium border
                                          ${entityTypeColors[entity.entity_type] || 'bg-gray-500/20 text-gray-400'}`}
                              >
                                {entity.entity_type}
                              </span>
                            </div>
                            <p className="text-white font-medium">{entity.entity_name}</p>
                            {entity.entity_value && (
                              <p className="text-sm text-slate-400 mt-1">{entity.entity_value}</p>
                            )}
                            {entity.context && (
                              <p className="text-xs text-slate-500 mt-2 line-clamp-2">
                                上下文: {entity.context}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-20">
                    <Database className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                    <p className="text-slate-400">暂无提取结果</p>
                    <p className="text-sm text-slate-500 mt-2">
                      选择文档后点击"开始提取"按钮
                    </p>
                  </div>
                )}
              </div>

              {filteredEntities.length > 0 && (
                <div className="p-4 border-t border-white/10">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">
                      共提取 <span className="text-white">{entities.length}</span> 个实体
                    </span>
                    <span className="text-slate-400">
                      当前显示 <span className="text-white">{filteredEntities.length}</span> 个
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
