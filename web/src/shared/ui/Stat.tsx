import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { LucideIcon } from './icons'

/**
 * Компактная плитка-показатель: ширина строго по содержимому (кладётся в flex-wrap контейнер).
 * sub - мелкая строка под значением; action - элемент управления в правом верхнем углу (настройка периода).
 * tone окрашивает значение (минус - красным); со ссылкой (to) ведёт в соответствующий раздел.
 */
export function Stat({
  label, value, to, icon: Icon, tone, note, sub, action,
}: { label: string; value: string; to?: string; icon?: LucideIcon; tone?: 'danger' | 'success'; note?: string; sub?: ReactNode; action?: ReactNode }) {
  const color = tone === 'danger' ? 'text-red-600 dark:text-red-400' : tone === 'success' ? 'text-emerald-600 dark:text-emerald-400' : 'text-ink'
  const body = (
    <>
      <p className={`flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-muted ${action ? 'pr-6' : ''}`}>
        {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden="true" /> : null}
        {label}
      </p>
      <p className={`whitespace-nowrap text-base font-semibold leading-snug tabular-nums ${color}`}>{value}</p>
      {sub ? <p className="whitespace-nowrap text-xs text-muted">{sub}</p> : null}
      {note ? <p className="text-xs text-muted">{note}</p> : null}
    </>
  )
  const cls = 'relative flex w-fit max-w-full flex-col rounded-control border border-line bg-surface-2 px-3 py-2'
  const inner = action ? (
    <div className={cls}>
      {body}
      <div className="absolute right-1 top-1">{action}</div>
    </div>
  ) : null
  if (inner) return inner
  return to ? (
    <Link to={to} className={`${cls} transition-colors hover:border-brand-400`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}
