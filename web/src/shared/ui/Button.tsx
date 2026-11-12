import type { ButtonHTMLAttributes } from 'react'
import type { LucideIcon } from './icons'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-brand-600 text-brand-fg shadow-sm hover:bg-brand-solid-hover focus-visible:outline-brand-500',
  secondary:
    'border border-line bg-surface text-ink shadow-sm hover:bg-surface-2 dark:hover:bg-surface-2',
  ghost: 'text-ink hover:bg-surface-2',
  danger: 'bg-red-600 text-white shadow-sm hover:bg-red-700',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  /** Иконка слева от подписи (декоративная: подпись остаётся доступным именем). */
  icon?: LucideIcon
}

export function Button({ variant = 'secondary', icon: Icon, className = '', type = 'button', children, ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-control px-3.5 text-sm font-medium outline-offset-2 transition-colors focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {Icon ? <Icon className="size-4 shrink-0" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}
