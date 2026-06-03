export type ThemeMode = 'business-blue' | 'night-mode' | 'system'

export type ResolvedTheme = 'business-blue' | 'night-mode'

const THEME_STORAGE_KEY = 'docfusion_theme'

// 系统主题变化事件
export const SYSTEM_THEME_CHANGE_EVENT = 'system-theme-change'

const isThemeMode = (value: string): value is ThemeMode => {
  return value === 'business-blue' || value === 'night-mode' || value === 'system'
}

// 获取系统主题偏好
const getSystemTheme = (): ResolvedTheme => {
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'night-mode'
  }
  return 'business-blue'
}

// 解析主题：如果是 system 则返回系统主题
const resolveTheme = (theme: ThemeMode): ResolvedTheme => {
  if (theme === 'system') return getSystemTheme()
  return theme
}

export const getStoredTheme = (): ThemeMode => {
  const saved = localStorage.getItem(THEME_STORAGE_KEY)

  if (saved === 'tech-black') {
    localStorage.setItem(THEME_STORAGE_KEY, 'night-mode')
    return 'night-mode'
  }

  if (saved === 'default') {
    localStorage.setItem(THEME_STORAGE_KEY, 'business-blue')
    return 'business-blue'
  }

  if (saved && isThemeMode(saved)) return saved
  return 'system'  // 默认跟随系统
}

export const getTheme = (): ResolvedTheme => {
  const current = document.documentElement.getAttribute('data-theme')
  if (current === 'night-mode') return 'night-mode'
  return 'business-blue'
}

export const applyTheme = (theme: ResolvedTheme) => {
  document.documentElement.setAttribute('data-theme', theme)
  // 同步 Tailwind dark mode class，使 dark: 前缀类生效
  if (theme === 'night-mode') {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export const setTheme = (theme: ThemeMode) => {
  localStorage.setItem(THEME_STORAGE_KEY, theme)
  const resolved = resolveTheme(theme)
  applyTheme(resolved)

  // 触发主题变化事件
  window.dispatchEvent(new CustomEvent(SYSTEM_THEME_CHANGE_EVENT, { detail: { theme, resolved } }))
}

// 初始化系统主题监听
let systemThemeCleanup: (() => void) | null = null

const setupSystemThemeListener = () => {
  if (systemThemeCleanup) {
    systemThemeCleanup()
  }

  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

  const handleChange = () => {
    const storedTheme = getStoredTheme()
    if (storedTheme === 'system') {
      const resolved = getSystemTheme()
      applyTheme(resolved)
      window.dispatchEvent(new CustomEvent(SYSTEM_THEME_CHANGE_EVENT, {
        detail: { theme: 'system', resolved }
      }))
    }
  }

  mediaQuery.addEventListener('change', handleChange)

  systemThemeCleanup = () => {
    mediaQuery.removeEventListener('change', handleChange)
  }
}

export const initTheme = () => {
  const storedTheme = getStoredTheme()
  const resolved = resolveTheme(storedTheme)
  applyTheme(resolved)

  // 设置系统主题监听
  setupSystemThemeListener()
}

// 获取当前实际应用的主题（用于 UI 显示）
export const getCurrentTheme = (): ThemeMode => {
  return getStoredTheme()
}
