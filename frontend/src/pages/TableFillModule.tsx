import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Loader2, Download, Table, Play, CheckCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore, DocumentInfo } from '../stores/documentStore'

interface TaskResult {
  taskId: string
  status: string
  filledFileId?: string
  filledFileUrl?: string
  result?: Record<string, unknown>
}

export default function TableFillModule() {
  const { documents, fetchDocuments, addDocuments } = useDocumentStore()
  const [selectedSourceDocs, setSelectedSourceDocs] = useState<string[]>([])
  const [selectedTemplateDoc, setSelectedTemplateDoc] = useState<string | null>(null)
  const [instruction, setInstruction] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [taskResult, setTaskResult] = useState<TaskResult | null>(null)

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    try {
      await addDocuments(acceptedFiles)
      toast.success(`上传了 ${acceptedFiles.length} 个文件`)
    } catch {
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

    setIsProcessing(true)
    setTaskResult(null)

    try {
      const response = await api.post('/table-fill/fill', {
        source_file_ids: selectedSourceDocs,
        template_file_id: selectedTemplateDoc,
        user_instruction: instruction || '帮我智能填表',
      })

      setTaskResult({
        taskId: response.data.task_id,
        status: response.data.status,
        filledFileId: response.data.filled_file_id,
        filledFileUrl: response.data.filled_file_url,
        result: response.data.result,
      })

      if (response.data.status === 'completed') {
        toast.success('表格填写完成！')
      }
    } catch {
      toast.error('表格填写失败')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleDownload = () => {
    if (taskResult?.filledFileUrl) {
      window.open(taskResult.filledFileUrl, '_blank')
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div className="glass p-4">
            <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <Upload className="w-5 h-5 text-primary-400" />
              上传文件
            </h3>
            <div
              {...getRootProps()}
              className={`upload-zone ${isDragActive ? 'upload-zone-active' : ''}`}
            >
              <input {...getInputProps()} />
              <Upload className="w-8 h-8 mx-auto mb-2 text-slate-400" />
              <p className="text-slate-400 text-sm">上传源文档和模板文件</p>
            </div>
          </div>

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">选择源文档（数据来源）</h3>
            <div className="space-y-2 max-h-40 overflow-y-auto scrollbar-thin">
              {documents.map((doc) => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all
                    ${selectedSourceDocs.includes(doc.id)
                      ? 'bg-primary-500/20 border border-primary-500/30'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedSourceDocs.includes(doc.id)}
                    onChange={() => toggleSourceDoc(doc.id)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
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

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">选择模板文件</h3>
            <div className="space-y-2 max-h-40 overflow-y-auto scrollbar-thin">
              {documents.map((doc) => (
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
                    <span className="text-sm text-white truncate">{doc.original_filename}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3">填写指令（可选）</h3>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="描述填写要求，例如：将所有数值数据填入对应的单元格中..."
              className="input min-h-[80px] resize-none"
            />
          </div>

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
                开始填写
              </>
            )}
          </button>
        </div>

        <div className="glass">
          <div className="p-4 border-b border-white/10">
            <h3 className="font-medium text-white">处理结果</h3>
          </div>

          <div className="p-4 min-h-[400px] flex flex-col items-center justify-center">
            {isProcessing ? (
              <div className="text-center">
                <Loader2 className="w-12 h-12 animate-spin text-primary-400 mx-auto mb-4" />
                <p className="text-slate-400">正在分析文档并填写表格...</p>
              </div>
            ) : taskResult ? (
              <div className="w-full space-y-4">
                <div className={`p-4 rounded-xl ${
                  taskResult.status === 'completed'
                    ? 'bg-green-500/10 border border-green-500/30'
                    : 'bg-orange-500/10 border border-orange-500/30'
                }`}>
                  <div className="flex items-center gap-3">
                    {taskResult.status === 'completed' ? (
                      <CheckCircle className="w-6 h-6 text-green-400" />
                    ) : (
                      <Loader2 className="w-6 h-6 animate-spin text-orange-400" />
                    )}
                    <div>
                      <p className="font-medium text-white">
                        {taskResult.status === 'completed' ? '填写完成' : '处理中...'}
                      </p>
                    </div>
                  </div>
                </div>

                {taskResult.status === 'completed' && taskResult.filledFileUrl && (
                  <button
                    onClick={handleDownload}
                    className="btn-secondary w-full flex items-center justify-center gap-2"
                  >
                    <Download className="w-5 h-5" />
                    下载填写后的文件
                  </button>
                )}
              </div>
            ) : (
              <div className="text-center">
                <Table className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                <p className="text-slate-400">选择源文档和模板后开始填写</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
