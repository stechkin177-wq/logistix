import { useEffect, useState, type ReactNode } from 'react'
import type { LucideIcon } from './icons'
import { MobilePinned } from './MobilePinned'

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
  tabs, active, onChange, label, variant = 'underline', pinned = false,
}: { tabs: TabDef[]; active: string; onChange: (key: string) => void; label: string; variant?: 'underline' | 'pills'; pinned?: boolean }): ReactNode {
  const pills = variant === 'pills'
  const [node, setNode] = useState<HTMLDivElement | null>(null)
  // активная вкладка всегда в видимой части ленты (узкий экран)
  useEffect(() => {
    const el = node?.querySelector('[aria-selected="true"]')
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [active, node])
  const list = (
    <div
      ref={setNode}
      role="tablist"
      aria-label={label}
      className={`thin-scroll scroll-shadow-x flex gap-1 overflow-x-auto overscroll-x-contain max-md:touch-none max-md:overflow-x-hidden [--scroll-bg:var(--ui-canvas)] ${pills ? 'rounded-card border border-line bg-surface p-1 shadow-card max-md:p-0.5' : 'border-b border-line'}`}
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
                ? `inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-control px-3 py-1.5 text-[13px] transition-colors max-md:min-w-0 max-md:shrink max-md:flex-1 max-md:flex-col max-md:justify-center max-md:gap-0.5 max-md:px-0.5 max-md:py-1 max-md:text-[11px] disabled:cursor-not-allowed disabled:opacity-50 ${
                    active === tab.key ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
                  }`
                : `-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors max-md:min-w-0 max-md:flex-1 max-md:justify-center max-md:px-1 max-md:text-xs disabled:cursor-not-allowed disabled:opacity-50 ${
                    active === tab.key
                      ? 'border-brand-600 font-medium text-brand-700 dark:text-brand-300'
                      : 'border-transparent text-muted hover:text-ink'
                  }`
            }
          >
            {Icon ? <Icon className={pills ? 'size-3.5 shrink-0' : 'size-4'} aria-hidden="true" /> : null}
            <span className="max-md:max-w-full max-md:truncate">{tab.label}</span>
            {tab.count !== undefined && tab.count > 0 ? (
              <span className="rounded-md border border-line px-1.5 text-[11px] leading-4 text-muted">{tab.count}</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
  // pinned: на телефоне вкладки неподвижны под шапкой страницы
  return pinned ? <MobilePinned>{list}</MobilePinned> : list
}
