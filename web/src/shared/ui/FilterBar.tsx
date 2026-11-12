import type { ReactNode, SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'

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
  return (
    <form
      role="search"
      onSubmit={(event: SyntheticEvent) => {
        event.preventDefault()
      }}
      className="flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-3 shadow-card"
    >
      {children}
      {onReset ? (
        <Button onClick={onReset} disabled={!canReset}>
          {t('common.reset')}
        </Button>
      ) : null}
      {actions ? <div className="ml-auto flex items-end gap-2">{actions}</div> : null}
    </form>
  )
}

/** Обёртка поля фильтра с ограниченной шириной. */
export function FilterItem({ children, className = 'w-40' }: { children: ReactNode; className?: string }) {
  return <div className={`min-w-0 ${className}`}>{children}</div>
}
