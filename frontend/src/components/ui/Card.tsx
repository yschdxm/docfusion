import { HTMLAttributes, forwardRef } from 'react'
import { clsx } from 'clsx'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'glass' | 'gradient'
}

const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = 'default', children, ...props }, ref) => {
    const variants = {
      default: 'bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl',
      glass: 'bg-white/10 backdrop-blur-xl border border-white/20 rounded-xl',
      gradient: 'bg-gradient-to-br from-primary-500/10 to-purple-500/10 backdrop-blur-xl border border-white/10 rounded-xl',
    }
    
    return (
      <div
        ref={ref}
        className={clsx(
          variants[variant],
          'transition-all duration-300 hover:shadow-xl hover:shadow-primary-500/10',
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
