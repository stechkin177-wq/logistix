import { Link } from 'react-router'

/** Карточка-показатель; со ссылкой (to) ведёт в соответствующий раздел. */
export function Stat({ label, value, to }: { label: string; value: string; to?: string }) {
  const body = (
    <>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
    </>
  )
  const cls = 'rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900'
  return to ? (
    <Link to={to} className={`${cls} block hover:border-brand-400`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}
