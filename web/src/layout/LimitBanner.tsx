import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useUsage } from '../features/billing/usage'
import { useSession } from '../shared/auth/useSession'
import { Banner } from '../shared/ui/Banner'

/** Владельцу компании (право управления модулями): лимит тарифа приближается, достигнут или превышен. */
export function LimitBanner() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const usage = useUsage(hasPermission('company.manage_modules'))
  const warnings = usage.data?.warnings ?? []
  if (warnings.length === 0) return null
  const exceeded = warnings.some((w) => w.state === 'exceeded')
  const first = warnings.find((w) => w.state === 'exceeded') ?? warnings[0]
  if (!first) return null
  return (
    <Banner kind="warning">
      {t(`billing.usage.banner.${exceeded ? 'exceeded' : first.state}`, { name: first.name, usage: first.usage ?? 0, limit: first.limit ?? 0, count: warnings.length })}{' '}
      <Link className="underline" to="/settings/company">{t('billing.usage.details')}</Link>
    </Banner>
  )
}
