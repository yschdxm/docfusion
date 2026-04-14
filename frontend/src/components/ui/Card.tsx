import { HTMLAttributes, forwardRef } from 'react'
import { clsx } from 'clsx'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'glass' | 'gradient'
}

const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = 'default', children, ...props }, ref) => {
    const variants = {
      default: 'bg-white border border-slate-200 rounded-xl',
      glass: 'bg-slate-50 border border-slate-200 rounded-xl',
      gradient: 'bg-gradient-to-br from-primary-50 to-blue-50 border border-primary-100 rounded-xl',
    }
    
    return (
      <div
        ref={ref}
        className={clsx(
          variants[variant],
          'transition-all duration-200 hover:border-primary-300 hover:shadow-lg hover:shadow-slate-300/40',
          className
        )}
        {...props}
      >
        {children}
      </div>
    )
  }
)

Card.displayName = 'Card'

export default Card
