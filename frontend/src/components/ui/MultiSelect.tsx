import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Search, X, Check } from 'lucide-react'
import { useI18n } from '../../hooks/useI18n'

export interface MultiSelectOption {
  value: string
  label: string
  description?: string
  tag?: string
}

interface MultiSelectProps {
  values: string[]
  onChange: (values: string[]) => void
  options: MultiSelectOption[]
  placeholder?: string
  searchPlaceholder?: string
  className?: string
  maxHeight?: number
  disabled?: boolean
}

export default function MultiSelect({
  values,
  onChange,
  options,
  placeholder,
  searchPlaceholder,
  className = '',
  maxHeight = 250,
  disabled = false,
}: MultiSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const { language } = useI18n()

  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)

  const defaultPlaceholder = placeholder || tr('请选择', 'Please select', '選択してください')
  const defaultSearchPlaceholder = searchPlaceholder || tr('搜索...', 'Search...', '検索...')

  const selectedOptions = useMemo(
    () => options.filter(opt => values.includes(opt.value)),
    [options, values]
  )

  const filteredOptions = useMemo(
    () => search
      ? options.filter(opt =>
          opt.label.toLowerCase().includes(search.toLowerCase()) ||
          opt.description?.toLowerCase().includes(search.toLowerCase()) ||
          opt.tag?.toLowerCase().includes(search.toLowerCase())
        )
      : options,
    [options, search]
  )

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (isOpen && searchInputRef.current) {
      searchInputRef.current.focus()
    }
  }, [isOpen])

  const toggleOption = (value: string) => {
    const newValues = values.includes(value)
      ? values.filter(v => v !== value)
      : [...values, value]
    onChange(newValues)
  }

  const removeValue = (value: string, e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(values.filter(v => v !== value))
  }

  const clearAll = (e: React.MouseEvent) => {
    e.stopPropagation()
    onChange([])
    setIsOpen(false)
  }

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`w-full flex items-center gap-2 px-3 py-2 min-h-[38px] rounded-xl border
          ${isOpen ? 'border-blue-400 dark:border-blue-500 ring-2 ring-blue-400/20' : 'border-slate-200 dark:border-slate-600'}
          ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-slate-300 dark:hover:border-slate-500'}
          bg-white dark:bg-slate-700 transition-colors text-left`}
      >
        <div className="flex-1 flex flex-wrap gap-1.5">
          {selectedOptions.length > 0 ? (
            selectedOptions.map(opt => (
              <span
                key={opt.value}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs
                  bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300"
              >
                <span className="max-w-[150px] truncate">{opt.label}</span>
                {!disabled && (
                  <button
                    type="button"
                    onClick={(e) => removeValue(opt.value, e)}
                    className="shrink-0 hover:text-blue-900 dark:hover:text-blue-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </span>
            ))
          ) : (
            <span className="text-sm text-slate-400 dark:text-slate-500">{defaultPlaceholder}</span>
          )}
        </div>
        <div className="shrink-0 flex items-center gap-1">
          {selectedOptions.length > 0 && !disabled && (
            <button
              type="button"
              onClick={clearAll}
              className="p-0.5 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {isOpen && (
        <div
          className="absolute left-0 right-0 mt-1 rounded-xl border border-slate-200 dark:border-slate-600
            bg-white dark:bg-slate-800 shadow-lg z-50 overflow-hidden"
        >
          {/* 搜索框 */}
          <div className="sticky top-0 p-2 border-b border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={defaultSearchPlaceholder}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-600
                  bg-slate-50 dark:bg-slate-700 text-slate-900 dark:text-slate-100
                  pl-8 pr-3 py-1.5 text-xs focus:ring-1 focus:ring-blue-500 focus:border-transparent"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>

          {/* 选项列表 */}
          <div className="overflow-y-auto scrollbar-thin" style={{ maxHeight: `${maxHeight}px` }}>
            {filteredOptions.length > 0 ? (
              filteredOptions.map((option) => {
                const isSelected = values.includes(option.value)
                return (
                  <div
                    key={option.value}
                    onClick={() => toggleOption(option.value)}
                    className={`flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors
                      ${isSelected
                        ? 'bg-blue-50 dark:bg-blue-900/30'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                      }`}
                  >
                    <div className={`shrink-0 w-4 h-4 rounded border flex items-center justify-center
                      ${isSelected
                        ? 'bg-blue-600 border-blue-600'
                        : 'border-slate-300 dark:border-slate-500'
                      }`}
                    >
                      {isSelected && <Check className="h-3 w-3 text-white" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-700 dark:text-slate-300 truncate">{option.label}</div>
                      {option.description && (
                        <div className="text-xs text-slate-500 dark:text-slate-400 truncate">{option.description}</div>
                      )}
                    </div>
                    {option.tag && (
                      <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] uppercase
                        bg-slate-100 dark:bg-slate-600 text-slate-500 dark:text-slate-400">
                        {option.tag}
                      </span>
                    )}
                  </div>
                )
              })
            ) : (
              <div className="px-4 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
                {search
                  ? tr('无匹配结果', 'No matching results', '一致する結果がありません')
                  : tr('暂无选项', 'No options', 'オプションなし')
                }
              </div>
            )}
          </div>

          {/* 底部统计 */}
          {selectedOptions.length > 0 && (
            <div className="px-3 py-2 border-t border-slate-200 dark:border-slate-600
              bg-slate-50 dark:bg-slate-700/50 text-xs text-slate-500 dark:text-slate-400">
              {tr('已选择', 'Selected', '選択済み')}: {selectedOptions.length}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
