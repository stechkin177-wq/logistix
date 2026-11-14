import { useState, type ReactNode, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { SlidersHorizontal } from './icons'

/** Строка фильтров: поля переносятся на узких экранах; «Сбросить» очищает всё. */
export function FilterBar({
  children, onReset, canReset = true, actions,
}: {
  children: ReactNode
  onReset?: () => void
  canReset?: boolean
  actions?: ReactNode
}) {
  const { t } = useTranslation()
  // на телефоне поля фильтров свёрнуты под кнопку: список виден сразу, без прокрутки через все поля
  const [open, setOpen] = useState(false)
  return (
    <form
      role="search"
      onSubmit={(event: SyntheticEvent) => {
        event.preventDefault()
      }}
      className="flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-3 shadow-card"
    >
      <Button className="md:hidden" icon={SlidersHorizontal} aria-expanded={open} onClick={() => { setOpen(!open) }}>
        {t('common.filters')}
      </Button>
      <div className={open ? 'contents' : 'hidden md:contents'}>
        {children}
        {onReset ? (
          <Button onClick={onReset} disabled={!canReset}>
            {t('common.reset')}
          </Button>
        ) : null}
      </div>
      {actions ? <div className="ml-auto flex items-end gap-2">{actions}</div> : null}
    </form>
  )
}

/** Обёртка поля фильтра с ограниченной шириной. */
export function FilterItem({ children, className = 'w-40' }: { children: ReactNode; className?: string }) {
  return <div className={`min-w-0 ${className} max-sm:w-full`}>{children}</div>
}
