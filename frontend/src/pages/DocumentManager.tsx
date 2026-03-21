import { useEffect, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { FileText, Table, FolderOpen, Trash2, Upload, Download, Search, Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import { useDocumentStore } from '../stores/documentStore'

type CategoryFilter = 'all' | 'source' | 'template' | 'output'

export default function DocumentManager() {
  const { documents, fetchDocuments, addDocuments, deleteDocument } = useDocumentStore()
  const [filter, setFilter] = useState<CategoryFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const onDrop = async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      toast.success(`成功上传 ${acceptedFiles.length} 个文件`)
    } catch (error) {
      toast.error('上传失败')
    }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/markdown': ['.md'],
      'text/plain': ['.txt'],
    },
  })

  const filteredDocs = documents.filter(doc => {
    const matchFilter = filter === 'all' || doc.doc_category === filter
    const matchSearch = doc.original_filename.toLowerCase().includes(searchTerm.toLowerCase())
    return matchFilter && matchSearch
  })

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')
  const outputDocs = documents.filter(d => d.doc_category === 'output')

  const handleDelete = async (docId: string, docName: string) => {
    if (!confirm(`确定要删除 "${docName}" 及其相关数据吗？`)) return
    
    try {
      await deleteDocument(docId)
      setSelectedDocs(prev => prev.filter(id => id !== docId))
      toast.success('删除成功')
    } catch (error) {
      toast.error('删除失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selectedDocs.length === 0) {
      toast.error('请选择要删除的文档')
      return
    }
    if (!confirm(`确定要删除选中的 ${selectedDocs.length} 个文档吗？`)) return

    try {
      for (const docId of selectedDocs) {
        await deleteDocument(docId)
      }
      setSelectedDocs([])
      toast.success('批量删除成功')
    } catch (error) {
      toast.error('批量删除失败')
    }
  }

  const toggleSelect = (docId: string) => {
    setSelectedDocs(prev => 
      prev.includes(docId) 
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
    )
  }

  const toggleSelectAll = () => {
    if (selectedDocs.length === filteredDocs.length) {
      setSelectedDocs([])
    } else {
      setSelectedDocs(filteredDocs.map(d => d.id))
    }
  }

  const categoryConfig = {
    source: { icon: FileText, color: 'text-blue-400', bg: 'bg-blue-500/20', label: '源文档' },
    template: { icon: Table, color: 'text-green-400', bg: 'bg-green-500/20', label: '模板' },
    output: { icon: FolderOpen, color: 'text-orange-400', bg: 'bg-orange-500/20', label: '输出' },
  }

  return (
    <div className="space-y-6">
      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div 
          className={`glass p-4 cursor-pointer transition-all ${filter === 'all' ? 'ring-2 ring-primary-500' : ''}`}
          onClick={() => setFilter('all')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary-500/20 flex items-center justify-center">
              <FileText className="w-5 h-5 text-primary-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{documents.length}</p>
              <p className="text-xs text-slate-400">全部文档</p>
            </div>
          </div>
        </div>

        <div 
          className={`glass p-4 cursor-pointer transition-all ${filter === 'source' ? 'ring-2 ring-blue-500' : ''}`}
          onClick={() => setFilter('source')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
              <FileText className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{sourceDocs.length}</p>
              <p className="text-xs text-slate-400">源文档</p>
            </div>
          </div>
        </div>

        <div 
          className={`glass p-4 cursor-pointer transition-all ${filter === 'template' ? 'ring-2 ring-green-500' : ''}`}
          onClick={() => setFilter('template')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-green-500/20 flex items-center justify-center">
              <Table className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{templateDocs.length}</p>
              <p className="text-xs text-slate-400">模板</p>
            </div>
          </div>
        </div>

        <div 
          className={`glass p-4 cursor-pointer transition-all ${filter === 'output' ? 'ring-2 ring-orange-500' : ''}`}
          onClick={() => setFilter('output')}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-orange-500/20 flex items-center justify-center">
              <FolderOpen className="w-5 h-5 text-orange-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{outputDocs.length}</p>
              <p className="text-xs text-slate-400">输出文件</p>
            </div>
          </div>
        </div>
      </div>

      {/* 工具栏 */}
      <div className="glass p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索文档..."
                className="input pl-10 w-64"
              />
            </div>
            
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as CategoryFilter)}
              className="input w-32"
            >
              <option value="all">全部</option>
              <option value="source">源文档</option>
              <option value="template">模板</option>
              <option value="output">输出</option>
            </select>
          </div>

          <div className="flex items-center gap-3">
            {selectedDocs.length > 0 && (
              <button
                onClick={handleBatchDelete}
                className="btn-secondary flex items-center gap-2 text-red-400 hover:text-red-300"
              >
                <Trash2 className="w-4 h-4" />
                删除选中 ({selectedDocs.length})
              </button>
            )}
            
            <div {...getRootProps()} className="btn-primary flex items-center gap-2 cursor-pointer">
              <input {...getInputProps()} />
              <Plus className="w-4 h-4" />
              上传文档
            </div>
          </div>
        </div>
      </div>

      {/* 文档列表 */}
      <div className="glass overflow-hidden">
        <div className="p-4 border-b border-white/10">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={selectedDocs.length === filteredDocs.length && filteredDocs.length > 0}
              onChange={toggleSelectAll}
              className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
            />
            <span className="text-sm text-slate-400">
              全选 ({filteredDocs.length} 个文档)
            </span>
          </label>
        </div>

        <div className="max-h-[500px] overflow-y-auto scrollbar-thin">
          {filteredDocs.length > 0 ? (
            filteredDocs.map((doc) => {
              const config = categoryConfig[doc.doc_category as keyof typeof categoryConfig] || categoryConfig.source
              const Icon = config.icon
              
              return (
                <div
                  key={doc.id}
                  className={`flex items-center gap-4 p-4 border-b border-white/5 hover:bg-white/5 transition-colors
                    ${selectedDocs.includes(doc.id) ? 'bg-primary-500/10' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleSelect(doc.id)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
                  />
                  
                  <div className={`w-10 h-10 rounded-lg ${config.bg} flex items-center justify-center shrink-0`}>
                    <Icon className={`w-5 h-5 ${config.color}`} />
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-medium truncate">{doc.original_filename}</p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.color}`}>
                        {config.label}
                      </span>
                      <span className="text-xs text-slate-500">{doc.file_type.toUpperCase()}</span>
                      {doc.file_size && (
                        <span className="text-xs text-slate-500">
                          {(doc.file_size / 1024).toFixed(1)} KB
                        </span>
                      )}
                      <span className="text-xs text-slate-500">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <a
                      href={doc.doc_category === 'output' 
                        ? `/api/v1/table-fill/download/${doc.id}`
                        : `/api/v1/documents/${doc.id}/download`}
                      className="p-2 rounded-lg hover:bg-blue-500/20 text-slate-400 hover:text-blue-400 transition-colors"
                      download
                    >
                      <Download className="w-4 h-4" />
                    </a>
                    <button
                      onClick={() => handleDelete(doc.id, doc.original_filename)}
                      className="p-2 rounded-lg hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )
            })
          ) : (
            <div className="p-12 text-center">
              <FileText className="w-16 h-16 mx-auto mb-4 text-slate-600" />
              <p className="text-slate-400">
                {searchTerm ? '未找到匹配的文档' : '暂无文档'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
