import { useEffect, useRef } from 'react'
import { HeaderBleedContext } from '../../shared/ui/headerBleed'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router'
import { isAllowed, NAV, type NavItem } from '../../layout/nav'
import { useSession } from '../../shared/auth/useSession'

const SECTIONS: { key: NonNullable<NavItem['section']>; labelKey: string }[] = [
  { key: 'organization', labelKey: 'nav.sectionOrganization' },
  { key: 'data', labelKey: 'nav.sectionData' },
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
    <div className="grid items-start gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
      <nav
        ref={navRef}
        aria-label={t('nav.settingsLabel')}
        className="thin-scroll scroll-shadow-x flex items-start gap-2 overflow-x-auto pb-1 pt-3 [--scroll-bg:var(--ui-canvas)] md:sticky md:top-0 md:max-h-[calc(100dvh-4rem)] md:pt-5 md:flex-col md:gap-3 md:overflow-y-auto md:pb-0"
      >
        {SECTIONS.map((section) => {
          const items = allowed.filter((item) => item.section === section.key)
          if (items.length === 0) return null
          return (
            <div key={section.key} className="flex shrink-0 gap-1 rounded-card border border-line bg-surface p-1.5 shadow-card md:w-full md:flex-col md:p-2">
              <p className="mb-1 hidden border-b border-line px-3 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted md:block">
                {t(section.labelKey)}
              </p>
              {items.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.key}
                    to={item.path ?? '/settings'}
                    className={({ isActive }) =>
                      `flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-control px-3 py-2 text-sm transition-colors ${
                        isActive ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'
                      }`
                    }
                  >
                    {Icon ? <Icon className="size-4 shrink-0" aria-hidden="true" /> : null}
                    {t(item.labelKey)}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
      </nav>
      <div className="min-w-0">
        <HeaderBleedContext.Provider value={false}>
          <Outlet />
        </HeaderBleedContext.Provider>
      </div>
    </div>
  )
}
