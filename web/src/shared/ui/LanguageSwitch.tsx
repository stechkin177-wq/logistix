import { useTranslation } from 'react-i18next'
import { LANGUAGES, setLanguage } from '../i18n'

/** Маленький переключатель языка: две кнопки RU / KK; выбранный язык выделен. */
export function LanguageSwitch({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  return (
    <div role="group" aria-label={t('common.language')} className={`inline-flex items-center rounded-control border border-line bg-surface-2 p-0.5 ${className}`}>
      {LANGUAGES.map((lng) => {
        const active = i18n.resolvedLanguage === lng
        return (
          <button
            key={lng}
            type="button"
            aria-pressed={active}
            title={t(`languages.${lng}`)}
            onClick={() => { setLanguage(lng) }}
            className={`h-7 min-w-9 rounded-[0.375rem] px-2 text-xs font-semibold uppercase transition-colors ${active ? 'bg-surface text-brand-700 shadow-sm dark:text-brand-200' : 'text-muted hover:text-ink'}`}
          >
            {lng}
          </button>
        )
      })}
    </div>
  )
}
