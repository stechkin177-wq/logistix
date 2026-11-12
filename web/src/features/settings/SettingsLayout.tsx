import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'
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
  const allowed = session ? (group?.children ?? []).filter((item) => isAllowed(item, session)) : []

  return (
    <div className="grid items-start gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
      <nav
        aria-label={t('nav.settingsLabel')}
        className="thin-scroll flex gap-1 overflow-x-auto rounded-card border border-line bg-surface p-2 shadow-card md:sticky md:top-0 md:flex-col md:overflow-visible"
      >
        {SECTIONS.map((section) => {
          const items = allowed.filter((item) => item.section === section.key)
          if (items.length === 0) return null
          return (
            <div key={section.key} className="flex gap-1 md:flex-col">
              <p className="hidden px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted md:block">
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
        <Outlet />
      </div>
    </div>
  )
}
