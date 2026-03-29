import { useLocation } from 'react-router-dom'
import { Bell, Settings, User } from 'lucide-react'

const pageTitles: Record<string, string> = {
  '/': '仪表盘',
  '/documents': '文档管理',
  '/document-operation': '文档智能操作',
  '/table-fill': '表格填写',
  '/knowledge': '知识图谱',
}

export default function Header() {
  const location = useLocation()
  const title = pageTitles[location.pathname] || '页面'

  return (
    <header className="glass-dark border-b border-white/10 px-6 py-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">{title}</h2>
          <p className="text-sm text-slate-400">
            {new Date().toLocaleDateString('zh-CN', { 
              weekday: 'long', 
              year: 'numeric', 
              month: 'long', 
              day: 'numeric' 
            })}
          </p>
        </div>
        
        <div className="flex items-center gap-4">
          <button className="p-2 rounded-lg hover:bg-white/10 transition-colors">
            <Bell className="w-5 h-5 text-slate-400" />
          </button>
          <button className="p-2 rounded-lg hover:bg-white/10 transition-colors">
            <Settings className="w-5 h-5 text-slate-400" />
          </button>
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-500 to-purple-500 
                          flex items-center justify-center">
            <User className="w-5 h-5 text-white" />
          </div>
        </div>
      </div>
    </header>
  )
}
