import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChangePasswordDialog } from '../features/account/ChangePasswordDialog'
import { errorMessage } from '../shared/api/errors'
import { useAuth } from '../shared/auth/useAuth'
import { useSession } from '../shared/auth/useSession'
import { LANGUAGES, setLanguage, type Language } from '../shared/i18n'
import { ChevronDown, KeyRound, Languages, LogOut } from '../shared/ui/icons'
import { SelectBox } from '../shared/ui/SelectBox'
import { SELECT_CLASS } from '../shared/ui/fieldStyles'
import { pushToast } from '../shared/ui/toast'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

/** Две буквы для аватара: из ФИО, иначе из email/телефона. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const first = parts[0] ?? '?'
  const second = parts[1]
  return (second ? first.charAt(0) + second.charAt(0) : first.slice(0, 2)).toUpperCase()
}

/** Блок профиля внизу меню: компания, пространство, язык, смена пароля, выход - одним раскрывающимся окном. */
export function ProfileMenu() {
  const { t, i18n } = useTranslation()
  const { session } = useSession()
  const { logout, switchCompany } = useAuth()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!session) return null
  const { company, companies, user } = session
  const person = user.full_name || user.email || user.phone || ''

  return (
    <div ref={root} className="relative border-t border-line p-2">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('nav.profile')}
        onClick={() => { setOpen(!open) }}
        className="flex w-full items-center gap-2.5 rounded-control p-2 text-left hover:bg-surface-2"
      >
        <span aria-hidden="true" className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800 dark:bg-brand-900 dark:text-brand-100">
          {initials(person)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">{company.name}</span>
          <span className="block truncate text-xs text-muted">{person}</span>
        </span>
        <ChevronDown className={`size-4 shrink-0 text-muted transition-transform ${open ? '' : 'rotate-180'}`} aria-hidden="true" />
      </button>
      {/* не размонтируем при закрытии: окно ввода кода переключателя пространства живёт внутри и не должно пропадать */}
      {
        <div role="menu" hidden={!open} className="absolute inset-x-2 bottom-full z-30 mb-1 space-y-3 rounded-card border border-line bg-surface p-3 shadow-pop">
          {companies.length >= 2 ? (
            <label className="block space-y-1 text-xs font-medium text-muted">
              {t('company.switch')}
              <SelectBox>
                <select
                  aria-label={t('company.switch')}
                  className={SELECT_CLASS}
                  value={company.id}
                  disabled={busy}
                  onChange={(event) => {
                    const id = Number(event.target.value)
                    if (!Number.isInteger(id) || id === company.id) return
                    setBusy(true)
                    switchCompany(id)
                      .catch((error: unknown) => { pushToast('error', errorMessage(error, t)) })
                      .finally(() => { setBusy(false) })
                  }}
                >
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </SelectBox>
            </label>
          ) : null}
          {user.platform_role ? <WorkspaceSwitcher mode="company" needsCode={user.platform_totp === true} companies={[]} /> : null}
          <label className="block space-y-1 text-xs font-medium text-muted">
            <span className="inline-flex items-center gap-1"><Languages className="size-3.5" aria-hidden="true" />{t('common.language')}</span>
            <SelectBox>
              <select
                aria-label={t('common.language')}
                className={SELECT_CLASS}
                value={i18n.resolvedLanguage}
                onChange={(event) => { setLanguage(event.target.value as Language) }}
              >
                {LANGUAGES.map((lng) => (
                  <option key={lng} value={lng}>{t(`languages.${lng}`)}</option>
                ))}
              </select>
            </SelectBox>
          </label>
          <div className="space-y-0.5 border-t border-line pt-2">
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); setChangingPassword(true) }}
              className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-sm hover:bg-surface-2"
            >
              <KeyRound className="size-4 text-muted" aria-hidden="true" />
              {t('account.changePassword')}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={logout}
              className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-sm text-red-600 hover:bg-surface-2 dark:text-red-400"
            >
              <LogOut className="size-4" aria-hidden="true" />
              {t('auth.logout')}
            </button>
          </div>
        </div>
      }
      {changingPassword ? <ChangePasswordDialog onClose={() => { setChangingPassword(false) }} /> : null}
    </div>
  )
}
