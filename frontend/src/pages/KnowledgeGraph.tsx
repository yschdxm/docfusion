import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { Network, Options } from 'vis-network/standalone'
import { DataSet } from 'vis-data'
import { RefreshCw, Network as NetworkIcon, List, FileText, Filter } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'
import Dropdown from '../components/ui/Dropdown'
import { useI18n } from '../hooks/useI18n'

interface Node {
  id: string
  name: string
  type: string
  value?: string
  document_ids?: string[]
}

interface Edge {
  source: string
  target: string
  type: string
  description?: string
}

/** 字符串哈希 → 色相，同类类型名始终同色 */
function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

function typeColor(type: string): string {
  const hue = hashStr(type) % 360
  return `hsl(${hue}, 65%, 60%)`
}

function typeBadgeStyle(type: string, dark = false): React.CSSProperties {
  const hue = hashStr(type) % 360
  if (dark) {
    return {
      backgroundColor: `hsl(${hue}, 40%, 20%)`,
      borderColor: `hsl(${hue}, 50%, 40%)`,
      color: `hsl(${hue}, 60%, 75%)`,
    }
  }
  return {
    backgroundColor: `hsl(${hue}, 80%, 95%)`,
    borderColor: `hsl(${hue}, 60%, 80%)`,
    color: `hsl(${hue}, 55%, 35%)`,
  }
}

const GraphContainer = memo(({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    if (networkRef.current) {
      networkRef.current.destroy()
      networkRef.current = null
    }

    if (nodes.length === 0) return

    const isDark = document.documentElement.getAttribute('data-theme') === 'night-mode'

    const uniqueNodes: Node[] = []
    const seenNodeIds = new Set<string>()
    for (const node of nodes) {
      if (!seenNodeIds.has(node.id)) {
        seenNodeIds.add(node.id)
        uniqueNodes.push(node)
      }
    }

    const visNodes = new DataSet(
      uniqueNodes.map((node) => ({
        id: node.id,
        label: node.name,
        color: {
          background: typeColor(node.type),
          border: typeColor(node.type),
          highlight: { background: '#165dff', border: '#165dff' },
        },
        font: { color: isDark ? '#e2e8f0' : '#1e293b', size: 12 },
        shape: 'dot',
        size: 20,
      }))
    )

    const visEdges = new DataSet(
      edges.map((edge, index) => ({
        id: `edge-${index}`,
        from: edge.source,
        to: edge.target,
        label: edge.type,
        color: { color: isDark ? '#475569' : '#94a3b8', highlight: '#165dff' },
        font: { color: isDark ? '#94a3b8' : '#64748b', size: 10, strokeWidth: 0 },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { enabled: true, type: 'continuous', roundness: 0.5 },
      }))
    )

    const options: Options = {
      nodes: { borderWidth: 2, borderWidthSelected: 3 },
      edges: { width: 1, selectionWidth: 2 },
      physics: {
        forceAtlas2Based: {
          gravitationalConstant: -50,
          centralGravity: 0.01,
          springLength: 100,
          springConstant: 0.08,
        },
        solver: 'forceAtlas2Based',
        stabilization: { iterations: 150 },
      },
      interaction: { hover: true, tooltipDelay: 200 },
    }

    networkRef.current = new Network(containerRef.current, { nodes: visNodes, edges: visEdges }, options)

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy()
        networkRef.current = null
      }
    }
  }, [nodes, edges])

  return <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: '500px' }} className="bg-slate-50" />
})

GraphContainer.displayName = 'GraphContainer'

export default function KnowledgeGraph() {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { documents, fetchDocuments } = useDocumentStore()
  const [allNodes, setAllNodes] = useState<Node[]>([])
  const [allEdges, setAllEdges] = useState<Edge[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('all')
  const [isDark, setIsDark] = useState(document.documentElement.getAttribute('data-theme') === 'night-mode')

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const sourceDocs = documents.filter((d) => d.doc_category === 'source')

  const fetchGraph = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await api.get('/knowledge/graph', { params: { limit: 500 } })
      setAllNodes(response.data.nodes || [])
      setAllEdges(response.data.edges || [])
    } catch (error) {
      console.error('Fetch graph error:', error)
      toast.error(tr('获取知识图谱失败', 'Failed to load knowledge graph', 'ナレッジグラフの取得に失敗しました'))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDocuments()
    fetchGraph()
  }, [fetchDocuments, fetchGraph])

  const filteredNodes = (() => {
    const filtered = allNodes.filter((node) => {
      const matchDoc = selectedDocs.length === 0 || (node.document_ids && node.document_ids.some((id) => selectedDocs.includes(id)))
      const matchType = entityTypeFilter === 'all' || node.type === entityTypeFilter
      return matchDoc && matchType
    })

    const uniqueNodes: Node[] = []
    const seenIds = new Set<string>()
    for (const node of filtered) {
      if (!seenIds.has(node.id)) {
        seenIds.add(node.id)
        uniqueNodes.push(node)
      }
    }
    return uniqueNodes
  })()

  const nodeIds = new Set(filteredNodes.map((n) => n.id))
  const filteredEdges = allEdges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))

  const toggleDocSelection = (docId: string) => {
    setSelectedDocs((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }

  const entityTypes = Array.from(new Set(allNodes.map((n) => n.type)))

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-500 mb-3 flex items-center gap-2">
              <FileText className="w-4 h-4" />
              {tr('选择文档', 'Select Documents', '文書を選択')}
            </h3>
            <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-thin">
              {sourceDocs.map((doc) => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-2 p-2.5 rounded-lg cursor-pointer transition-all ${
                    selectedDocs.includes(doc.id)
                      ? 'bg-blue-50 border border-blue-200'
                      : 'bg-slate-50 hover:bg-slate-100 border border-transparent'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleDocSelection(doc.id)}
                    className="w-4 h-4 rounded border-slate-300 bg-white text-primary-500"
                  />
                  <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="text-xs text-slate-900 truncate">{doc.original_filename}</span>
                </label>
              ))}
              {sourceDocs.length === 0 && <p className="text-xs text-slate-500 text-center py-2">{tr('暂无源文档', 'No source documents', 'ソース文書がありません')}</p>}
            </div>
            {selectedDocs.length > 0 && (
              <button onClick={() => setSelectedDocs([])} className="mt-3 text-xs text-primary-500 hover:text-primary-600">
                {tr('清除选择（显示全部）', 'Clear selection (show all)', '選択をクリア（すべて表示）')}
              </button>
            )}
          </div>

          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-500 mb-3 flex items-center gap-2">
              <Filter className="w-4 h-4" />
              {tr('实体类型', 'Entity Type', 'エンティティ種別')}
            </h3>
            <Dropdown
              value={entityTypeFilter}
              onChange={setEntityTypeFilter}
              options={[{ value: 'all', label: tr('全部类型', 'All Types', 'すべての種別') }, ...entityTypes.map((type) => ({ value: type, label: type }))]}
              placeholder={tr('选择实体类型', 'Select entity type', 'エンティティ種別を選択')}
            />
          </div>

          <div className="glass p-4 space-y-3">
            <div className="flex justify-between">
              <span className="text-sm text-slate-500">{tr('实体节点', 'Entity Nodes', 'エンティティノード')}</span>
              <span className="text-sm font-medium text-slate-900">{filteredNodes.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-slate-500">{tr('关系边', 'Edges', '関係エッジ')}</span>
              <span className="text-sm font-medium text-slate-900">{filteredEdges.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-slate-500">{tr('实体类型', 'Entity Types', 'エンティティ種別')}</span>
              <span className="text-sm font-medium text-slate-900">{entityTypes.length}</span>
            </div>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => setViewMode('graph')}
                className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                  viewMode === 'graph'
                    ? 'bg-white text-slate-900 border border-slate-300 shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-50'
                }`}
              >
                <NetworkIcon className="w-4 h-4" />
                {tr('图谱视图', 'Graph View', 'グラフ表示')}
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                  viewMode === 'list'
                    ? 'bg-white text-slate-900 border border-slate-300 shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-50'
                }`}
              >
                <List className="w-4 h-4" />
                {tr('列表视图', 'List View', 'リスト表示')}
              </button>
            </div>
            <button onClick={fetchGraph} disabled={isLoading} className="btn-secondary flex items-center gap-2">
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              {tr('刷新', 'Refresh', '更新')}
            </button>
          </div>

          {viewMode === 'graph' ? (
            <div className="glass overflow-hidden" style={{ height: '500px' }}>
              {filteredNodes.length > 0 ? (
                <GraphContainer nodes={filteredNodes} edges={filteredEdges} />
              ) : (
                <div className="h-full flex items-center justify-center bg-slate-50">
                  <div className="text-center">
                    <NetworkIcon className="w-16 h-16 mx-auto mb-4 text-slate-400" />
                    <p className="text-slate-600">{selectedDocs.length > 0 ? tr('选中文档暂无图谱数据', 'No graph data for selected documents', '選択文書にグラフデータがありません') : tr('暂无知识图谱数据', 'No knowledge graph data', 'ナレッジグラフデータがありません')}</p>
                    <p className="text-sm text-slate-500 mt-2">{tr('请先完成文档信息提取', 'Please complete document extraction first', '先に文書抽出を完了してください')}</p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="glass p-3 max-h-[500px] overflow-y-auto scrollbar-thin">
              {filteredNodes.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {filteredNodes.map((node) => (
                    <div key={node.id} className="p-3 rounded-lg bg-slate-50 border border-slate-200 hover:border-primary-200 transition-colors">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="px-2 py-0.5 rounded text-xs border" style={typeBadgeStyle(node.type, isDark)}>{node.type}</span>
                      </div>
                      <p className="text-slate-900 font-medium">{node.name}</p>
                      {node.value && <p className="text-sm text-slate-500 mt-1 truncate">{node.value}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-20">
                  <List className="w-16 h-16 mx-auto mb-4 text-slate-400" />
                  <p className="text-slate-600">{selectedDocs.length > 0 ? tr('选中文档暂无实体数据', 'No entities for selected documents', '選択文書にエンティティがありません') : tr('暂无实体数据', 'No entities', 'エンティティがありません')}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
