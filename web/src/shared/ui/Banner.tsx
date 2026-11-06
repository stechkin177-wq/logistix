import type { ReactNode } from 'react'

type Kind = 'info' | 'warning' | 'error'

const KINDS: Record<Kind, string> = {
  info: 'border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100',
  warning:
    'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100',
  error:
    'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100',
}

export function Banner({ kind = 'info', children }: { kind?: Kind; children: ReactNode }) {
  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      className={`rounded border px-3 py-2 text-sm ${KINDS[kind]}`}
    >
      {children}
    </div>
  )
}
