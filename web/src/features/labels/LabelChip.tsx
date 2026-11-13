import type { LabelRef } from './types'

/** Классы указаны целиком: Tailwind собирает только литералы. */
const COLORS: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-800 ring-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-600',
  red: 'bg-red-100 text-red-900 ring-red-300 dark:bg-red-950 dark:text-red-100 dark:ring-red-800',
  orange: 'bg-orange-100 text-orange-900 ring-orange-300 dark:bg-orange-950 dark:text-orange-100 dark:ring-orange-800',
  amber: 'bg-amber-100 text-amber-900 ring-amber-300 dark:bg-amber-950 dark:text-amber-100 dark:ring-amber-800',
  green: 'bg-emerald-100 text-emerald-900 ring-emerald-300 dark:bg-emerald-950 dark:text-emerald-100 dark:ring-emerald-800',
  teal: 'bg-teal-100 text-teal-900 ring-teal-300 dark:bg-teal-950 dark:text-teal-100 dark:ring-teal-800',
  blue: 'bg-blue-100 text-blue-900 ring-blue-300 dark:bg-blue-950 dark:text-blue-100 dark:ring-blue-800',
  violet: 'bg-violet-100 text-violet-900 ring-violet-300 dark:bg-violet-950 dark:text-violet-100 dark:ring-violet-800',
  pink: 'bg-pink-100 text-pink-900 ring-pink-300 dark:bg-pink-950 dark:text-pink-100 dark:ring-pink-800',
}

export function LabelChip({ label }: { label: Pick<LabelRef, 'name' | 'color'> }) {
  return (
    <span className={`inline-flex max-w-40 items-center truncate whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${COLORS[label.color] ?? COLORS.slate}`} title={label.name}>
      {label.name}
    </span>
  )
}

/** Метки объекта в списке или шапке; пусто - ничего не показываем. */
export function LabelChips({ labels }: { labels: LabelRef[] | undefined }) {
  if (!labels || labels.length === 0) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {labels.map((l) => <LabelChip key={l.id} label={l} />)}
    </span>
  )
}
