import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsMobile } from '../hooks/useIsMobile'
import { ChevronDown, Info } from './icons'

const KEY = 'logistix.hints.open'

function readOpen(hint: string): boolean {
  try { return (JSON.parse(localStorage.getItem(KEY) ?? '[]') as string[]).includes(hint) } catch { return false }
}

/**
 * Пояснение под шапкой: значок, короткий заголовок и текст «что это и как работает».
 * На телефоне свёрнуто до заголовка (чтобы не вытеснять список); раскрытое состояние запоминается.
 */
export function PageHint({ hint }: { hint: string }) {
  const { t } = useTranslation()
  const mobile = useIsMobile()
  const [open, setOpen] = useState(() => readOpen(hint))
  const collapsed = mobile && !open
  const toggle = () => {
    const next = !open
    setOpen(next)
    try {
      const all = new Set(JSON.parse(localStorage.getItem(KEY) ?? '[]') as string[])
      if (next) all.add(hint); else all.delete(hint)
      localStorage.setItem(KEY, JSON.stringify([...all]))
    } catch { /* хранилище недоступно */ }
  }
  const body = (
    <>
      <Info className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-ink">{t(`hints.${hint}.title`)}</p>
        {collapsed ? null : <p className="text-muted">{t(`hints.${hint}.text`)}</p>}
      </div>
      {mobile ? <ChevronDown className={`mt-0.5 size-4 shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" /> : null}
    </>
  )
  const cls = `flex items-start gap-3 rounded-card border border-brand-200/70 bg-brand-50/60 px-3 py-2.5 dark:border-brand-800/50 dark:bg-brand-900/20 ${mobile ? '' : 'min-h-[4.25rem]'}`
  return mobile ? (
    <aside>
      <button type="button" aria-expanded={open} onClick={toggle} className={`${cls} w-full text-left`}>{body}</button>
    </aside>
  ) : (
    <aside className={cls}>{body}</aside>
  )
}
