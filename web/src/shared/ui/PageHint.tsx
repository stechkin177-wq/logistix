import { useTranslation } from 'react-i18next'
import { Info } from './icons'

/** Пояснение под шапкой: значок, короткий заголовок и текст «что это и как работает». */
export function PageHint({ hint }: { hint: string }) {
  const { t } = useTranslation()
  return (
    <aside className="flex items-start gap-3 rounded-card border border-brand-200/70 bg-brand-50/60 px-3 py-2.5 dark:border-brand-800/50 dark:bg-brand-900/20">
      <Info className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-ink">{t(`hints.${hint}.title`)}</p>
        <p className="text-muted">{t(`hints.${hint}.text`)}</p>
      </div>
    </aside>
  )
}
