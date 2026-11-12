import type { ReactNode } from 'react'

export interface Segment {
  value: string
  label: ReactNode
}

/** Переключатель вида из двух-трёх кнопок (список/канбан и т. п.): группа с aria-pressed у выбранной. */
export function SegmentedControl({
  label, options, value, onChange,
}: { label: string; options: Segment[]; value: string; onChange: (value: string) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-control border border-line bg-surface-2 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => {
            onChange(option.value)
          }}
          className={`h-8 rounded-[0.4rem] px-3 text-sm font-medium transition-colors ${
            value === option.value ? 'bg-brand-600 text-brand-fg shadow-sm' : 'text-muted hover:text-ink'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
