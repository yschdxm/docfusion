import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Table, Network, TrendingUp, FolderOpen, Activity } from 'lucide-react'
import { useDocumentStore } from '../stores/documentStore'

export default function Dashboard() {
  const { documents, fetchDocuments } = useDocumentStore()

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const sourceDocs = documents.filter(d => d.doc_category === 'source')
  const templateDocs = documents.filter(d => d.doc_category === 'template')
  const outputDocs = documents.filter(d => d.doc_category === 'output')

  const features = [
    {
      icon: FolderOpen,
      title: '文档管理',
      description: '管理所有上传的文档、模板和输出文件，上传文档自动提取信息',
      path: '/documents',
      color: 'from-slate-500 to-slate-600',
    },
    {
      icon: FileText,
      title: '文档智能操作',
      description: '通过自然语言指令操作文档，支持内容提取、格式转换等操作',
      path: '/document-operation',
      color: 'from-blue-500 to-cyan-500',
    },
    {
      icon: Table,
      title: '表格填写',
      description: '根据源文档自动填写模板表格，支持多种格式',
      path: '/table-fill',
      color: 'from-orange-500 to-amber-500',
    },
    {
      icon: Network,
      title: '知识图谱',
      description: '构建文档知识图谱，支持语义查询和关联发现',
      path: '/knowledge',
      color: 'from-purple-500 to-pink-500',
    },
  ]

  const statCards = [
    { icon: FileText, label: '源文档', value: sourceDocs.length, color: 'text-blue-400' },
    { icon: Table, label: '模板', value: templateDocs.length, color: 'text-green-400' },
    { icon: FolderOpen, label: '输出文件', value: outputDocs.length, color: 'text-orange-400' },
    { icon: Activity, label: '文档总数', value: documents.length, color: 'text-purple-400' },
  ]

  return (
    <div className="space-y-8">
      <div className="glass p-8 rounded-3xl bg-gradient-to-r from-primary-500/10 to-purple-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">
              欢迎使用 <span className="gradient-text">DocFusion</span>
            </h1>
            <p className="text-slate-400 max-w-xl">
              基于大语言模型的文档理解与多源数据融合系统，让您的文档处理更加智能高效
            </p>
          </div>
          <div className="hidden lg:block">
            <TrendingUp className="w-24 h-24 text-primary-500/30" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {statCards.map((stat, index) => (
          <div key={index} className="stat-card">
            <stat.icon className={`w-8 h-8 mx-auto mb-3 ${stat.color}`} />
            <div className="text-3xl font-bold text-white mb-1">{stat.value}</div>
            <div className="text-sm text-slate-400">{stat.label}</div>
          </div>
        ))}
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-6 text-white">核心功能</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, index) => (
            <Link
              key={index}
              to={feature.path}
              className="card group"
            >
              <div className="flex items-start gap-4">
                <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${feature.color} 
                                flex items-center justify-center shrink-0
                                group-hover:scale-110 transition-transform duration-300`}>
                  <feature.icon className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white mb-2 group-hover:text-primary-400 
                                 transition-colors">
                    {feature.title}
                  </h3>
                  <p className="text-sm text-slate-400">{feature.description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      <div className="glass p-6">
        <h2 className="text-xl font-semibold mb-4 text-white">支持的文件格式</h2>
        <div className="flex flex-wrap gap-3">
          {['DOCX', 'XLSX', 'MD', 'TXT'].map((format) => (
            <span 
              key={format}
              className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 
                        text-sm font-medium text-slate-300"
            >
              {format}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
