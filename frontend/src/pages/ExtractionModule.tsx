import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Loader2, Search, Filter, Database } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

interface Entity {
  entity_type: string
  entity_name: string
  entity_value: string
  context?: string
}

export default function ExtractionModule() {
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [entities, setEntities] = useState<Entity[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('all')

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles)
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

    setIsLoading(true)
    try {
      const response = await api.post('/extraction/extract', {
        file_ids: selectedDocs,
        entity_types: ['PERSON', 'LOCATION', 'ORGANIZATION', 'DATE', 'NUMBER'],
      })
      setEntities(response.data.entities || [])
      toast.success(`成功提取 ${response.data.entities?.length || 0} 个实体`)
    } catch (error) {
      toast.error('提取失败')
    } finally {
      setIsLoading(false)
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
              {documents.map((doc) => (
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
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500
                              focus:ring-primary-500 focus:ring-offset-0"
                  />
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-white truncate">{doc.original_filename}</span>
                </label>
              ))}
              {documents.length === 0 && (
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
        </div>

        <div className="lg:col-span-2">
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
                      <option key={type} value={type}>
                        {type}
                      </option>
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
                  <p className="text-slate-400">
                    {isLoading ? '正在提取实体信息...' : '暂无提取结果'}
                  </p>
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
        </div>
      </div>
    </div>
  )
}
