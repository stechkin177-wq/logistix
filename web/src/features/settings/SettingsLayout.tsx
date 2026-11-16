import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router'
import { isAllowed, NAV } from '../../layout/nav'
import { useSession } from '../../shared/auth/useSession'
import { MobilePinned } from '../../shared/ui/MobilePinned'

/** Вкладки профиля слева направо; подпись «Финансы» короче названия страницы. */
const PROFILE_TABS: { key: string; labelKey: string }[] = [
  { key: 'company', labelKey: 'nav.company' },
  { key: 'branding', labelKey: 'nav.branding' },
  { key: 'users', labelKey: 'nav.users' },
  { key: 'roles', labelKey: 'nav.roles' },
  { key: 'departments', labelKey: 'nav.departments' },
  { key: 'modules', labelKey: 'nav.modules' },
  { key: 'financesettings', labelKey: 'nav.financeTab' },
  { key: 'audit', labelKey: 'nav.audit' },
]

/**
 * Оболочка профиля: сверху горизонтальные вкладки (компания, пользователи, роли, отделы, модули, финансы, аудит),
 * ниже выбранная страница. Страницы «Данных и документов» открываются из бокового меню и идут без вкладок.
 * Права и модули проверяются так же, как в меню (isAllowed).
 */
export function SettingsLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  const group = NAV.find((item) => item.key === 'settings')
  const { pathname } = useLocation()
  const navRef = useRef<HTMLElement>(null)
  // активная вкладка прокручивается в видимую область (узкий экран)
  useEffect(() => {
    const active = navRef.current?.querySelector('[aria-current="page"]')
    // в jsdom (тесты) scrollIntoView не реализован
    if (active && typeof active.scrollIntoView === 'function') active.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [pathname])
  const items = session ? (group?.children ?? []).filter((item) => isAllowed(item, session)) : []
  const tabs = PROFILE_TABS.flatMap((tab) => {
    const item = items.find((i) => i.key === tab.key)
    return item ? [{ ...tab, to: item.path ?? '/settings', icon: item.icon }] : []
  })
  const inProfile = tabs.some((tab) => pathname.startsWith(tab.to))

  return (
    <div className="space-y-3">
      {inProfile ? (
        <MobilePinned>
        <nav
          ref={navRef}
          aria-label={t('nav.settingsLabel')}
          className="thin-scroll scroll-shadow-x flex gap-1 overflow-x-auto rounded-card border border-line bg-surface p-1 shadow-card [--scroll-bg:var(--ui-canvas)]"
        >
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <NavLink
                key={tab.key}
                to={tab.to}
                className={({ isActive }) =>
                  `flex shrink-0 items-center gap-2 whitespace-nowrap rounded-control px-3 py-1.5 text-[13px] transition-colors ${
                    isActive ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
                  }`
                }
              >
                {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden="true" /> : null}
                {t(tab.labelKey)}
              </NavLink>
            )
          })}
        </nav>
        </MobilePinned>
      ) : null}
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  )
}
