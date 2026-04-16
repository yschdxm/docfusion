export interface PreferenceState {
  desktopNotice: boolean
  keyboardShortcuts: boolean
}

export const PREFERENCES_STORAGE_KEY = 'profile_center_preferences'
export const PREFERENCES_CHANGED_EVENT = 'docfusion-preferences-changed'

export const defaultPreferences: PreferenceState = {
  desktopNotice: false,
  keyboardShortcuts: true,
}

export const getStoredPreferences = (): PreferenceState => {
  const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY)
  if (!raw) return defaultPreferences
  try {
    return { ...defaultPreferences, ...(JSON.parse(raw) as Partial<PreferenceState>) }
  } catch {
    return defaultPreferences
  }
}

export const setStoredPreferences = (next: PreferenceState) => {
  localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(next))
  window.dispatchEvent(new Event(PREFERENCES_CHANGED_EVENT))
}
