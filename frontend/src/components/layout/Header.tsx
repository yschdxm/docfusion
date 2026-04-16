import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, Check, ChevronDown, CircleHelp, Keyboard, Languages, LogOut, Palette, Settings, User } from 'lucide-react'
import { AUTH_USER_CHANGED_EVENT, getAuthUser, logout, type AuthUser } from '../../services/auth'
import { getStoredTheme, setTheme, type ThemeMode } from '../../services/theme'
import { getStoredLanguage, I18N_CHANGED_EVENT, languageLabelMap, setLanguage, type LanguageCode } from '../../services/i18n'
import { type PreferenceState, getStoredPreferences, setStoredPreferences } from '../../services/preferences'
import { SHORTCUTS } from '../../services/shortcuts'

type SettingsTab = 'preferences' | 'theme' | 'language'
const NOTICE_KEY = 'header_desktop_notices'

interface HeaderNotice {
  id: string
  title: string
  message: string
  time: number
  read: boolean
}

interface AppNoticeEventDetail {
  title: string
  message: string
}

const i18n = {
  'zh-CN': {
    page: {
      '/': '仪表盘',
      '/documents': '文档管理',
      '/document-operation': '智能助手',
      '/knowledge': '知识图谱',
      '/work-log': '工作日志',
      '/profile': '个人中心',
    },
    genericPage: '页面',
    settings: '设置',
    settingsTabs: { preferences: '系统偏好', theme: '主题', language: '语言' },
    pref: { on: '已开启', off: '已关闭' },
    enterProfile: '进入个人中心',
    userFallback: '用户',
    logout: '退出登录',
  },
  'en-US': {
    page: {
      '/': 'Dashboard',
      '/documents': 'Documents',
      '/document-operation': 'Doc Operations',
      '/knowledge': 'Knowledge Graph',
      '/work-log': 'Work Log',
      '/profile': 'Profile',
    },
    genericPage: 'Page',
    settings: 'Settings',
    settingsTabs: { preferences: 'Preferences', theme: 'Theme', language: 'Language' },
    pref: { on: 'On', off: 'Off' },
    enterProfile: 'Profile',
    userFallback: 'User',
    logout: 'Logout',
  },
  'ja-JP': {
    page: {
      '/': 'Dashboard',
      '/documents': 'Documents',
      '/document-operation': 'Doc Operations',
      '/knowledge': 'Knowledge Graph',
      '/work-log': 'Work Log',
      '/profile': 'Profile',
    },
    genericPage: 'Page',
    settings: 'Settings',
    settingsTabs: { preferences: 'Preferences', theme: 'Theme', language: 'Language' },
    pref: { on: 'On', off: 'Off' },
    enterProfile: 'Profile',
    userFallback: 'User',
    logout: 'Logout',
  },
} as const

const themeOptions: Array<{ value: ThemeMode }> = [{ value: 'business-blue' }, { value: 'night-mode' }]

export default function Header() {
  const location = useLocation()
  const navigate = useNavigate()

  const [user, setUser] = useState<AuthUser | null>(getAuthUser())
  const [language, setLanguageState] = useState<LanguageCode>(getStoredLanguage())
  const [showSettings, setShowSettings] = useState(false)
  const [showNoticePanel, setShowNoticePanel] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [activeHelpSection, setActiveHelpSection] = useState<'modules' | 'workflow' | 'shortcuts' | 'faq' | null>(null)
  const [theme, setThemeState] = useState<ThemeMode>(getStoredTheme())
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('preferences')
  const [preferences, setPreferences] = useState<PreferenceState>(() => getStoredPreferences())
  const [notices, setNotices] = useState<HeaderNotice[]>(() => {
    const raw = localStorage.getItem(NOTICE_KEY)
    if (!raw) return []
    try {
      const parsed = JSON.parse(raw) as HeaderNotice[]
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  })
  const settingsRef = useRef<HTMLDivElement>(null)
  const noticeRef = useRef<HTMLDivElement>(null)
  const helpRef = useRef<HTMLDivElement>(null)

  const dict = i18n[language]
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const title = dict.page[location.pathname as keyof typeof dict.page] || dict.genericPage
  const dateText = useMemo(
    () =>
      new Date().toLocaleDateString(language, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
    [language]
  )

  const unreadCount = notices.filter((n) => !n.read).length

  const pushNotice = (titleText: string, messageText: string, force = false) => {
    if (!preferences.desktopNotice && !force) return

    const next: HeaderNotice = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      title: titleText,
      message: messageText,
      time: Date.now(),
      read: false,
    }
    setNotices((prev) => [next, ...prev].slice(0, 30))

    if (typeof window !== 'undefined' && 'Notification' in window) {
      const send = () => new Notification(titleText, { body: messageText })
      if (Notification.permission === 'granted') send()
      if (Notification.permission === 'default') {
        Notification.requestPermission().then((permission) => {
          if (permission === 'granted') send()
        })
      }
    }
  }

  const markAllRead = () => {
    setNotices([])
  }

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(event.target as Node)) {
        setShowSettings(false)
      }
      if (noticeRef.current && !noticeRef.current.contains(event.target as Node)) {
        setShowNoticePanel(false)
      }
      if (helpRef.current && !helpRef.current.contains(event.target as Node)) {
        setShowHelp(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  useEffect(() => {
    setStoredPreferences(preferences)
  }, [preferences])

  useEffect(() => {
    localStorage.setItem(NOTICE_KEY, JSON.stringify(notices))
  }, [notices])

  useEffect(() => {
    const syncUser = () => setUser(getAuthUser())
    const syncLanguage = () => setLanguageState(getStoredLanguage())
    const onAppNotice = (event: Event) => {
      const customEvent = event as CustomEvent<AppNoticeEventDetail>
      const detail = customEvent.detail
      if (!detail?.title || !detail?.message) return
      pushNotice(detail.title, detail.message)
    }
    window.addEventListener(AUTH_USER_CHANGED_EVENT, syncUser)
    window.addEventListener(I18N_CHANGED_EVENT, syncLanguage)
    window.addEventListener('app-notify', onAppNotice as EventListener)
    return () => {
      window.removeEventListener(AUTH_USER_CHANGED_EVENT, syncUser)
      window.removeEventListener(I18N_CHANGED_EVENT, syncLanguage)
      window.removeEventListener('app-notify', onAppNotice as EventListener)
    }
  }, [preferences.desktopNotice])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleThemeChange = (value: ThemeMode) => {
    setTheme(value)
    setThemeState(value)
    pushNotice(
      tr('主题已切换', 'Theme updated', 'テーマを更新しました'),
      value === 'business-blue'
        ? tr('当前主题：商务蓝。', 'Current theme: Business Blue.', '現在のテーマ: Business Blue')
        : tr('当前主题：夜间模式。', 'Current theme: Night Mode.', '現在のテーマ: Night Mode')
    )
  }

  const handleLanguageChange = (value: LanguageCode) => {
    setLanguage(value)
    setLanguageState(value)
    pushNotice(
      tr('语言已切换', 'Language updated', '言語を更新しました'),
      tr('页面语言已更新。', 'Page language has been updated.', 'ページ言語を更新しました。')
    )
  }

  const togglePreference = (key: keyof PreferenceState) => {
    setPreferences((prev) => {
      const nextValue = !prev[key]
      const next = { ...prev, [key]: nextValue }

      if (key === 'desktopNotice' && nextValue) {
        pushNotice(
          tr('桌面通知已开启', 'Desktop notifications enabled', 'デスクトップ通知を有効化しました'),
          tr('新消息将显示在右上角铃铛面板。', 'New messages will appear in the bell panel.', '新しい通知は右上のベルに表示されます。'),
          true
        )
        if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
          Notification.requestPermission().catch(() => {})
        }
      }

      return next
    })
  }

  return (
    <header className="glass-dark border-b border-slate-200 px-4 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">{title}</h2>
          <p className="text-xs text-slate-500">{dateText}</p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative" ref={noticeRef}>
            <button
              onClick={() => {
                setShowNoticePanel((prev) => !prev)
              }}
              aria-label={tr('打开通知中心', 'Open notifications', '通知を開く')}
              className="relative rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute -right-1 -top-1 min-w-[16px] rounded-full bg-red-500 px-1 text-center text-[10px] leading-4 text-white">
                  {unreadCount > 99 ? '99+' : unreadCount}
                </span>
              )}
            </button>

            {showNoticePanel && (
              <div role="region" aria-label={tr('通知面板', 'Notifications panel', '通知パネル')} className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium text-slate-800">{tr('桌面通知', 'Desktop Notifications', 'デスクトップ通知')}</p>
                  <button onClick={markAllRead} className="text-xs text-primary-600 hover:text-primary-700">
                    {tr('全部已读', 'Mark all read', 'すべて既読')}
                  </button>
                </div>
                <div className="max-h-72 space-y-2 overflow-y-auto scrollbar-thin">
                  {notices.length === 0 ? (
                    <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
                      {tr('暂无通知', 'No notifications', '通知はありません')}
                    </p>
                  ) : (
                    notices.map((notice) => (
                      <div
                        key={notice.id}
                        className={`rounded-lg border px-3 py-2 ${notice.read ? 'border-slate-200 bg-slate-50' : 'border-blue-200 bg-blue-50'}`}
                      >
                        <p className="text-sm font-medium text-slate-800">{notice.title}</p>
                        <p className="mt-0.5 text-xs text-slate-600">{notice.message}</p>
                        <p className="mt-1 text-[11px] text-slate-500">{new Date(notice.time).toLocaleString(language)}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="relative" ref={settingsRef}>
            <button
              onClick={() => setShowSettings((prev) => !prev)}
              aria-label={tr('打开系统设置', 'Open settings', '設定を開く')}
              className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
              title={dict.settings}
            >
              <Settings className="h-4 w-4" />
            </button>

            {showSettings && (
              <div role="dialog" aria-modal="false" aria-label={tr('系统设置', 'System settings', 'システム設定')} className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                <div className="mb-2 flex items-center gap-1 rounded-lg bg-slate-100 p-1">
                  <button
                    onClick={() => setSettingsTab('preferences')}
                    className={`flex-1 rounded-md px-2 py-1 text-xs ${settingsTab === 'preferences' ? 'bg-white text-primary-600 shadow-sm' : 'text-slate-600'}`}
                  >
                    {dict.settingsTabs.preferences}
                  </button>
                  <button
                    onClick={() => setSettingsTab('theme')}
                    className={`flex-1 rounded-md px-2 py-1 text-xs ${settingsTab === 'theme' ? 'bg-white text-primary-600 shadow-sm' : 'text-slate-600'}`}
                  >
                    {dict.settingsTabs.theme}
                  </button>
                  <button
                    onClick={() => setSettingsTab('language')}
                    className={`flex-1 rounded-md px-2 py-1 text-xs ${settingsTab === 'language' ? 'bg-white text-primary-600 shadow-sm' : 'text-slate-600'}`}
                  >
                    {dict.settingsTabs.language}
                  </button>
                </div>

                {settingsTab === 'preferences' && (
                  <div className="space-y-2">
                    {[
                      {
                        key: 'desktopNotice',
                        label: tr('桌面通知', 'Desktop Notifications', 'デスクトップ通知'),
                        icon: Bell,
                        hint: tr('开启后提醒会发送到右上角铃铛面板。', 'When enabled, alerts are delivered to the bell panel.', '有効時は右上のベルに通知されます。'),
                      },
                      {
                        key: 'keyboardShortcuts',
                        label: tr('快捷键', 'Keyboard Shortcuts', 'キーボードショートカット'),
                        icon: Keyboard,
                        hint: tr('全局快捷键：Ctrl+Alt+M 上传源文档，Ctrl+Alt+T 上传模板，Ctrl+Alt+J 导出工作日志。', 'Global shortcuts: Ctrl+Alt+M upload source, Ctrl+Alt+T upload template, Ctrl+Alt+J export work log.', 'グローバルショートカット: Ctrl+Alt+M ソース文書、Ctrl+Alt+T テンプレート、Ctrl+Alt+J 作業ログ出力。'),
                      },
                    ].map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => togglePreference(item.key as keyof PreferenceState)}
                        className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:bg-slate-100"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <item.icon className="h-4 w-4 text-slate-500" />
                            <span className="text-sm text-slate-800">{item.label}</span>
                          </div>
                          <span
                            className="text-xs px-2 py-0.5 rounded"
                            style={{
                              backgroundColor: preferences[item.key as keyof PreferenceState]
                                ? 'color-mix(in srgb, var(--theme-primary) 16%, transparent)'
                                : 'color-mix(in srgb, var(--theme-body-text) 10%, transparent)',
                              color: 'var(--theme-body-text)',
                            }}
                          >
                            {preferences[item.key as keyof PreferenceState] ? dict.pref.on : dict.pref.off}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">{item.hint}</p>
                      </button>
                    ))}
                  </div>
                )}

                {settingsTab === 'theme' && (
                  <div className="space-y-1">
                    {themeOptions.map((option) => {
                      const label = option.value === 'business-blue' ? tr('商务蓝', 'Business Blue', 'ビジネスブルー') : tr('夜间模式', 'Night Mode', 'ナイトモード')
                      const desc =
                        option.value === 'business-blue'
                          ? tr('默认商务蓝风格主题', 'Default business-friendly blue style', '標準のビジネス向けブルースタイル')
                          : tr('适合暗光环境的低亮度界面', 'Low-light interface for dark environments', '暗い環境向けの低輝度インターフェース')
                      return (
                        <button
                          key={option.value}
                          onClick={() => handleThemeChange(option.value)}
                          className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors ${theme === option.value ? 'bg-primary-50' : 'hover:bg-slate-50'}`}
                        >
                          <div className="flex items-start gap-2">
                            <Palette className="mt-0.5 h-4 w-4 text-slate-500" />
                            <div>
                              <div className="text-sm text-slate-800">{label}</div>
                              <div className="text-xs text-slate-500">{desc}</div>
                            </div>
                          </div>
                          {theme === option.value && <Check className="h-4 w-4 text-primary-600" />}
                        </button>
                      )
                    })}
                  </div>
                )}

                {settingsTab === 'language' && (
                  <div className="space-y-1">
                    {(Object.keys(languageLabelMap) as LanguageCode[]).map((item) => (
                      <button
                        key={item}
                        onClick={() => handleLanguageChange(item)}
                        className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors ${language === item ? 'bg-primary-50' : 'hover:bg-slate-50'}`}
                      >
                        <div className="flex items-center gap-2">
                          <Languages className="h-4 w-4 text-slate-500" />
                          <span className="text-sm text-slate-800">{languageLabelMap[item]}</span>
                        </div>
                        {language === item && <Check className="h-4 w-4 text-primary-600" />}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="relative" ref={helpRef}>
            <button
              onClick={() =>
                setShowHelp((prev) => {
                  const next = !prev
                  if (next) setActiveHelpSection(null)
                  return next
                })
              }
              aria-label={tr('打开使用帮助', 'Open help', 'ヘルプを開く')}
              className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
              title={tr('使用帮助', 'Help', 'ヘルプ')}
            >
              <CircleHelp className="h-4 w-4" />
            </button>

            {showHelp && (
              <div role="dialog" aria-modal="false" aria-label={tr('使用帮助', 'Help', 'ヘルプ')} className="absolute right-0 z-50 mt-2 w-[22rem] rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                <h4 className="text-sm font-semibold text-slate-900">{tr('帮助中心', 'Help Center', 'ヘルプセンター')}</h4>

                <div className="mt-3 space-y-2">
                  {[
                    { key: 'modules', title: tr('功能模块', 'Feature Modules', '機能モジュール') },
                    { key: 'workflow', title: tr('使用流程', 'How to Use', '利用フロー') },
                    { key: 'shortcuts', title: tr('快捷键', 'Keyboard Shortcuts', 'キーボードショートカット') },
                    { key: 'faq', title: tr('常见问题', 'FAQ', 'よくある質問') },
                  ].map((section) => (
                    <div key={section.key} className="rounded-lg border border-slate-200 bg-slate-50">
                      <button
                        type="button"
                        onClick={() => setActiveHelpSection((prev) => (prev === section.key ? null : (section.key as 'modules' | 'workflow' | 'shortcuts' | 'faq')))}
                        className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-800 hover:bg-slate-100"
                      >
                        <span>{section.title}</span>
                        <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${activeHelpSection === section.key ? 'rotate-180' : ''}`} />
                      </button>

                      {activeHelpSection === section.key && (
                        <div className="space-y-1.5 border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
                          {section.key === 'modules' && (
                            <>
                              <p>{tr('文档管理：上传、检索、预览、下载文档。', 'Documents: upload, search, preview, and download files.', '文書管理: アップロード・検索・プレビュー・ダウンロード。')}</p>
                              <p>{tr('智能助手：通过自然语言提取、改写、转换内容。', 'Doc Operations: extract, rewrite, and convert via natural language.', '文書操作: 自然言語で抽出・改写・変換。')}</p>
                              <p>{tr('表格填写：从源文档自动填充模板表格。', 'Table Fill: auto-fill templates from source docs.', '表入力: ソース文書からテンプレートに自動入力。')}</p>
                              <p>{tr('知识图谱：查看实体关系与跨文档关联。', 'Knowledge Graph: view entity relations across docs.', 'ナレッジグラフ: 文書横断の関係を確認。')}</p>
                              <p>{tr('工作日志：查看统计、维护待办、导出日志。', 'Work Log: stats, todos, and export.', '作業ログ: 統計・TODO・エクスポート。')}</p>
                            </>
                          )}

                          {section.key === 'workflow' && (
                            <>
                              <p>{tr('1. 上传源文档和模板。', '1) Upload source docs and templates.', '1) ソース文書とテンプレートをアップロード。')}</p>
                              <p>{tr('2. 在智能助手中完成提取与处理。', '2) Process and extract in Doc Operations.', '2) 文書操作で処理・抽出。')}</p>
                              <p>{tr('3. 在表格填写中生成业务表格。', '3) Generate business tables in Table Fill.', '3) 表入力で業務表を生成。')}</p>
                              <p>{tr('4. 在工作日志导出结果与过程记录。', '4) Export records in Work Log.', '4) 作業ログで記録を出力。')}</p>
                            </>
                          )}

                          {section.key === 'shortcuts' && (
                            <>
                              <p>{`${SHORTCUTS.uploadSource}: ${tr('上传源文档', 'Upload source docs', 'ソース文書をアップロード')}`}</p>
                              <p>{`${SHORTCUTS.uploadTemplate}: ${tr('上传模板', 'Upload templates', 'テンプレートをアップロード')}`}</p>
                              <p>{`${SHORTCUTS.exportWorkLog}: ${tr('导出工作日志', 'Export work log', '作業ログをエクスポート')}`}</p>
                              <p>{tr('可在“设置-系统偏好”中关闭快捷键。', 'You can disable shortcuts in Settings -> Preferences.', '設定 -> システム設定で無効化できます。')}</p>
                            </>
                          )}

                          {section.key === 'faq' && (
                            <>
                              <p>{tr('Q: 为什么没看到铃铛通知？ A: 请在设置中开启“桌面通知”。', 'Q: No bell notifications? A: Enable "Desktop Notifications" in Settings.', 'Q: 通知が出ない？ A: 設定で「デスクトップ通知」を有効化。')}</p>
                              <p>{tr('Q: 提取失败怎么办？ A: 在文档管理里点击“重新提取”。', 'Q: Extraction failed? A: Click "Retry extraction" in Documents.', 'Q: 抽出失敗時は？ A: 文書管理で「再抽出」。')}</p>
                              <p>{tr('Q: 导出的日志在哪？ A: 浏览器下载目录，文件名 work-log-日期.json。', 'Q: Where is exported log? A: Browser download folder, named work-log-date.json.', 'Q: エクスポート先は？ A: ブラウザのダウンロード先です。')}</p>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={() => navigate('/profile')}
            className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 transition-colors hover:bg-slate-50 md:flex"
            title={dict.enterProfile}
          >
            <div className="flex h-5 w-5 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-blue-500">
              <User className="h-3 w-3 text-white" />
            </div>
            <span className="text-sm text-slate-700">{user?.username || dict.userFallback}</span>
          </button>

          <button onClick={handleLogout} className="btn-secondary px-2 py-1 text-sm" title={dict.logout}>
            <LogOut className="h-4 w-4" />
            {dict.logout}
          </button>
        </div>
      </div>
    </header>
  )
}
