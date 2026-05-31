import { NavLink } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, FileText, Network, NotebookPen } from 'lucide-react'
import { useI18n } from '../../hooks/useI18n'
import { sidebarI18n } from '../../services/i18n'
import { useState, useEffect } from 'react'
import api from '../../services/api'
import Dropdown from '../ui/Dropdown'
import { getTheme } from '../../services/theme'

interface SidebarProps {
  isMobile?: boolean
  onClose?: () => void
}

export default function Sidebar({ isMobile, onClose }: SidebarProps) {
  const { language } = useI18n()
  const t = sidebarI18n[language]
  const [currentProvider, setCurrentProvider] = useState<string>('deepseek')
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')

  // 监听主题变化
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  // 获取当前模型配置
  useEffect(() => {
    const fetchModelConfig = async () => {
      try {
        const { data } = await api.get('/agent/model')
        setCurrentProvider(data.provider)
      } catch (error) {
        console.error('获取模型配置失败:', error)
      }
    }
    fetchModelConfig()
  }, [])

  // 切换模型
  const handleModelSwitch = async (provider: string) => {
    if (provider === currentProvider) return

    try {
      const { data } = await api.post('/agent/model/switch', { provider })
      if (data.success) {
        setCurrentProvider(provider)
      }
    } catch (error) {
      console.error('切换模型失败:', error)
    }
  }

  const modelOptions = [
    { value: 'mimo', label: 'MiMO v2 Flash' },
    { value: 'deepseek', label: 'DeepSeek V4 Flash' },
  ]

  const navItems = [
    { path: '/', icon: LayoutDashboard, label: t.dashboard },
    { path: '/documents', icon: FolderOpen, label: t.documents },
    { path: '/document-operation', icon: FileText, label: language === 'zh-CN' ? '智能助手' : t.operation },
    { path: '/knowledge', icon: Network, label: t.knowledge },
    { path: '/work-log', icon: NotebookPen, label: t.workLog },
  ]

  return (
    <aside className={`flex w-60 flex-col overflow-hidden border-r border-slate-200 bg-white h-full ${isMobile ? 'shadow-2xl' : ''}`}>
      <div className="relative border-b border-slate-200/80 px-5 py-5">
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="logo" className="h-10 w-10 shrink-0 object-contain drop-shadow-sm" />
          <h1 className="flex-1 min-w-0 text-xl font-bold leading-tight tracking-tight text-[#0d5fb0]">{t.systemName}</h1>
          {isMobile && onClose && (
            <button
              onClick={onClose}
              className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              aria-label="关闭菜单"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
        <p className="mt-1.5 pl-[52px] text-xs text-slate-500">{t.systemSub}</p>
      </div>

      <nav className="flex-1 space-y-1.5 px-4 py-5">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `group relative flex items-center gap-3 rounded-xl px-3.5 py-3 text-lg font-medium transition-all duration-200 ${
                isActive
                  ? 'bg-[linear-gradient(135deg,rgba(59,130,246,0.18),rgba(59,130,246,0.09))] text-[var(--theme-primary)] shadow-[inset_0_0_0_1px_rgba(59,130,246,0.28),0_8px_18px_rgba(59,130,246,0.16)]'
                  : 'text-slate-700 hover:bg-slate-100/80 hover:text-slate-900'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`absolute bottom-2 left-0 top-2 w-1 rounded-full transition-all duration-200 ${
                    isActive ? 'bg-[var(--theme-primary)] opacity-100' : 'bg-transparent opacity-0 group-hover:opacity-60'
                  }`}
                />
                <span
                  className={`flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
                    isActive ? 'bg-white/75 text-[var(--theme-primary)]' : 'text-slate-500 group-hover:bg-white group-hover:text-slate-800'
                  }`}
                >
                  <item.icon className="h-5 w-5" />
                </span>
                <span className="truncate">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-200/80 px-4 py-4">
        <div className={`rounded-xl border border-slate-200 px-4 py-3 ${isDarkMode ? 'night-mode-gradient-bg' : 'bg-[linear-gradient(180deg,#ffffff,#f6f9ff)]'}`}>
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Engine</p>
          <Dropdown
            value={currentProvider}
            onChange={handleModelSwitch}
            options={modelOptions}
            className="mt-1"
            dropup={true}
          />
        </div>
      </div>
    </aside>
  )
}
