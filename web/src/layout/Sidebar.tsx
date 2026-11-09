import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, matchPath, useLocation } from 'react-router'
import { useBranding } from '../shared/branding/useBranding'
import { useAuth } from '../shared/auth/useAuth'
import { useSession } from '../shared/auth/useSession'
import { LANGUAGES, setLanguage, type Language } from '../shared/i18n'
import { Banner } from '../shared/ui/Banner'
import { Button } from '../shared/ui/Button'
import { Dialog } from '../shared/ui/Dialog'
import { TextField } from '../shared/ui/TextField'
import { pushToast } from '../shared/ui/toast'
import { ApiError, errorMessage } from '../shared/api/errors'
import { ChangePasswordDialog } from '../features/account/ChangePasswordDialog'
import { visibleNav, type NavItem } from './nav'

function containsPath(item: NavItem, pathname: string): boolean {
  return (item.children ?? []).some((c) => (c.path !== undefined && matchPath({ path: c.path, end: false }, pathname) !== null) || containsPath(c, pathname))
}

/** Сворачиваемая группа «Ещё»: редкие разделы убраны с основного меню, открыта на своих страницах. */
function CollapsibleGroup({ item }: { item: NavItem }) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const shown = open || containsPath(item, pathname)
  return (
    <li>
      <button
        type="button"
        aria-expanded={shown}
        onClick={() => { setOpen(!shown) }}
        className="flex w-full items-center justify-between px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-600"
      >
        {t(item.labelKey)}
        <span aria-hidden="true">{shown ? '▾' : '▸'}</span>
      </button>
      {shown ? (
        <ul>
          {(item.children ?? []).map((child) => (
            <NavEntry key={child.key} item={child} depth={1} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function NavEntry({ item, depth = 0 }: { item: NavItem; depth?: number }) {
  const { t } = useTranslation()
  const pad = depth > 0 ? 'pl-6' : 'pl-3'
  if (item.collapsible) return <CollapsibleGroup item={item} />
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

/** Переход в Центр управления; владельцу платформы нужен свежий код TOTP (ступенчатая проверка). */
function PlatformSwitch({ needsCode }: { needsCode: boolean }) {
  const { t } = useTranslation()
  const { switchToPlatform } = useAuth()
  const [asking, setAsking] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const go = (value?: string) => {
    setBusy(true)
    setError(undefined)
    switchToPlatform(value)
      .then(() => { setAsking(false) })
      .catch((e: unknown) => {
        if (needsCode) setError(e instanceof ApiError && e.code === 'totp_invalid' ? t('auth.totpInvalid') : errorMessage(e, t))
        else pushToast('error', errorMessage(e, t))
      })
      .finally(() => { setBusy(false) })
  }
  return (
    <>
      <Button variant="ghost" className="w-full" disabled={busy} onClick={() => { if (needsCode) { setCode(''); setError(undefined); setAsking(true) } else go() }}>
        {t('platformShell.toCenter')}
      </Button>
      <Dialog
        open={asking}
        title={t('platformShell.toCenter')}
        onClose={() => { setAsking(false) }}
        busy={busy}
        footer={
          <>
            <Button onClick={() => { setAsking(false) }} disabled={busy}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={busy || code.trim().length < 6} onClick={() => { go(code.trim()) }}>{t('auth.totpSubmit')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          {error ? <Banner kind="error">{error}</Banner> : null}
          <p className="text-sm">{t('platformShell.codeHint')}</p>
          <TextField label={t('auth.totpCode')} inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => { setCode(e.target.value) }} />
        </div>
      </Dialog>
    </>
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
  const { logout } = useAuth()
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
        {session?.user.platform_role ? <PlatformSwitch needsCode={session.user.platform_totp === true} /> : null}
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
