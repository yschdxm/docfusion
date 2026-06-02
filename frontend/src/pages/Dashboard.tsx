import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Clock, FileText, FolderOpen, Network, NotebookPen, Table, TrendingUp } from 'lucide-react'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'
import DocumentPreviewModal from '../components/DocumentPreviewModal'

const dashboardI18n = {
  'zh-CN': {
    featureDocs: '文档管理',
    featureDocsDesc: '统一管理上传文档、模板和输出文件，支持检索、预览、编辑与下载。',
    featureOps: '智能助手',
    featureOpsDesc: '通过自然语言指令完成文档内容提取、改写、格式调整与转换。',
    featureKg: '知识图谱',
    featureKgDesc: '构建实体关系图谱，支持语义问答、跨文档关联分析与可视化。',
    featureWorkLog: '工作日志',
    featureWorkLogDesc: '查看统计、维护待办、导出工作日志。',
    source: '源文档',
    template: '模板',
    output: '输出文件',
    total: '文档总数',
    realtime: '实时',
    welcome: '欢迎使用',
    suggestion: '今日建议：先在文档管理完成批量上传，再进入智能操作与表格填写。',
    todoLatest: '待办事项：',
    heroDesc: '面向文档理解与多源融合的智能办公平台。将文档处理、知识抽取与自动填表统一到一个可追踪、可协同的工作流中。',
    core: '核心功能入口',
    modules: '共 4 个模块',
    formats: '支持的文件格式',
    logoAlt: '知融云枢Logo',
    brandName: '知融云枢',
    enter: '进入',
    recentDocs: '最近文档',
    viewAll: '查看全部',
    noDocs: '暂无文档，上传后将显示在这里',
    sourceLabel: '源文档',
    templateLabel: '模板',
    outputLabel: '输出',
  },
  'en-US': {
    featureDocs: 'Document Manager',
    featureDocsDesc: 'Manage uploaded files, templates, and outputs with search, preview, edit, and download.',
    featureOps: 'Smart Doc Operations',
    featureOpsDesc: 'Use natural language to extract, rewrite, adjust format, and convert documents.',
    featureKg: 'Knowledge Graph',
    featureKgDesc: 'Build entity graphs for semantic QA, cross-doc association, and visualization.',
    featureWorkLog: 'Work Log',
    featureWorkLogDesc: 'View stats, manage todos, and export work logs.',
    source: 'Source Docs',
    template: 'Templates',
    output: 'Output Files',
    total: 'Total Docs',
    realtime: 'Realtime',
    welcome: 'Welcome to',
    suggestion: 'Today tip: upload in Document Manager first, then proceed to operations.',
    todoLatest: 'Todo:',
    heroDesc: 'A smart office platform for document understanding and multi-source fusion in one traceable workflow.',
    core: 'Core Modules',
    modules: '4 modules',
    formats: 'Supported Formats',
    logoAlt: 'ZhiRong Hub Logo',
    brandName: 'ZhiRong Hub',
    enter: 'Enter',
    recentDocs: 'Recent Documents',
    viewAll: 'View All',
    noDocs: 'No documents yet. Upload to see them here.',
    sourceLabel: 'Source',
    templateLabel: 'Template',
    outputLabel: 'Output',
  },
  'ja-JP': {
    featureDocs: 'ドキュメント管理',
    featureDocsDesc: 'アップロード文書・テンプレート・出力ファイルを一元管理します。',
    featureOps: '文書スマート操作',
    featureOpsDesc: '自然言語で抽出・改写・整形・変換を実行します。',
    featureKg: 'ナレッジグラフ',
    featureKgDesc: '意味検索や関連分析のための関係グラフを構築します。',
    featureWorkLog: '作業ログ',
    featureWorkLogDesc: '統計の確認、TODO管理、作業ログのエクスポート。',
    source: '源文書',
    template: 'テンプレート',
    output: '出力ファイル',
    total: '文書総数',
    realtime: 'リアルタイム',
    welcome: 'ようこそ',
    suggestion: '本日の提案: 先に文書管理で一括アップロードし、その後に操作へ進んでください。',
    todoLatest: 'TODO:',
    heroDesc: '文書理解と多源融合を統合した、追跡可能なスマートオフィス基盤です。',
    core: '主要機能',
    modules: '全4モジュール',
    formats: '対応フォーマット',
    logoAlt: '知融云枢ロゴ',
    brandName: '知融云枢',
    enter: '入力',
    recentDocs: '最近の文書',
    viewAll: 'すべて表示',
    noDocs: '文書がありません。アップロードするとここに表示されます。',
    sourceLabel: 'ソース',
    templateLabel: 'テンプレート',
    outputLabel: '出力',
  },
} as const

const TODO_STORAGE_KEY = 'worklog_todos'

interface TodoItem {
  id: string
  text: string
  done: boolean
  createdAt: string
}

export default function Dashboard() {
  const { language } = useI18n()
  const t = dashboardI18n[language]
  const { documents, fetchDocuments } = useDocumentStore()
  const [tipIndex, setTipIndex] = useState(0)
  const [latestTodoText, setLatestTodoText] = useState('')
  const [previewDoc, setPreviewDoc] = useState<DocumentInfo | null>(null)

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  useEffect(() => {
    const loadLatestTodo = () => {
      const raw = localStorage.getItem(TODO_STORAGE_KEY)
      if (!raw) {
        setLatestTodoText('')
        return
      }

      try {
        const parsed = JSON.parse(raw) as TodoItem[]
        if (!Array.isArray(parsed) || parsed.length === 0) {
          setLatestTodoText('')
          return
        }

        const latest = [...parsed].sort((a, b) => {
          const at = new Date(a.createdAt).getTime() || 0
          const bt = new Date(b.createdAt).getTime() || 0
          return bt - at
        })[0]

        setLatestTodoText(latest?.text || '')
      } catch {
        setLatestTodoText('')
      }
    }

    loadLatestTodo()
    window.addEventListener('storage', loadLatestTodo)
    window.addEventListener('focus', loadLatestTodo)

    return () => {
      window.removeEventListener('storage', loadLatestTodo)
      window.removeEventListener('focus', loadLatestTodo)
    }
  }, [])

  const rotatingTips = useMemo(() => {
    const tips: string[] = [t.suggestion]
    if (latestTodoText.trim()) {
      tips.push(`${t.todoLatest} ${latestTodoText.trim()}`)
    }
    return tips
  }, [latestTodoText, t.suggestion, t.todoLatest])

  useEffect(() => {
    setTipIndex(0)
  }, [rotatingTips.length])

  useEffect(() => {
    if (rotatingTips.length <= 1) return

    const timer = window.setInterval(() => {
      setTipIndex((prev) => (prev + 1) % rotatingTips.length)
    }, 4000)

    return () => window.clearInterval(timer)
  }, [rotatingTips])

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')
  const templateDocs = documents.filter((d) => d.doc_category === 'template')
  const outputDocs = documents.filter((d) => d.doc_category === 'output')

  const recentDocs = useMemo(() => {
    return [...documents]
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 8)
  }, [documents])

  const categoryMeta: Record<string, { label: string; cls: string }> = {
    source: { label: t.sourceLabel, cls: 'bg-blue-100 text-blue-700' },
    template: { label: t.templateLabel, cls: 'bg-emerald-100 text-emerald-700' },
    output: { label: t.outputLabel, cls: 'bg-amber-100 text-amber-700' },
  }

  const features = [
    {
      icon: FolderOpen,
      title: t.featureDocs,
      description: t.featureDocsDesc,
      path: '/documents',
      color: 'from-slate-600 to-slate-700',
    },
    {
      icon: FileText,
      title: t.featureOps,
      description: t.featureOpsDesc,
      path: '/document-operation',
      color: 'from-blue-600 to-blue-500',
    },
    {
      icon: Network,
      title: t.featureKg,
      description: t.featureKgDesc,
      path: '/knowledge',
      color: 'from-violet-600 to-indigo-500',
    },
    {
      icon: NotebookPen,
      title: t.featureWorkLog,
      description: t.featureWorkLogDesc,
      path: '/work-log',
      color: 'from-amber-600 to-orange-500',
    },
  ]

  const statCards = [
    { icon: FileText, label: t.source, value: sourceDocs.length, color: 'text-blue-600', bg: 'bg-blue-100' },
    { icon: Table, label: t.template, value: templateDocs.length, color: 'text-emerald-600', bg: 'bg-emerald-100' },
    { icon: FolderOpen, label: t.output, value: outputDocs.length, color: 'text-amber-600', bg: 'bg-amber-100' },
    { icon: Activity, label: t.total, value: documents.length, color: 'text-indigo-600', bg: 'bg-indigo-100' },
  ]

  return (
    <div className="flex flex-col h-full min-h-0 gap-2">
      {/* Hero — 紧凑单行 */}
      <section className="glass relative overflow-hidden px-4 py-2.5 shrink-0">
        <div className="absolute -right-10 -top-10 h-36 w-36 rounded-full bg-blue-100 blur-2xl" />
        <div className="absolute right-20 top-8 h-20 w-20 rounded-full bg-emerald-100 blur-2xl" />
        <div className="relative z-10 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-base lg:text-lg font-semibold text-slate-900">
              {t.welcome} <span className="gradient-text">{t.brandName}</span>
            </h1>
            <p className="mt-0.5 max-w-2xl text-[10px] lg:text-[11px] leading-4 text-slate-500 line-clamp-1">{t.heroDesc}</p>
            <div className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] text-slate-500">
              <TrendingUp className="h-2.5 w-2.5 text-primary-600" />
              <span key={tipIndex} className="inline-block animate-in truncate">{rotatingTips[tipIndex] || t.suggestion}</span>
            </div>
          </div>
          <div className="hidden lg:block shrink-0">
            <img src="/logo.png" alt={t.logoAlt} className="h-12 w-12 object-contain" />
          </div>
        </div>
      </section>

      {/* Stats — 精简一行式 */}
      <section className="grid grid-cols-4 gap-2 shrink-0">
        {statCards.map((stat) => (
          <div key={stat.label} className="glass px-2.5 py-2 lg:px-4 lg:py-2.5 overflow-hidden">
            <div className="flex items-center gap-2">
              <div className={`flex h-7 w-7 lg:h-8 lg:w-8 items-center justify-center rounded-lg ${stat.bg} shrink-0`}>
                <stat.icon className={`h-3.5 w-3.5 lg:h-4 lg:w-4 ${stat.color}`} />
              </div>
              <div className="min-w-0">
                <div className="text-base lg:text-lg font-bold text-slate-900 leading-tight">{stat.value}</div>
                <div className="text-[10px] lg:text-xs text-slate-500 leading-tight">{stat.label}</div>
              </div>
            </div>
          </div>
        ))}
      </section>

      {/* Main: Features (left) + Recent Docs (right) — 占据剩余空间 */}
      <section className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-2">
        {/* Features - primary area */}
        <div className="xl:col-span-8 min-h-0 flex flex-col gap-2">
          <div className="flex items-center justify-between shrink-0">
            <h2 className="text-xs lg:text-sm font-semibold text-slate-900">{t.core}</h2>
            <span className="text-[10px] text-slate-500">{t.modules}</span>
          </div>
          <div className="flex-1 min-h-0 grid grid-cols-2 gap-2 auto-rows-fr">
            {features.map((feature) => (
              <Link key={feature.path} to={feature.path} className="card !p-2.5 lg:!p-4 card-hover-lift group flex flex-col items-center justify-center text-center overflow-hidden">
                <div className={`flex h-9 w-9 lg:h-12 lg:w-12 xl:h-14 xl:w-14 items-center justify-center rounded-xl bg-gradient-to-br ${feature.color} mb-1.5 lg:mb-2 transition-transform group-hover:scale-110`}>
                  <feature.icon className="h-4 w-4 lg:h-6 lg:w-6 xl:h-7 xl:w-7 text-white" />
                </div>
                <h3 className="text-xs lg:text-sm font-semibold text-slate-900 group-hover:text-primary-600">{feature.title}</h3>
                <p className="mt-0.5 text-[9px] lg:text-[10px] leading-3.5 text-slate-500 line-clamp-2">{feature.description}</p>
              </Link>
            ))}
          </div>
          <div className="glass px-3 py-1.5 shrink-0 flex items-center gap-2 overflow-hidden">
            <h3 className="text-[11px] font-semibold text-slate-900 shrink-0">{t.formats}</h3>
            <div className="flex flex-wrap gap-1">
              {['DOCX', 'XLSX', 'MD', 'TXT'].map((format) => (
                <span key={format} className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">
                  {format}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Recent Docs - sidebar */}
        <div className="xl:col-span-4 min-h-0 flex flex-col">
          <div className="glass rounded-xl flex-1 min-h-0 flex flex-col overflow-hidden">
            <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-1.5">
                <Clock className="w-3 h-3 text-slate-500" />
                <h2 className="text-xs lg:text-sm font-semibold text-slate-900">{t.recentDocs}</h2>
              </div>
              <Link to="/documents" className="text-[10px] lg:text-[11px] text-primary-600 hover:text-primary-700">{t.viewAll} →</Link>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
              {recentDocs.length === 0 ? (
                <div className="flex items-center justify-center h-full px-4">
                  <p className="text-[11px] text-slate-400 text-center">{t.noDocs}</p>
                </div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {recentDocs.map((doc) => {
                    const meta = categoryMeta[doc.doc_category] || { label: doc.doc_category, cls: 'bg-slate-100 text-slate-600' }
                    return (
                      <button
                        key={doc.id}
                        onClick={() => setPreviewDoc(doc)}
                        title={doc.original_filename}
                        className="flex items-center gap-2 px-3 py-1.5 lg:py-2 hover:bg-slate-50/60 transition-colors w-full text-left"
                      >
                        <FileText className="w-3 h-3 text-slate-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-[11px] lg:text-xs text-slate-700 truncate">{doc.original_filename}</p>
                          <p className="text-[9px] lg:text-[10px] text-slate-400">{new Date(doc.created_at).toLocaleDateString(language)}</p>
                        </div>
                        <span className={`text-[9px] lg:text-[10px] px-1.5 py-0.5 rounded shrink-0 ${meta.cls}`}>{meta.label}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      <DocumentPreviewModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />
    </div>
  )
}

