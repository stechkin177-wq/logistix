import { Link } from 'react-router'
import type { LucideIcon } from './icons'

/** Карточка-показатель; со ссылкой (to) ведёт в соответствующий раздел. tone окрашивает значение (минус - красным). */
export function Stat({
  label, value, to, icon: Icon, tone, note,
}: { label: string; value: string; to?: string; icon?: LucideIcon; tone?: 'danger' | 'success'; note?: string }) {
  const color = tone === 'danger' ? 'text-red-600 dark:text-red-400' : tone === 'success' ? 'text-emerald-600 dark:text-emerald-400' : 'text-ink'
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-muted">{label}</p>
        {Icon ? <Icon className="size-4 shrink-0 text-muted" aria-hidden="true" /> : null}
      </div>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {note ? <p className="mt-1 text-xs text-muted">{note}</p> : null}
    </>
  )
  const cls = 'rounded-card border border-line bg-surface-2 p-4 dark:bg-surface-2'
  return to ? (
    <Link to={to} className={`${cls} block transition-colors hover:border-brand-400`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}
