import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { useBranding } from '../shared/branding/useBranding'
import { useAuth } from '../shared/auth/useAuth'
import { useSession } from '../shared/auth/useSession'
import { LANGUAGES, setLanguage, type Language } from '../shared/i18n'
import { Button } from '../shared/ui/Button'
import { pushToast } from '../shared/ui/toast'
import { errorMessage } from '../shared/api/errors'
import { ChangePasswordDialog } from '../features/account/ChangePasswordDialog'
import { visibleNav, type NavItem } from './nav'

function NavEntry({ item, depth = 0 }: { item: NavItem; depth?: number }) {
  const { t } = useTranslation()
  const pad = depth > 0 ? 'pl-6' : 'pl-3'
  return (
    <li>
      {item.path === undefined ? (
        <p className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          {t(item.labelKey)}
        </p>
      ) : (
        <NavLink
          to={item.path}
          end={item.path === '/'}
          className={({ isActive }) =>
            `block rounded py-1 pr-3 text-sm ${pad} ${
              isActive
                ? 'bg-brand-100 font-medium text-slate-900 dark:bg-brand-900 dark:text-white'
                : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
            }`
          }
        >
          {t(item.labelKey)}
        </NavLink>
      )}
      {item.children ? (
        <ul>
          {item.children.map((child) => (
            <NavEntry key={child.key} item={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function CompanySwitcher() {
  const { t } = useTranslation()
  const { session } = useSession()
  const { switchCompany } = useAuth()
  const [busy, setBusy] = useState(false)
  if (!session) return null
  const { company, companies } = session

  if (companies.length < 2) {
    return <p className="truncate text-sm font-medium">{company.name}</p>
  }
  return (
    <select
      aria-label={t('company.switch')}
      className="h-8 w-full rounded border border-slate-300 bg-white px-1 text-sm dark:border-slate-600 dark:bg-slate-900"
      value={company.id}
      disabled={busy}
      onChange={(event) => {
        const id = Number(event.target.value)
        if (!Number.isInteger(id) || id === company.id) return
        setBusy(true)
        switchCompany(id)
          .catch((error: unknown) => {
            pushToast('error', errorMessage(error, t))
          })
          .finally(() => {
            setBusy(false)
          })
      }}
    >
      {companies.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  )
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t, i18n } = useTranslation()
  const { session } = useSession()
  const { logout, switchToPlatform } = useAuth()
  const [changingPassword, setChangingPassword] = useState(false)
  const branding = useBranding()
  const items = session ? visibleNav(session) : []

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="flex h-12 items-center gap-2 border-b border-slate-200 px-3 dark:border-slate-800">
        {branding.logo_url ? (
          <img src={branding.logo_url} alt="" className="size-6 rounded object-contain" />
        ) : null}
        <span className="truncate text-sm font-semibold">{branding.app_name}</span>
      </div>
      <nav aria-label={t('nav.label')} className="flex-1 overflow-y-auto p-2" onClick={onNavigate}>
        <ul className="space-y-0.5">
          {items.map((item) => (
            <NavEntry key={item.key} item={item} />
          ))}
        </ul>
      </nav>
      <div className="space-y-2 border-t border-slate-200 p-2 dark:border-slate-800">
        <CompanySwitcher />
        {session?.user.platform_role ? (
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => {
              switchToPlatform().catch((error: unknown) => {
                pushToast('error', errorMessage(error, t))
              })
            }}
          >
            {t('platformShell.toCenter')}
          </Button>
        ) : null}
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
          <span className="truncate text-xs text-slate-500">
            {session?.user.full_name || session?.user.email || session?.user.phone}
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
  )
}
