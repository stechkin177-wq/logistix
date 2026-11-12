import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, type LucideIcon } from './icons'

interface Props {
  title: ReactNode
  icon?: LucideIcon
  subtitle?: ReactNode
  /** Ссылка «назад»: страница-карточка возвращает в список. */
  back?: { to: string; label: string }
  /** Рядом с названием: статус, метки. */
  meta?: ReactNode
  /** Кнопки справа. */
  actions?: ReactNode
}

/** Единая шапка страницы: [← назад] [иконка] Название [статус] ........ [действия]. Единственный h1 страницы. */
export function PageHeader({ title, icon: Icon, subtitle, back, meta, actions }: Props) {
  const { t } = useTranslation()
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {back ? (
          <Link
            to={back.to}
            aria-label={`${t('common.back')}: ${back.label}`}
            title={back.label}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-control border border-line bg-surface text-muted hover:text-ink"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
          </Link>
        ) : Icon ? (
          <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-200">
            <Icon className="size-[18px]" aria-hidden="true" />
          </span>
        ) : null}
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold leading-tight text-ink">{title}</h1>
          {subtitle ? <p className="truncate text-xs text-muted">{subtitle}</p> : null}
        </div>
        {meta ? <div className="flex flex-wrap items-center gap-2">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}
