import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useUsage } from '../features/billing/usage'
import { useSession } from '../shared/auth/useSession'
import { Banner } from '../shared/ui/Banner'
import { X } from '../shared/ui/icons'

const STORAGE_KEY = 'limit-banner-dismissed'

/** Владельцу компании (право управления модулями): лимит тарифа приближается, достигнут или превышен. */
export function LimitBanner() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const usage = useUsage(hasPermission('company.manage_modules'))
  const warnings = usage.data?.warnings ?? []
  // скрытие действует до конца сессии браузера и только для этого состояния лимита
  const stateKey = warnings.map((w) => `${w.name}:${w.state}`).join('|')
  const [dismissedKey, setDismissedKey] = useState<string | null>(() => (typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(STORAGE_KEY)))
  const dismissed = dismissedKey === stateKey
  if (warnings.length === 0 || dismissed) return null
  const exceeded = warnings.some((w) => w.state === 'exceeded')
  const first = warnings.find((w) => w.state === 'exceeded') ?? warnings[0]
  if (!first) return null
  return (
    <div className="relative">
    <Banner kind="warning">
      <span className="block pr-7">
      {t(`billing.usage.banner.${exceeded ? 'exceeded' : first.state}`, { name: first.name, usage: first.usage ?? 0, limit: first.limit ?? 0, count: warnings.length })}{' '}
      <Link className="underline" to="/settings/company">{t('billing.usage.details')}</Link>
      </span>
    </Banner>
    <button
      type="button"
      aria-label={t('common.close')}
      className="absolute right-1 top-1 inline-flex size-9 items-center justify-center rounded-control text-amber-900 hover:bg-amber-100 dark:text-amber-100 dark:hover:bg-amber-900"
      onClick={() => {
        sessionStorage.setItem(STORAGE_KEY, stateKey)
        setDismissedKey(stateKey)
      }}
    >
      <X className="size-4" aria-hidden="true" />
    </button>
    </div>
  )
}
