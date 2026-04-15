import { useEffect, useState } from 'react'
import { getStoredLanguage, I18N_CHANGED_EVENT, type LanguageCode } from '../services/i18n'

export function useI18n() {
  const [language, setLanguageState] = useState<LanguageCode>(getStoredLanguage())

  useEffect(() => {
    const syncLanguage = () => setLanguageState(getStoredLanguage())
    window.addEventListener(I18N_CHANGED_EVENT, syncLanguage)
    return () => window.removeEventListener(I18N_CHANGED_EVENT, syncLanguage)
  }, [])

  return { language }
}
