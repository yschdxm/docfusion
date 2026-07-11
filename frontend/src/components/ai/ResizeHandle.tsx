/**
 * 拖动手柄组件
 *
 * 用于调整侧边栏宽度
 */

import { useCallback, useRef, useState } from 'react'
import { useI18n } from '../../hooks/useI18n'
import { getTheme } from '../../services/theme'
import { useEffect } from 'react'

interface ResizeHandleProps {
  /** 调整大小的回调，delta 为负数表示向左拖动（增大边栏宽度） */
  onResize: (delta: number) => void
  /** 拖动方向 */
  direction?: 'left' | 'right'
}

export default function ResizeHandle({ onResize, direction = 'left' }: ResizeHandleProps) {
  const { language } = useI18n()
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const [isDarkMode, setIsDarkMode] = useState(getTheme() === 'night-mode')
  const [isDragging, setIsDragging] = useState(false)
  const dragStartRef = useRef<{ x: number } | null>(null)

  // 监听主题变化
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.getAttribute('data-theme') === 'night-mode')
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const handleDragStart = useCallback((clientX: number) => {
    dragStartRef.current = { x: clientX }
    setIsDragging(true)

    const handleMove = (ev: MouseEvent | TouchEvent) => {
      if (!dragStartRef.current) return
      const x = 'touches' in ev ? ev.touches[0].clientX : ev.clientX
      const delta = dragStartRef.current.x - x
      onResize(direction === 'left' ? delta : -delta)
      dragStartRef.current = { x }
    }

    const handleEnd = () => {
      dragStartRef.current = null
      setIsDragging(false)
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleEnd)
      document.removeEventListener('touchmove', handleMove)
      document.removeEventListener('touchend', handleEnd)
    }

    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleEnd)
    document.addEventListener('touchmove', handleMove)
    document.addEventListener('touchend', handleEnd)
  }, [onResize, direction])

  return (
    <>
      <div
        onMouseDown={(e) => handleDragStart(e.clientX)}
        onTouchStart={(e) => handleDragStart(e.touches[0].clientX)}
        className={`shrink-0 cursor-col-resize group flex items-center justify-center transition-colors ${
          isDarkMode ? 'hover:bg-slate-700' : 'hover:bg-slate-100'
        }`}
        style={{ width: 12 }}
        title={tr('拖动调整宽度', 'Drag to resize', 'ドラッグしてリサイズ')}
      >
        <div className={`w-0.5 h-8 rounded-full transition-colors ${
          isDarkMode
            ? 'bg-slate-600 group-hover:bg-primary-400'
            : 'bg-slate-300 group-hover:bg-primary-400'
        }`} />
      </div>
      {/* 拖动时的透明遮罩，防止 iframe 抢夺事件 */}
      {isDragging && (
        <div className="fixed inset-0 z-50 cursor-col-resize" />
      )}
    </>
  )
}
