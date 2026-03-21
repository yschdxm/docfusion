import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, Send, FileText, Loader2, Plus, CheckCircle, Table } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function DocumentOperation() {
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const onSourceDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'source')
      toast.success(`成功上传 ${acceptedFiles.length} 个源文档`)
    } catch (error) {
      toast.error('上传失败')
    }
  }, [addDocuments])

  const onTemplateDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles, 'template')
      toast.success(`成功上传 ${acceptedFiles.length} 个模板`)
    } catch (error) {
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

  const toggleDocSelection = (docId: string) => {
    setSelectedDocs((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    )
  }

  const getActiveDoc = () => {
    if (selectedDocs.length > 0) {
      return documents.find(d => d.id === selectedDocs[0])
    }
    if (selectedTemplate) {
      return documents.find(d => d.id === selectedTemplate)
    }
    return null
  }

  const handleSend = async () => {
    if (!inputValue.trim()) {
      toast.error('请输入指令')
      return
    }

    const activeDocId = selectedDocs[0] || selectedTemplate
    if (!activeDocId) {
      toast.error('请选择一个文档或模板')
      return
    }

    const userMessage: Message = { role: 'user', content: inputValue }
    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)

    try {
      const response = await api.post('/documents/operate', {
        file_id: activeDocId,
        instruction: inputValue,
      })

      const result = response.data.result
      const assistantMessage: Message = {
        role: 'assistant',
        content: result?.result || result?.message || '操作完成',
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      toast.error('操作失败')
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '抱歉，操作执行失败，请重试。' },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const activeDoc = getActiveDoc()

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-200px)]">
      <div className="lg:col-span-1 space-y-4">
        {/* 源文档区域 */}
        <div className="glass p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-400" />
              源文档
            </h3>
            <span className="text-xs text-slate-500">{sourceDocs.length} 个</span>
          </div>
          
          <div
            {...getSourceRootProps()}
            className={`upload-zone mb-3 ${isSourceDragActive ? 'upload-zone-active' : ''}`}
          >
            <input {...getSourceInputProps()} />
            <div className="flex items-center justify-center gap-2">
              <Plus className="w-4 h-4 text-slate-400" />
              <span className="text-slate-400 text-sm">添加源文档</span>
            </div>
          </div>

          <div className="space-y-2 max-h-40 overflow-y-auto scrollbar-thin">
            {sourceDocs.map((doc) => (
              <div
                key={doc.id}
                className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all
                  ${selectedDocs.includes(doc.id)
                    ? 'bg-blue-500/20 border border-blue-500/30'
                    : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  }`}
                onClick={() => toggleDocSelection(doc.id)}
              >
                <input
                  type="checkbox"
                  checked={selectedDocs.includes(doc.id)}
                  onChange={() => toggleDocSelection(doc.id)}
                  className="w-4 h-4 rounded border-white/20 bg-white/10 text-blue-500"
                />
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-sm text-white truncate flex-1">{doc.original_filename}</span>
              </div>
            ))}
            {sourceDocs.length === 0 && (
              <p className="text-xs text-slate-500 text-center py-2">暂无源文档</p>
            )}
          </div>
        </div>

        {/* 模板区域 */}
        <div className="glass p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
              <Table className="w-4 h-4 text-green-400" />
              模板文件
            </h3>
            <span className="text-xs text-slate-500">{templateDocs.length} 个</span>
          </div>

          <div
            {...getTemplateRootProps()}
            className={`upload-zone mb-3 ${isTemplateDragActive ? 'upload-zone-active' : ''}`}
          >
            <input {...getTemplateInputProps()} />
            <div className="flex items-center justify-center gap-2">
              <Plus className="w-4 h-4 text-slate-400" />
              <span className="text-slate-400 text-sm">添加模板</span>
            </div>
          </div>

          <div className="space-y-2 max-h-40 overflow-y-auto scrollbar-thin">
            {templateDocs.map((doc) => (
              <div
                key={doc.id}
                className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all
                  ${selectedTemplate === doc.id
                    ? 'bg-green-500/20 border border-green-500/30'
                    : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  }`}
                onClick={() => setSelectedTemplate(selectedTemplate === doc.id ? null : doc.id)}
              >
                <Table className="w-4 h-4 text-green-400" />
                <span className="text-sm text-white truncate flex-1">{doc.original_filename}</span>
                {selectedTemplate === doc.id && (
                  <CheckCircle className="w-4 h-4 text-green-400" />
                )}
              </div>
            ))}
            {templateDocs.length === 0 && (
              <p className="text-xs text-slate-500 text-center py-2">暂无模板</p>
            )}
          </div>
        </div>

        {/* 已选择提示 */}
        <div className="glass p-3">
          <p className="text-xs text-slate-400">
            已选择: {selectedDocs.length} 个源文档
            {selectedTemplate && ', 1 个模板'}
          </p>
        </div>
      </div>

      <div className="lg:col-span-2 glass flex flex-col">
        <div className="p-4 border-b border-white/10">
          <h3 className="font-medium text-white">
            {activeDoc ? `当前操作: ${activeDoc.original_filename}` : '请选择一个文档开始操作'}
          </h3>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
          {messages.length === 0 && (
            <div className="text-center py-20">
              <FileText className="w-16 h-16 mx-auto mb-4 text-slate-600" />
              <p className="text-slate-400">请输入自然语言指令来操作文档</p>
              <p className="text-sm text-slate-500 mt-2">
                例如："提取文档中的所有表格数据"、"将文档转换为Markdown格式"
              </p>
            </div>
          )}
          {messages.map((message, index) => (
            <div
              key={index}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] p-4 rounded-2xl ${
                  message.role === 'user'
                    ? 'bg-primary-500/20 text-white'
                    : 'bg-white/5 text-slate-200'
                }`}
              >
                {message.content}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white/5 p-4 rounded-2xl">
                <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-white/10">
          <div className="flex gap-3">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSend()}
              placeholder="输入自然语言指令..."
              className="input flex-1"
              disabled={isLoading || !activeDoc}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !activeDoc || !inputValue.trim()}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
