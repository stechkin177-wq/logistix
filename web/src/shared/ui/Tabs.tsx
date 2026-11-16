import type { ReactNode } from 'react'
import type { LucideIcon } from './icons'

export interface TabDef {
  key: string
  label: string
  disabled?: boolean
  title?: string
  icon?: LucideIcon
  /** Счётчик у подписи (число записей во вкладке). */
  count?: number
}

/** Вкладки (role=tablist); панель рендерит вызывающий. Выбранная вкладка хранится снаружи (URL). */
export function Tabs({
  tabs, active, onChange, label, variant = 'underline',
}: { tabs: TabDef[]; active: string; onChange: (key: string) => void; label: string; variant?: 'underline' | 'pills' }): ReactNode {
  const pills = variant === 'pills'
  return (
    <div
      role="tablist"
      aria-label={label}
      className={`thin-scroll scroll-shadow-x flex gap-1 overflow-x-auto [--scroll-bg:var(--ui-canvas)] ${pills ? 'rounded-card border border-line bg-surface p-1 shadow-card' : 'border-b border-line'}`}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon
        return (
          <button
            key={tab.key}
            role="tab"
            type="button"
            id={`tab-${tab.key}`}
            aria-selected={active === tab.key}
            aria-controls={`panel-${tab.key}`}
            disabled={tab.disabled}
            title={tab.title}
            onClick={() => {
              onChange(tab.key)
            }}
            className={
              pills
                ? `inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-control px-3 py-1.5 text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    active === tab.key ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
                  }`
                : `-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    active === tab.key
                      ? 'border-brand-600 font-medium text-brand-700 dark:text-brand-300'
                      : 'border-transparent text-muted hover:text-ink'
                  }`
            }
          >
            {Icon ? <Icon className={pills ? 'size-3.5 shrink-0' : 'size-4'} aria-hidden="true" /> : null}
            {tab.label}
            {tab.count !== undefined && tab.count > 0 ? (
              <span className="rounded-md border border-line px-1.5 text-[11px] leading-4 text-muted">{tab.count}</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
