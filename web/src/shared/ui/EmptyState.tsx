import type { ReactNode } from 'react'
import { Inbox, type LucideIcon } from './icons'

export function EmptyState({ title, hint, children, icon: Icon = Inbox }: { title: string; hint?: string; children?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="flex flex-col items-center gap-1.5 px-4 py-14 text-center">
      <span className="mb-1 inline-flex size-11 items-center justify-center rounded-full bg-surface-2 text-muted">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-sm text-xs text-muted">{hint}</p> : null}
      {children}
    </div>
  )
}
