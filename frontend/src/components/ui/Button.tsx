import { ButtonHTMLAttributes, forwardRef } from 'react'
import { clsx } from 'clsx'
import { Loader2 } from 'lucide-react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost'
  isLoading?: boolean
  size?: 'sm' | 'md' | 'lg'
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', isLoading, children, disabled, ...props }, ref) => {
    const baseStyles = 'inline-flex items-center justify-center font-medium rounded-xl transition-all duration-200 transform'
    
    const variants = {
      primary: 'bg-gradient-to-r from-primary-500 to-purple-500 text-white hover:from-primary-600 hover:to-purple-600 hover:scale-105 active:scale-95 shadow-lg hover:shadow-primary-500/25',
      secondary: 'bg-white/10 text-white border border-white/20 hover:bg-white/20 hover:border-white/30 hover:scale-105 active:scale-95',
      ghost: 'text-slate-400 hover:text-white hover:bg-white/10',
    }
    
    const sizes = {
      sm: 'px-4 py-2 text-sm',
      md: 'px-6 py-3 text-sm',
      lg: 'px-8 py-4 text-base',
    }
    
    return (
      <button
        ref={ref}
        className={clsx(
          baseStyles,
          variants[variant],
          sizes[size],
          (disabled || isLoading) && 'opacity-50 cursor-not-allowed hover:scale-100',
          className
        )}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'

export default Button
