import type { ReactNode } from 'react'

export interface TabDef {
  key: string
  label: string
  disabled?: boolean
  title?: string
}

/** Вкладки (role=tablist); панель рендерит вызывающий. Выбранная вкладка хранится снаружи (URL). */
export function Tabs({ tabs, active, onChange, label }: { tabs: TabDef[]; active: string; onChange: (key: string) => void; label: string }): ReactNode {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700">
      {tabs.map((tab) => (
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
          className={`whitespace-nowrap border-b-2 px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${
            active === tab.key
              ? 'border-brand-600 font-medium text-brand-700 dark:text-brand-300'
              : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-300'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
