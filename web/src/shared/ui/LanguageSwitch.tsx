import { useTranslation } from 'react-i18next'
import { LANGUAGES, setLanguage } from '../i18n'
import { SelectBox } from './SelectBox'

/** Выбор языка: компактный список «RU ⌄» (русский по умолчанию). */
export function LanguageSwitch({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  return (
    <SelectBox className={`inline-block ${className}`}>
      <select
        aria-label={t('common.language')}
        title={t('common.language')}
        value={i18n.resolvedLanguage ?? 'ru'}
        onChange={(e) => { setLanguage(e.target.value as (typeof LANGUAGES)[number]) }}
        className="h-9 w-[4.25rem] cursor-pointer appearance-none rounded-control bg-transparent pl-2.5 pr-7 text-sm font-medium uppercase text-muted outline-brand-500 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        {LANGUAGES.map((lng) => (
          <option key={lng} value={lng} title={t(`languages.${lng}`)}>{lng.toUpperCase()}</option>
        ))}
      </select>
    </SelectBox>
  )
}
