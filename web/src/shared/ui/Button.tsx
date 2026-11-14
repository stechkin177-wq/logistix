import type { ButtonHTMLAttributes } from 'react'
import type { LucideIcon } from './icons'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerSoft' | 'dangerGhost'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-brand-600 text-brand-fg shadow-sm hover:bg-brand-solid-hover focus-visible:outline-brand-500',
  secondary:
    'border border-line bg-surface text-ink shadow-sm hover:bg-surface-2 dark:hover:bg-surface-2',
  ghost: 'text-ink hover:bg-surface-2',
  danger: 'bg-red-600 text-white shadow-sm hover:bg-red-700',
  /** Удаление в шапке страницы: заметно, но не конкурирует с главной кнопкой. */
  dangerSoft:
    'border border-red-300 bg-surface text-red-700 shadow-sm hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950',
  /** Удаление в строке таблицы. */
  dangerGhost: 'text-red-700 hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950',
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
