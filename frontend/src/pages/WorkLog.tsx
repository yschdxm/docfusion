import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChartNoAxesColumnIncreasing,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Download,
  FileOutput,
  FileText,
  LayoutGrid,
  Maximize2,
  PieChart,
  Plus,
  TrendingUp,
  Table,
  X,
  Undo2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'
import api from '../services/api'
import { useI18n } from '../hooks/useI18n'
import { WORKLOG_EXPORT_EVENT } from '../services/shortcuts'

type LogTab = 'calendar' | 'funnel' | 'templatePie' | 'uploadTrend'
type PeriodMode = 'month' | 'year'
type TrendGranularity = 'day' | 'week' | 'month'

interface TodoItem {
  id: string
  text: string
  done: boolean
  createdAt: string
}

interface TemplateUsageItem {
  template_id: string
  template_name: string
  usage_count: number
}

interface TemplateUsageResponse {
  total_usage: number
  items: TemplateUsageItem[]
}

const TODO_STORAGE_KEY = 'worklog_todos'
const NOTE_STORAGE_KEY = 'worklog_note'

const monthLabelsZh = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
const monthLabelsEn = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monthLabelsJa = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
const pieColors = ['#82c1ff', '#ffbce5', '#f0c985', '#c5adfe', '#a5f77e', '#ef4444', '#0ea5e9', '#84cc16', '#f97316', '#6366f1']

const toDateKey = (date: Date) => {
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${year}-${month}-${day}`
}

const parseSafeDate = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date
}

const sortByCreatedAtDesc = (items: DocumentInfo[]) => {
  return [...items].sort((a, b) => {
    const at = parseSafeDate(a.created_at)?.getTime() ?? 0
    const bt = parseSafeDate(b.created_at)?.getTime() ?? 0
    return bt - at
  })
}

const categoryLabel = (category: string, language: 'zh-CN' | 'en-US' | 'ja-JP') => {
  if (category === 'source') return language === 'zh-CN' ? '文档' : language === 'ja-JP' ? '文書' : 'Document'
  if (category === 'template') return language === 'zh-CN' ? '模板' : language === 'ja-JP' ? 'テンプレート' : 'Template'
  if (category === 'output') return language === 'zh-CN' ? '输出' : language === 'ja-JP' ? '出力' : 'Output'
  return language === 'zh-CN' ? '其他' : language === 'ja-JP' ? 'その他' : 'Other'
}

const categoryStyle = (category: string) => {
  if (category === 'source') return 'bg-blue-100 text-blue-700'
  if (category === 'template') return 'bg-emerald-100 text-emerald-700'
  if (category === 'output') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-700'
}

export default function WorkLog() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments } = useDocumentStore()

  const [activeTab, setActiveTab] = useState<LogTab>('calendar')
  const [periodMode, setPeriodMode] = useState<PeriodMode>('month')
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [selectedYear, setSelectedYear] = useState(() => new Date().getFullYear())

  const [showDatePicker, setShowDatePicker] = useState(false)
  const [pickerYear, setPickerYear] = useState(() => new Date().getFullYear())

  const [todos, setTodos] = useState<TodoItem[]>(() => {
    const saved = localStorage.getItem(TODO_STORAGE_KEY)
    if (!saved) return []
    try {
      const parsed = JSON.parse(saved) as TodoItem[]
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  })
  const [todoInput, setTodoInput] = useState('')
  const [note, setNote] = useState(() => localStorage.getItem(NOTE_STORAGE_KEY) || '')
  const [showTodoModal, setShowTodoModal] = useState(false)
  const [selectedDayKey, setSelectedDayKey] = useState<string | null>(null)
  const [trendGranularity, setTrendGranularity] = useState<TrendGranularity>('day')
  const [templateUsageApiData, setTemplateUsageApiData] = useState<TemplateUsageResponse | null>(null)
  const persistTodos = (next: TodoItem[]) => {
    setTodos(next)
    localStorage.setItem(TODO_STORAGE_KEY, JSON.stringify(next))
  }

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  useEffect(() => {
    const fetchTemplateUsage = async () => {
      try {
        const response = await api.get<TemplateUsageResponse>('/table-fill/stats/template-usage', {
          params: { limit: 10 },
        })
        setTemplateUsageApiData(response.data)
      } catch (error) {
        console.error('Failed to fetch template usage stats:', error)
        setTemplateUsageApiData(null)
      }
    }
    fetchTemplateUsage()
  }, [documents.length])


  useEffect(() => {
    localStorage.setItem(NOTE_STORAGE_KEY, note)
  }, [note])

  useEffect(() => {
    setSelectedYear(currentMonth.getFullYear())
  }, [currentMonth])

  const sourceDocs = useMemo(() => documents.filter((d) => d.doc_category === 'source'), [documents])
  const templateDocs = useMemo(() => documents.filter((d) => d.doc_category === 'template'), [documents])
  const outputDocs = useMemo(() => documents.filter((d) => d.doc_category === 'output'), [documents])

  const recentSources = useMemo(() => sortByCreatedAtDesc(sourceDocs).slice(0, 8), [sourceDocs])
  const recentTemplates = useMemo(() => sortByCreatedAtDesc(templateDocs).slice(0, 8), [templateDocs])
  const recentOutputs = useMemo(() => sortByCreatedAtDesc(outputDocs).slice(0, 8), [outputDocs])

  const pendingTodos = useMemo(() => todos.filter((t) => !t.done), [todos])
  const todoPreview = useMemo(() => pendingTodos.slice(0, 6), [pendingTodos])

  const docsByDate = useMemo(() => {
    return documents.reduce<Record<string, DocumentInfo[]>>((acc, doc) => {
      const d = parseSafeDate(doc.created_at)
      if (!d) return acc
      const key = toDateKey(d)
      if (!acc[key]) acc[key] = []
      acc[key].push(doc)
      return acc
    }, {})
  }, [documents])

  const dayDetailDocs = useMemo(() => {
    if (!selectedDayKey) return []
    return sortByCreatedAtDesc(docsByDate[selectedDayKey] || [])
  }, [docsByDate, selectedDayKey])

  const dailyStats = useMemo(() => {
    return documents.reduce<Record<string, { source: number; template: number; output: number; total: number }>>((acc, doc) => {
      const parsed = parseSafeDate(doc.created_at)
      if (!parsed) return acc

      const key = toDateKey(parsed)
      if (!acc[key]) {
        acc[key] = { source: 0, template: 0, output: 0, total: 0 }
      }

      if (doc.doc_category === 'source') acc[key].source += 1
      if (doc.doc_category === 'template') acc[key].template += 1
      if (doc.doc_category === 'output') acc[key].output += 1
      acc[key].total += 1
      return acc
    }, {})
  }, [documents])

  const currentMonthStats = useMemo(() => {
    const y = currentMonth.getFullYear()
    const m = currentMonth.getMonth()
    const firstWeekday = new Date(y, m, 1).getDay()
    const daysInMonth = new Date(y, m + 1, 0).getDate()

    const cells: Array<{ day: number; key: string | null }> = []
    for (let i = 0; i < firstWeekday; i += 1) cells.push({ day: 0, key: null })
    for (let d = 1; d <= daysInMonth; d += 1) {
      const key = toDateKey(new Date(y, m, d))
      cells.push({ day: d, key })
    }

    return { cells }
  }, [currentMonth])

  const yearMonthlyStats = useMemo(() => {
    return Array.from({ length: 12 }, (_, monthIndex) => {
      let source = 0
      let template = 0
      let output = 0

      documents.forEach((doc) => {
        const d = parseSafeDate(doc.created_at)
        if (!d) return
        if (d.getFullYear() !== selectedYear || d.getMonth() !== monthIndex) return

        if (doc.doc_category === 'source') source += 1
        if (doc.doc_category === 'template') template += 1
        if (doc.doc_category === 'output') output += 1
      })

      return {
        month: monthIndex,
        source,
        template,
        output,
        total: source + template + output,
      }
    })
  }, [documents, selectedYear])

  const funnelData = useMemo(() => {
    const uploadCount = sourceDocs.length + templateDocs.length

    const extractedCompleted = sourceDocs.filter((doc) => doc.extraction_status?.status === 'completed').length
    const extractCount = extractedCompleted > 0 ? extractedCompleted : sourceDocs.length

    const fillEstimate = Math.min(extractCount, Math.max(outputDocs.length, Math.min(extractCount, templateDocs.length)))
    const outputCount = outputDocs.length

    const rawStages = [
      { key: 'upload', label: tr('上传', 'Upload', 'アップロード'), value: uploadCount, color: 'bg-blue-500' },
      { key: 'extract', label: tr('提取', 'Extract', '抽出'), value: extractCount, color: 'bg-emerald-500' },
      { key: 'fill', label: tr('填写', 'Fill', '入力'), value: fillEstimate, color: 'bg-violet-500' },
      { key: 'output', label: tr('输出', 'Output', '出力'), value: outputCount, color: 'bg-amber-500' },
    ]

    const stages = rawStages.map((stage, index) => {
      if (index === 0) return stage
      return {
        ...stage,
        value: Math.min(stage.value, rawStages[index - 1].value),
      }
    })

    const base = Math.max(stages[0]?.value || 1, 1)
    return stages.map((stage, index) => {
      const previous = index > 0 ? Math.max(stages[index - 1].value, 1) : Math.max(stage.value, 1)
      return {
        ...stage,
        widthPercent: Math.max(12, Math.round((stage.value / base) * 100)),
        fromPrevious: index === 0 ? 100 : Math.round((stage.value / previous) * 100),
      }
    })
  }, [outputDocs.length, sourceDocs, templateDocs.length, tr])

  const templateTop10 = useMemo(() => {
    const apiItems = templateUsageApiData?.items ?? []

    const sorted = apiItems.map((item) => ({
      name: item.template_name || tr('未命名模板', 'Unnamed template', '無名テンプレート'),
      count: item.usage_count || 0,
    }))

    const total = templateUsageApiData?.total_usage || sorted.reduce((sum, item) => sum + item.count, 0) || 1
    let cumulative = 0

    return sorted.map((item, index) => {
      const percent = Math.round((item.count / total) * 100)
      const start = cumulative
      cumulative += (item.count / total) * 360
      const end = cumulative
      return {
        ...item,
        percent,
        color: pieColors[index % pieColors.length],
        start,
        end,
      }
    })
  }, [templateDocs, templateUsageApiData])

  const uploadTrendData = useMemo(() => {
    const uploadedDocs = documents.filter((doc) => doc.doc_category === 'source' || doc.doc_category === 'template')
    const now = new Date()

    if (trendGranularity === 'day') {
      const points: Array<{ key: string; label: string; value: number }> = []
      for (let i = 13; i >= 0; i -= 1) {
        const d = new Date(now)
        d.setDate(now.getDate() - i)
        const key = toDateKey(d)
        const value = uploadedDocs.reduce((sum, doc) => {
          const created = parseSafeDate(doc.created_at)
          return created && toDateKey(created) === key ? sum + 1 : sum
        }, 0)
        points.push({ key, label: `${d.getMonth() + 1}/${d.getDate()}`, value })
      }
      return points
    }

    if (trendGranularity === 'week') {
      const points: Array<{ key: string; label: string; value: number }> = []
      const getWeekStart = (date: Date) => {
        const d = new Date(date)
        const day = d.getDay()
        const diff = day === 0 ? -6 : 1 - day
        d.setDate(d.getDate() + diff)
        d.setHours(0, 0, 0, 0)
        return d
      }

      const currentWeekStart = getWeekStart(now)
      for (let i = 11; i >= 0; i -= 1) {
        const weekStart = new Date(currentWeekStart)
        weekStart.setDate(currentWeekStart.getDate() - i * 7)
        const weekEnd = new Date(weekStart)
        weekEnd.setDate(weekStart.getDate() + 6)
        const value = uploadedDocs.reduce((sum, doc) => {
          const created = parseSafeDate(doc.created_at)
          if (!created) return sum
          return created >= weekStart && created <= weekEnd ? sum + 1 : sum
        }, 0)
        points.push({
          key: `${weekStart.getFullYear()}-${weekStart.getMonth() + 1}-${weekStart.getDate()}`,
          label: `${weekStart.getMonth() + 1}/${weekStart.getDate()}`,
          value,
        })
      }
      return points
    }

    const points: Array<{ key: string; label: string; value: number }> = []
    for (let i = 11; i >= 0; i -= 1) {
      const monthDate = new Date(now.getFullYear(), now.getMonth() - i, 1)
      const year = monthDate.getFullYear()
      const month = monthDate.getMonth()
      const value = uploadedDocs.reduce((sum, doc) => {
        const created = parseSafeDate(doc.created_at)
        if (!created) return sum
        return created.getFullYear() === year && created.getMonth() === month ? sum + 1 : sum
      }, 0)
      points.push({
        key: `${year}-${month + 1}`,
        label: language === 'zh-CN' || language === 'ja-JP' ? `${month + 1}月` : `${month + 1}`,
        value,
      })
    }
    return points
  }, [documents, trendGranularity])

  const uploadTrendSummary = useMemo(() => {
    const total = uploadTrendData.reduce((sum, item) => sum + item.value, 0)
    const avg = uploadTrendData.length > 0 ? total / uploadTrendData.length : 0
    const peak = uploadTrendData.reduce((max, item) => Math.max(max, item.value), 0)
    return { total, avg: Number(avg.toFixed(1)), peak }
  }, [uploadTrendData])

  const trendChartPoints = useMemo(() => {
    if (uploadTrendData.length === 0) return []
    const max = Math.max(...uploadTrendData.map((item) => item.value), 1)
    const count = uploadTrendData.length
    return uploadTrendData.map((item, index) => {
      // Place each point at the center of its date column so chart and labels align.
      const x = ((index + 0.5) / count) * 100
      const y = 90 - (item.value / max) * 70
      return { ...item, x, y }
    })
  }, [uploadTrendData])

  const trendPolyline = useMemo(() => {
    if (trendChartPoints.length === 0) return ''
    return trendChartPoints.map((point) => `${point.x},${point.y}`).join(' ')
  }, [trendChartPoints])

  const addTodo = () => {
    const text = todoInput.trim()
    if (!text) return

    const next = [
      {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        text,
        done: false,
        createdAt: new Date().toISOString(),
      },
      ...todos,
    ]
    persistTodos(next)
    setTodoInput('')
  }

  const toggleTodo = (id: string) => {
    const next = todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t))
    persistTodos(next)
  }

  const removeTodo = (id: string) => {
    const removed = todos.find((t) => t.id === id)
    if (!removed) return

    persistTodos(todos.filter((t) => t.id !== id))

    toast.custom(
      (t) => (
        <div className="glass flex items-center gap-3 px-3 py-2 text-sm text-slate-700">
          <span>{tr('待办已删除', 'Todo deleted', 'TODOを削除しました')}</span>
          <button
            className="btn-secondary px-2 py-1 text-xs"
            title={tr('撤销', 'Undo', '元に戻す')}
            onClick={() => {
              persistTodos([removed, ...todos.filter((todo) => todo.id !== removed.id)])
              toast.dismiss(t.id)
            }}
          >
            <Undo2 className="w-3.5 h-3.5" />
            {tr('撤销', 'Undo', '元に戻す')}
          </button>
        </div>
      ),
      { duration: 3500 }
    )
  }

  const exportWorkLog = useCallback(() => {
    const payload = {
      exportedAt: new Date().toISOString(),
      summary: {
        sourceCount: sourceDocs.length,
        templateCount: templateDocs.length,
        outputCount: outputDocs.length,
        pendingTodos: pendingTodos.length,
      },
      recent: {
        source: recentSources,
        template: recentTemplates,
        output: recentOutputs,
      },
      note,
      todos,
      dailyStats,
      yearStats: {
        year: selectedYear,
        monthly: yearMonthlyStats,
      },
    }

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `work-log-${toDateKey(new Date())}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    const message = tr('工作日志已导出', 'Work log exported', '作業ログをエクスポートしました')
    toast.success(message)
    window.dispatchEvent(
      new CustomEvent('app-notify', {
        detail: {
          title: tr('导出成功', 'Export succeeded', 'エクスポート成功'),
          message,
        },
      })
    )
  }, [dailyStats, note, outputDocs.length, pendingTodos.length, recentOutputs, recentSources, recentTemplates, selectedYear, sourceDocs.length, templateDocs.length, todos, tr, yearMonthlyStats])

  useEffect(() => {
    window.addEventListener(WORKLOG_EXPORT_EVENT, exportWorkLog)
    return () => window.removeEventListener(WORKLOG_EXPORT_EVENT, exportWorkLog)
  }, [exportWorkLog])

  const openDatePicker = () => {
    if (showDatePicker) {
      setShowDatePicker(false)
      return
    }

    setPickerYear(periodMode === 'month' ? currentMonth.getFullYear() : selectedYear)
    setShowDatePicker(true)
  }

  const hasAnyDayData = (source: number, template: number, output: number) => source > 0 || template > 0 || output > 0

  return (
    <div className="flex flex-col h-full min-h-0 gap-2.5">
      {/* 手机端：紧凑统计 + 待办 */}
      <div className="lg:hidden shrink-0 space-y-2">
        <div className="grid grid-cols-3 gap-2">
          <div className="glass px-2.5 py-2 rounded-lg flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-blue-100 flex items-center justify-center shrink-0">
              <FileText className="w-3 h-3 text-blue-600" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900 leading-tight">{sourceDocs.length}</p>
              <p className="text-[9px] text-slate-500 leading-tight truncate">{tr('源文档', 'Source', 'ソース')}</p>
            </div>
          </div>
          <div className="glass px-2.5 py-2 rounded-lg flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-emerald-100 flex items-center justify-center shrink-0">
              <Table className="w-3 h-3 text-emerald-600" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900 leading-tight">{templateDocs.length}</p>
              <p className="text-[9px] text-slate-500 leading-tight truncate">{tr('模板', 'Template', 'テンプレート')}</p>
            </div>
          </div>
          <div className="glass px-2.5 py-2 rounded-lg flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-amber-100 flex items-center justify-center shrink-0">
              <FileOutput className="w-3 h-3 text-amber-600" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900 leading-tight">{outputDocs.length}</p>
              <p className="text-[9px] text-slate-500 leading-tight truncate">{tr('输出', 'Output', '出力')}</p>
            </div>
          </div>
        </div>
        <div className="glass px-3 py-2 rounded-lg flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-violet-100 flex items-center justify-center shrink-0">
            <ClipboardList className="w-3 h-3 text-violet-600" />
          </div>
          <input
            value={todoInput}
            onChange={(e) => setTodoInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addTodo() }}
            placeholder={tr('输入待办任务', 'Add todo', 'TODO入力')}
            className="input h-7 text-[11px] flex-1 min-w-0"
          />
          <button onClick={addTodo} className="btn-secondary p-1" title={tr('添加待办', 'Add todo', 'TODOを追加')}>
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => setShowTodoModal(true)} className="text-[10px] text-primary-600 shrink-0" title={tr('查看全部待办', 'View all todos', 'すべてのTODOを表示')}>
            {pendingTodos.length} {tr('项待办', 'todo', '件')}
          </button>
        </div>
      </div>

      {/* 桌面端：四列卡片 */}
      <div className="hidden lg:grid grid-cols-4 gap-3 shrink-0">
        <div className="glass p-3 rounded-xl flex flex-col">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center shrink-0">
                <FileText className="w-3.5 h-3.5 text-blue-600" />
              </div>
              <p className="text-xs font-medium text-slate-900 truncate">{tr('最近上传文档', 'Recent Uploaded Docs', '最近アップロードした文書')}</p>
            </div>
            <span className="text-[10px] text-slate-500">{sourceDocs.length} {tr('份', 'items', '件')}</span>
          </div>
          <div className="space-y-1 overflow-y-auto min-h-0 max-h-28 scrollbar-thin">
            {recentSources.length > 0 ? (
              recentSources.map((item) => (
                <p key={item.id} className="text-[11px] text-slate-500 truncate">{item.original_filename}</p>
              ))
            ) : (
              <p className="text-[11px] text-slate-500">{tr('暂无记录', 'No records', '記録なし')}</p>
            )}
          </div>
        </div>

        <div className="glass p-3 rounded-xl flex flex-col">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center shrink-0">
                <Table className="w-3.5 h-3.5 text-emerald-600" />
              </div>
              <p className="text-xs font-medium text-slate-900 truncate">{tr('最近上传模板', 'Recent Uploaded Templates', '最近アップロードしたテンプレート')}</p>
            </div>
            <span className="text-[10px] text-slate-500">{templateDocs.length} {tr('份', 'items', '件')}</span>
          </div>
          <div className="space-y-1 overflow-y-auto min-h-0 max-h-28 scrollbar-thin">
            {recentTemplates.length > 0 ? (
              recentTemplates.map((item) => (
                <p key={item.id} className="text-[11px] text-slate-500 truncate">{item.original_filename}</p>
              ))
            ) : (
              <p className="text-[11px] text-slate-500">{tr('暂无记录', 'No records', '記録なし')}</p>
            )}
          </div>
        </div>

        <div className="glass p-3 rounded-xl flex flex-col">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center shrink-0">
                <FileOutput className="w-3.5 h-3.5 text-amber-600" />
              </div>
              <p className="text-xs font-medium text-slate-900 truncate">{tr('最近输出文件', 'Recent Output Files', '最近出力ファイル')}</p>
            </div>
            <span className="text-[10px] text-slate-500">{outputDocs.length} {tr('份', 'items', '件')}</span>
          </div>
          <div className="space-y-1 overflow-y-auto min-h-0 max-h-28 scrollbar-thin">
            {recentOutputs.length > 0 ? (
              recentOutputs.map((item) => (
                <p key={item.id} className="text-[11px] text-slate-500 truncate">{item.original_filename}</p>
              ))
            ) : (
              <p className="text-[11px] text-slate-500">{tr('暂无记录', 'No records', '記録なし')}</p>
            )}
          </div>
        </div>

        <div className="glass p-3 rounded-xl flex flex-col">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center shrink-0">
                <ClipboardList className="w-3.5 h-3.5 text-violet-600" />
              </div>
              <p className="text-xs font-medium text-slate-900 truncate">{tr('待办事项', 'Todo Items', 'TODO項目')}</p>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-500">{tr('待办', 'Todos', 'TODO')} {pendingTodos.length}</span>
              <button onClick={() => setShowTodoModal(true)} aria-label={tr('展开全部待办', 'Expand all todos', 'TODOをすべて表示')} className="p-0.5 rounded hover:bg-slate-100" title={tr('展开全部', 'Expand All', 'すべて展開')}>
                <Maximize2 className="w-3 h-3 text-slate-500" />
              </button>
            </div>
          </div>
          <div className="flex gap-1.5 mb-1.5 shrink-0">
            <input
              value={todoInput}
              onChange={(e) => setTodoInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addTodo()
              }}
              placeholder={tr('输入近期任务', 'Enter upcoming task', '近日中のタスクを入力')}
              className="input h-8 text-[11px]"
            />
            <button onClick={addTodo} className="btn-secondary px-2 py-1.5" title={tr('添加待办', 'Add todo', 'TODOを追加')}>
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="space-y-1 overflow-y-auto min-h-0 max-h-24 scrollbar-thin">
            {todoPreview.length > 0 ? (
              todoPreview.map((todo) => (
                <label key={todo.id} className="flex items-center gap-1.5 text-[11px] text-slate-600">
                  <input type="checkbox" checked={todo.done} onChange={() => toggleTodo(todo.id)} className="h-3 w-3" />
                  <span className="truncate">{todo.text}</span>
                </label>
              ))
            ) : (
              <p className="text-[11px] text-slate-500">{tr('暂无待办', 'No todos', 'TODOなし')}</p>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-2.5">
        <div className="xl:col-span-9 min-h-0 flex flex-col">
          <div className="glass rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col">
            <div className="px-3 sm:px-4 py-2 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="flex flex-wrap items-center gap-1">
                <button
                  onClick={() => setActiveTab('calendar')}
                  className={`px-2 py-1 rounded-lg text-[11px] sm:text-xs ${activeTab === 'calendar' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                  title={tr('日历', 'Calendar', 'カレンダー')}
                >
                  <span className="inline-flex items-center gap-1"><CalendarDays className="w-3 h-3 sm:w-3.5 sm:h-3.5" /> {tr('日历', 'Calendar', 'カレンダー')}</span>
                </button>
                <button
                  onClick={() => setActiveTab('funnel')}
                  className={`px-2 py-1 rounded-lg text-[11px] sm:text-xs ${activeTab === 'funnel' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                  title={tr('漏斗', 'Funnel', 'ファネル')}
                >
                  <span className="inline-flex items-center gap-1"><LayoutGrid className="w-3 h-3 sm:w-3.5 sm:h-3.5" /> {tr('漏斗', 'Funnel', 'ファネル')}</span>
                </button>
                <button
                  onClick={() => setActiveTab('templatePie')}
                  className={`px-2 py-1 rounded-lg text-[11px] sm:text-xs ${activeTab === 'templatePie' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                  title={tr('模板排行', 'Templates', 'テンプレート')}
                >
                  <span className="inline-flex items-center gap-1"><PieChart className="w-3 h-3 sm:w-3.5 sm:h-3.5" /> {tr('模板排行', 'Templates', 'テンプレート')}</span>
                </button>
                <button
                  onClick={() => setActiveTab('uploadTrend')}
                  className={`px-2 py-1 rounded-lg text-[11px] sm:text-xs ${activeTab === 'uploadTrend' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                  title={tr('趋势', 'Trend', '推移')}
                >
                  <span className="inline-flex items-center gap-1"><TrendingUp className="w-3 h-3 sm:w-3.5 sm:h-3.5" /> {tr('趋势', 'Trend', '推移')}</span>
                </button>
              </div>

              <button onClick={exportWorkLog} className="btn-secondary px-2 py-1 sm:px-2.5 sm:py-1 text-[11px] sm:text-xs" title={tr('导出工作日志', 'Export Work Log', '作業ログをエクスポート')}>
                <Download className="w-3.5 h-3.5" />
                {tr('导出工作日志', 'Export Work Log', '作業ログをエクスポート')}
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin flex flex-col">
            {activeTab === 'calendar' && (
              <div className="p-3 sm:p-4 flex-1 min-h-0 flex flex-col gap-2.5 sm:gap-3">
                <div className="flex items-center justify-between gap-3 flex-wrap shrink-0">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        if (periodMode === 'month') {
                          setCurrentMonth((prev) => new Date(prev.getFullYear(), prev.getMonth() - 1, 1))
                        } else {
                          setSelectedYear((prev) => prev - 1)
                        }
                      }}
                      className="btn-secondary px-2 py-1.5"
                      title={tr('上一期', 'Previous', '前へ')}
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>

                    <button onClick={openDatePicker} className="btn-secondary min-w-[150px] justify-center text-sm" title={tr('选择日期', 'Select date', '日付を選択')}>
                      {periodMode === 'month'
                        ? (language === 'zh-CN' || language === 'ja-JP'
                          ? `${currentMonth.getFullYear()}年 ${currentMonth.getMonth() + 1}月`
                          : `${currentMonth.getFullYear()}/${currentMonth.getMonth() + 1}`)
                        : (language === 'zh-CN' || language === 'ja-JP'
                          ? `${selectedYear}年`
                          : `${selectedYear}`)}
                    </button>

                    <button
                      onClick={() => {
                        if (periodMode === 'month') {
                          setCurrentMonth((prev) => new Date(prev.getFullYear(), prev.getMonth() + 1, 1))
                        } else {
                          setSelectedYear((prev) => prev + 1)
                        }
                      }}
                      className="btn-secondary px-2 py-1.5"
                      title={tr('下一期', 'Next', '次へ')}
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPeriodMode('month')}
                      className={`px-2.5 py-1 rounded-lg text-xs ${periodMode === 'month' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                      title={tr('按月', 'By Month', '月別')}
                    >
                      {tr('按月', 'By Month', '月別')}
                    </button>
                    <button
                      onClick={() => setPeriodMode('year')}
                      className={`px-2.5 py-1 rounded-lg text-xs ${periodMode === 'year' ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'}`}
                      title={tr('按年', 'By Year', '年別')}
                    >
                      {tr('按年', 'By Year', '年別')}
                    </button>
                    <button
                      onClick={() => {
                        const now = new Date()
                        setCurrentMonth(new Date(now.getFullYear(), now.getMonth(), 1))
                        setSelectedYear(now.getFullYear())
                      }}
                      className="btn-secondary px-2.5 py-1 text-xs"
                      title={tr('回到当前', 'Go to current', '現在に戻る')}
                    >
                      {periodMode === 'month' ? tr('本月', 'This Month', '今月') : tr('本年', 'This Year', '今年')}
                    </button>
                  </div>
                </div>

                {showDatePicker && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 shrink-0">
                    <div className="flex items-center justify-between mb-3">
                      <button onClick={() => setPickerYear((y) => y - 1)} className="btn-secondary px-2 py-1" title={tr('上一年', 'Prev Year', '前年')}>{tr('上一年', 'Prev Year', '前年')}</button>
                      <span className="text-sm font-medium text-slate-800">{language === 'zh-CN' ? `${pickerYear} 年` : language === 'ja-JP' ? `${pickerYear}年` : `${pickerYear}`}</span>
                      <button onClick={() => setPickerYear((y) => y + 1)} className="btn-secondary px-2 py-1" title={tr('下一年', 'Next Year', '次年')}>{tr('下一年', 'Next Year', '次年')}</button>
                    </div>

                    {periodMode === 'month' ? (
                      <div className="grid grid-cols-4 gap-2">
                        {(language === 'zh-CN' ? monthLabelsZh : language === 'ja-JP' ? monthLabelsJa : monthLabelsEn).map((label, idx) => (
                          <button
                            key={label}
                            onClick={() => {
                              setCurrentMonth(new Date(pickerYear, idx, 1))
                              setShowDatePicker(false)
                            }}
                            className={`rounded-lg px-3 py-2 text-sm ${
                              currentMonth.getFullYear() === pickerYear && currentMonth.getMonth() === idx
                                ? 'bg-primary-500/15 text-primary-600'
                                : 'bg-white text-slate-700 hover:bg-slate-100'
                            }`}
                            title={label}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="grid grid-cols-4 gap-2">
                        {Array.from({ length: 12 }, (_, i) => pickerYear - 6 + i).map((year) => (
                          <button
                            key={year}
                            onClick={() => {
                              setSelectedYear(year)
                              setShowDatePicker(false)
                            }}
                            className={`rounded-lg px-3 py-2 text-sm ${
                              selectedYear === year ? 'bg-primary-500/15 text-primary-600' : 'bg-white text-slate-700 hover:bg-slate-100'
                            }`}
                            title={String(year)}
                          >
                            {language === 'zh-CN' ? `${year}年` : language === 'ja-JP' ? `${year}年` : `${year}`}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {periodMode === 'month' ? (
                  <>
                    <div className="grid grid-cols-7 gap-1.5 text-[11px] text-slate-500 px-0.5 shrink-0">
                      {(language === 'zh-CN' ? ['日', '一', '二', '三', '四', '五', '六'] : language === 'ja-JP' ? ['日', '月', '火', '水', '木', '金', '土'] : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']).map((w) => (
                        <div key={w} className="text-center py-0.5">{w}</div>
                      ))}
                    </div>

                    <div className="flex-1 min-h-0 grid grid-cols-7 gap-1.5 auto-rows-fr">
                      {currentMonthStats.cells.map((cell, idx) => {
                        if (!cell.key) {
                          return <div key={`empty-${idx}`} className="rounded-lg bg-transparent" />
                        }

                        const dayStats = dailyStats[cell.key] || { source: 0, template: 0, output: 0, total: 0 }
                        const hasData = hasAnyDayData(dayStats.source, dayStats.template, dayStats.output)
                        return (
                          <button
                            key={cell.key}
                            onClick={() => setSelectedDayKey(cell.key)}
                            className="calendar-cell rounded-lg border border-slate-200 bg-slate-50 p-1.5 text-left hover:border-primary-300 transition-colors flex flex-col"
                            title={String(cell.day)}
                          >
                            <div className="text-[11px] font-medium text-slate-700">{cell.day}</div>
                            {hasData && (
                              <>
                                <div className="calendar-cell-tags mt-auto flex flex-col gap-0.5">
                                  {dayStats.source > 0 && (
                                    <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-blue-50 text-blue-600 rounded px-1 py-0.5 truncate">
                                      {tr('文档', 'Docs', '文書')} {dayStats.source}
                                    </span>
                                  )}
                                  {dayStats.template > 0 && (
                                    <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-emerald-50 text-emerald-600 rounded px-1 py-0.5 truncate">
                                      {tr('模板', 'Tmp', 'テンプレート')} {dayStats.template}
                                    </span>
                                  )}
                                  {dayStats.output > 0 && (
                                    <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-amber-50 text-amber-600 rounded px-1 py-0.5 truncate">
                                      {tr('输出', 'Out', '出力')} {dayStats.output}
                                    </span>
                                  )}
                                </div>
                                <div className="calendar-cell-dots mt-auto items-center gap-0.5 flex-wrap">
                                  {dayStats.source > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500" />}
                                  {dayStats.template > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />}
                                  {dayStats.output > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500" />}
                                </div>
                              </>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <div className="flex-1 min-h-0 grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 auto-rows-fr">
                    {yearMonthlyStats.map((item) => {
                      const hasData = hasAnyDayData(item.source, item.template, item.output)
                      return (
                        <button
                          key={item.month}
                          onClick={() => {
                            setCurrentMonth(new Date(selectedYear, item.month, 1))
                            setPeriodMode('month')
                          }}
                          className="calendar-cell rounded-lg border border-slate-200 bg-slate-50 p-2 text-left hover:border-primary-300 transition-colors flex flex-col"
                          title={language === 'zh-CN' || language === 'ja-JP' ? `${item.month + 1}月` : String(item.month + 1)}
                        >
                          <div className="text-[11px] font-medium text-slate-700">{language === 'zh-CN' || language === 'ja-JP' ? `${item.month + 1}月` : `${item.month + 1}`}</div>
                          {hasData && (
                            <>
                              <div className="calendar-cell-tags mt-auto flex flex-col gap-0.5">
                                {item.source > 0 && (
                                  <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-blue-50 text-blue-600 rounded px-1 py-0.5 truncate">
                                    {tr('文档', 'Docs', '文書')} {item.source}
                                  </span>
                                )}
                                {item.template > 0 && (
                                  <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-emerald-50 text-emerald-600 rounded px-1 py-0.5 truncate">
                                    {tr('模板', 'Tmp', 'テンプレート')} {item.template}
                                  </span>
                                )}
                                {item.output > 0 && (
                                  <span className="inline-flex items-center text-[8px] lg:text-[9px] leading-none bg-amber-50 text-amber-600 rounded px-1 py-0.5 truncate">
                                    {tr('输出', 'Out', '出力')} {item.output}
                                  </span>
                                )}
                              </div>
                              <div className="calendar-cell-dots mt-auto items-center gap-0.5 flex-wrap">
                                {item.source > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500" />}
                                {item.template > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />}
                                {item.output > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500" />}
                              </div>
                            </>
                          )}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'funnel' && (
              <div className="p-4 space-y-2.5">
                <p className="text-xs text-slate-500">{tr('上传→提取→填写→输出，快速定位流程卡点', 'Upload -> Extract -> Fill -> Output, quickly locate bottlenecks', 'アップロード→抽出→入力→出力、ボトルネックを素早く把握')}</p>
                {funnelData.map((stage, index) => (
                  <div key={stage.key} className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
                    <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                      <span>{stage.label}</span>
                      <span>{stage.value} {tr('条', 'items', '件')}</span>
                    </div>
                    <div className="mt-1.5 h-7 rounded-lg bg-slate-200 overflow-hidden">
                      <div className={`h-full ${stage.color} px-3 text-white text-xs flex items-center justify-between`} style={{ width: `${stage.widthPercent}%` }}>
                        <span>{stage.label}</span>
                        <span>{stage.fromPrevious}%</span>
                      </div>
                    </div>
                    {index > 0 && stage.fromPrevious < 100 && (
                      <p className="mt-1 text-[10px] text-amber-600">{tr('较上一阶段转化率', 'Conversion from previous stage', '前段階からの転換率')} {stage.fromPrevious}%</p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'templatePie' && (
              <div className="p-4 lg:p-6 space-y-4">
                {templateTop10.length === 0 ? (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
                    {tr('暂无模板数据，上传模板后将展示 Top10 使用排行。', 'No template data yet. Top10 ranking will appear after template usage is generated.', 'テンプレートデータがありません。利用後にTop10ランキングが表示されます。')}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 flex items-center justify-center">
                      <div
                        className="w-48 h-48 lg:w-64 lg:h-64 xl:w-72 xl:h-72 rounded-full"
                        style={{
                          background: `conic-gradient(${templateTop10
                            .map((item) => `${item.color} ${item.start}deg ${item.end}deg`)
                            .join(', ')})`,
                        }}
                      />
                    </div>

                    <div className="space-y-2">
                      {templateTop10.map((item, index) => (
                        <div key={item.name} className="rounded-lg border border-slate-200 bg-white px-3.5 py-2 flex items-center justify-between gap-3">
                          <div className="min-w-0 flex items-center gap-2.5">
                            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
                            <p className="text-xs lg:text-sm text-slate-700 truncate">{index + 1}. {item.name}</p>
                          </div>
                          <span className="text-xs text-slate-500 shrink-0">{item.count} {tr('次', 'times', '回')} ({item.percent}%)</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'uploadTrend' && (
              <div className="p-4 lg:p-6 space-y-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-1.5">
                    {(['day', 'week', 'month'] as TrendGranularity[]).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setTrendGranularity(mode)}
                        className={`px-2.5 py-1 rounded-lg text-xs ${
                          trendGranularity === mode ? 'bg-primary-500/15 text-primary-600' : 'text-slate-600 hover:bg-slate-100'
                        }`}
                        title={mode === 'day' ? tr('按天', 'By Day', '日別') : mode === 'week' ? tr('按周', 'By Week', '週別') : tr('按月', 'By Month', '月別')}
                      >
                        {mode === 'day' ? tr('按天', 'By Day', '日別') : mode === 'week' ? tr('按周', 'By Week', '週別') : tr('按月', 'By Month', '月別')}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-600">
                    <span className="inline-flex items-center gap-1"><ChartNoAxesColumnIncreasing className="w-3.5 h-3.5" /> {tr('总上传', 'Total Uploads', '総アップロード')} {uploadTrendSummary.total}</span>
                    <span>{tr('均值', 'Avg', '平均')} {uploadTrendSummary.avg}</span>
                    <span>{tr('峰值', 'Peak', 'ピーク')} {uploadTrendSummary.peak}</span>
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="h-48 lg:h-64 xl:h-72 w-full">
                    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
                      <line x1="0" y1="90" x2="100" y2="90" stroke="#cbd5e1" strokeWidth="0.8" />
                      <polyline
                        points={trendPolyline}
                        fill="none"
                        stroke="#7dc4ff"
                        strokeWidth="0.2"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />
                      {trendChartPoints.map((point) => (
                        <circle
                          key={point.key}
                          cx={point.x}
                          cy={point.y}
                          r="0.6"
                          fill="#3282c4"
                        />
                      ))}
                    </svg>
                  </div>
                  <div
                    className="mt-3 grid gap-1.5"
                    style={{ gridTemplateColumns: `repeat(${Math.max(uploadTrendData.length, 1)}, minmax(0, 1fr))` }}
                  >
                    {uploadTrendData.map((item) => (
                      <div key={item.key} className="rounded-md border border-slate-200 bg-white px-1.5 py-1.5 text-center">
                        <p className="text-[10px] lg:text-xs text-slate-500 truncate">{item.label}</p>
                        <p className="text-xs lg:text-sm text-slate-700 mt-0.5">{item.value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
            </div>
          </div>
        </div>

        <div className="xl:col-span-3 min-h-0">
          <div className="glass p-4 rounded-xl h-full flex flex-col">
            <h3 className="text-sm font-medium text-slate-900 mb-2 shrink-0">{tr('工作日记本', 'Work Notebook', '作業ノート')}</h3>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={tr('写下近期计划、风险提醒、会议结论...', 'Write plans, risks, and meeting conclusions...', '計画、リスク、会議結論を記録...')}
              className="input flex-1 min-h-0 resize-none text-sm"
            />
            <p className="mt-2 text-[10px] text-slate-500 shrink-0">{tr('内容自动保存到本地浏览器。', 'Content is auto-saved in browser.', '内容はブラウザに自動保存されます。')}</p>
          </div>
        </div>
      </div>

      {showTodoModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm p-4 md:p-8 flex items-center justify-center">
          <div role="dialog" aria-modal="true" aria-labelledby="worklog-todo-title" className="glass w-full max-w-2xl max-h-[85vh] overflow-hidden rounded-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h4 id="worklog-todo-title" className="text-base font-semibold text-slate-900">{tr('全部待办事项', 'All Todo Items', 'すべてのTODO')}</h4>
              <button onClick={() => setShowTodoModal(false)} aria-label={tr('关闭待办弹窗', 'Close todo dialog', 'TODOダイアログを閉じる')} className="p-2 rounded-lg hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-600" />
              </button>
            </div>

            <div className="p-5 space-y-3 overflow-y-auto max-h-[calc(85vh-76px)] scrollbar-thin">
              <div className="flex gap-2">
                <input
                  value={todoInput}
                  onChange={(e) => setTodoInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') addTodo()
                  }}
                  placeholder={tr('输入近期任务', 'Enter upcoming task', '近日中のタスクを入力')}
                  className="input"
                />
                <button onClick={addTodo} className="btn-secondary px-3 py-2" title={tr('添加待办', 'Add todo', 'TODOを追加')}>
                  <Plus className="w-4 h-4" />
                </button>
              </div>

              {todos.length === 0 ? (
                <p className="text-sm text-slate-500">{tr('暂无待办事项', 'No todo items', 'TODOはありません')}</p>
              ) : (
                todos.map((todo) => (
                  <div key={todo.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <label className="flex items-center gap-2 min-w-0 flex-1">
                      <input type="checkbox" checked={todo.done} onChange={() => toggleTodo(todo.id)} className="h-4 w-4" />
                      <span className={`text-sm truncate ${todo.done ? 'line-through text-slate-400' : 'text-slate-700'}`}>{todo.text}</span>
                    </label>
                    <button onClick={() => removeTodo(todo.id)} title={tr('删除', 'Delete', '削除')} className="text-xs text-rose-600 hover:text-rose-700">{tr('删除', 'Delete', '削除')}</button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {selectedDayKey && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm p-4 md:p-8 flex items-center justify-center">
          <div role="dialog" aria-modal="true" aria-labelledby="worklog-day-title" className="glass w-full max-w-3xl max-h-[85vh] overflow-hidden rounded-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h4 id="worklog-day-title" className="text-base font-semibold text-slate-900">{selectedDayKey} {tr('文件明细', 'File Details', 'ファイル詳細')}</h4>
              <button onClick={() => setSelectedDayKey(null)} aria-label={tr('关闭文件明细弹窗', 'Close file detail dialog', 'ファイル詳細ダイアログを閉じる')} className="p-2 rounded-lg hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-600" />
              </button>
            </div>

            <div className="p-5 space-y-3 overflow-y-auto max-h-[calc(85vh-76px)] scrollbar-thin">
              {dayDetailDocs.length === 0 ? (
                <p className="text-sm text-slate-500">{tr('当天暂无文件记录。', 'No file records for this day.', '当日のファイル記録はありません。')}</p>
              ) : (
                dayDetailDocs.map((doc) => (
                  <div key={doc.id} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-slate-800 truncate">{doc.original_filename}</p>
                      <span className={`text-xs px-2 py-0.5 rounded ${categoryStyle(doc.doc_category)}`}>
                        {categoryLabel(doc.doc_category, language)}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">
                      {parseSafeDate(doc.created_at)?.toLocaleString(language) || '-'}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
