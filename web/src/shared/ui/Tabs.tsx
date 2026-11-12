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
export function Tabs({ tabs, active, onChange, label }: { tabs: TabDef[]; active: string; onChange: (key: string) => void; label: string }): ReactNode {
  return (
    <div role="tablist" aria-label={label} className="thin-scroll flex gap-1 overflow-x-auto border-b border-line">
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
            className={`-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active === tab.key
                ? 'border-brand-600 font-medium text-brand-700 dark:text-brand-300'
                : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {Icon ? <Icon className="size-4" aria-hidden="true" /> : null}
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
