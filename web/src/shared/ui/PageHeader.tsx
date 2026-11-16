import { useContext, useEffect, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from 'react-i18next'
import { useBranding } from '../branding/useBranding'
import { createPortal } from 'react-dom'
import { HeaderSlotContext, HintSlotContext } from './headerBleed'
import { PageHint } from './PageHint'
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
  /** Ключ пояснения (hints.<ключ>.title/text): показывается первой строкой под шапкой. */
  hint?: string
}

/** Единая шапка страницы: [← назад] [иконка] Название [статус] ........ [действия]. Единственный h1 страницы. */
export function PageHeader({ title, icon: Icon, subtitle, back, meta, actions, hint }: Props) {
  const { t } = useTranslation()
  const { app_name: appName } = useBranding()
  const slot = useContext(HeaderSlotContext)
  const hintSlot = useContext(HintSlotContext)
  // заголовок вкладки браузера повторяет название раздела: вкладки и история различимы
  const text = typeof title === 'string' ? title : null
  useEffect(() => {
    if (text === null) return
    document.title = `${text} · ${appName}`
    return () => { document.title = appName }
  }, [text, appName])
  const header = (
    <header className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-2 ${slot ? 'rounded-card border border-line bg-surface px-3 py-2 shadow-card md:px-4' : 'pb-2 pt-3'}`}>
      <div className="flex min-w-0 flex-[1_1_16rem] flex-wrap items-center gap-x-3 gap-y-1">
        {back ? (
          <Link
            to={back.to}
            aria-label={`${t('common.back')}: ${back.label}`}
            title={back.label}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-control border border-line bg-surface text-muted hover:text-ink"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
          </Link>
        ) : null}
        {Icon ? (
          <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-200">
            <Icon className="size-[18px]" aria-hidden="true" />
          </span>
        ) : null}
        <div className="min-w-[8rem] max-w-full flex-1">
          <h1 className="line-clamp-2 break-words text-lg font-semibold leading-tight text-ink">{title}</h1>
          {subtitle ? <p className="line-clamp-2 text-xs text-muted">{subtitle}</p> : null}
        </div>
        {meta ? <div className="flex flex-wrap items-center gap-2">{meta}</div> : null}
      </div>
      {actions ? <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-2">{actions}</div> : null}
    </header>
  )
  const hintNode = hint ? <PageHint hint={hint} /> : null
  if (slot === undefined) return <>{header}{hintNode}</>
  return (
    <>
      {slot ? createPortal(header, slot) : null}
      {hintNode && hintSlot ? createPortal(hintNode, hintSlot) : null}
    </>
  )
}
