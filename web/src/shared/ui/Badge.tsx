import type { ReactNode } from 'react'

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

/** Цвета подобраны с контрастом не ниже 4.5:1 (тёмный текст на светлом фоне и наоборот). */
const TONES: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100',
  info: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100',
  success: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
  warning: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100',
  danger: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100',
}

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}
