import { useState, useRef, useEffect } from 'react'
import { ChevronDown } from 'lucide-react'

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
}

export default function Dropdown({
  value,
  onChange,
  options,
  placeholder = '请选择',
  className = '',
  buttonClassName = '',
  icon,
  dropup = false
}: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const selectedOption = options.find(opt => opt.value === value)

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

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
          {options.length > 0 ? (
            options.map((option) => (
              <div
                key={option.value}
                onClick={() => {
                  onChange(option.value)
                  setIsOpen(false)
                }}
                className={`dropdown-item ${value === option.value ? 'dropdown-item-active' : ''}`}
              >
                <span className="text-sm text-slate-700 whitespace-nowrap">{option.label}</span>
              </div>
            ))
          ) : (
            <div className="px-4 py-3 text-sm text-slate-500 text-center">
              暂无选项
            </div>
          )}
        </div>
      )}
    </div>
  )
}
