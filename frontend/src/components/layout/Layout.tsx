import { type ChangeEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import Sidebar from './Sidebar'
import Header from './Header'
import { useDocumentStore } from '../../stores/documentStore'
import { useI18n } from '../../hooks/useI18n'
import { PREFERENCES_CHANGED_EVENT, getStoredPreferences } from '../../services/preferences'
import { PENDING_WORKLOG_EXPORT_KEY, WORKLOG_EXPORT_EVENT } from '../../services/shortcuts'

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [query])
  return matches
}

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const { addDocuments } = useDocumentStore()
  const sourceInputRef = useRef<HTMLInputElement>(null)
  const templateInputRef = useRef<HTMLInputElement>(null)
  const [shortcutsEnabled, setShortcutsEnabled] = useState(() => getStoredPreferences().keyboardShortcuts)

  // 响应式：移动端检测 & 侧边栏状态
  const isMobile = useMediaQuery('(max-width: 1023px)')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  // 路由切换时自动关闭移动端侧边栏
  useEffect(() => {
    if (isMobile) setSidebarOpen(false)
  }, [location.pathname, isMobile])

  const uploadFiles = async (files: File[], category: 'source' | 'template') => {
    if (files.length === 0) return

    try {
      await addDocuments(files, category)
      const isSource = category === 'source'
      const successTitle = tr('上传成功', 'Upload succeeded', 'アップロード成功')
      const successMessage = isSource
        ? tr(`已上传 ${files.length} 个源文档，正在自动提取信息`, `Uploaded ${files.length} source docs, extraction started`, `${files.length} 件のソース文書をアップロードし、抽出を開始しました`)
        : tr(`已上传 ${files.length} 个模板`, `Uploaded ${files.length} templates`, `${files.length} 件のテンプレートをアップロードしました`)
      toast.success(
        successMessage
      )
      window.dispatchEvent(
        new CustomEvent('app-notify', {
          detail: { title: successTitle, message: successMessage },
        })
      )
    } catch {
      toast.error(tr('上传失败', 'Upload failed', 'アップロード失敗'))
    }
  }

  const onSelectSourceFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : []
    event.target.value = ''
    await uploadFiles(files, 'source')
  }

  const onSelectTemplateFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : []
    event.target.value = ''
    await uploadFiles(files, 'template')
  }

  useEffect(() => {
    const syncPreferences = () => {
      setShortcutsEnabled(getStoredPreferences().keyboardShortcuts)
    }

    window.addEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences)
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences)
  }, [])

  useEffect(() => {
    if (location.pathname === '/work-log' && sessionStorage.getItem(PENDING_WORKLOG_EXPORT_KEY) === '1') {
      sessionStorage.removeItem(PENDING_WORKLOG_EXPORT_KEY)
      window.dispatchEvent(new Event(WORKLOG_EXPORT_EVENT))
    }
  }, [location.pathname])

  useEffect(() => {
    const isEditableTarget = (target: EventTarget | null) => {
      const element = target as HTMLElement | null
      if (!element) return false
      const tagName = element.tagName.toLowerCase()
      return element.isContentEditable || tagName === 'input' || tagName === 'textarea' || tagName === 'select'
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (!shortcutsEnabled) return
      if (isEditableTarget(event.target)) return

      const hasPrimaryModifier = event.ctrlKey || event.metaKey
      if (!hasPrimaryModifier || !event.altKey || event.shiftKey) return

      const key = event.key.toLowerCase()
      if (key === 'm') {
        event.preventDefault()
        sourceInputRef.current?.click()
        return
      }

      if (key === 't') {
        event.preventDefault()
        templateInputRef.current?.click()
        return
      }

      if (key === 'j') {
        event.preventDefault()
        if (location.pathname === '/work-log') {
          window.dispatchEvent(new Event(WORKLOG_EXPORT_EVENT))
        } else {
          sessionStorage.setItem(PENDING_WORKLOG_EXPORT_KEY, '1')
          navigate('/work-log')
        }
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [location.pathname, navigate, shortcutsEnabled])

  return (
    <div className="h-screen flex overflow-hidden">
      <input
        ref={sourceInputRef}
        type="file"
        multiple
        className="hidden"
        accept=".docx,.xlsx,.md,.txt"
        onChange={onSelectSourceFiles}
      />
      <input
        ref={templateInputRef}
        type="file"
        multiple
        className="hidden"
        accept=".docx,.xlsx"
        onChange={onSelectTemplateFiles}
      />

      {/* 移动端侧边栏遮罩 */}
      {isMobile && sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm animate-fade-in lg:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* 侧边栏：移动端抽屉 / 平板端折叠图标 / 桌面端完整 */}
      <div
        className={`
          ${isMobile
            ? `fixed inset-y-0 left-0 z-40 transition-transform duration-300 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`
            : 'shrink-0'
          }
        `}
      >
        <Sidebar isMobile={isMobile} onClose={closeSidebar} />
      </div>

      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <Header isMobile={isMobile} onToggleSidebar={() => setSidebarOpen(prev => !prev)} sidebarOpen={sidebarOpen} />
        <main className="flex-1 p-3 sm:p-4 lg:p-6 min-h-0">
          <div className="animate-in h-full">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
