import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { Network, Options } from 'vis-network/standalone'
import { DataSet } from 'vis-data'
import { Search, RefreshCw, Loader2, Network as NetworkIcon, List, Send, FileText, Filter } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import { useDocumentStore } from '../stores/documentStore'

interface Node {
  id: string
  name: string
  type: string
  value?: string
  document_id?: string
}

interface Edge {
  source: string
  target: string
  type: string
  description?: string
}

interface QueryResult {
  answer: string
  relatedEntities: Node[]
}

// 使用 memo 包装图谱组件，避免不必要的重渲染
const GraphContainer = memo(({ nodes, edges }: { nodes: Node[], edges: Edge[] }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    // 清理旧实例
    if (networkRef.current) {
      networkRef.current.destroy()
      networkRef.current = null
    }

    if (nodes.length === 0) return

    const typeColors: Record<string, string> = {
      PERSON: '#3b82f6',
      LOCATION: '#22c55e',
      ORGANIZATION: '#a855f7',
      DATE: '#f97316',
      NUMBER: '#06b6d4',
      TABLE_DATA: '#ec4899',
      CUSTOM: '#eab308',
    }

    const visNodes = new DataSet(
      nodes.map((node) => ({
        id: node.id,
        label: node.name,
        color: {
          background: typeColors[node.type] || '#64748b',
          border: typeColors[node.type] || '#64748b',
          highlight: { background: '#6366f1', border: '#6366f1' },
        },
        font: { color: '#f1f5f9', size: 12 },
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
        color: { color: '#475569', highlight: '#6366f1' },
        font: { color: '#94a3b8', size: 10, strokeWidth: 0 },
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

  return (
    <div 
      ref={containerRef} 
      style={{ width: '100%', height: '100%', minHeight: '500px' }}
      className="bg-slate-900/50"
    />
  )
})

GraphContainer.displayName = 'GraphContainer'

export default function KnowledgeGraph() {
  const { documents, fetchDocuments } = useDocumentStore()
  const [allNodes, setAllNodes] = useState<Node[]>([])
  const [allEdges, setAllEdges] = useState<Edge[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph')
  const [query, setQuery] = useState('')
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null)
  const [isQuerying, setIsQuerying] = useState(false)
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('all')

  const sourceDocs = documents.filter(d => d.doc_category === 'source')

  useEffect(() => {
    fetchDocuments()
    fetchGraph()
  }, [fetchDocuments])

  const fetchGraph = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await api.get('/knowledge/graph', { params: { limit: 500 } })
      setAllNodes(response.data.nodes || [])
      setAllEdges(response.data.edges || [])
    } catch (error) {
      console.error('Fetch graph error:', error)
      toast.error('获取知识图谱失败')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // 过滤节点
  const filteredNodes = allNodes.filter(node => {
    const matchDoc = selectedDocs.length === 0 || selectedDocs.includes(node.document_id || '')
    const matchType = entityTypeFilter === 'all' || node.type === entityTypeFilter
    return matchDoc && matchType
  })

  // 过滤边
  const nodeIds = new Set(filteredNodes.map(n => n.id))
  const filteredEdges = allEdges.filter(edge => 
    nodeIds.has(edge.source) && nodeIds.has(edge.target)
  )

  const handleQuery = async () => {
    if (!query.trim()) return
    setIsQuerying(true)
    setQueryResult(null)
    try {
      const response = await api.post('/knowledge/query', { query })
      setQueryResult({
        answer: response.data.answer,
        relatedEntities: response.data.related_entities || [],
      })
    } catch {
      toast.error('查询失败')
    } finally {
      setIsQuerying(false)
    }
  }

  const toggleDocSelection = (docId: string) => {
    setSelectedDocs(prev =>
      prev.includes(docId) ? prev.filter(id => id !== docId) : [...prev, docId]
    )
  }

  const entityTypes = Array.from(new Set(allNodes.map(n => n.type)))

  const typeColors: Record<string, string> = {
    PERSON: 'bg-blue-500/20 text-blue-400',
    LOCATION: 'bg-green-500/20 text-green-400',
    ORGANIZATION: 'bg-purple-500/20 text-purple-400',
    DATE: 'bg-orange-500/20 text-orange-400',
    NUMBER: 'bg-cyan-500/20 text-cyan-400',
    TABLE_DATA: 'bg-pink-500/20 text-pink-400',
    CUSTOM: 'bg-yellow-500/20 text-yellow-400',
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* 左侧筛选面板 */}
        <div className="lg:col-span-1 space-y-4">
          {/* 文档选择 */}
          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
              <FileText className="w-4 h-4" />
              选择文档
            </h3>
            <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-thin">
              {sourceDocs.map((doc) => (
                <label
                  key={doc.id}
                  className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all
                    ${selectedDocs.includes(doc.id)
                      ? 'bg-primary-500/20 border border-primary-500/30'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                    }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(doc.id)}
                    onChange={() => toggleDocSelection(doc.id)}
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
                  />
                  <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="text-xs text-white truncate">{doc.original_filename}</span>
                </label>
              ))}
              {sourceDocs.length === 0 && (
                <p className="text-xs text-slate-500 text-center py-2">暂无源文档</p>
              )}
            </div>
            {selectedDocs.length > 0 && (
              <button
                onClick={() => setSelectedDocs([])}
                className="mt-3 text-xs text-primary-400 hover:text-primary-300"
              >
                清除选择（显示全部）
              </button>
            )}
          </div>

          {/* 实体类型筛选 */}
          <div className="glass p-4">
            <h3 className="text-sm font-medium text-slate-400 mb-3 flex items-center gap-2">
              <Filter className="w-4 h-4" />
              实体类型
            </h3>
            <select
              value={entityTypeFilter}
              onChange={(e) => setEntityTypeFilter(e.target.value)}
              className="input w-full"
            >
              <option value="all">全部类型</option>
              {entityTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>

          {/* 统计信息 */}
          <div className="glass p-4 space-y-3">
            <div className="flex justify-between">
              <span className="text-sm text-slate-400">实体节点</span>
              <span className="text-sm font-medium text-white">{filteredNodes.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-slate-400">关系边</span>
              <span className="text-sm font-medium text-white">{filteredEdges.length}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-slate-400">实体类型</span>
              <span className="text-sm font-medium text-white">{entityTypes.length}</span>
            </div>
          </div>
        </div>

        {/* 右侧主内容 */}
        <div className="lg:col-span-3 space-y-4">
          {/* 工具栏 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => setViewMode('graph')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                  ${viewMode === 'graph' ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
              >
                <NetworkIcon className="w-4 h-4" />
                图谱视图
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                  ${viewMode === 'list' ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
              >
                <List className="w-4 h-4" />
                列表视图
              </button>
            </div>
            <button
              onClick={fetchGraph}
              disabled={isLoading}
              className="btn-secondary flex items-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>

          {/* 搜索框 */}
          <div className="glass p-4">
            <div className="flex gap-3">
              <div className="relative flex-1">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleQuery()}
                  placeholder="在知识图谱中查询..."
                  className="input pl-12"
                />
              </div>
              <button
                onClick={handleQuery}
                disabled={isQuerying || !query.trim()}
                className="btn-primary disabled:opacity-50"
              >
                {isQuerying ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
              </button>
            </div>

            {queryResult && (
              <div className="mt-4 p-4 rounded-xl bg-primary-500/10 border border-primary-500/30">
                <p className="text-white mb-3">{queryResult.answer}</p>
                {queryResult.relatedEntities.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {queryResult.relatedEntities.map((entity, index) => (
                      <span
                        key={index}
                        className={`px-3 py-1 rounded-full text-xs ${typeColors[entity.type] || 'bg-gray-500/20 text-gray-400'}`}
                      >
                        {entity.name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 图谱/列表显示区域 */}
          {viewMode === 'graph' ? (
            <div className="glass overflow-hidden" style={{ height: '500px' }}>
              {filteredNodes.length > 0 ? (
                <GraphContainer nodes={filteredNodes} edges={filteredEdges} />
              ) : (
                <div className="h-full flex items-center justify-center bg-slate-900/50">
                  <div className="text-center">
                    <NetworkIcon className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                    <p className="text-slate-400">
                      {selectedDocs.length > 0 ? '选中的文档暂无知识图谱数据' : '暂无知识图谱数据'}
                    </p>
                    <p className="text-sm text-slate-500 mt-2">请先进行信息提取</p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="glass p-4 max-h-[500px] overflow-y-auto scrollbar-thin">
              {filteredNodes.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filteredNodes.map((node) => (
                    <div key={node.id} className="p-4 rounded-xl bg-white/5 border border-white/10 hover:border-primary-500/30 transition-colors">
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${typeColors[node.type] || 'bg-gray-500/20 text-gray-400'}`}>
                          {node.type}
                        </span>
                      </div>
                      <p className="text-white font-medium">{node.name}</p>
                      {node.value && <p className="text-sm text-slate-400 mt-1 truncate">{node.value}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-20">
                  <List className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                  <p className="text-slate-400">
                    {selectedDocs.length > 0 ? '选中的文档暂无实体数据' : '暂无实体数据'}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
