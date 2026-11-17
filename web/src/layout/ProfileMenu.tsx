import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../shared/api/errors'
import { useAuth } from '../shared/auth/useAuth'
import { useSession } from '../shared/auth/useSession'
import { ChevronDown, LogOut, UserRound } from '../shared/ui/icons'
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

/** Блок аккаунта в правом верхнем углу: компания и пользователь, раскрывающееся окно (смена компании и пространства), кнопка «Выйти». */
export function ProfileMenu() {
  const { t } = useTranslation()
  const { session } = useSession()
  const { logout, switchCompany } = useAuth()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
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
    <div ref={root} className="relative flex items-center gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('nav.profile')}
        onClick={() => { setOpen(!open) }}
        className="flex h-9 items-center gap-2 rounded-control border border-line bg-surface p-0.5 text-left shadow-card hover:bg-surface-2 md:pr-2"
      >
        <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800 dark:bg-brand-900 dark:text-brand-100">
          {initials(person)}
        </span>
        <span className="hidden min-w-0 max-w-[14rem] md:block">
          <span className="block truncate text-sm font-medium leading-tight text-ink">{company.name}</span>
          <span className="block truncate text-xs leading-tight text-muted">{person}</span>
        </span>
        <ChevronDown className={`hidden size-4 shrink-0 text-muted transition-transform md:block ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {/* не размонтируем при закрытии: окно ввода кода переключателя пространства живёт внутри и не должно пропадать */}
      {
        <div role="menu" hidden={!open} className="absolute right-0 top-full z-40 mt-2 w-72 max-w-[calc(100vw-1.5rem)] space-y-3 rounded-card border border-line bg-surface p-3 shadow-pop">
          {/* на телефоне в самой плашке видны только инициалы: компания и пользователь - здесь */}
          <div className="border-b border-line pb-2 md:hidden">
            <p className="truncate text-sm font-medium text-ink">{company.name}</p>
            <p className="truncate text-xs text-muted">{person}</p>
          </div>
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
          <div className="space-y-0.5 border-t border-line pt-2">
            <Link
              to="/settings/company"
              role="menuitem"
              onClick={() => { setOpen(false) }}
              className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-sm text-ink hover:bg-surface-2"
            >
              <UserRound className="size-4" aria-hidden="true" />
              {t('nav.profileTitle')}
            </Link>
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
    </div>
  )
}
