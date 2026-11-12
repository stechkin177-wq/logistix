import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'
import { useAuth } from '../../shared/auth/useAuth'
import { usePlatformSession } from '../../shared/auth/usePlatformSession'
import { useBranding } from '../../shared/branding/useBranding'
import { LANGUAGES, setLanguage, type Language } from '../../shared/i18n'
import { Button } from '../../shared/ui/Button'
import { CreditCard, History, KeyRound, Landmark, LogOut, Menu } from '../../shared/ui/icons'
import { SelectBox } from '../../shared/ui/SelectBox'
import { SELECT_CLASS } from '../../shared/ui/fieldStyles'
import { Toaster } from '../../shared/ui/Toaster'
import { WorkspaceSwitcher } from '../../layout/WorkspaceSwitcher'
import { ChangePasswordDialog } from '../account/ChangePasswordDialog'

const LINKS = [
  { to: '/platform/plans', labelKey: 'nav.platformPlans', icon: CreditCard },
  { to: '/platform/companies', labelKey: 'nav.platformCompanies', icon: Landmark },
  { to: '/platform/history', labelKey: 'nav.platformHistory', icon: History },
]

/** Оболочка Центра управления платформы: не зависит от тарифов и модулей компаний. */
export function PlatformLayout() {
  const { t, i18n } = useTranslation()
  const { session } = usePlatformSession()
  const { logout } = useAuth()
  const branding = useBranding()
  const [changingPassword, setChangingPassword] = useState(false)
  const [open, setOpen] = useState(false)
  const companies = session?.companies ?? []

  const panel = (flat: boolean) => (
    <aside className={`flex h-full w-60 shrink-0 flex-col bg-surface ${flat ? '' : 'rounded-card border border-line shadow-card'}`}>
      <div className="px-4 py-3">
        <p className="truncate text-sm font-semibold">{branding.app_name}</p>
        <p className="text-xs text-muted">{t('platformShell.title')}</p>
      </div>
      <nav aria-label={t('platformShell.nav')} className="thin-scroll flex-1 space-y-0.5 overflow-y-auto px-2 pb-2" onClick={() => { setOpen(false) }}>
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-control px-3 py-2 text-sm transition-colors ${
                isActive ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
              }`
            }
          >
            <link.icon className="size-[18px] shrink-0" aria-hidden="true" />
            {t(link.labelKey)}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-2 border-t border-line p-3">
        <WorkspaceSwitcher mode="platform" companies={companies} />
        <SelectBox>
          <select
            aria-label={t('common.language')}
            className={SELECT_CLASS}
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
        </SelectBox>
        <div className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate text-xs text-muted">
            {session?.user.full_name || session?.user.email}
            {session ? ` · ${t(`platformShell.role.${session.user.platform_role}`)}` : ''}
          </span>
          <Button variant="ghost" icon={LogOut} onClick={logout}>
            {t('auth.logout')}
          </Button>
        </div>
        <Button
          variant="ghost"
          icon={KeyRound}
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
  )

  return (
    <div className="flex h-dvh bg-canvas text-ink">
      <div className="hidden p-3 pr-0 md:block">{panel(false)}</div>
      {open ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="w-72 max-w-[85vw] bg-surface shadow-pop">{panel(true)}</div>
          <button type="button" aria-label={t('common.close')} className="flex-1 bg-slate-950/50" onClick={() => { setOpen(false) }} />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 md:hidden">
          <Button variant="ghost" icon={Menu} aria-label={t('nav.menu')} onClick={() => { setOpen(true) }} />
          <span className="truncate text-sm font-semibold">{t('platformShell.title')}</span>
        </header>
        <main className="thin-scroll min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-5">
          <div className="mx-auto w-full max-w-[1500px]">
            <Outlet />
          </div>
        </main>
      </div>
      <Toaster />
    </div>
  )
}
