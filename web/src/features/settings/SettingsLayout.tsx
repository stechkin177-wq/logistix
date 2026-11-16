import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router'
import { isAllowed, NAV, type NavItem } from '../../layout/nav'
import { useSession } from '../../shared/auth/useSession'

// раздел «Данные и документы» открывается из бокового меню (список под «Настройки»)
const SECTIONS: { key: NonNullable<NavItem['section']>; labelKey: string }[] = [
  { key: 'organization', labelKey: 'nav.sectionOrganization' },
  { key: 'finance', labelKey: 'nav.sectionFinance' },
]

/**
 * Единая оболочка настроек: слева разделы (на телефоне - лента сверху), справа выбранная страница.
 * Список разделов - из того же дерева меню NAV, поэтому права и модули проверяются так же.
 */
export function SettingsLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  const group = NAV.find((item) => item.key === 'settings')
  const { pathname } = useLocation()
  const navRef = useRef<HTMLElement>(null)
  // на телефоне подразделы идут в строку: активный подраздел прокручивается в видимую область
  useEffect(() => {
    const active = navRef.current?.querySelector('[aria-current="page"]')
    // в jsdom (тесты) scrollIntoView не реализован
    if (active && typeof active.scrollIntoView === 'function') active.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [pathname])
  const allowed = session ? (group?.children ?? []).filter((item) => isAllowed(item, session)) : []

  return (
    <div className="grid items-start gap-4 md:grid-cols-[12.5rem_minmax(0,1fr)]">
      <nav
        ref={navRef}
        aria-label={t('nav.settingsLabel')}
        className="thin-scroll scroll-shadow-x flex items-start gap-2 overflow-x-auto pb-1 [--scroll-bg:var(--ui-canvas)] md:sticky md:top-3 md:max-h-[calc(100dvh-9rem)] md:flex-col md:gap-2 md:overflow-y-auto md:pb-0"
      >
        {SECTIONS.map((section) => {
          const items = allowed.filter((item) => item.section === section.key)
          if (items.length === 0) return null
          return (
            <div key={section.key} className="flex shrink-0 gap-0.5 rounded-card border border-line bg-surface p-1 shadow-card md:w-full md:flex-col md:p-1.5">
              <p className="mb-0.5 hidden border-b border-line px-2.5 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted md:block">
                {t(section.labelKey)}
              </p>
              {items.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.key}
                    to={item.path ?? '/settings'}
                    className={({ isActive }) =>
                      `flex shrink-0 items-center gap-2 whitespace-nowrap rounded-control px-2.5 py-1.5 text-[13px] transition-colors ${
                        isActive ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
                      }`
                    }
                  >
                    {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden="true" /> : null}
                    {t(item.labelKey)}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
      </nav>
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  )
}
