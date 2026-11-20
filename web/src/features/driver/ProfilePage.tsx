import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useAuth } from '../../shared/auth/useAuth'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card } from '../../shared/ui/Card'
import { LanguageSwitch } from '../../shared/ui/LanguageSwitch'
import { Spinner } from '../../shared/ui/Spinner'
import { ThemeToggle } from '../../shared/ui/ThemeToggle'
import { LogOut } from '../../shared/ui/icons'
import { useDriverMe } from './hooks'
import { clearDriverCache } from './pwa'

/** Профиль водителя: данные карточки, язык, тема, выход (с очисткой кэша на устройстве). */
export function ProfilePage() {
  const { t } = useTranslation()
  const { date } = useFormat()
  const { logout } = useAuth()
  const me = useDriverMe()
  const rows = me.data
    ? [
        [t('driver.phone'), me.data.driver.phone],
        [t('driver.license'), [me.data.driver.license_number, me.data.driver.license_categories].filter(Boolean).join(' · ')],
        [t('driver.licenseExpires'), me.data.driver.license_expires ? date(me.data.driver.license_expires) : ''],
        [t('driver.company'), me.data.company.name],
      ]
    : []
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{me.data?.driver.full_name ?? t('driver.tabs.profile')}</h1>
      {me.isPending ? <Spinner /> : null}
      {me.isError ? <Banner kind="error">{errorMessage(me.error, t)}</Banner> : null}
      {rows.length > 0 ? (
        <Card className="divide-y divide-line">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3 px-4 py-3 text-sm"><span className="text-muted">{label}</span><span className="text-right font-medium">{value || '-'}</span></div>
          ))}
        </Card>
      ) : null}
      <Card className="flex items-center justify-between px-4 py-3">
        <span className="text-sm">{t('driver.appearance')}</span>
        <span className="flex items-center gap-1"><LanguageSwitch /><ThemeToggle /></span>
      </Card>
      <Button className="h-12! w-full" icon={LogOut} onClick={() => { void clearDriverCache().finally(logout) }}>{t('driver.logout')}</Button>
    </div>
  )
}
