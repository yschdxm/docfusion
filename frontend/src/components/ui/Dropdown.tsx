import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Search } from 'lucide-react'

interface DropdownOption {
  value: string
  label: string
}

interface DropdownProps {
  value: string
  onChange: (value: string) => void
  options: DropdownOption[]
  placeholder?: string
  className?: string
  buttonClassName?: string
  icon?: React.ReactNode
  dropup?: boolean
  searchable?: boolean
}

export default function Dropdown({
  value,
  onChange,
  options,
  placeholder = '请选择',
  className = '',
  buttonClassName = '',
  icon,
  dropup = false,
  searchable = false,
}: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const selectedOption = options.find(opt => opt.value === value)

  const filteredOptions = searchable && search
    ? options.filter(opt => opt.label.toLowerCase().includes(search.toLowerCase()))
    : options

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
    if (isOpen && searchable && searchInputRef.current) {
      searchInputRef.current.focus()
    }
  }, [isOpen, searchable])

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center gap-2 px-3 py-2 bg-transparent border-0 rounded-lg
                  hover:bg-slate-100/50 transition-colors text-left ${buttonClassName}`}
      >
        {icon && <span className="shrink-0">{icon}</span>}
        <span className="text-sm font-semibold text-[var(--theme-primary)] flex-1 whitespace-nowrap">
          {selectedOption?.label || placeholder}
        </span>
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform shrink-0 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className={`absolute left-0 right-0 dropdown-menu max-h-60 overflow-y-auto scrollbar-thin z-[9999] ${dropup ? 'bottom-full mb-2' : 'top-full mt-2'}`}>
          {searchable && (
            <div className="sticky top-0 bg-white dark:bg-slate-800 p-2 border-b border-slate-200 dark:border-slate-600">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索..."
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 text-slate-900 dark:text-slate-100 pl-8 pr-3 py-1.5 text-xs focus:ring-1 focus:ring-blue-500 focus:border-transparent"
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            </div>
          )}
          {filteredOptions.length > 0 ? (
            filteredOptions.map((option) => (
              <div
                key={option.value}
                onClick={() => {
                  onChange(option.value)
                  setIsOpen(false)
                  setSearch('')
                }}
                className={`dropdown-item ${value === option.value ? 'dropdown-item-active' : ''}`}
              >
                <span className="text-sm text-slate-700 whitespace-nowrap">{option.label}</span>
              </div>
            ))
          ) : (
            <div className="px-4 py-3 text-sm text-slate-500 text-center">
              {search ? '无匹配结果' : '暂无选项'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
