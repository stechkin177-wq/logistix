import type { ReactNode } from 'react'

export function EmptyState({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 px-4 py-12 text-center">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {hint ? <p className="text-xs text-slate-500">{hint}</p> : null}
      {children}
    </div>
  )
}
