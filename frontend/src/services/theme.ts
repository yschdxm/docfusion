export type ThemeMode = 'business-blue' | 'night-mode'

const THEME_STORAGE_KEY = 'docfusion_theme'

const isThemeMode = (value: string): value is ThemeMode => {
  return value === 'business-blue' || value === 'night-mode'
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
  return 'business-blue'
}

export const applyTheme = (theme: ThemeMode) => {
  document.documentElement.setAttribute('data-theme', theme)
}

export const setTheme = (theme: ThemeMode) => {
  localStorage.setItem(THEME_STORAGE_KEY, theme)
  applyTheme(theme)
}

export const initTheme = () => {
  applyTheme(getStoredTheme())
}
