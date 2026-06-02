import { useState, useEffect } from 'react'
import { useI18n } from '../hooks/useI18n'
import { getAuthUser, isSuperAdmin } from '../services/auth'
import {
  getAdminUsers, getAdminUser, updateAdminUser, updateUserRole,
  getSystemConfigs, updateSystemConfigs,
  getSharedDocs, setDocShared, removeDocShared,
  AdminUser, SharedDoc,
} from '../services/admin'
import api from '../services/api'
import toast from 'react-hot-toast'
import {
  Users, Settings, Share, Search, Edit, Trash2, Save,
  FileText, Table, Lock, Unlock, Eye, EyeOff, RefreshCw, Plus, ChevronDown, X, Boxes,
  Download, Upload, FolderOpen,
} from 'lucide-react'
import Dropdown from '../components/ui/Dropdown'
import DocumentPreviewModal from '../components/DocumentPreviewModal'

type AdminTab = 'users' | 'registration' | 'models' | 'shared-docs'

interface LlmModel {
  name: string
  max_context_tokens: string
  max_output_tokens: string
}

interface LlmProvider {
  id: string
  name: string
  api_key: string
  base_url: string
  models: LlmModel[]
}

interface ModelForm {
  api_key: string
  base_url: string
  model: string
  max_context_tokens: string
  max_output_tokens: string
}

// 生成短ID
const genId = () => Math.random().toString(36).substring(2, 10)

// 文档分类图标（与 DocumentManager 保持一致）
const categoryIconMap: Record<string, { icon: typeof FileText; color: string; bg: string }> = {
  source: { icon: FileText, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-100 dark:bg-blue-900/30' },
  template: { icon: Table, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-100 dark:bg-emerald-900/30' },
  output: { icon: FolderOpen, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-100 dark:bg-amber-900/30' },
}

const DocCategoryIcon = ({ category, size = 'md' }: { category: string; size?: 'sm' | 'md' }) => {
  const config = categoryIconMap[category] || categoryIconMap.source
  const Icon = config.icon
  const sizeClass = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'
  return (
    <div className={`w-9 h-9 shrink-0 rounded-lg ${config.bg} flex items-center justify-center ${config.color}`}>
      <Icon className={sizeClass} />
    </div>
  )
}

const zh = {
  title: '管理中心',
  tabs: { users: '用户管理', registration: '注册控制', models: '模型配置', docs: '共享文档' },
  search: '搜索用户名/邮箱/手机号', roleFilter: '所有角色',
  user: '用户', admin: '管理员', superAdmin: '主管理员',
  active: '正常', inactive: '停用',
  edit: '编辑', viewFiles: '查看文件',
  username: '用户名', email: '邮箱', phone: '手机号', role: '角色', status: '状态', actions: '操作',
  password: '密码', newPassword: '新密码', passwordHint: '留空则不修改',
  save: '保存', cancel: '取消', close: '关闭',
  regOpen: '开放注册', regClosed: '关闭注册', regHint: '关闭后新用户将无法注册',
  apiKey: 'API Key', baseUrl: 'Base URL', model: '模型名称', selectModel: '选择模型',
  fetchModels: '获取模型列表', fetching: '获取中...', maxCtx: '上下文长度', maxOut: '最大输出长度',
  llmConfig: 'LLM 供应商配置', addLlm: '添加供应商', removeLlm: '移除',
  embConfig: '嵌入模型配置', rerankConfig: '重排模型配置',
  rateLimit: '流控配置', rpm: '每分钟请求 (RPM)', tpm: '每分钟Token (TPM)',
  providerName: '供应商名称', providerNameHint: '例如: openai, deepseek, mimo',
  sharedDocs: '共享文档', noDocs: '暂无文档', sourceDocs: '原文档', templates: '模板', outputDocs: '输出文档', all: '全部',
  addShared: '添加共享文档', setShared: '设为共享', removeShared: '取消共享',
  editUser: '编辑用户', userFiles: '用户文件',
  roleChangeHint: '注意：被赋予权限的管理员不能再赋予其他用户权限',
  selfProtect: '不能修改自己的账号状态',
  deleteConfirm: '确定要删除这个供应商及其所有模型吗？',
  addModel: '添加模型',
  noModels: '暂无模型，请先获取模型列表',
  modelsCount: '个模型',
  availableModels: '可用模型',
  clickToAdd: '点击添加',
  removeModel: '移除',
  importConfig: '导入配置',
  exportConfig: '导出配置',
  exportSuccess: '配置已导出',
  importSuccess: '已导入',
  importFormatError: '配置文件格式错误',
  importParseError: '配置文件解析失败，请检查JSON格式',
  providers: '个供应商',
  // 按钮提示
  toggleStatus: '启用/停用', prevPage: '上一页', nextPage: '下一页',
  toggleReg: '切换注册状态', showKey: '显示密钥', hideKey: '隐藏密钥',
  removeProvider: '删除供应商', fetchModelsHint: '获取模型列表',
  addModelHint: '点击添加模型', removeModelHint: '移除模型',
  importHint: '从JSON文件导入配置', exportHint: '导出配置为JSON文件',
  saveHint: '保存所有配置', removeSharedHint: '取消共享', setSharedHint: '设为共享',
  // 用户文件弹窗
  sourceDocsCat: '原文档', templateDocsCat: '模板', allDocs: '全部',
  download: '下载', preview: '预览',
  downloadSuccess: '下载已开始', downloadFail: '下载失败',
  outputDocsCat: '输出文档',
}

const en = {
  title: 'Admin Center',
  tabs: { users: 'Users', registration: 'Registration', models: 'Models', docs: 'Shared Docs' },
  search: 'Search username/email/phone', roleFilter: 'All Roles',
  user: 'User', admin: 'Admin', superAdmin: 'Super Admin',
  active: 'Active', inactive: 'Inactive', edit: 'Edit', viewFiles: 'View Files',
  username: 'Username', email: 'Email', phone: 'Phone', role: 'Role', status: 'Status', actions: 'Actions',
  password: 'Password', newPassword: 'New Password', passwordHint: 'Leave empty to keep',
  save: 'Save', cancel: 'Cancel', close: 'Close',
  regOpen: 'Registration Open', regClosed: 'Registration Closed', regHint: 'New users cannot register when closed',
  apiKey: 'API Key', baseUrl: 'Base URL', model: 'Model', selectModel: 'Select Model',
  fetchModels: 'Fetch Models', fetching: 'Fetching...', maxCtx: 'Max Context', maxOut: 'Max Output',
  llmConfig: 'LLM Provider Config', addLlm: 'Add Provider', removeLlm: 'Remove',
  embConfig: 'Embedding Config', rerankConfig: 'Rerank Config',
  rateLimit: 'Rate Limit', rpm: 'Requests/Min (RPM)', tpm: 'Tokens/Min (TPM)',
  providerName: 'Provider Name', providerNameHint: 'e.g. openai, deepseek, mimo',
  sharedDocs: 'Shared Docs', noDocs: 'No documents', sourceDocs: 'Source', templates: 'Templates', outputDocs: 'Output', all: 'All',
  addShared: 'Add Shared Documents', setShared: 'Set Shared', removeShared: 'Remove Shared',
  editUser: 'Edit User', userFiles: 'User Files',
  roleChangeHint: 'Note: Admins cannot grant admin privileges to other users',
  selfProtect: 'Cannot modify your own account status',
  deleteConfirm: 'Delete this provider and all its models?',
  addModel: 'Add Model',
  noModels: 'No models yet, fetch models first',
  modelsCount: 'models',
  availableModels: 'Available Models',
  clickToAdd: 'Click to add',
  removeModel: 'Remove',
  importConfig: 'Import Config',
  exportConfig: 'Export Config',
  exportSuccess: 'Config exported',
  importSuccess: 'Imported',
  importFormatError: 'Invalid config file format',
  importParseError: 'Failed to parse config file, check JSON format',
  providers: ' providers',
  // Button tooltips
  toggleStatus: 'Enable/Disable', prevPage: 'Previous', nextPage: 'Next',
  toggleReg: 'Toggle registration', showKey: 'Show key', hideKey: 'Hide key',
  removeProvider: 'Remove provider', fetchModelsHint: 'Fetch model list',
  addModelHint: 'Click to add model', removeModelHint: 'Remove model',
  importHint: 'Import config from JSON', exportHint: 'Export config as JSON',
  saveHint: 'Save all settings', removeSharedHint: 'Remove shared', setSharedHint: 'Set as shared',
  // User files modal
  sourceDocsCat: 'Source', templateDocsCat: 'Templates', allDocs: 'All',
  download: 'Download', preview: 'Preview',
  downloadSuccess: 'Download started', downloadFail: 'Download failed',
  outputDocsCat: 'Output',
}

export default function AdminCenter() {
  const { language } = useI18n()
  const tl = language === 'en-US' ? en : zh
  const currentUser = getAuthUser()
  const isSuper = isSuperAdmin()

  const [activeTab, setActiveTab] = useState<AdminTab>('users')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [totalUsers, setTotalUsers] = useState(0)
  const [userPage, setUserPage] = useState(1)
  const [userSearch, setUserSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null)
  const [viewingUserDocs, setViewingUserDocs] = useState<{ user: AdminUser; docs: any[] } | null>(null)
  const [editForm, setEditForm] = useState({ username: '', email: '', phone: '', password: '' })
  const [registrationEnabled, setRegistrationEnabled] = useState(true)

  // 供应商和模型
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)
  const [fetchingModels, setFetchingModels] = useState<string | null>(null)
  const [fetchedModels, setFetchedModels] = useState<Record<string, string[]>>({})

  // 嵌入和重排
  const [embeddingForm, setEmbeddingForm] = useState<ModelForm>({ api_key: '', base_url: '', model: '', max_context_tokens: '', max_output_tokens: '' })
  const [rerankForm, setRerankForm] = useState<ModelForm>({ api_key: '', base_url: '', model: '', max_context_tokens: '', max_output_tokens: '' })
  const [embeddingFetchedModels, setEmbeddingFetchedModels] = useState<string[] | null>(null)
  const [rerankFetchedModels, setRerankFetchedModels] = useState<string[] | null>(null)

  // 流控
  const [rateLimitForm, setRateLimitForm] = useState({ rpm: '100', tpm: '10000000' })

  // 通用
  const [showApiKeys, setShowApiKeys] = useState<Record<string, boolean>>({})
  const [sharedDocs, setSharedDocs] = useState<SharedDoc[]>([])
  const [allDocs, setAllDocs] = useState<any[]>([])
  const [sharedDocCategory, setSharedDocCategory] = useState('')
  const [docSearch, setDocSearch] = useState('')
  const [previewDoc, setPreviewDoc] = useState<any>(null)
  const [userDocCategory, setUserDocCategory] = useState<string>('')

  const loadUsers = async () => {
    try {
      const data = await getAdminUsers({ page: userPage, page_size: 20, search: userSearch || undefined, role: roleFilter || undefined })
      setUsers(data.users); setTotalUsers(data.total)
    } catch (e) { console.error(e) }
  }

  const loadConfigs = async () => {
    try {
      const data = await getSystemConfigs()
      const cm: Record<string, string> = {}
      data.forEach((c) => { cm[c.key] = c.value })

      // 解析供应商列表
      try {
        const providersJson = cm.llm_providers
        if (providersJson) {
          const parsed: LlmProvider[] = JSON.parse(providersJson)
          // 从配置中恢复每个供应商的模型列表
          const restored: LlmProvider[] = parsed.map((p) => {
            const models: LlmModel[] = []
            // 查找该供应商的所有模型配置
            const prefix = `llm_${p.id}_`
            for (const key of Object.keys(cm)) {
              if (key.startsWith(prefix) && key.endsWith('_max_context_tokens')) {
                const modelName = key.slice(prefix.length, -('_max_context_tokens'.length))
                if (modelName) {
                  models.push({
                    name: modelName,
                    max_context_tokens: cm[key] || '',
                    max_output_tokens: cm[`llm_${p.id}_${modelName}_max_output_tokens`] || '',
                  })
                }
              }
            }
            return { ...p, models }
          })
          setProviders(restored)
        } else {
          setProviders([])
        }
      } catch {
        setProviders([])
      }

      // 嵌入模型
      setEmbeddingForm({
        api_key: cm.embedding_api_key || '',
        base_url: cm.embedding_base_url || '',
        model: cm.embedding_model || '',
        max_context_tokens: '',
        max_output_tokens: '',
      })

      // 重排模型
      setRerankForm({
        api_key: cm.rerank_api_key || '',
        base_url: cm.rerank_base_url || '',
        model: cm.rerank_model || '',
        max_context_tokens: '',
        max_output_tokens: '',
      })

      // 流控
      setRateLimitForm({ rpm: cm.llm_rpm || '100', tpm: cm.llm_tpm || '10000000' })

      // 注册
      setRegistrationEnabled(cm.registration_enabled !== 'false')
    } catch (e) { console.error(e) }
  }

  const loadSharedDocs = async () => {
    try { const data = await getSharedDocs(sharedDocCategory || undefined); setSharedDocs(data.documents) }
    catch (e) { console.error(e) }
  }

  const loadAllDocs = async () => {
    try { const { data } = await api.get('/documents'); setAllDocs(data || []) }
    catch (e) { console.error(e) }
  }

  useEffect(() => {
    if (activeTab === 'users') loadUsers()
    else if (activeTab === 'models' || activeTab === 'registration') loadConfigs()
    else if (activeTab === 'shared-docs') { loadSharedDocs(); loadAllDocs() }
  }, [activeTab, userPage, userSearch, roleFilter, sharedDocCategory])

  // ==================== 供应商操作 ====================

  const addProvider = () => {
    const newProvider: LlmProvider = {
      id: genId(),
      name: '',
      api_key: '',
      base_url: '',
      models: [],
    }
    setProviders([...providers, newProvider])
    setExpandedProvider(newProvider.id)
  }

  const removeProvider = (id: string) => {
    if (!confirm(tl.deleteConfirm)) return
    setProviders(providers.filter((p) => p.id !== id))
    if (expandedProvider === id) setExpandedProvider(null)
  }

  const updateProvider = (id: string, field: keyof LlmProvider, value: any) => {
    setProviders(providers.map((p) => p.id === id ? { ...p, [field]: value } : p))
  }

  const handleFetchModels = async (providerId: string) => {
    const provider = providers.find((p) => p.id === providerId)
    if (!provider || !provider.api_key || !provider.base_url) {
      toast.error('请先填写 API Key 和 Base URL')
      return
    }
    setFetchingModels(providerId)
    try {
      const { data } = await api.post('/admin/configs/fetch-models', {
        api_key: provider.api_key,
        base_url: provider.base_url,
      })
      const modelNames = data.models.map((m: any) => m.id)
      setFetchedModels((prev) => ({ ...prev, [providerId]: modelNames }))
      toast.success(`获取到 ${modelNames.length} 个模型`)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '获取模型列表失败')
    } finally {
      setFetchingModels(null)
    }
  }

  const addModelToProvider = (providerId: string, modelName: string) => {
    setProviders(providers.map((p) => {
      if (p.id !== providerId) return p
      if (p.models.some((m) => m.name === modelName)) return p
      return {
        ...p,
        models: [...p.models, { name: modelName, max_context_tokens: '', max_output_tokens: '' }],
      }
    }))
  }

  const removeModelFromProvider = (providerId: string, modelName: string) => {
    setProviders(providers.map((p) => {
      if (p.id !== providerId) return p
      return { ...p, models: p.models.filter((m) => m.name !== modelName) }
    }))
  }

  const updateModelField = (providerId: string, modelName: string, field: keyof LlmModel, value: string) => {
    setProviders(providers.map((p) => {
      if (p.id !== providerId) return p
      return {
        ...p,
        models: p.models.map((m) => m.name === modelName ? { ...m, [field]: value } : m),
      }
    }))
  }

  // ==================== 嵌入/重排获取模型 ====================

  const handleFetchModelsForService = async (type: 'embedding' | 'rerank') => {
    const form = type === 'embedding' ? embeddingForm : rerankForm
    if (!form.api_key || !form.base_url) {
      toast.error('请先填写 API Key 和 Base URL')
      return
    }
    setFetchingModels(type)
    try {
      const { data } = await api.post('/admin/configs/fetch-models', {
        api_key: form.api_key,
        base_url: form.base_url,
      })
      const modelNames = data.models.map((m: any) => m.id)
      if (type === 'embedding') {
        setEmbeddingFetchedModels(modelNames)
      } else {
        setRerankFetchedModels(modelNames)
      }
      toast.success(`获取到 ${modelNames.length} 个模型`)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '获取模型列表失败')
    } finally {
      setFetchingModels(null)
    }
  }

  // ==================== 保存 ====================

  const handleSaveUser = async () => {
    if (!editingUser) return
    try {
      await updateAdminUser(editingUser.id, { username: editForm.username, email: editForm.email, phone: editForm.phone, password: editForm.password || undefined })
      toast.success('用户信息已更新'); setEditingUser(null); loadUsers()
    } catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  const handleChangeRole = async (userId: string, newRole: string) => {
    if (!confirm('确定要修改该用户的角色吗？')) return
    try { await updateUserRole(userId, newRole); toast.success('角色已更新'); loadUsers() }
    catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  const handleToggleUserStatus = async (user: AdminUser) => {
    if (user.id === currentUser?.id) { toast.error(tl.selfProtect); return }
    try { await updateAdminUser(user.id, { is_active: !user.is_active }); toast.success('用户状态已更新'); loadUsers() }
    catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  const handleSaveRegistration = async () => {
    try { await updateSystemConfigs({ registration_enabled: String(registrationEnabled) }); toast.success('配置已保存') }
    catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  const handleSaveModelConfig = async () => {
    // 校验：每个供应商的每个模型都必须填写上下文长度和最大输出长度
    for (const p of providers) {
      for (const m of p.models) {
        if (!m.max_context_tokens || !m.max_output_tokens) {
          toast.error(`请填写供应商「${p.name || '未命名'}」中模型「${m.name}」的上下文长度和最大输出长度`)
          return
        }
      }
    }

    try {
      const configs: Record<string, string> = {}

      // 保存供应商列表
      configs.llm_providers = JSON.stringify(providers.map((p) => ({
        id: p.id,
        name: p.name,
        api_key: p.api_key,
        base_url: p.base_url,
      })))

      // 保存每个供应商的模型配置
      providers.forEach((p) => {
        p.models.forEach((m) => {
          configs[`llm_${p.id}_${m.name}_max_context_tokens`] = m.max_context_tokens
          configs[`llm_${p.id}_${m.name}_max_output_tokens`] = m.max_output_tokens
        })
      })

      // 保存嵌入和重排
      if (embeddingForm.api_key) configs.embedding_api_key = embeddingForm.api_key
      if (embeddingForm.base_url) configs.embedding_base_url = embeddingForm.base_url
      if (embeddingForm.model) configs.embedding_model = embeddingForm.model
      if (rerankForm.api_key) configs.rerank_api_key = rerankForm.api_key
      if (rerankForm.base_url) configs.rerank_base_url = rerankForm.base_url
      if (rerankForm.model) configs.rerank_model = rerankForm.model

      // 保存流控
      configs.llm_rpm = rateLimitForm.rpm
      configs.llm_tpm = rateLimitForm.tpm

      await updateSystemConfigs(configs)
      toast.success('配置已保存')
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '操作失败')
    }
  }

  const handleSetShared = async (docId: string) => {
    try { await setDocShared(docId); toast.success('文档已设为共享'); loadSharedDocs(); loadAllDocs() }
    catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  const handleRemoveShared = async (docId: string) => {
    if (!confirm('确定要取消该文档的共享吗？')) return
    try { await removeDocShared(docId); toast.success('已取消共享'); loadSharedDocs(); loadAllDocs() }
    catch (error: any) { toast.error(error.response?.data?.detail || '操作失败') }
  }

  // ==================== 用户文件操作 ====================

  const handleDownloadDoc = async (doc: any) => {
    try {
      const response = await api.get(`/documents/${doc.id}/download`, { responseType: 'blob' })
      const disposition = response.headers['content-disposition'] as string | undefined
      let filename = doc.original_filename
      if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i)
        if (utf8Match) filename = decodeURIComponent(utf8Match[1])
        else {
          const plainMatch = disposition.match(/filename="?([^";\n]+)"?/)
          if (plainMatch) filename = plainMatch[1]
        }
      }
      const blob = response.data instanceof Blob
        ? response.data
        : new Blob([response.data], { type: response.headers['content-type'] || 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
      toast.success(tl.downloadSuccess)
    } catch {
      toast.error(tl.downloadFail)
    }
  }

  // ==================== 导入导出 ====================

  const handleExportConfig = () => {
    const exportData = {
      version: 1,
      exported_at: new Date().toISOString(),
      providers: providers.map((p) => ({
        name: p.name,
        api_key: p.api_key,
        base_url: p.base_url,
        models: p.models,
      })),
      embedding: {
        api_key: embeddingForm.api_key,
        base_url: embeddingForm.base_url,
        model: embeddingForm.model,
      },
      rerank: {
        api_key: rerankForm.api_key,
        base_url: rerankForm.base_url,
        model: rerankForm.model,
      },
      rate_limit: {
        rpm: rateLimitForm.rpm,
        tpm: rateLimitForm.tpm,
      },
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `docfusion-model-config-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast.success(tl.exportSuccess)
  }

  const handleImportConfig = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return

      try {
        const text = await file.text()
        const data = JSON.parse(text)

        if (!data.version || !data.providers) {
          toast.error(tl.importFormatError)
          return
        }

        // 导入供应商
        const importedProviders: LlmProvider[] = data.providers.map((p: any) => ({
          id: genId(),
          name: p.name || '',
          api_key: p.api_key || '',
          base_url: p.base_url || '',
          models: Array.isArray(p.models) ? p.models.map((m: any) => ({
            name: m.name || '',
            max_context_tokens: m.max_context_tokens || '',
            max_output_tokens: m.max_output_tokens || '',
          })) : [],
        }))
        setProviders(importedProviders)

        // 导入嵌入模型
        if (data.embedding) {
          setEmbeddingForm({
            api_key: data.embedding.api_key || '',
            base_url: data.embedding.base_url || '',
            model: data.embedding.model || '',
            max_context_tokens: '',
            max_output_tokens: '',
          })
        }

        // 导入重排模型
        if (data.rerank) {
          setRerankForm({
            api_key: data.rerank.api_key || '',
            base_url: data.rerank.base_url || '',
            model: data.rerank.model || '',
            max_context_tokens: '',
            max_output_tokens: '',
          })
        }

        // 导入流控
        if (data.rate_limit) {
          setRateLimitForm({
            rpm: data.rate_limit.rpm || '100',
            tpm: data.rate_limit.tpm || '10000000',
          })
        }

        // 展开第一个供应商
        if (importedProviders.length > 0) {
          setExpandedProvider(importedProviders[0].id)
        }

        toast.success(`${tl.importSuccess} ${importedProviders.length} ${tl.providers}`)
      } catch {
        toast.error(tl.importParseError)
      }
    }
    input.click()
  }

  // ==================== 工具函数 ====================

  const getRoleBadge = (role: string) => {
    const s: Record<string, string> = { user: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300', admin: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300', super_admin: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300' }
    const l: Record<string, string> = { user: tl.user, admin: tl.admin, super_admin: tl.superAdmin }
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${s[role] || s.user}`}>{l[role] || role}</span>
  }

  const nonSharedDocs = allDocs.filter((doc) => !doc.is_shared)

  const tabs = [
    { key: 'users' as AdminTab, icon: Users, label: tl.tabs.users },
    { key: 'registration' as AdminTab, icon: Settings, label: tl.tabs.registration },
    { key: 'models' as AdminTab, icon: Boxes, label: tl.tabs.models },
    { key: 'shared-docs' as AdminTab, icon: Share, label: tl.tabs.docs },
  ]

  const renderFormInput = (label: string, value: string, onChange: (v: string) => void, options?: { type?: string; placeholder?: string; icon?: React.ReactNode }) => (
    <div>
      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{label}</label>
      <div className="relative">
        <input
          type={options?.type || 'text'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={options?.placeholder}
          className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 text-slate-900 dark:text-slate-100 px-4 py-2.5 pr-10 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
        />
        {options?.icon && <div className="absolute right-3 top-1/2 -translate-y-1/2">{options.icon}</div>}
      </div>
    </div>
  )

  const renderServiceConfigCard = (
    title: string,
    form: ModelForm,
    setForm: (f: ModelForm) => void,
    fetchKey: string,
    onFetch: () => void,
    fetchedModels: string[] | null,
  ) => (
    <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700">
      <div className="p-4 sm:p-5 border-b border-slate-100 dark:border-slate-700 rounded-t-2xl">
        <h4 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h4>
      </div>
      <div className="p-4 sm:p-5">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {renderFormInput(tl.apiKey, form.api_key, (v) => setForm({ ...form, api_key: v }), {
            type: showApiKeys[fetchKey] ? 'text' : 'password',
            icon: (
              <button type="button" onClick={() => setShowApiKeys({ ...showApiKeys, [fetchKey]: !showApiKeys[fetchKey] })}
                title={showApiKeys[fetchKey] ? tl.hideKey : tl.showKey}
                className="text-slate-400 hover:text-slate-600">
                {showApiKeys[fetchKey] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            )
          })}
          {renderFormInput(tl.baseUrl, form.base_url, (v) => setForm({ ...form, base_url: v }), { placeholder: 'https://api.openai.com/v1' })}

          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{tl.model}</label>
            <div className="flex gap-2">
              {fetchedModels ? (
                <div className="flex-1">
                  <Dropdown
                    value={form.model}
                    onChange={(v) => setForm({ ...form, model: v })}
                    options={[{ value: '', label: tl.selectModel }, ...fetchedModels.map((m) => ({ value: m, label: m }))]}
                    className="w-full"
                    searchable
                  />
                </div>
              ) : (
                <input type="text" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="text-embedding-3-small"
                  className="flex-1 rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 text-slate-900 dark:text-slate-100 px-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500" />
              )}
              <button type="button" onClick={onFetch} disabled={fetchingModels === fetchKey || !form.api_key || !form.base_url}
                title={tl.fetchModelsHint}
                className="flex items-center gap-1.5 rounded-xl bg-slate-100 dark:bg-slate-700 px-3 py-2 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 transition-colors shrink-0">
                <RefreshCw className={`h-4 w-4 ${fetchingModels === fetchKey ? 'animate-spin' : ''}`} />
                <span className="hidden sm:inline">{fetchingModels === fetchKey ? tl.fetching : tl.fetchModels}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className="h-full flex flex-col">
      {/* 固定的Tab */}
      <div className="shrink-0 pb-4 border-b border-slate-200 dark:border-slate-700">
        <div className="flex gap-1 sm:gap-2 overflow-x-auto pb-1 scrollbar-none">
        {tabs.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-2 rounded-xl px-3 sm:px-4 py-2.5 text-sm font-medium transition-all whitespace-nowrap ${
              activeTab === tab.key ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/25' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}>
            <tab.icon className="h-4 w-4" />
            <span>{tab.label}</span>
          </button>
        ))}
        </div>
      </div>

      {/* 可滚动的内容区域 */}
      <div className="flex-1 min-h-0 overflow-y-auto pt-4 scrollbar-thin">
        {/* 用户管理 */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="text" placeholder={tl.search} value={userSearch} onChange={(e) => setUserSearch(e.target.value)}
                className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 pl-10 pr-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500" />
            </div>
            <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}
              className="rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 px-4 py-2.5 text-sm">
              <option value="">{tl.roleFilter}</option>
              <option value="user">{tl.user}</option>
              <option value="admin">{tl.admin}</option>
              {isSuper && <option value="super_admin">{tl.superAdmin}</option>}
            </select>
          </div>

          <div className="grid gap-3">
            {users.map((user) => (
              <div key={user.id} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-4 hover:shadow-lg transition-shadow">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-white font-semibold text-sm shrink-0">
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-semibold text-slate-900 dark:text-slate-100 truncate">{user.username}</p>
                        {getRoleBadge(user.role)}
                      </div>
                      <p className="text-sm text-slate-500 dark:text-slate-400 truncate">{user.email}</p>
                      <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{user.phone}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => { setEditingUser(user); setEditForm({ username: user.username, email: user.email, phone: user.phone, password: '' }) }}
                      className="p-2 rounded-lg text-slate-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 hover:text-blue-600 transition-colors" title={tl.edit}>
                      <Edit className="h-4 w-4" />
                    </button>
                    <button onClick={() => { setViewingUserDocs({ user, docs: [] }); getAdminUser(user.id).then((data) => setViewingUserDocs({ user, docs: data.documents })) }}
                      className="p-2 rounded-lg text-slate-400 hover:bg-green-50 dark:hover:bg-green-900/30 hover:text-green-600 transition-colors" title={tl.viewFiles}>
                      <FileText className="h-4 w-4" />
                    </button>
                    {isSuper && user.id !== currentUser?.id && user.role !== 'super_admin' && (
                      <select value={user.role} onChange={(e) => handleChangeRole(user.id, e.target.value)}
                        className="rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-1.5 text-xs">
                        <option value="user">{tl.user}</option>
                        <option value="admin">{tl.admin}</option>
                      </select>
                    )}
                    <button onClick={() => handleToggleUserStatus(user)}
                      title={user.is_active ? tl.inactive : tl.active}
                      className={`p-2 rounded-lg transition-colors ${user.id === currentUser?.id ? 'text-slate-300 cursor-not-allowed' : user.is_active ? 'text-slate-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600' : 'text-slate-400 hover:bg-green-50 dark:hover:bg-green-900/30 hover:text-green-600'}`}
                      disabled={user.id === currentUser?.id}>
                      {user.is_active ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {totalUsers > 20 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500 dark:text-slate-400">共 {totalUsers} 条</span>
              <div className="flex gap-2">
                <button onClick={() => setUserPage((p) => Math.max(1, p - 1))} disabled={userPage === 1}
                  className="rounded-lg px-3 py-1.5 text-sm bg-slate-100 dark:bg-slate-700 disabled:opacity-50">上一页</button>
                <span className="rounded-lg bg-blue-50 dark:bg-blue-900/30 px-3 py-1.5 text-sm text-blue-700 dark:text-blue-300">{userPage}</span>
                <button onClick={() => setUserPage((p) => p + 1)} disabled={userPage * 20 >= totalUsers}
                  className="rounded-lg px-3 py-1.5 text-sm bg-slate-100 dark:bg-slate-700 disabled:opacity-50">下一页</button>
              </div>
            </div>
          )}

          {isSuper && (
            <div className="rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
              {tl.roleChangeHint}
            </div>
          )}
        </div>
      )}

      {/* 注册控制 */}
      {activeTab === 'registration' && (
        <div className="max-w-md">
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{registrationEnabled ? tl.regOpen : tl.regClosed}</h3>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{tl.regHint}</p>
              </div>
              <button onClick={() => setRegistrationEnabled(!registrationEnabled)}
                title={tl.toggleReg}
                className={`relative h-8 w-14 rounded-full transition-colors ${registrationEnabled ? 'bg-blue-500' : 'bg-slate-300 dark:bg-slate-600'}`}>
                <span className={`absolute top-1 h-6 w-6 rounded-full bg-white shadow-sm transition-transform ${registrationEnabled ? 'left-7' : 'left-1'}`} />
              </button>
            </div>
            <button onClick={handleSaveRegistration} title={tl.saveHint}
              className="mt-6 flex items-center gap-2 rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-600 transition-colors shadow-lg shadow-blue-500/25">
              <Save className="h-4 w-4" />{tl.save}
            </button>
          </div>
        </div>
      )}

      {/* 模型配置 */}
      {activeTab === 'models' && (
        <div className="space-y-6">
          {/* LLM 供应商 */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{tl.llmConfig}</h3>
              <button onClick={addProvider}
                className="flex items-center gap-1.5 rounded-xl bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 transition-colors shadow-lg shadow-blue-500/25">
                <Plus className="h-4 w-4" />{tl.addLlm}
              </button>
            </div>

            {providers.length === 0 && (
              <div className="rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-8 text-center text-slate-400 dark:text-slate-500">
                暂无供应商，点击上方按钮添加
              </div>
            )}

            <div className="space-y-3">
              {providers.map((provider) => (
                <div key={provider.id} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700">
                  {/* 供应商标题栏 */}
                  <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                    onClick={() => setExpandedProvider(expandedProvider === provider.id ? null : provider.id)}>
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-3 h-3 rounded-full shrink-0 ${expandedProvider === provider.id ? 'bg-blue-500' : 'bg-slate-300 dark:bg-slate-600'}`} />
                      <div className="min-w-0">
                        <p className="font-medium text-slate-900 dark:text-slate-100 truncate">{provider.name || '未命名供应商'}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                          {provider.models.length > 0
                            ? `${provider.models.length} ${tl.modelsCount}: ${provider.models.map((m) => m.name).join(', ')}`
                            : provider.base_url || '未配置'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button onClick={(e) => { e.stopPropagation(); removeProvider(provider.id) }}
                        title={tl.removeProvider}
                        className="p-1.5 rounded-lg text-slate-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 transition-colors">
                        <Trash2 className="h-4 w-4" />
                      </button>
                      <ChevronDown className={`h-5 w-5 text-slate-400 transition-transform ${expandedProvider === provider.id ? 'rotate-180' : ''}`} />
                    </div>
                  </div>

                  {/* 展开的供应商内容 */}
                  {expandedProvider === provider.id && (
                    <div className="p-4 sm:p-5 border-t border-slate-100 dark:border-slate-700 space-y-5">
                      {/* 供应商信息 */}
                      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                        {renderFormInput(tl.providerName, provider.name, (v) => updateProvider(provider.id, 'name', v), { placeholder: tl.providerNameHint })}
                        {renderFormInput(tl.apiKey, provider.api_key, (v) => updateProvider(provider.id, 'api_key', v), {
                          type: showApiKeys[`prov_${provider.id}`] ? 'text' : 'password',
                          icon: (
                            <button type="button" onClick={() => setShowApiKeys({ ...showApiKeys, [`prov_${provider.id}`]: !showApiKeys[`prov_${provider.id}`] })}
                              title={showApiKeys[`prov_${provider.id}`] ? tl.hideKey : tl.showKey}
                              className="text-slate-400 hover:text-slate-600">
                              {showApiKeys[`prov_${provider.id}`] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          )
                        })}
                        {renderFormInput(tl.baseUrl, provider.base_url, (v) => updateProvider(provider.id, 'base_url', v), { placeholder: 'https://api.openai.com/v1' })}
                      </div>

                      {/* 获取模型 + 已选模型 */}
                      <div className="flex items-center justify-between">
                        <h5 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{tl.model} ({provider.models.length})</h5>
                        <button type="button" onClick={() => handleFetchModels(provider.id)}
                          title={tl.fetchModelsHint}
                          disabled={fetchingModels === provider.id || !provider.api_key || !provider.base_url}
                          className="flex items-center gap-1.5 rounded-xl bg-blue-50 dark:bg-blue-900/30 px-3 py-2 text-sm text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 disabled:opacity-50 transition-colors">
                          <RefreshCw className={`h-4 w-4 ${fetchingModels === provider.id ? 'animate-spin' : ''}`} />
                          {fetchingModels === provider.id ? tl.fetching : tl.fetchModels}
                        </button>
                      </div>

                      {/* 可用模型（从API获取的） */}
                      {fetchedModels[provider.id] && fetchedModels[provider.id].length > 0 && (
                        <div className="rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-3">
                          <p className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2">{tl.availableModels} ({fetchedModels[provider.id].length}) — {tl.clickToAdd}</p>
                          <div className="flex flex-wrap gap-1.5">
                            {fetchedModels[provider.id].map((modelName) => {
                              const alreadyAdded = provider.models.some((m) => m.name === modelName)
                              return (
                                <button key={modelName} type="button"
                                  onClick={() => { if (!alreadyAdded) { addModelToProvider(provider.id, modelName) } }}
                                  disabled={alreadyAdded}
                                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                                    alreadyAdded
                                      ? 'bg-slate-200 dark:bg-slate-600 text-slate-400 dark:text-slate-500 cursor-not-allowed'
                                      : 'bg-white dark:bg-slate-700 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-800/50 border border-blue-200 dark:border-blue-700'
                                  }`}>
                                  {modelName}
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      )}

                      {/* 已添加的模型列表 */}
                      {provider.models.length === 0 ? (
                        <div className="rounded-xl border-2 border-dashed border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/30 p-6 text-center text-sm text-slate-400 dark:text-slate-500">
                          {tl.noModels}
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {provider.models.map((model) => (
                            <div key={model.name} className="rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/30 p-3">
                              <div className="flex items-center justify-between mb-2">
                                <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{model.name}</p>
                                <button type="button" onClick={() => removeModelFromProvider(provider.id, model.name)}
                                  title={tl.removeModelHint}
                                  className="p-1 rounded-lg text-slate-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 transition-colors">
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <label className="block text-[10px] font-medium text-slate-500 dark:text-slate-400 mb-0.5">{tl.maxCtx} <span className="text-red-500">*</span></label>
                                  <input type="text" value={model.max_context_tokens}
                                    onChange={(e) => updateModelField(provider.id, model.name, 'max_context_tokens', e.target.value)}
                                    placeholder="128000"
                                    className={`w-full rounded-lg border bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 px-2.5 py-1.5 text-xs text-center focus:ring-1 focus:ring-blue-500 ${
                                      !model.max_context_tokens ? 'border-red-300 dark:border-red-600' : 'border-slate-200 dark:border-slate-600'
                                    }`} />
                                </div>
                                <div>
                                  <label className="block text-[10px] font-medium text-slate-500 dark:text-slate-400 mb-0.5">{tl.maxOut} <span className="text-red-500">*</span></label>
                                  <input type="text" value={model.max_output_tokens}
                                    onChange={(e) => updateModelField(provider.id, model.name, 'max_output_tokens', e.target.value)}
                                    placeholder="4096"
                                    className={`w-full rounded-lg border bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 px-2.5 py-1.5 text-xs text-center focus:ring-1 focus:ring-blue-500 ${
                                      !model.max_output_tokens ? 'border-red-300 dark:border-red-600' : 'border-slate-200 dark:border-slate-600'
                                    }`} />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* 嵌入模型 */}
          {renderServiceConfigCard(
            tl.embConfig, embeddingForm, setEmbeddingForm, 'embedding',
            () => handleFetchModelsForService('embedding'),
            embeddingFetchedModels,
          )}

          {/* 重排模型 */}
          {renderServiceConfigCard(
            tl.rerankConfig, rerankForm, setRerankForm, 'rerank',
            () => handleFetchModelsForService('rerank'),
            rerankFetchedModels,
          )}

          {/* 流控配置 */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            <div className="p-4 sm:p-5 border-b border-slate-100 dark:border-slate-700">
              <h4 className="text-base font-semibold text-slate-900 dark:text-slate-100">{tl.rateLimit}</h4>
            </div>
            <div className="p-4 sm:p-5">
              <div className="grid grid-cols-2 gap-3">
                {renderFormInput(tl.rpm, rateLimitForm.rpm, (v) => setRateLimitForm({ ...rateLimitForm, rpm: v }))}
                {renderFormInput(tl.tpm, rateLimitForm.tpm, (v) => setRateLimitForm({ ...rateLimitForm, tpm: v }))}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={handleImportConfig} title={tl.importHint}
              className="flex items-center gap-2 rounded-xl bg-slate-100 dark:bg-slate-700 px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors">
              <Upload className="h-4 w-4" />{tl.importConfig}
            </button>
            <button onClick={handleExportConfig} title={tl.exportHint}
              className="flex items-center gap-2 rounded-xl bg-slate-100 dark:bg-slate-700 px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors">
              <Download className="h-4 w-4" />{tl.exportConfig}
            </button>
            <div className="flex-1" />
            <button onClick={handleSaveModelConfig} title={tl.saveHint}
              className="flex items-center gap-2 rounded-xl bg-blue-500 px-6 py-3 text-sm font-medium text-white hover:bg-blue-600 transition-colors shadow-lg shadow-blue-500/25">
              <Save className="h-4 w-4" />{tl.save}
            </button>
          </div>
        </div>
      )}

      {/* 共享文档 */}
      {activeTab === 'shared-docs' && (
        <div className="space-y-6">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-3">{tl.sharedDocs}</h3>
            <div className="flex gap-2 mb-4 overflow-x-auto">
              {[{ key: '', label: tl.all }, { key: 'source', label: tl.sourceDocs }, { key: 'template', label: tl.templates }, { key: 'output', label: tl.outputDocs }].map((cat) => (
                <button key={cat.key} onClick={() => setSharedDocCategory(cat.key)}
                  className={`rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors ${sharedDocCategory === cat.key ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/25' : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600'}`}>
                  {cat.label}
                </button>
              ))}
            </div>

            {sharedDocs.length === 0 ? (
              <div className="rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-12 text-center text-slate-400 dark:text-slate-500">{tl.noDocs}</div>
            ) : (
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
                {sharedDocs.map((doc) => (
                  <div key={doc.id} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-4 hover:shadow-lg transition-shadow">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <DocCategoryIcon category={doc.doc_category} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400">{doc.file_type.toUpperCase()}</p>
                        </div>
                      </div>
                      <button onClick={() => handleRemoveShared(doc.id)} title={tl.removeSharedHint} className="p-2 rounded-lg text-slate-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 shrink-0">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-3">{tl.addShared}</h3>
            <div className="relative mb-4">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="text" placeholder="搜索文档..." value={docSearch} onChange={(e) => setDocSearch(e.target.value)}
                className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 pl-10 pr-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500" />
            </div>

            {nonSharedDocs.length === 0 ? (
              <div className="rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-12 text-center text-slate-400 dark:text-slate-500">{tl.noDocs}</div>
            ) : (
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
                {nonSharedDocs.filter((doc) => !docSearch || doc.original_filename.toLowerCase().includes(docSearch.toLowerCase())).map((doc) => (
                  <div key={doc.id} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-4 hover:shadow-lg transition-shadow">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <DocCategoryIcon category={doc.doc_category} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400">{doc.file_type.toUpperCase()}</p>
                        </div>
                      </div>
                      <button onClick={() => handleSetShared(doc.id)} title={tl.setSharedHint} className="p-2 rounded-lg text-slate-400 hover:bg-green-50 dark:hover:bg-green-900/30 hover:text-green-600 shrink-0">
                        <Share className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      </div>

      {/* 编辑用户弹窗 */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-white dark:bg-slate-800 p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-4">{tl.editUser}</h3>
            <div className="space-y-3">
              {renderFormInput(tl.username, editForm.username, (v) => setEditForm({ ...editForm, username: v }))}
              {renderFormInput(tl.email, editForm.email, (v) => setEditForm({ ...editForm, email: v }))}
              {renderFormInput(tl.phone, editForm.phone, (v) => setEditForm({ ...editForm, phone: v }))}
              {renderFormInput(tl.newPassword, editForm.password, (v) => setEditForm({ ...editForm, password: v }), { placeholder: tl.passwordHint })}
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setEditingUser(null)} className="rounded-xl px-5 py-2.5 text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">{tl.cancel}</button>
              <button onClick={handleSaveUser} className="rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-600 transition-colors shadow-lg shadow-blue-500/25">{tl.save}</button>
            </div>
          </div>
        </div>
      )}

      {/* 用户文件弹窗 */}
      {viewingUserDocs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="w-full max-w-2xl max-h-[85vh] rounded-2xl bg-white dark:bg-slate-800 shadow-2xl overflow-hidden flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between p-5 border-b border-slate-200 dark:border-slate-700">
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">{tl.userFiles} — {viewingUserDocs.user.username}</h3>
              <button onClick={() => { setViewingUserDocs(null); setUserDocCategory(''); setPreviewDoc(null) }}
                title={tl.close}
                className="p-2 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* 分类筛选 */}
            <div className="flex gap-2 px-5 pt-4 pb-2">
              {[{ key: '', label: tl.allDocs }, { key: 'source', label: tl.sourceDocsCat }, { key: 'template', label: tl.templateDocsCat }, { key: 'output', label: tl.outputDocsCat }].map((cat) => (
                <button key={cat.key} onClick={() => setUserDocCategory(cat.key)}
                  title={cat.label}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    userDocCategory === cat.key
                      ? 'bg-blue-500 text-white shadow-sm'
                      : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600'
                  }`}>
                  {cat.label}
                </button>
              ))}
            </div>

            {/* 文件列表 */}
            <div className="flex-1 overflow-y-auto px-5 pb-4 scrollbar-thin">
              {(() => {
                const filtered = userDocCategory
                  ? viewingUserDocs.docs.filter((d: any) => d.doc_category === userDocCategory)
                  : viewingUserDocs.docs
                return filtered.length === 0 ? (
                  <p className="text-center text-slate-400 dark:text-slate-500 py-16">{tl.noDocs}</p>
                ) : (
                  <div className="space-y-2 pt-2">
                    {filtered.map((doc: any) => (
                      <div key={doc.id} className="flex items-center gap-3 rounded-xl border border-slate-200 dark:border-slate-700 p-3 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                        <DocCategoryIcon category={doc.doc_category} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{doc.original_filename}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400">{doc.file_type.toUpperCase()}</p>
                        </div>
                        <div className="flex items-center gap-0.5 shrink-0">
                          <button onClick={() => handleDownloadDoc(doc)}
                            title={tl.download}
                            className="rounded p-1.5 sm:p-2 text-slate-400 transition-colors hover:bg-blue-500/20 hover:text-blue-400">
                            <Download className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                          </button>
                          <button onClick={() => setPreviewDoc(doc)}
                            title={tl.preview}
                            className="rounded p-1.5 sm:p-2 text-slate-400 transition-colors hover:bg-slate-100 dark:hover:bg-slate-600 hover:text-slate-900 dark:hover:text-slate-100">
                            <Eye className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              })()}
            </div>
          </div>
        </div>
      )}

      {/* 文档预览弹窗 */}
      {previewDoc && (
        <DocumentPreviewModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}
    </div>
  )
}
