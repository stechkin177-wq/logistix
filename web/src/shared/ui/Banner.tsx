import type { ReactNode } from 'react'
import { CircleAlert, Info, TriangleAlert } from './icons'

type Kind = 'info' | 'warning' | 'error'

const KINDS: Record<Kind, string> = {
  info: 'border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100',
  warning:
    'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100',
  error:
    'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100',
}

const ICONS = { info: Info, warning: TriangleAlert, error: CircleAlert } as const

export function Banner({ kind = 'info', children }: { kind?: Kind; children: ReactNode }) {
  const Icon = ICONS[kind]
  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      className={`flex items-start gap-2 rounded-card border px-3.5 py-2.5 text-sm ${KINDS[kind]}`}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
