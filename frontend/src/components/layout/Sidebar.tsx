import { NavLink } from 'react-router-dom'
import { 
  LayoutDashboard, 
  FileText, 
  Search, 
  Table, 
  Network,
  Sparkles 
} from 'lucide-react'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: '仪表盘' },
  { path: '/document-operation', icon: FileText, label: '文档智能操作' },
  { path: '/extraction', icon: Search, label: '信息提取' },
  { path: '/table-fill', icon: Table, label: '表格填写' },
  { path: '/knowledge', icon: Network, label: '知识图谱' },
]

export default function Sidebar() {
  return (
    <aside className="w-64 glass-dark border-r border-white/10 flex flex-col">
      <div className="p-6 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary-500 to-purple-500 
                          flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold gradient-text">DocFusion</h1>
            <p className="text-xs text-slate-400">文档智能融合系统</p>
          </div>
        </div>
      </div>
      
      <nav className="flex-1 p-4 space-y-2">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `nav-link ${isActive ? 'nav-link-active' : ''}`
            }
          >
            <item.icon className="w-5 h-5" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      
      <div className="p-4 border-t border-white/10">
        <div className="glass p-4 text-center">
          <p className="text-xs text-slate-400">Powered by</p>
          <p className="text-sm font-medium gradient-text">MiMO v2 Flash</p>
        </div>
      </div>
    </aside>
  )
}
