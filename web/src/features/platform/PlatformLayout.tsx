import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'
import { useAuth } from '../../shared/auth/useAuth'
import { usePlatformSession } from '../../shared/auth/usePlatformSession'
import { useBranding } from '../../shared/branding/useBranding'
import { LANGUAGES, setLanguage, type Language } from '../../shared/i18n'
import { Button } from '../../shared/ui/Button'
import { Toaster } from '../../shared/ui/Toaster'
import { WorkspaceSwitcher } from '../../layout/WorkspaceSwitcher'
import { ChangePasswordDialog } from '../account/ChangePasswordDialog'

const LINKS = [
  { to: '/platform/plans', labelKey: 'nav.platformPlans' },
  { to: '/platform/companies', labelKey: 'nav.platformCompanies' },
  { to: '/platform/history', labelKey: 'nav.platformHistory' },
]

/** Оболочка Центра управления платформы: не зависит от тарифов и модулей компаний. */
export function PlatformLayout() {
  const { t, i18n } = useTranslation()
  const { session } = usePlatformSession()
  const { logout } = useAuth()
  const branding = useBranding()
  const [changingPassword, setChangingPassword] = useState(false)
  const companies = session?.companies ?? []

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="border-b border-slate-200 px-3 py-2 dark:border-slate-800">
          <p className="truncate text-sm font-semibold">{branding.app_name}</p>
          <p className="text-xs text-slate-500">{t('platformShell.title')}</p>
        </div>
        <nav aria-label={t('platformShell.nav')} className="flex-1 space-y-0.5 p-2">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `block rounded px-3 py-1 text-sm ${
                  isActive
                    ? 'bg-brand-100 font-medium text-slate-900 dark:bg-brand-900 dark:text-white'
                    : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                }`
              }
            >
              {t(link.labelKey)}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t border-slate-200 p-2 dark:border-slate-800">
          <WorkspaceSwitcher mode="platform" companies={companies} />
          <select
            aria-label={t('common.language')}
            className="h-8 w-full rounded border border-slate-300 bg-white px-1 text-sm dark:border-slate-600 dark:bg-slate-900"
            value={i18n.resolvedLanguage}
            onChange={(event) => {
              setLanguage(event.target.value as Language)
            }}
          >
            {LANGUAGES.map((lng) => (
              <option key={lng} value={lng}>
                {t(`languages.${lng}`)}
              </option>
            ))}
          </select>
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-xs text-slate-500">
              {session?.user.full_name || session?.user.email}
              {session ? ` · ${t(`platformShell.role.${session.user.platform_role}`)}` : ''}
            </span>
            <Button variant="ghost" onClick={logout}>
              {t('auth.logout')}
            </Button>
          </div>
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => {
              setChangingPassword(true)
            }}
          >
            {t('account.changePassword')}
          </Button>
          {changingPassword ? (
            <ChangePasswordDialog
              onClose={() => {
                setChangingPassword(false)
              }}
            />
          ) : null}
        </div>
      </aside>
      <main className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-4">
        <Outlet />
      </main>
      <Toaster />
    </div>
  )
}
