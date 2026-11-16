import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router'
import { ForbiddenPage } from '../errors/ForbiddenPage'
import { flattenNav, isAllowed, NAV } from '../../layout/nav'
import { useSession } from '../../shared/auth/useSession'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Settings } from '../../shared/ui/icons'

/**
 * /settings: страница «Настройки» - карточки подразделов «Данные и документы» (почта, метки, справочники…).
 * Страницы организации и финансов живут во вкладках профиля. Если данных нет - первая доступная страница профиля.
 */
export function SettingsIndex() {
  const { t } = useTranslation()
  const { session } = useSession()
  const group = NAV.find((item) => item.key === 'settings')
  const all = session ? flattenNav(group?.children ?? []).filter((item) => item.path !== undefined && isAllowed(item, session)) : []
  const data = all.filter((item) => item.section === 'data')
  if (data.length === 0) {
    const first = all[0]
    return first?.path ? <Navigate to={first.path} replace /> : <ForbiddenPage />
  }
  return (
    <div className="space-y-3">
      <PageHeader icon={Settings} title={t('nav.settings')} subtitle={t('settingsHub.title')} />
      <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
        {data.map((item) => {
          const Icon = item.icon
          return (
            <Link key={item.key} to={item.path ?? '/settings'} className="flex items-start gap-3 rounded-card border border-line bg-surface p-3 shadow-card transition-colors hover:border-brand-400">
              {Icon ? (
                <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-200">
                  <Icon className="size-[18px]" aria-hidden="true" />
                </span>
              ) : null}
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-ink">{t(item.labelKey)}</span>
                <span className="block text-xs text-muted">{t(`settingsHub.${item.key}`)}</span>
              </span>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
