import { useTranslation } from 'react-i18next'
import { LANGUAGES, setLanguage } from '../i18n'
import { Languages } from './icons'
import { SelectBox } from './SelectBox'

/** Выбор языка раскрывающимся списком (русский по умолчанию). */
export function LanguageSwitch({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  return (
    <SelectBox className={`inline-block ${className}`}>
      <Languages className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
      <select
        aria-label={t('common.language')}
        value={i18n.resolvedLanguage ?? 'ru'}
        onChange={(e) => { setLanguage(e.target.value as (typeof LANGUAGES)[number]) }}
        className="h-9 cursor-pointer appearance-none rounded-control border border-line bg-surface pl-8 pr-8 text-sm font-medium shadow-card"
      >
        {LANGUAGES.map((lng) => (
          <option key={lng} value={lng}>{t(`languages.${lng}`)}</option>
        ))}
      </select>
    </SelectBox>
  )
}
