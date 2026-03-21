import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, Send, FileText, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function DocumentOperation() {
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedDoc, setSelectedDoc] = useState<typeof documents[0] | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)

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

  const handleSend = async () => {
    if (!inputValue.trim() || !selectedDoc) {
      toast.error('请选择文档并输入指令')
      return
    }

    const userMessage: Message = { role: 'user', content: inputValue }
    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)

    try {
      const response = await api.post('/documents/operate', {
        file_id: selectedDoc.id,
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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-200px)]">
      <div className="lg:col-span-1 space-y-4">
        <div
          {...getRootProps()}
          className={`upload-zone ${isDragActive ? 'upload-zone-active' : ''}`}
        >
          <input {...getInputProps()} />
          <div className="text-center">
            <Upload className="w-10 h-10 mx-auto mb-3 text-slate-400" />
            <p className="text-slate-400">拖拽文件或点击上传</p>
            <p className="text-xs text-slate-500 mt-1">支持 docx, xlsx, md, txt</p>
          </div>
        </div>

        <div className="glass p-4">
          <h3 className="text-sm font-medium text-slate-400 mb-3">已上传文档</h3>
          <div className="space-y-2 max-h-80 overflow-y-auto scrollbar-thin">
            {documents.map((doc) => (
              <button
                key={doc.id}
                onClick={() => setSelectedDoc(doc)}
                className={`w-full text-left p-3 rounded-lg transition-all duration-200
                  ${selectedDoc?.id === doc.id
                    ? 'bg-primary-500/20 border border-primary-500/30'
                    : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  }`}
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-white truncate">{doc.original_filename}</span>
                </div>
                <span className="text-xs text-slate-500 ml-6">{doc.file_type.toUpperCase()}</span>
              </button>
            ))}
            {documents.length === 0 && (
              <p className="text-sm text-slate-500 text-center py-4">暂无文档</p>
            )}
          </div>
        </div>
      </div>

      <div className="lg:col-span-2 glass flex flex-col">
        <div className="p-4 border-b border-white/10">
          <h3 className="font-medium text-white">
            {selectedDoc ? `当前文档: ${selectedDoc.original_filename}` : '请选择一个文档'}
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
              disabled={isLoading || !selectedDoc}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !selectedDoc || !inputValue.trim()}
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
