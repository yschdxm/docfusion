/**
 * useTheme — 共享主题 hook
 *
 * 监听 document.documentElement 的 data-theme 属性变化，
 * 返回当前主题（'light' | 'dark'）。
 *
 * 替代各组件自建 MutationObserver 的重复代码。
 */

import { useState, useEffect } from 'react'

export function useTheme(): 'light' | 'dark' {
  const [theme, setTheme] = useState<'light' | 'dark'>(
    document.documentElement.getAttribute('data-theme') === 'night-mode' ? 'dark' : 'light'
  )

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setTheme(
        document.documentElement.getAttribute('data-theme') === 'night-mode' ? 'dark' : 'light'
      )
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    return () => observer.disconnect()
  }, [])

  return theme
}
