import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { useAuth } from '../../shared/auth/useAuth'
import { usePlatformSession } from '../../shared/auth/usePlatformSession'
import { useBranding } from '../../shared/branding/useBranding'
import { setScreenDefaultTheme } from '../../shared/branding/applyBranding'
import { HeaderSlotContext, HintSlotContext } from '../../shared/ui/headerBleed'
import { LanguageSwitch } from '../../shared/ui/LanguageSwitch'
import { ThemeToggle } from '../../shared/ui/ThemeToggle'
import { initials } from '../../layout/ProfileMenu'
import { ChevronDown, KeyRound, LayoutDashboard, LogOut, Settings } from '../../shared/ui/icons'
import { Toaster } from '../../shared/ui/Toaster'
import { WorkspaceSwitcher } from '../../layout/WorkspaceSwitcher'
import { ChangePasswordDialog } from '../account/ChangePasswordDialog'

/** Дашборд и «Управление» (подписки, тарифы, история - вкладки внутри раздела). */
const DASHBOARD = { to: '/platform/dashboard', labelKey: 'nav.platformDashboard', icon: LayoutDashboard, match: ['/platform/dashboard'] }
const MANAGE = { to: '/platform/companies', labelKey: 'platformShell.manage', icon: Settings, match: ['/platform/companies', '/platform/plans', '/platform/history'] }
const LINKS = [DASHBOARD, MANAGE]
const matches = (link: (typeof LINKS)[number], pathname: string) => link.match.some((m) => pathname.startsWith(m))

/** Оболочка Центра управления платформы: не зависит от тарифов и модулей компаний. */
export function PlatformLayout() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const current = LINKS.find((l) => matches(l, pathname))
  const { session } = usePlatformSession()
  const { logout } = useAuth()
  const branding = useBranding()
  const [changingPassword, setChangingPassword] = useState(false)
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  // ширина полосы прокрутки основной области: шапка выравнивается по ней без обрезки всплывающих окон
  const mainRef = useRef<HTMLElement>(null)
  const [scrollbar, setScrollbar] = useState(0)
  useLayoutEffect(() => {
    const el = mainRef.current
    if (!el) return
    const measure = () => { setScrollbar(el.offsetWidth - el.clientWidth) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => { observer.disconnect() }
  }, [])
  const [hintSlot, setHintSlot] = useState<HTMLElement | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  // Центр управления по умолчанию в светлой теме; переключатель темы работает как на основном сайте
  useEffect(() => {
    setScreenDefaultTheme('light')
    return () => { setScreenDefaultTheme(null) }
  }, [])
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [menuOpen])
  const companies = session?.companies ?? []

  const panel = () => (
    <aside className="flex h-full w-60 shrink-0 flex-col rounded-card border border-line bg-surface shadow-card">
      <div className="flex min-h-14 items-center gap-2.5 px-4 py-2">
        {branding.logo_url ? (
          <img src={branding.logo_url} alt="" className="size-7 rounded-md object-contain" />
        ) : (
          <span aria-hidden="true" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-600 text-xs font-bold text-brand-fg">
            {branding.app_name.charAt(0).toUpperCase()}
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">{branding.app_name}</p>
          <p className="text-xs leading-tight text-muted">{t('platformShell.title')}</p>
        </div>
      </div>
      <nav aria-label={t('platformShell.nav')} className="thin-scroll flex-1 space-y-0.5 overflow-y-auto px-2 pb-2" >
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={() =>
              `flex items-center gap-2.5 rounded-control px-3 py-2 text-sm transition-colors ${
                matches(link, pathname) ? 'bg-brand-50 font-medium text-brand-700 dark:bg-white/10 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
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
      </div>
    </aside>
  )

  return (
    <div className="fixed inset-0 flex overscroll-none bg-canvas text-ink">
      <div className="hidden p-3 pr-0 md:block">{panel()}</div>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 touch-none select-none items-center gap-3 border-b border-line bg-surface px-3 md:h-auto md:border-b-0 md:bg-transparent md:px-5 md:pb-0 md:pt-3">
          <div className="flex min-w-0 items-center gap-2 md:hidden">
            {branding.logo_url ? (
              <img src={branding.logo_url} alt="" className="size-7 shrink-0 rounded-md object-contain" />
            ) : (
              <span aria-hidden="true" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-600 text-xs font-bold text-brand-fg">
                {branding.app_name.charAt(0).toUpperCase()}
              </span>
            )}
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold leading-tight">{branding.app_name}</p>
              <p className="text-[10px] leading-[1.15] text-muted">{t('platformShell.title')}</p>
            </div>
          </div>
          {current ? (
            <p className="hidden min-w-0 items-center gap-2 rounded-control bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700 dark:bg-white/10 dark:text-brand-100">
              <current.icon className="size-4 shrink-0" aria-hidden="true" />
              <span className="truncate">{t(current.labelKey)}</span>
            </p>
          ) : null}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <LanguageSwitch />
            <ThemeToggle />
            <div ref={menuRef} className="relative">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label={t('nav.profile')}
                onClick={() => { setMenuOpen(!menuOpen) }}
                className="flex h-9 items-center gap-2 rounded-control border border-line bg-surface p-0.5 text-left shadow-card hover:bg-surface-2 md:pr-2"
              >
                <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800 dark:bg-brand-900 dark:text-brand-100">
                  {initials(session?.user.full_name || session?.user.email || '')}
                </span>
                <span className="hidden min-w-0 max-w-[14rem] md:block">
                  <span className="block truncate text-sm font-medium leading-tight text-ink">{session?.user.full_name || session?.user.email}</span>
                  {session ? <span className="block truncate text-xs leading-tight text-muted">{t(`platformShell.role.${session.user.platform_role}`)}</span> : null}
                </span>
                <ChevronDown className={`hidden size-4 shrink-0 text-muted transition-transform md:block ${menuOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
              </button>
              {menuOpen ? (
                <div role="menu" className="absolute right-0 top-full z-40 mt-2 w-60 space-y-0.5 rounded-card border border-line bg-surface p-1.5 shadow-pop">
                  {LINKS.map((link) => (
                    <Link
                      key={link.to}
                      to={link.to}
                      role="menuitem"
                      onClick={() => { setMenuOpen(false) }}
                      className={`flex w-full items-center gap-2 rounded-control px-2 py-2 text-sm hover:bg-surface-2 md:hidden ${matches(link, pathname) ? 'font-medium text-brand-700 dark:text-brand-200' : 'text-ink'}`}
                    >
                      <link.icon className="size-4" aria-hidden="true" />
                      {t(link.labelKey)}
                    </Link>
                  ))}
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => { setMenuOpen(false); setChangingPassword(true) }}
                    className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-sm text-ink hover:bg-surface-2"
                  >
                    <KeyRound className="size-4" aria-hidden="true" />
                    {t('account.changePassword')}
                  </button>
                  <div className="px-1 py-1 md:hidden"><WorkspaceSwitcher mode="platform" companies={companies} /></div>
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
              ) : null}
            </div>
          </div>
        </header>
        {/* шапка страницы - вне прокрутки, как на основном сайте */}
        <div style={{ paddingRight: scrollbar }} className="shrink-0 touch-none empty:hidden">
          <div ref={setSlot} className="mx-auto flex w-full max-w-[1500px] flex-col px-3 pt-2 empty:hidden md:px-5 md:pt-2" />
        </div>
        <main ref={mainRef} className="thin-scroll min-h-0 min-w-0 flex-1 overscroll-contain overflow-x-hidden overflow-y-auto p-3 pt-0 [scrollbar-gutter:stable] md:p-5 md:pt-0">
          <div className="mx-auto w-full max-w-[1500px] space-y-3 pt-3">
            <div ref={setHintSlot} className="space-y-3 empty:hidden" />
            <HeaderSlotContext.Provider value={slot}>
              <HintSlotContext.Provider value={hintSlot}>
                <Outlet />
              </HintSlotContext.Provider>
            </HeaderSlotContext.Provider>
          </div>
        </main>
      </div>
      {changingPassword ? <ChangePasswordDialog onClose={() => { setChangingPassword(false) }} /> : null}
      <Toaster />
    </div>
  )
}
