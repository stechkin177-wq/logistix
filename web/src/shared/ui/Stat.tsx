import { Link } from 'react-router'
import type { LucideIcon } from './icons'

/** Карточка-показатель; со ссылкой (to) ведёт в соответствующий раздел. tone окрашивает значение (минус - красным). */
export function Stat({
  label, value, to, icon: Icon, tone, note,
}: { label: string; value: string; to?: string; icon?: LucideIcon; tone?: 'danger' | 'success'; note?: string }) {
  const color = tone === 'danger' ? 'text-red-600 dark:text-red-400' : tone === 'success' ? 'text-emerald-600 dark:text-emerald-400' : 'text-ink'
  const body = (
    <>
      {Icon ? <Icon className="absolute right-4 top-4 size-4 text-muted" aria-hidden="true" /> : null}
      <p className="pr-6 text-xs font-medium text-muted">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {note ? <p className="mt-1 text-xs text-muted">{note}</p> : null}
    </>
  )
  const cls = 'relative rounded-card border border-line bg-surface-2 p-4 dark:bg-surface-2'
  return to ? (
    <Link to={to} className={`${cls} block transition-colors hover:border-brand-400`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}
