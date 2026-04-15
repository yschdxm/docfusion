import { NavLink } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, FileText, Network, NotebookPen } from 'lucide-react'
import { useI18n } from '../../hooks/useI18n'
import { sidebarI18n } from '../../services/i18n'

export default function Sidebar() {
  const { language } = useI18n()
  const t = sidebarI18n[language]

  const navItems = [
    { path: '/', icon: LayoutDashboard, label: t.dashboard },
    { path: '/documents', icon: FolderOpen, label: t.documents },
    { path: '/document-operation', icon: FileText, label: language === 'zh-CN' ? '智能助手' : t.operation },
    { path: '/knowledge', icon: Network, label: t.knowledge },
    { path: '/work-log', icon: NotebookPen, label: t.workLog },
  ]

  return (
    <aside className="flex w-60 flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_12px_36px_rgba(15,23,42,0.06)]">
      <div className="relative border-b border-slate-200/80 px-6 py-6">
        <div className="relative flex items-center gap-3">
          <img src="/logo.png" alt="logo" className="h-12 w-12 object-contain drop-shadow-sm" />
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-bold leading-none tracking-tight text-[#0d5fb0]">{t.systemName}</h1>
            <p className="mt-1 text-sm text-slate-500">{t.systemSub}</p>
          </div>
        </div>
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
        <div className="rounded-xl border border-slate-200 bg-[linear-gradient(180deg,#ffffff,#f6f9ff)] px-4 py-3">
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Engine</p>
          <p className="mt-1 text-sm font-semibold text-[var(--theme-primary)]">MiMO v2 Flash</p>
        </div>
      </div>
    </aside>
  )
}
