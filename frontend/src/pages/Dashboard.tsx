import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, FileText, FolderOpen, Network, Table, TrendingUp } from 'lucide-react'
import { useDocumentStore } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'

const dashboardI18n = {
  'zh-CN': {
    featureDocs: '文档管理',
    featureDocsDesc: '统一管理上传文档、模板和输出文件，支持检索、预览、编辑与下载。',
    featureOps: '智能助手',
    featureOpsDesc: '通过自然语言指令完成文档内容提取、改写、格式调整与转换。',
    featureFill: '表格填写',
    featureFillDesc: '基于源文档自动填写模板，支持多源数据合并和任务进度追踪。',
    featureKg: '知识图谱',
    featureKgDesc: '构建实体关系图谱，支持语义问答、跨文档关联分析与可视化。',
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
  },
  'en-US': {
    featureDocs: 'Document Manager',
    featureDocsDesc: 'Manage uploaded files, templates, and outputs with search, preview, edit, and download.',
    featureOps: 'Smart Doc Operations',
    featureOpsDesc: 'Use natural language to extract, rewrite, adjust format, and convert documents.',
    featureFill: 'Table Filling',
    featureFillDesc: 'Auto-fill templates from source docs, with multi-source merge and task tracking.',
    featureKg: 'Knowledge Graph',
    featureKgDesc: 'Build entity graphs for semantic QA, cross-doc association, and visualization.',
    source: 'Source Docs',
    template: 'Templates',
    output: 'Output Files',
    total: 'Total Docs',
    realtime: 'Realtime',
    welcome: 'Welcome to',
    suggestion: 'Today tip: upload in Document Manager first, then proceed to operation and table filling.',
    todoLatest: 'Todo:',
    heroDesc: 'A smart office platform for document understanding and multi-source fusion in one traceable workflow.',
    core: 'Core Modules',
    modules: '4 modules',
    formats: 'Supported Formats',
    logoAlt: 'ZhiRong Hub Logo',
  },
  'ja-JP': {
    featureDocs: 'ドキュメント管理',
    featureDocsDesc: 'アップロード文書・テンプレート・出力ファイルを一元管理します。',
    featureOps: '文書スマート操作',
    featureOpsDesc: '自然言語で抽出・改写・整形・変換を実行します。',
    featureFill: '表入力',
    featureFillDesc: '源文書からテンプレートを自動入力し、進捗を追跡します。',
    featureKg: 'ナレッジグラフ',
    featureKgDesc: '意味検索や関連分析のための関係グラフを構築します。',
    source: '源文書',
    template: 'テンプレート',
    output: '出力ファイル',
    total: '文書総数',
    realtime: 'リアルタイム',
    welcome: 'ようこそ',
    suggestion: '本日の提案: 先に文書管理で一括アップロードし、その後に操作と表入力へ進んでください。',
    todoLatest: 'TODO:',
    heroDesc: '文書理解と多源融合を統合した、追跡可能なスマートオフィス基盤です。',
    core: '主要機能',
    modules: '全4モジュール',
    formats: '対応フォーマット',
    logoAlt: '知融云枢ロゴ',
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
      icon: Table,
      title: t.featureFill,
      description: t.featureFillDesc,
      path: '/table-fill',
      color: 'from-amber-600 to-orange-500',
    },
    {
      icon: Network,
      title: t.featureKg,
      description: t.featureKgDesc,
      path: '/knowledge',
      color: 'from-violet-600 to-indigo-500',
    },
  ]

  const statCards = [
    { icon: FileText, label: t.source, value: sourceDocs.length, color: 'text-blue-600', bg: 'bg-blue-100' },
    { icon: Table, label: t.template, value: templateDocs.length, color: 'text-emerald-600', bg: 'bg-emerald-100' },
    { icon: FolderOpen, label: t.output, value: outputDocs.length, color: 'text-amber-600', bg: 'bg-amber-100' },
    { icon: Activity, label: t.total, value: documents.length, color: 'text-indigo-600', bg: 'bg-indigo-100' },
  ]

  return (
    <div className="space-y-6">
      <section className="glass relative overflow-hidden rounded-2xl p-8">
        <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-blue-100 blur-2xl" />
        <div className="absolute right-20 top-8 h-24 w-24 rounded-full bg-emerald-100 blur-2xl" />
        <div className="relative z-10 flex items-center justify-between gap-6">
          <div>
            <h1 className="text-3xl font-semibold text-slate-900">
              {t.welcome} <span className="gradient-text">知融云枢</span>
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{t.heroDesc}</p>
            <div className="mt-5 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <TrendingUp className="h-4 w-4 text-primary-600" />
              <span key={tipIndex} className="inline-block animate-in">{rotatingTips[tipIndex] || t.suggestion}</span>
            </div>
          </div>
          <div className="hidden lg:block">
            <img src="/logo2.png" alt={t.logoAlt} className="h-28 w-28 object-contain" />
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statCards.map((stat) => (
          <div key={stat.label} className="glass p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className={`flex h-9 w-9 items-center justify-center rounded-md ${stat.bg}`}>
                <stat.icon className={`h-4 w-4 ${stat.color}`} />
              </div>
              <span className="text-xs text-slate-500">{t.realtime}</span>
            </div>
            <div className="text-2xl font-semibold text-slate-900">{stat.value}</div>
            <div className="mt-1 text-xs text-slate-500">{stat.label}</div>
          </div>
        ))}
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{t.core}</h2>
          <span className="text-xs text-slate-500">{t.modules}</span>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {features.map((feature) => (
            <Link key={feature.path} to={feature.path} className="card card-hover-lift group">
              <div className={`mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br ${feature.color}`}>
                <feature.icon className="h-5 w-5 text-white" />
              </div>
              <h3 className="text-base font-semibold text-slate-900 group-hover:text-primary-600">{feature.title}</h3>
              <p className="mt-2 text-xs leading-5 text-slate-500">{feature.description}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="glass p-5">
        <h2 className="text-base font-semibold text-slate-900">{t.formats}</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {['DOCX', 'XLSX', 'MD', 'TXT'].map((format) => (
            <span key={format} className="rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700">
              {format}
            </span>
          ))}
        </div>
      </section>
    </div>
  )
}

